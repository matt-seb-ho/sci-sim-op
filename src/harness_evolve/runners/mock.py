"""A deterministic, free, offline runner, so the search loop is testable.

This exists because v1 was never testable end to end, and as a direct
consequence ran three rounds with a silently broken reward channel that nobody
noticed. A loop that can only be exercised by spending 25 minutes and real
money per task-run does not get exercised.

What it models, and why each piece is here rather than being a constant:

* **adapter text that genuinely helps.** Marker phrases in the candidate's
  files raise quality. Without this the search has no gradient and a green test
  suite would prove only that the plumbing runs.
* **an adapter that is too long and costs more.** Tokens past
  :attr:`MockWorld.free_tokens` inflate tool calls and spend while *lowering*
  quality. That is the over-specification failure mode the efficiency gate
  exists to catch, and the v1 lineage exhibits it (primer 270 B -> 3159 B over
  three unmonitored rounds). A mock where longer is never worse would let a
  broken acceptance gate pass its tests.
* **zero-score terminations at a settable rate.** Preventing these is the
  entire effect under study: adapters cut across-run sigma by roughly an order
  of magnitude by removing the tail, and the tail is two tasks in ten. A search
  loop must be exercised against a problem where the tail *is* the signal, so
  the rate is a knob and the stop policy moves it.

Scoring is delegated to the :class:`~harness_evolve.simulators.base.
SimulatorSpec`, never faked here. The runner controls *what the agent wrote*
-- a deck missing sections, a deck with hallucinated extras, an empty workspace
-- and the simulator scores it under its own rules. A zero termination is
therefore an empty or unparseable workspace, and it comes back as 0.0 because
the failures-as-zero convention says so, not because this module hardcoded it.
That keeps the mock honest about the one thing v1 got wrong: the reward channel.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from harness_evolve.core.candidate import estimate_tokens
from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import Cost, Rollout, Score, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate
    from harness_evolve.simulators.base import SimulatorSpec

#: Sections used when the simulator declares none. GEOS-shaped because the
#: structural-completeness regime is the one the mock needs to reproduce.
DEFAULT_SECTIONS: tuple[str, ...] = (
    "Solvers", "Mesh", "Events", "NumericalMethods", "ElementRegions", "Constitutive",
)

#: Fixed clock. Wall-clock timestamps would make two identical runs differ,
#: and "identical inputs produce an identical Rollout" is the property this
#: runner exists to provide.
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

#: Tool names cycled through the synthetic trajectory. Real enough that the
#: evidence layer's tool-call extraction has something shaped like its input.
_TOOL_CYCLE: tuple[str, ...] = (
    "Read", "Glob", "Grep", "Write", "Edit", "Bash",
    "mcp__geos-rag__search_geos_docs", "mcp__xmllint__validate_geos_xml",
)


def _u01(*parts: object) -> float:
    """A deterministic uniform draw in [0, 1) from arbitrary keys.

    Hash-derived rather than ``random.Random`` because the value must depend
    only on the keys, never on call order -- otherwise adding a check upstream
    silently reshuffles every outcome downstream.
    """
    blob = b"\x1f".join(str(p).encode() for p in parts)
    return int.from_bytes(hashlib.blake2b(blob, digest_size=8).digest(), "big") / 2.0**64


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class MockWorld:
    """The knobs. Every default is a modelling choice, not a magic number.

    Defaults put an unadapted candidate near the observed regime: mid-40s mean
    score with a ~20% zero rate, which a well-formed adapter roughly halves.
    """

    #: Phrases whose presence in adapter text raises quality. The search has a
    #: gradient only because these exist; tests override them.
    helpful_markers: tuple[str, ...] = (
        "required sections", "materialList", "discretization", "targetRegions",
    )
    #: Phrases marking a declared negative constraint. Their presence suppresses
    #: hallucinated extras -- the failure mode a positive-only cheatsheet makes
    #: worse (extra_block 9 -> 11, hallucinated_extras 4 -> 7).
    constraint_markers: tuple[str, ...] = ("no more", "do NOT", "at most", "exactly")

    base_quality: float = 0.45
    marker_gain: float = 0.08
    #: Per-task additive difficulty. Negative is harder. Sparse by design: the
    #: interesting slices have a couple of cliff tasks and seven easy ones.
    task_difficulty: Mapping[TaskId, float] = field(default_factory=dict)
    noise: float = 0.06

    #: Zero-score termination rate for a candidate with no stop-policy guard.
    zero_rate: float = 0.20
    #: Fraction of that rate a fully-guarded stop policy removes. Not 1.0: the
    #: measured effect is a large reduction in the tail, never its elimination.
    guard_zero_reduction: float = 0.75
    retry_guard_weight: float = 0.20
    check_guard_weight: float = 0.15

    #: Adapter tokens that cost nothing. Past this, everything gets worse.
    free_tokens: int = 400
    length_quality_penalty: float = 0.05      # per 1k tokens over budget
    overlength_zero_penalty: float = 0.02     # per 1k tokens over budget
    extra_tool_calls_per_1k_tokens: float = 6.0

    base_tool_calls: float = 30.0
    retry_tool_calls: float = 8.0
    seconds_per_tool_call: float = 12.0
    context_tokens_per_call: float = 900.0
    output_tokens_per_call: float = 120.0
    usd_per_input_token: float = 3e-6
    usd_per_output_token: float = 15e-6
    #: A zero termination burns budget too, just less of it: the agent usually
    #: died or gave up partway. Zeros being free would make the cost gate lie.
    zero_tool_call_fraction: float = 0.6

    retry_quality_gain: float = 0.07

    def with_zero_rate(self, rate: float) -> "MockWorld":
        """The knob the tail experiments turn."""
        return replace(self, zero_rate=rate)


@dataclass(frozen=True)
class MockOutcome:
    """What the world decided, before the simulator scored anything.

    Exposed via :meth:`MockRunner.plan` so a test can assert on the knobs
    without touching the filesystem, and so a failing search-loop test can say
    which half broke: the world model or the scoring path.
    """

    task: TaskId
    seed: int
    quality: float
    is_zero: bool
    zero_reason: str
    zero_probability: float
    guard: float
    blocks: int
    n_markers: int
    over_tokens: int
    declares_constraints: bool
    n_extras: int
    cost: Cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "seed": self.seed,
            "quality": round(self.quality, 4),
            "is_zero": self.is_zero,
            "zero_reason": self.zero_reason,
            "zero_probability": round(self.zero_probability, 4),
            "guard": round(self.guard, 4),
            "blocks": self.blocks,
            "n_markers": self.n_markers,
            "over_tokens": self.over_tokens,
            "declares_constraints": self.declares_constraints,
            "n_extras": self.n_extras,
        }


class MockRunner(RolloutRunner):
    """Deterministic runner over a synthetic world. No network, no Docker, $0."""

    def __init__(
        self,
        spec: "SimulatorSpec",
        *,
        world: MockWorld | None = None,
        root: Path | None = None,
        sections: Sequence[str] | None = None,
    ) -> None:
        """
        Args:
            spec: the simulator that scores. Required, and never bypassed --
                the runner's job is to produce an artifact, not a number.
            world: the knobs; see :class:`MockWorld`.
            root: where synthetic workspaces and ground truth land. A temp
                directory when omitted, but pass one from tests: ``Rollout``
                carries paths, and a stable ``root`` is what makes two runs
                compare equal field for field.
            sections: override the deck's section list. Defaults to the
                simulator's ``required_sections``, falling back to
                :data:`DEFAULT_SECTIONS`.
        """
        self.spec = spec
        self.world = world or MockWorld()
        self._root = Path(root) if root is not None else None
        self.sections: tuple[str, ...] = tuple(
            sections or getattr(spec, "required_sections", ()) or DEFAULT_SECTIONS
        )

    @property
    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(
            can_execute=True,
            produces_trajectories=True,
            produces_validator_events=True,
            deterministic=True,
            usd_per_task_run=0.0,
        )

    @property
    def root(self) -> Path:
        if self._root is None:
            import tempfile

            self._root = Path(tempfile.mkdtemp(prefix="harness_evolve_mock_"))
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def preflight(self) -> list[str]:
        """Always ready: that is the point of it."""
        return []

    # -- the world model -------------------------------------------------
    def plan(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> MockOutcome:
        """Decide the outcome. Pure: no I/O, no scoring, no mutation."""
        w = self.world
        cid = candidate.cid
        text = "\n".join(candidate.files[p] for p in sorted(candidate.files))
        lowered = text.lower()

        n_markers = sum(1 for m in w.helpful_markers if m.lower() in lowered)
        declares_constraints = any(m.lower() in lowered for m in w.constraint_markers)
        tokens = estimate_tokens(text)
        over_tokens = max(0, tokens - w.free_tokens)
        over_k = over_tokens / 1000.0

        policy = candidate.manifest.stop_policy
        n_checks = len(policy.checks)
        guard = _clamp(policy.retries * w.retry_guard_weight + n_checks * w.check_guard_weight)

        p_zero = _clamp(
            w.zero_rate * (1.0 - w.guard_zero_reduction * guard)
            + w.overlength_zero_penalty * over_k
        )
        u_zero = _u01(cid, task, seed, "zero")
        is_zero = u_zero < p_zero
        zero_reason = ""
        if is_zero:
            # Both observed shapes of a zero, so downstream code that
            # distinguishes them gets exercised.
            zero_reason = (
                "empty_workspace" if _u01(cid, task, seed, "zero_kind") < 0.5
                else "parse_error"
            )

        q0 = _clamp(
            w.base_quality
            + w.task_difficulty.get(task, 0.0)
            + w.marker_gain * n_markers
            - w.length_quality_penalty * over_k
            + w.noise * (2.0 * _u01(cid, task, seed, "quality") - 1.0)
        )
        # A stop hook can only repair what it can see, and only as often as its
        # retry budget allows. No enabled checks means no blocks, which is the
        # control condition every claim about the stop interface needs.
        wanted = 0 if q0 >= 0.8 else (1 if q0 >= 0.5 else 2)
        blocks = min(policy.retries, wanted) if n_checks else 0
        quality = 0.0 if is_zero else _clamp(q0 + w.retry_quality_gain * blocks)

        n_extras = 0 if declares_constraints else 1 + int(2 * (1.0 - quality))

        tool_calls = (
            w.base_tool_calls
            + w.retry_tool_calls * blocks
            + w.extra_tool_calls_per_1k_tokens * over_k
            + 4.0 * _u01(cid, task, seed, "tools")
        )
        if is_zero:
            tool_calls *= w.zero_tool_call_fraction
        input_tokens = tool_calls * (tokens + w.context_tokens_per_call)
        output_tokens = tool_calls * w.output_tokens_per_call
        cost = Cost(
            tool_calls=round(tool_calls, 2),
            wall_seconds=round(tool_calls * w.seconds_per_tool_call, 2),
            input_tokens=round(input_tokens, 1),
            output_tokens=round(output_tokens, 1),
            usd=round(
                input_tokens * w.usd_per_input_token + output_tokens * w.usd_per_output_token,
                6,
            ),
        )
        return MockOutcome(
            task=task,
            seed=seed,
            quality=quality,
            is_zero=is_zero,
            zero_reason=zero_reason,
            zero_probability=p_zero,
            guard=guard,
            blocks=blocks,
            n_markers=n_markers,
            over_tokens=over_tokens,
            declares_constraints=declares_constraints,
            n_extras=n_extras,
            cost=cost,
        )

    # -- the runner contract ---------------------------------------------
    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        """Materialize a synthetic rollout and score it through the simulator."""
        outcome = self.plan(candidate, task, seed)
        workspace = self._workspace_dir(candidate.cid, task, seed)
        if workspace.exists():
            shutil.rmtree(workspace)
        inputs_dir = workspace / "inputs"
        inputs_dir.mkdir(parents=True)

        ground_truth = self._write_ground_truth(task)
        self._write_generated(inputs_dir, task, outcome)
        events_path = workspace / "events.jsonl"
        events_path.write_text(self._events_jsonl(candidate, task, outcome))
        validator_events = self._validator_events(task, outcome)
        (workspace / ".verify_hook_events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in validator_events)
        )

        # The simulator scores; the runner does not second-guess the number it
        # returns. Overriding it here would rebuild exactly the fiction that
        # hid v1's dead reward channel.
        score = self.spec.score(inputs_dir, ground_truth, task)
        score = replace(
            score,
            detail={**dict(score.detail), "mock": outcome.to_dict()},
        )
        return Rollout(
            task=task,
            candidate_id=candidate.cid,
            seed=seed,
            score=score,
            cost=outcome.cost,
            artifacts_dir=str(workspace),
            events_path=str(events_path),
            validator_events=validator_events,
            error=outcome.zero_reason or None,
        )

    # -- synthetic artifacts ---------------------------------------------
    def _workspace_dir(self, cid: str, task: TaskId, seed: int) -> Path:
        return self.root / "runs" / cid / task / f"seed{seed}"

    def _write_ground_truth(self, task: TaskId) -> Path:
        """The reference deck. Written once per task; identical across runs."""
        gt = self.root / "ground_truth" / task
        gt.mkdir(parents=True, exist_ok=True)
        target = gt / "reference.xml"
        if not target.exists():
            target.write_text(self._reference_deck(task))
        return gt

    def _reference_deck(self, task: TaskId) -> str:
        """A complete, self-consistent deck for ``task``."""
        body = "\n".join(self._section_xml(task, s) for s in self.sections)
        return f"<Problem>\n{body}\n</Problem>\n"

    def _section_xml(self, task: TaskId, section: str) -> str:
        """One section, with the cross-references a real deck carries."""
        if section == "Solvers":
            return (
                "  <Solvers>\n"
                f'    <SinglePhaseFVM name="flow_{task}" discretization="disc_{task}" '
                f'targetRegions="{{ region_{task} }}"/>\n'
                "  </Solvers>"
            )
        if section == "NumericalMethods":
            return (
                "  <NumericalMethods>\n    <FiniteVolume>\n"
                f'      <TwoPointFluxApproximation name="disc_{task}"/>\n'
                "    </FiniteVolume>\n  </NumericalMethods>"
            )
        if section == "ElementRegions":
            return (
                "  <ElementRegions>\n"
                f'    <CellElementRegion name="region_{task}" materialList="{{ mat_{task} }}"/>\n'
                "  </ElementRegions>"
            )
        if section == "Constitutive":
            return (
                "  <Constitutive>\n"
                f'    <CompressibleSinglePhaseFluid name="mat_{task}" defaultDensity="1000"/>\n'
                "  </Constitutive>"
            )
        return f'  <{section} name="{section.lower()}_{task}"/>'

    def _write_generated(self, inputs_dir: Path, task: TaskId, outcome: MockOutcome) -> None:
        """Write what the agent 'produced'.

        A zero termination is an empty or unparseable workspace -- the artifact
        the failures-as-zero convention is about. Nothing here writes a score.
        """
        if outcome.is_zero:
            if outcome.zero_reason == "empty_workspace":
                return
            (inputs_dir / "deck.xml").write_text(
                "<Problem>\n  <Solvers>\n    <SinglePhaseFVM name=\"flow\"\n"
            )
            return
        (inputs_dir / "deck.xml").write_text(self._generated_deck(task, outcome))

    def _generated_deck(self, task: TaskId, outcome: MockOutcome) -> str:
        """A quality-degraded copy of the reference deck.

        Degradations are the measured failure categories, not noise:
        ``missing_block`` (sections dropped), ``hallucinated_extras`` (spurious
        Constitutive children, suppressed when the adapter declares negative
        constraints), and the lazily-resolved dangling reference that
        ``geosx --validate-input`` exits 0 on.
        """
        keep = max(1, round(outcome.quality * len(self.sections)))
        kept = self.sections[:keep]
        parts: list[str] = []
        for section in kept:
            xml = self._section_xml(task, section)
            if section == "Solvers" and outcome.quality < 0.9:
                xml = xml.replace(f'disc_{task}"', f'disc_{task}_MISSING"')
            if section == "Constitutive" and outcome.n_extras:
                extras = "\n".join(
                    f'    <NullModel name="extra_{i}"/>' for i in range(outcome.n_extras)
                )
                xml = xml.replace("  </Constitutive>", f"{extras}\n  </Constitutive>")
            parts.append(xml)
        return "<Problem>\n" + "\n".join(parts) + "\n</Problem>\n"

    # -- synthetic telemetry ---------------------------------------------
    def _events_jsonl(
        self, candidate: "Candidate", task: TaskId, outcome: MockOutcome
    ) -> str:
        """A trajectory shaped like Claude Code's ``--output-format stream-json``.

        Same record types the evidence layer reads off a real run (``system``
        init, ``assistant`` turns carrying ``tool_use`` blocks, ``user``
        tool results, a terminal ``result``), so nothing downstream needs a
        mock-specific branch.
        """
        n_calls = max(1, int(outcome.cost.tool_calls))
        lines: list[str] = [
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": f"mock-{candidate.cid}-{task}-{outcome.seed}",
                    "model": "mock-frozen-agent",
                    "tools": list(_TOOL_CYCLE),
                    "mcp_servers": [
                        {"name": "geos-rag", "status": "connected"},
                        {"name": "xmllint", "status": "connected"},
                    ],
                }
            )
        ]
        for i in range(n_calls):
            tool = _TOOL_CYCLE[i % len(_TOOL_CYCLE)]
            lines.append(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "id": f"msg_mock_{i:04d}",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": f"toolu_mock_{i:04d}",
                                    "name": tool,
                                    "input": {"file_path": "inputs/deck.xml", "step": i},
                                }
                            ],
                        },
                    }
                )
            )
            lines.append(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": f"toolu_mock_{i:04d}",
                                    "content": "ok",
                                }
                            ],
                        },
                    }
                )
            )
        lines.append(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "error" if outcome.is_zero else "success",
                    "is_error": outcome.is_zero,
                    "num_turns": n_calls,
                    "duration_ms": int(outcome.cost.wall_seconds * 1000),
                    "total_cost_usd": outcome.cost.usd,
                    "usage": {
                        "input_tokens": int(outcome.cost.input_tokens),
                        "output_tokens": int(outcome.cost.output_tokens),
                    },
                }
            )
        )
        return "\n".join(lines) + "\n"

    def _validator_events(self, task: TaskId, outcome: MockOutcome) -> list[dict[str, Any]]:
        """Stop-hook decisions, in ``verify_outputs.py``'s own log shape.

        One record per hook invocation: ``blocks`` blocks then a terminal
        decision. Timestamps come off :data:`EPOCH`, not the clock, because two
        identical runs must produce identical rollouts.
        """
        events: list[dict[str, Any]] = []
        categories = ["missing_section", "parse_error", "constraints"]
        for i in range(outcome.blocks):
            events.append(
                {
                    "timestamp": (EPOCH + timedelta(seconds=60 * (i + 1))).isoformat(),
                    "decision": "block",
                    "reason_category": categories[i % len(categories)],
                    "retries_so_far": i,
                    "detail": f"{task}: repair attempt {i + 1}",
                }
            )
        events.append(
            {
                "timestamp": (EPOCH + timedelta(seconds=60 * (outcome.blocks + 1))).isoformat(),
                "decision": "allow",
                "reason_category": outcome.zero_reason or "allow",
                "retries_so_far": outcome.blocks,
                "detail": "",
            }
        )
        return events
