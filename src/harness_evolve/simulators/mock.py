"""A synthetic simulator whose whole purpose is to make the search loop testable.

v1 was never exercised end to end, which is why nobody noticed it was running
with no reward signal at all. Fixing that needs a simulator with no binary, no
`/data` volume, no API key and no wall-clock cost, but which still has the
*shape* of the real problem: an agent that sometimes produces nothing scorable,
a score that responds to what the adapter says, and a token budget that punishes
an adapter for growing without bound.

Everything here is deterministic in ``(candidate_id, task, seed)``. The
generative model is deliberately simple and fully documented so a test can
construct a search problem with a known optimum:

* ``mention`` -- the fraction of the task's required sections named anywhere in
  the adapter text -- is the only channel through which adapter *content* acts.
* ``zero_p`` (probability of an unscorable rollout) falls from
  ``zero_rate`` to ``zero_rate_floor`` as ``mention`` goes 0 -> 1, scaled by
  ``help_strength``. This is the mock's version of the one effect the real
  system is claimed to have: adapters buy reliability, not quality.
* ``quality`` rises from ``base_quality`` with ``mention`` and falls when the
  adapter exceeds ``token_budget``.

With ``help_strength=1.0``, ``noise=0.0`` and ``zero_rate_floor=0.0``, an
adapter that names every required section and stays inside budget scores
exactly 1.0 on every seed, and an empty adapter does not. That is the known
optimum tests are built around.
"""

from __future__ import annotations

import hashlib
import random
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from harness_evolve.simulators.base import (
    Artifact,
    ContaminationPolicy,
    Diagnosis,
    SimulatorRegistry,
    SimulatorSpec,
)
from harness_evolve.types import Cost, Finding, Score, TaskId

#: Extension of a synthetic deck. Distinct from every real simulator's
#: extension so a mock artifact can never be mistaken for a GEOS/OpenFOAM one.
DECK_SUFFIX = ".mock"

#: Sections every synthetic task requires. Kept non-GEOS-sounding on purpose.
CORE_SECTIONS: tuple[str, ...] = ("Grid", "Schedule")

#: Sections a task may additionally require, drawn deterministically per task.
OPTIONAL_SECTIONS: tuple[str, ...] = (
    "Materials",
    "Boundaries",
    "Outputs",
    "Solvers",
    "Regions",
    "Functions",
)

#: Section names the mock agent hallucinates when quality is low.
DISTRACTOR_SECTIONS: tuple[str, ...] = ("Debug", "Notes", "Scratch", "Legacy")

#: Extra-section penalty. Same value as TreeSim's beta so the mock's scoring
#: curve has the same shape as the GEOS one it stands in for.
EXTRA_PENALTY_BETA = 0.1


def _seed_int(*parts: Any) -> int:
    """Stable across processes, unlike :func:`hash`, which is salted per run."""
    h = hashlib.blake2b(digest_size=8)
    for p in parts:
        h.update(str(p).encode())
        h.update(b"\x00")
    return int.from_bytes(h.digest(), "big")


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def adapter_text(source: str | Mapping[str, str] | Sequence[str]) -> str:
    """Normalize a candidate's content to one blob of text.

    Accepts ``Candidate.files`` directly without importing ``core``: the
    simulators package stays a leaf so a future ``core`` -> ``simulators``
    import cannot close a cycle.
    """
    if isinstance(source, str):
        return source
    if isinstance(source, Mapping):
        return "\n".join(str(v) for _, v in sorted(source.items()))
    return "\n".join(str(v) for v in source)


@dataclass(frozen=True)
class MockConfig:
    """Knobs of the synthetic generative model.

    Defaults are chosen so a default-configured mock reproduces the qualitative
    fact the real system is built around -- a fifth of ungrounded rollouts are
    unscorable, and grounding removes most of them -- without any single run
    being so noisy that a test needs hundreds of seeds.
    """

    zero_rate: float = 0.20
    zero_rate_floor: float = 0.0
    help_strength: float = 0.8
    base_quality: float = 0.45
    noise: float = 0.10
    token_budget: int = 400
    overlong_penalty: float = 0.30
    chars_per_token: float = 3.6
    base_tool_calls: float = 30.0

    def validate(self) -> None:
        if not 0.0 <= self.zero_rate_floor <= self.zero_rate <= 1.0:
            raise ValueError(
                "require 0 <= zero_rate_floor <= zero_rate <= 1; got "
                f"{self.zero_rate_floor} / {self.zero_rate}"
            )
        if not 0.0 <= self.help_strength <= 1.0:
            raise ValueError(f"help_strength must be in [0,1]: {self.help_strength}")
        if self.token_budget <= 0:
            raise ValueError(f"token_budget must be positive: {self.token_budget}")


@dataclass(frozen=True)
class MockTask:
    """A synthetic task: the set of sections a correct deck must define."""

    task_id: TaskId
    required_sections: tuple[str, ...]
    keys_per_section: int

    def deck_text(self) -> str:
        """The canonical (ground-truth) deck for this task."""
        rng = random.Random(_seed_int("gt", self.task_id))
        lines: list[str] = []
        for section in self.required_sections:
            lines.append(f"[{section}]")
            for i in range(self.keys_per_section):
                lines.append(f"p{i} = {rng.randrange(1, 1000)}")
        return "\n".join(lines) + "\n"


@dataclass
class MockDeck:
    """Parsed synthetic deck: ordered sections, each a flat key/value map."""

    sections: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "MockDeck":
        """Parse deck text, raising :class:`ValueError` on the first bad line."""
        deck = cls()
        current: dict[str, str] | None = None
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = deck.sections.setdefault(line[1:-1].strip(), {})
                continue
            if "=" not in line or current is None:
                raise ValueError(f"line {lineno}: cannot parse {raw!r}")
            key, _, value = line.partition("=")
            current[key.strip()] = value.strip()
        return deck

    def render(self) -> str:
        lines: list[str] = []
        for section, kv in self.sections.items():
            lines.append(f"[{section}]")
            lines.extend(f"{k} = {v}" for k, v in kv.items())
        return "\n".join(lines) + "\n"


@dataclass
class MockOutcome:
    """One synthetic rollout: what a runner needs, without executing anything."""

    score: Score
    cost: Cost
    workspace: Path
    zeroed: bool
    quality: float
    zero_probability: float
    mention: float


@SimulatorRegistry.register
class MockSimulator(SimulatorSpec):
    """Offline stand-in for a real simulator.

    Implements the full :class:`SimulatorSpec` contract over a synthetic deck
    format, and additionally supplies the generative side (:meth:`simulate`)
    that a mock runner needs. Both halves live here so the fake agent and the
    fake scorer can never drift apart.
    """

    name = "mock"
    leaky_extensions = ("mock",)
    required_sections = CORE_SECTIONS

    def __init__(self, config: MockConfig | None = None, **overrides: Any) -> None:
        cfg = config or MockConfig()
        if overrides:
            cfg = replace(cfg, **overrides)
        cfg.validate()
        self.config = cfg

    # -- task construction ------------------------------------------------
    def task_for(self, task: TaskId) -> MockTask:
        """The synthetic task named ``task``. Pure function of the id."""
        rng = random.Random(_seed_int("task", task))
        n_extra = rng.randint(1, 3)
        extra = tuple(sorted(rng.sample(OPTIONAL_SECTIONS, n_extra)))
        return MockTask(
            task_id=task,
            required_sections=CORE_SECTIONS + extra,
            keys_per_section=rng.randint(2, 4),
        )

    def write_ground_truth(self, root: Path, task: TaskId) -> Path:
        """Materialize ``task``'s ground truth under ``root/<task>``.

        Layout matches the GEOS one (``<gt_root>/<task_id>/``) so the default
        contamination policy and any path convention in the core loop hold for
        the mock too.
        """
        task_dir = Path(root) / task
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / f"deck{DECK_SUFFIX}").write_text(self.task_for(task).deck_text())
        return task_dir

    # -- generative side (what a mock runner calls) -----------------------
    def simulate(
        self,
        candidate_id: str,
        candidate_files: str | Mapping[str, str] | Sequence[str],
        task: TaskId,
        seed: int,
        workspace: Path,
        ground_truth_root: Path | None = None,
    ) -> MockOutcome:
        """Fake one rollout: write a deck into ``workspace`` and score it.

        Scoring goes through :meth:`score` rather than reusing the internal
        quality draw, so the failures-as-zero path is exercised by every mock
        rollout instead of being a branch only tests reach.
        """
        spec = self.task_for(task)
        text = adapter_text(candidate_files)
        mention = self.mention_fraction(text, spec)
        overage = self.budget_overage(text)
        rng = random.Random(_seed_int("rollout", candidate_id, task, seed))

        cfg = self.config
        zero_p = cfg.zero_rate_floor + (cfg.zero_rate - cfg.zero_rate_floor) * (
            1.0 - cfg.help_strength * mention
        )
        quality = _clamp01(
            cfg.base_quality
            + cfg.help_strength * mention
            - cfg.overlong_penalty * overage
            + rng.uniform(-cfg.noise, cfg.noise)
        )

        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        zeroed = rng.random() < zero_p
        if zeroed:
            # Half the zeros are "agent wrote nothing", half are "agent wrote
            # something unparseable". Both are real v1 termination modes and
            # they exit through different branches of `score`.
            if rng.random() < 0.5:
                for stale in workspace.glob(f"*{DECK_SUFFIX}"):
                    stale.unlink()
            else:
                (workspace / f"deck{DECK_SUFFIX}").write_text(
                    "[Grid\nthis deck was truncated mid-write\n"
                )
        else:
            (workspace / f"deck{DECK_SUFFIX}").write_text(
                self._generate_deck(spec, quality, rng).render()
            )

        if ground_truth_root is None:
            with tempfile.TemporaryDirectory() as tmp:
                gt_dir = self.write_ground_truth(Path(tmp), task)
                score = self.score(workspace, gt_dir, task)
        else:
            gt_dir = self.write_ground_truth(ground_truth_root, task)
            score = self.score(workspace, gt_dir, task)

        return MockOutcome(
            score=score,
            cost=self._cost(quality, overage, rng),
            workspace=workspace,
            zeroed=zeroed,
            quality=quality,
            zero_probability=zero_p,
            mention=mention,
        )

    def mention_fraction(self, text: str, spec: MockTask) -> float:
        """Fraction of the task's required sections named in the adapter text.

        The single channel by which adapter *content* moves the score. Matching
        is case-insensitive substring, which is crude but is what makes the
        optimum obvious enough to assert on.
        """
        if not spec.required_sections:
            return 0.0
        low = text.lower()
        hits = sum(1 for s in spec.required_sections if s.lower() in low)
        return hits / len(spec.required_sections)

    def budget_overage(self, text: str) -> float:
        """Fractional overshoot of the token budget; 0.0 when within budget."""
        est = len(text) / self.config.chars_per_token
        return max(0.0, (est - self.config.token_budget) / self.config.token_budget)

    def _generate_deck(
        self, spec: MockTask, quality: float, rng: random.Random
    ) -> MockDeck:
        gt = MockDeck.parse(spec.deck_text())
        deck = MockDeck()
        # Section inclusion and per-key correctness are independent draws, so
        # sqrt(quality) on each makes E[score] ~= quality -- without it the
        # score is quadratic in quality and every knob reads twice as strong as
        # its name suggests.
        p_ok = quality ** 0.5
        for section, kv in gt.sections.items():
            if rng.random() > p_ok:
                continue
            out: dict[str, str] = {}
            for key, value in kv.items():
                if rng.random() <= p_ok:
                    out[key] = value
                else:
                    out[key] = str(int(value) + rng.randrange(1, 100))
            deck.sections[section] = out
        # A low-quality agent also invents sections nobody asked for; this is
        # what makes the extras penalty reachable in mock rollouts.
        for distractor in DISTRACTOR_SECTIONS:
            if rng.random() > p_ok:
                deck.sections[distractor] = {"p0": "0"}
        return deck

    def _cost(self, quality: float, overage: float, rng: random.Random) -> Cost:
        # Cost inflates with adapter length, which is what makes the efficiency
        # gate in the core loop something a mock search can actually trip.
        calls = self.config.base_tool_calls * (1.0 + 0.5 * overage) + rng.uniform(-2, 2)
        return Cost(
            tool_calls=round(max(1.0, calls), 2),
            wall_seconds=round(max(1.0, calls) * 3.0, 2),
            input_tokens=round(calls * 900.0, 1),
            output_tokens=round(calls * 120.0, 1),
        )

    # -- SimulatorSpec ----------------------------------------------------
    def parse(self, workspace: Path) -> Artifact:
        artifact = Artifact()
        workspace = Path(workspace)
        if not workspace.is_dir():
            return artifact
        decks: list[MockDeck] = []
        for path in sorted(workspace.rglob(f"*{DECK_SUFFIX}")):
            rel = path.relative_to(workspace).as_posix()
            try:
                text = path.read_text()
            except OSError as exc:
                artifact.parse_errors[rel] = str(exc)
                continue
            artifact.files[rel] = text
            try:
                decks.append(MockDeck.parse(text))
            except ValueError as exc:
                artifact.parse_errors[rel] = str(exc)
        merged = MockDeck()
        for deck in decks:
            for section, kv in deck.sections.items():
                merged.sections.setdefault(section, {}).update(kv)
        artifact.tree = merged
        return artifact

    def present_sections(self, artifact: Artifact) -> set[str]:
        deck = artifact.tree
        return set(deck.sections) if isinstance(deck, MockDeck) else set()

    def validate(self, artifact: Artifact, workspace: Path) -> list[Finding]:
        """The mock's "validator": parse errors plus the completeness gate.

        No subprocess, so a stop-hook policy can be exercised offline against
        findings whose shape matches what geosx produces.
        """
        findings = [
            Finding("mock_validate", "error", f"unparseable deck: {msg}", location=rel)
            for rel, msg in sorted(artifact.parse_errors.items())
        ]
        if artifact.is_empty:
            findings.append(
                Finding("mock_validate", "error", "workspace contains no deck file")
            )
        findings.extend(self.check_completeness(artifact))
        return findings

    def score(self, generated: Path, ground_truth: Path, task: TaskId) -> Score:
        """Section coverage x key accuracy, minus an extras penalty.

        Same shape as GEOS TreeSim one level deep: each ground-truth section
        contributes ``1/N``, weighted by how many of its keys the generated deck
        got right, and hallucinated sections cost ``beta * extras/(N+extras)``.
        """
        gen = self.parse(Path(generated))
        gt = self.parse(Path(ground_truth))
        if not isinstance(gt.tree, MockDeck) or not gt.tree.sections:
            return Score(task=task, value=0.0, status="missing_ground_truth")
        if gen.is_empty:
            return Score(task=task, value=0.0, status="empty_workspace")
        if gen.parse_errors:
            return Score(
                task=task,
                value=0.0,
                status="parse_error",
                detail={"parse_errors": dict(gen.parse_errors)},
            )

        gt_sections = gt.tree.sections
        gen_sections = gen.tree.sections
        section_scores: dict[str, float] = {}
        for section, gt_kv in gt_sections.items():
            gen_kv = gen_sections.get(section)
            if gen_kv is None:
                section_scores[section] = 0.0
                continue
            keys = set(gt_kv) | set(gen_kv)
            matched = sum(1 for k in keys if gt_kv.get(k) == gen_kv.get(k))
            section_scores[section] = matched / len(keys) if keys else 1.0

        extras = sorted(set(gen_sections) - set(gt_sections))
        coverage = sum(section_scores.values()) / len(gt_sections)
        denom = len(gt_sections) + len(extras)
        penalty = EXTRA_PENALTY_BETA * (len(extras) / denom) if denom else 0.0
        return Score(
            task=task,
            value=round(_clamp01(coverage - penalty), 6),
            status="success",
            detail={
                "section_scores": {k: round(v, 6) for k, v in section_scores.items()},
                "extra_sections": extras,
                "n_extra": len(extras),
            },
        )

    def diagnose(
        self, generated: Path, ground_truth: Path, task: TaskId
    ) -> Diagnosis:
        result = self.score(generated, ground_truth, task)
        detail: Mapping[str, Any] = result.detail
        section_scores = dict(detail.get("section_scores", {}))
        missing = [s for s, v in section_scores.items() if v == 0.0]
        return Diagnosis(
            section_scores=section_scores,
            missing_elements=missing,
            extra_elements=list(detail.get("extra_sections", [])),
            n_extra=int(detail.get("n_extra", 0) or 0),
            category="missing_block" if missing else ("no_failure" if result.value >= 1.0 else "bad_attribute_value"),
            notes=[] if result.status == "success" else [f"status={result.status}"],
        )

    def contamination_policy(
        self, task: TaskId, ground_truth_root: Path
    ) -> ContaminationPolicy:
        policy = super().contamination_policy(task, ground_truth_root)
        return ContaminationPolicy(
            blocked_basenames=policy.blocked_basenames,
            blocked_paths=policy.blocked_paths,
            reason="mock task ground truth",
        )

    def preflight(self) -> list[str]:
        """Never unavailable. Being always runnable is the entire point."""
        return []
