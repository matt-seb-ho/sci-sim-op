"""Runner tests. All offline: no Docker, no network, no API key.

The point of this file is that the search loop can be exercised end to end
without spending anything. v1 could not be, and ran three rounds on a dead
reward channel.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from harness_evolve.core.candidate import Candidate
from harness_evolve.core.manifest import Manifest
from harness_evolve.runners.cached import (
    CachedRunner,
    CacheMiss,
    CorpusError,
    RolloutRecord,
)
from harness_evolve.runners.mock import MockRunner, MockWorld
from harness_evolve.runners.subprocess import (
    CommandResult,
    SubprocessRunner,
    SubprocessRunnerConfig,
)
from harness_evolve.simulators.base import Artifact, SimulatorSpec
from harness_evolve.types import Cost, Rollout, Score

# ---------------------------------------------------------------------------
# a minimal local simulator
#
# W2 owns `simulators/mock.py`; these tests code against the `SimulatorSpec`
# protocol only, so they neither depend on nor block that work.
# ---------------------------------------------------------------------------

SECTIONS = ("Solvers", "Mesh", "Events", "NumericalMethods", "ElementRegions", "Constitutive")


class FakeSpec(SimulatorSpec):
    """Structural scorer: what fraction of the reference's sections are present.

    Obeys failures-as-zero, which is what lets the mock runner express a zero
    termination as an empty workspace rather than by writing a 0 itself.
    """

    name = "fake"
    required_sections = SECTIONS

    def __init__(self) -> None:
        self.score_calls: list[tuple[Path, Path, str]] = []

    def parse(self, workspace: Path) -> Artifact:
        artifact = Artifact()
        for p in sorted(Path(workspace).glob("*.xml")):
            text = p.read_text()
            artifact.files[p.name] = text
            try:
                artifact.tree = ET.fromstring(text)
            except ET.ParseError as exc:
                artifact.parse_errors[p.name] = str(exc)
        return artifact

    def validate(self, artifact: Artifact, workspace: Path) -> list:
        return []

    def present_sections(self, artifact: Artifact) -> set[str]:
        out: set[str] = set()
        for text in artifact.files.values():
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                continue
            out |= {c.tag for c in root if isinstance(c.tag, str)}
        return out

    def score(self, generated: Path, ground_truth: Path, task: str) -> Score:
        self.score_calls.append((Path(generated), Path(ground_truth), task))
        artifact = self.parse(generated)
        if artifact.is_empty:
            return Score(task=task, value=0.0, status="empty_workspace")
        if artifact.parse_errors:
            return Score(task=task, value=0.0, status="parse_error")
        present = self.present_sections(artifact)
        return Score(task=task, value=len(present & set(SECTIONS)) / len(SECTIONS))


class RaisingSpec(FakeSpec):
    def score(self, generated: Path, ground_truth: Path, task: str) -> Score:
        raise RuntimeError("scorer blew up")


# ---------------------------------------------------------------------------
# candidate helpers
# ---------------------------------------------------------------------------

_MANIFEST = """
[meta]
generation = 0

[components.primer]
kind = "prose"
path = "PRIMER.md"
budget_tokens = 4000

[components.cheatsheet]
kind = "itemized"
path = "memory/cheatsheet.md"
budget_tokens = 4000

[components.stop_policy]
kind = "config"
retries = {retries}
feedback_shape = "{shape}"
checks = [{checks}]
"""


def make_candidate(
    primer: str = "Write a deck.",
    cheatsheet: str = "",
    *,
    retries: int = 2,
    checks: tuple[str, ...] = ("parse", "geosx_validate"),
    shape: str = "structured_errors",
) -> Candidate:
    manifest = Manifest.from_toml(
        _MANIFEST.format(
            retries=retries,
            shape=shape,
            checks=", ".join(f'"{c}"' for c in checks),
        )
    )
    return Candidate(
        manifest=manifest,
        files={"PRIMER.md": primer, "memory/cheatsheet.md": cheatsheet},
    )


def make_scaffolding(root: Path) -> Path:
    plugin = root / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "hooks" / "verify_outputs.py").write_text("# stop hook\n")
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text("{}\n")
    return plugin


# ===========================================================================
# MockRunner
# ===========================================================================


def test_mock_runner_is_deterministic(tmp_path: Path) -> None:
    runner = MockRunner(FakeSpec(), root=tmp_path)
    cand = make_candidate("mind the required sections and the materialList")

    first = runner.run(cand, "taskA", seed=3)
    second = runner.run(cand, "taskA", seed=3)

    assert first.score == second.score
    assert first.cost == second.cost
    assert first.validator_events == second.validator_events
    assert first.artifacts_dir == second.artifacts_dir
    assert Path(first.events_path).read_text() == Path(second.events_path).read_text()


def test_mock_runner_determinism_survives_a_fresh_instance(tmp_path: Path) -> None:
    # Determinism must come from the inputs, not from instance state: the
    # search loop constructs runners freely and paired statistics depend on
    # two processes agreeing.
    cand = make_candidate("materialList")
    a = MockRunner(FakeSpec(), root=tmp_path / "a").run(cand, "t", seed=1)
    b = MockRunner(FakeSpec(), root=tmp_path / "b").run(cand, "t", seed=1)
    assert a.score.value == b.score.value
    assert a.cost == b.cost
    assert a.validator_events == b.validator_events


def test_mock_runner_seeds_and_tasks_differ(tmp_path: Path) -> None:
    runner = MockRunner(FakeSpec(), root=tmp_path)
    cand = make_candidate()
    outcomes = {
        (t, s): runner.plan(cand, t, s).quality
        for t in ("t1", "t2", "t3")
        for s in (1, 2)
    }
    assert len(set(outcomes.values())) > 1


def test_mock_runner_delegates_scoring_to_the_simulator(tmp_path: Path) -> None:
    spec = FakeSpec()
    runner = MockRunner(spec, root=tmp_path)
    rollout = runner.run(make_candidate(), "taskA", seed=1)
    assert len(spec.score_calls) == 1
    generated, ground_truth, task = spec.score_calls[0]
    assert task == "taskA"
    assert generated.name == "inputs"
    assert (ground_truth / "reference.xml").is_file()
    # Provenance is attached, the number is not overwritten.
    assert "mock" in rollout.score.detail


def test_helpful_adapter_text_raises_score(tmp_path: Path) -> None:
    world = MockWorld(helpful_markers=("checklist", "materialList"), marker_gain=0.15)
    runner = MockRunner(FakeSpec(), root=tmp_path, world=world)
    plain = make_candidate("just do it")
    helpful = make_candidate("follow the checklist and check every materialList")

    for task in ("t1", "t2", "t3", "t4"):
        assert (
            runner.plan(helpful, task, 1).quality > runner.plan(plain, task, 1).quality
        )
    assert runner.run(helpful, "t1", 1).score.value >= runner.run(plain, "t1", 1).score.value


def test_overlong_adapter_costs_more_and_scores_no_better(tmp_path: Path) -> None:
    # The over-specification failure mode: v1's primer grew 270 B -> 3159 B
    # over three unmonitored rounds. A mock where length is free would let a
    # broken efficiency gate pass its tests.
    world = MockWorld(free_tokens=100)
    runner = MockRunner(FakeSpec(), root=tmp_path, world=world)
    short = make_candidate("materialList")
    long = make_candidate("materialList" + " padding words here" * 400)

    short_plan = runner.plan(short, "t1", 1)
    long_plan = runner.plan(long, "t1", 1)

    assert long_plan.over_tokens > 0 and short_plan.over_tokens == 0
    assert long_plan.cost.tool_calls > short_plan.cost.tool_calls
    assert long_plan.cost.usd > short_plan.cost.usd
    assert long_plan.quality < short_plan.quality


def test_zero_rate_knob_at_the_extremes(tmp_path: Path) -> None:
    # Guard reduction off, so the knob is the only thing moving the rate. A
    # manifest must declare at least one check, so every candidate carries some
    # guard; leaving it on here would test the guard, not the knob.
    cand = make_candidate()
    always = MockRunner(
        FakeSpec(), root=tmp_path / "a",
        world=MockWorld(zero_rate=1.0, guard_zero_reduction=0.0),
    )
    never = MockRunner(
        FakeSpec(), root=tmp_path / "n",
        world=MockWorld(zero_rate=0.0, guard_zero_reduction=0.0),
    )
    tasks = [f"t{i}" for i in range(40)]
    assert all(always.plan(cand, t, 1).is_zero for t in tasks)
    assert not any(never.plan(cand, t, 1).is_zero for t in tasks)


def test_zero_rate_knob_tracks_its_setting(tmp_path: Path) -> None:
    # Preventing zero-score terminations is the entire effect being studied, so
    # the search loop must be exercisable against a problem whose tail is the
    # signal. Guard reduction is switched off here so the rate is exactly the
    # knob.
    cand = make_candidate()
    tasks = [f"task{i:03d}" for i in range(300)]
    for rate, lo, hi in ((0.1, 15, 45), (0.3, 60, 120), (0.6, 150, 210)):
        runner = MockRunner(
            FakeSpec(),
            root=tmp_path / f"r{rate}",
            world=MockWorld(zero_rate=rate, guard_zero_reduction=0.0),
        )
        n_zero = sum(runner.plan(cand, t, 1).is_zero for t in tasks)
        assert lo <= n_zero <= hi, f"rate={rate} gave {n_zero}/300"


def test_stop_policy_guard_shrinks_the_tail(tmp_path: Path) -> None:
    # "Static hooks raise the floor" -- here that is a retry budget and enabled
    # checks pulling the zero rate down. If this stopped holding, the search
    # would have no reason to touch the stop policy at all.
    world = MockWorld(zero_rate=0.5)
    runner = MockRunner(FakeSpec(), root=tmp_path, world=world)
    unguarded = make_candidate(retries=0, checks=("parse",))
    guarded = make_candidate(retries=4, checks=("parse", "geosx_validate", "constraints"))
    tasks = [f"task{i:03d}" for i in range(200)]

    n_unguarded = sum(runner.plan(unguarded, t, 1).is_zero for t in tasks)
    n_guarded = sum(runner.plan(guarded, t, 1).is_zero for t in tasks)
    assert n_guarded < n_unguarded


def test_zero_termination_produces_an_unscorable_workspace(tmp_path: Path) -> None:
    spec = FakeSpec()
    runner = MockRunner(spec, root=tmp_path, world=MockWorld(zero_rate=1.0))
    rollout = runner.run(make_candidate(), "t1", seed=1)

    assert rollout.score.is_zero
    # The zero came from the simulator scoring a broken artifact, not from the
    # runner writing a 0. That is the difference between a mock and a fiction.
    assert rollout.score.status in ("empty_workspace", "parse_error")
    assert rollout.error in ("empty_workspace", "parse_error")


def test_zero_termination_still_costs_something(tmp_path: Path) -> None:
    runner = MockRunner(FakeSpec(), root=tmp_path, world=MockWorld(zero_rate=1.0))
    rollout = runner.run(make_candidate(), "t1", seed=1)
    assert rollout.cost.tool_calls > 0
    assert rollout.cost.usd > 0


def test_mock_emits_a_trajectory_and_validator_events(tmp_path: Path) -> None:
    runner = MockRunner(FakeSpec(), root=tmp_path)
    cand = make_candidate(retries=2, checks=("parse", "geosx_validate"))
    rollout = runner.run(cand, "t1", seed=1)

    records = [
        json.loads(line)
        for line in Path(rollout.events_path).read_text().splitlines()
        if line.strip()
    ]
    assert records[0]["type"] == "system"
    assert records[-1]["type"] == "result"
    n_tool_use = sum(
        1
        for r in records
        if r.get("type") == "assistant"
        for block in r["message"]["content"]
        if block["type"] == "tool_use"
    )
    assert n_tool_use == int(rollout.cost.tool_calls)

    decisions = [e["decision"] for e in rollout.validator_events]
    assert decisions[-1] == "allow"
    assert decisions.count("block") == runner.plan(cand, "t1", 1).blocks


def test_mock_reports_its_capabilities_honestly() -> None:
    caps = MockRunner(FakeSpec()).capabilities
    assert caps.deterministic is True
    assert caps.usd_per_task_run == 0.0
    assert MockRunner(FakeSpec()).preflight() == []


def test_run_many_covers_the_grid(tmp_path: Path) -> None:
    runner = MockRunner(FakeSpec(), root=tmp_path)
    rollouts = runner.run_many(make_candidate(), ["a", "b", "c"], seeds=[1, 2])
    assert len(rollouts) == 6
    assert {(r.task, r.seed) for r in rollouts} == {
        (t, s) for t in "abc" for s in (1, 2)
    }


# ===========================================================================
# CachedRunner
# ===========================================================================


def _rollout(cid: str, task: str, seed: int, value: float = 0.7) -> Rollout:
    return Rollout(
        task=task,
        candidate_id=cid,
        seed=seed,
        score=Score(task=task, value=value, detail={"note": "replayed"}),
        cost=Cost(tool_calls=42.0, usd=1.25),
        artifacts_dir="/somewhere",
        events_path="/somewhere/events.jsonl",
        validator_events=[{"decision": "block", "reason_category": "parse_error"}],
    )


def test_cached_runner_replays_faithfully(tmp_path: Path) -> None:
    cand = make_candidate()
    runner = CachedRunner.from_rollouts([_rollout(cand.cid, "t1", 1)])
    replayed = runner.run(cand, "t1", 1)

    assert replayed.score.value == 0.7
    assert replayed.cost.tool_calls == 42.0
    # Validator events survive the round trip: Rollout.to_dict() reduces them to
    # a count, and the stop-policy evidence would be gone if the corpus used it.
    assert replayed.validator_events == [
        {"decision": "block", "reason_category": "parse_error"}
    ]


def test_cached_runner_admits_it_cannot_execute() -> None:
    caps = CachedRunner().capabilities
    assert caps.can_execute is False
    assert caps.usd_per_task_run == 0.0


def test_cache_miss_raises_rather_than_defaulting() -> None:
    cand = make_candidate()
    other = make_candidate("different primer")
    runner = CachedRunner.from_rollouts([_rollout(cand.cid, "t1", 1)])

    with pytest.raises(CacheMiss) as exc:
        runner.run(cand, "t1", 2)
    assert "seed 2" in str(exc.value) and "[1]" in str(exc.value)

    with pytest.raises(CacheMiss) as exc:
        runner.run(cand, "t9", 1)
    assert "t1" in str(exc.value)

    with pytest.raises(CacheMiss) as exc:
        runner.run(other, "t1", 1)
    assert "no rollouts at all" in str(exc.value)
    assert "can_execute" in str(exc.value)


def test_cache_miss_is_catchable_as_keyerror() -> None:
    runner = CachedRunner()
    with pytest.raises(KeyError):
        runner.run(make_candidate(), "t1", 1)


def test_cached_runner_round_trips_through_a_corpus_file(tmp_path: Path) -> None:
    cand = make_candidate()
    rollouts = [_rollout(cand.cid, t, s) for t in ("t1", "t2") for s in (1, 2)]
    CachedRunner.write_corpus(tmp_path / "corpus" / "round1.jsonl", rollouts)

    runner = CachedRunner(tmp_path / "corpus")
    assert len(runner) == 4
    assert runner.preflight() == []
    assert runner.run(cand, "t2", 2).score.value == 0.7
    assert runner.missing(cand.cid, ["t1", "t2", "t3"], [1, 2]) == [
        (cand.cid, "t3", 1),
        (cand.cid, "t3", 2),
    ]


def test_corpus_records_without_a_score_are_rejected_at_load(tmp_path: Path) -> None:
    # A corpus entry with no score is the on-disk form of the v1 defect.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "bad.jsonl").write_text(
        json.dumps({"task": "t1", "candidate_id": "cand_x", "seed": 1, "score": {}}) + "\n"
    )
    with pytest.raises(CorpusError, match="no score value"):
        CachedRunner(corpus)


def test_cached_runner_reads_rollout_to_dict_shape() -> None:
    # `Rollout.to_dict()` is lossy but common; accept it and lose only the
    # validator events, rather than refusing the file.
    rec = RolloutRecord.from_dict(_rollout("cand_x", "t1", 1).to_dict())
    assert rec.to_rollout().score.value == 0.7
    assert rec.validator_events == []


def test_empty_corpus_preflight_explains_itself(tmp_path: Path) -> None:
    reasons = CachedRunner(tmp_path / "nope").preflight()
    assert any("does not exist" in r for r in reasons)
    assert any("empty" in r for r in reasons)


# ===========================================================================
# SubprocessRunner
# ===========================================================================


class FakeCommand:
    """Stand-in for the containerised harness. Records argv and env."""

    def __init__(self, result_dir: Path, *, returncode: int = 0, write: bool = True,
                 timed_out: bool = False) -> None:
        self.result_dir = result_dir
        self.returncode = returncode
        self.write = write
        self.timed_out = timed_out
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, argv, env, timeout, cwd) -> CommandResult:
        self.calls.append((list(argv), dict(env)))
        if self.write:
            inputs = self.result_dir / "inputs"
            inputs.mkdir(parents=True, exist_ok=True)
            (inputs / "deck.xml").write_text(
                "<Problem><Solvers/><Mesh/><Events/></Problem>"
            )
            (self.result_dir / "events.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "content": [
                                        {"type": "tool_use", "name": "Write", "input": {}}
                                    ]
                                },
                            }
                        )
                    ] * 3
                    + [
                        json.dumps(
                            {
                                "type": "result",
                                "total_cost_usd": 2.5,
                                "duration_ms": 90000,
                                "usage": {"input_tokens": 1000, "output_tokens": 200},
                            }
                        )
                    ]
                )
                + "\n"
            )
            (self.result_dir / ".verify_hook_events.jsonl").write_text(
                json.dumps({"decision": "block", "reason_category": "parse_error"}) + "\n"
            )
        return CommandResult(
            returncode=self.returncode,
            stderr="boom" if self.returncode else "",
            timed_out=self.timed_out,
        )


def _config(tmp_path: Path, task: str = "t1") -> SubprocessRunnerConfig:
    harness = tmp_path / "repo3"
    (harness / "scripts").mkdir(parents=True)
    (harness / "scripts" / "run_experiment.py").write_text("# launcher\n")
    (tmp_path / "experiments" / task).mkdir(parents=True)
    gt = tmp_path / "gt" / task
    gt.mkdir(parents=True)
    (gt / "reference.xml").write_text("<Problem/>")
    return SubprocessRunnerConfig(
        harness_root=harness,
        experiments_dir=tmp_path / "experiments",
        ground_truth_dir=tmp_path / "gt",
        results_root=tmp_path / "results",
        scaffolding_dir=make_scaffolding(tmp_path),
        adapter_root=tmp_path / "adapters",
        agent="agent_x",
        timeout_s=60.0,
    )


def test_subprocess_runner_exports_the_stop_policy(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate(retries=5, checks=("parse", "geosx_validate"), shape="errors_plus_tables")
    runner = SubprocessRunner(FakeSpec(), cfg)
    result_dir = runner.result_dir(runner.run_name(cand, 1), "t1")
    fake = FakeCommand(result_dir)
    runner = SubprocessRunner(FakeSpec(), cfg, command_runner=fake)

    runner.run(cand, "t1", seed=1)

    argv, env = fake.calls[0]
    assert env["GEOS_HOOK_MAX_RETRIES"] == "5"
    assert env["GEOS_HOOK_XMLLINT"] == "1"
    assert env["GEOS_EVOLVE_FEEDBACK_SHAPE"] == "errors_plus_tables"
    assert env["GEOS_EVOLVE_CHECKS"] == "parse,geosx_validate"
    assert env["HARNESS_EVOLVE_CANDIDATE"] == cand.cid
    assert env["HARNESS_EVOLVE_SEED"] == "1"

    assert "--include" in argv and argv[argv.index("--include") + 1] == "t1"
    assert argv[argv.index("--agents") + 1] == "agent_x"
    adapter_dir = Path(argv[argv.index("--plugin-dir") + 1])
    assert (adapter_dir / "hooks" / "verify_outputs.py").is_file()
    assert (adapter_dir / "PRIMER.md").is_file()
    # Also written inside the mounted adapter: repo3's docker_cmd.py forwards a
    # fixed GEOS_HOOK_* allowlist and would drop the GEOS_EVOLVE_* names.
    env_file = (adapter_dir / "stop_policy.env").read_text()
    assert "GEOS_EVOLVE_FEEDBACK_SHAPE=errors_plus_tables" in env_file


def test_stop_policy_with_validator_off_is_exported_too(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate(retries=0, checks=("parse",))
    runner = SubprocessRunner(FakeSpec(), cfg)
    fake = FakeCommand(runner.result_dir(runner.run_name(cand, 1), "t1"))
    runner = SubprocessRunner(FakeSpec(), cfg, command_runner=fake)
    runner.run(cand, "t1", 1)
    _, env = fake.calls[0]
    assert env["GEOS_HOOK_MAX_RETRIES"] == "0"
    assert env["GEOS_HOOK_XMLLINT"] == "0"


def test_nonzero_exit_still_yields_a_score(tmp_path: Path) -> None:
    # The v1 defect in miniature: the run failed, so scoring never happened, so
    # the loop consumed None. A failed run that produced output is still scored.
    cfg = _config(tmp_path)
    cand = make_candidate()
    runner = SubprocessRunner(FakeSpec(), cfg)
    fake = FakeCommand(runner.result_dir(runner.run_name(cand, 1), "t1"), returncode=1)
    runner = SubprocessRunner(FakeSpec(), cfg, command_runner=fake)

    rollout = runner.run(cand, "t1", 1)

    assert rollout.score.value > 0.0
    assert rollout.error is not None and "exited 1" in rollout.error
    assert rollout.score.detail["process_exit"] == 1


def test_timeout_yields_a_zero_not_an_exception(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate()
    runner = SubprocessRunner(FakeSpec(), cfg)
    fake = FakeCommand(
        runner.result_dir(runner.run_name(cand, 1), "t1"),
        returncode=124,
        write=False,
        timed_out=True,
    )
    runner = SubprocessRunner(FakeSpec(), cfg, command_runner=fake)

    rollout = runner.run(cand, "t1", 1)

    assert rollout.score.value == 0.0
    assert rollout.score.status == "no_workspace"
    assert rollout.error == "harness timed out"
    assert rollout.score.detail["timed_out"] is True


def test_empty_workspace_scores_zero_with_a_reason(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate()
    runner = SubprocessRunner(FakeSpec(), cfg)
    result_dir = runner.result_dir(runner.run_name(cand, 1), "t1")
    (result_dir / "inputs").mkdir(parents=True)

    fake = FakeCommand(result_dir, write=False)
    runner = SubprocessRunner(FakeSpec(), cfg, command_runner=fake)
    rollout = runner.run(cand, "t1", 1)
    assert (rollout.score.value, rollout.score.status) == (0.0, "empty_workspace")


def test_scorer_crash_is_a_zero_not_a_lost_rollout(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate()
    runner = SubprocessRunner(RaisingSpec(), cfg)
    fake = FakeCommand(runner.result_dir(runner.run_name(cand, 1), "t1"))
    runner = SubprocessRunner(RaisingSpec(), cfg, command_runner=fake)

    rollout = runner.run(cand, "t1", 1)
    assert rollout.score.status == "scorer_error"
    assert "scorer blew up" in rollout.score.detail["error"]


def test_cost_and_validator_events_come_off_disk(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate()
    runner = SubprocessRunner(FakeSpec(), cfg)
    fake = FakeCommand(runner.result_dir(runner.run_name(cand, 1), "t1"))
    runner = SubprocessRunner(FakeSpec(), cfg, command_runner=fake)

    rollout = runner.run(cand, "t1", 1)
    assert rollout.cost.tool_calls == 3.0
    assert rollout.cost.usd == 2.5
    assert rollout.cost.wall_seconds == 90.0
    assert rollout.validator_events[0]["reason_category"] == "parse_error"


def test_seeds_get_separate_result_namespaces(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cand = make_candidate()
    runner = SubprocessRunner(FakeSpec(), cfg)
    assert runner.run_name(cand, 1) != runner.run_name(cand, 2)
    assert cand.cid in runner.run_name(cand, 1)


def test_preflight_lists_reasons_instead_of_dying(tmp_path: Path) -> None:
    # This box has no Docker and no /data volume. preflight must say so, in a
    # list, without raising -- so a search can degrade to cached or mock rather
    # than discovering it mid-round.
    cfg = _config(tmp_path)
    cfg.data_volume = tmp_path / "no-such-volume"
    cfg.docker_binary = "definitely-not-a-real-binary"
    runner = SubprocessRunner(FakeSpec(), cfg)

    reasons = runner.preflight()
    assert any("docker binary" in r for r in reasons)
    assert any("data volume" in r for r in reasons)
    assert all(isinstance(r, str) for r in reasons)


def test_preflight_flags_a_missing_ground_truth(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.ground_truth_dir = tmp_path / "gone"
    reasons = SubprocessRunner(FakeSpec(), cfg).preflight()
    assert any("ground truth" in r for r in reasons)


def test_preflight_reports_an_unreachable_daemon(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.docker_binary = "sh"  # on PATH, so the probe is what decides
    runner = SubprocessRunner(
        FakeSpec(),
        cfg,
        command_runner=lambda argv, env, timeout, cwd: CommandResult(1, stderr="no daemon"),
    )
    assert any("daemon not reachable" in r for r in runner.preflight())


# ===========================================================================
# the deck-author seam
# ===========================================================================


def test_mock_runner_writes_a_format_the_paired_simulator_can_parse(tmp_path: Path) -> None:
    # The obvious pairing is MockRunner + the synthetic simulator plugin, and
    # if the runner wrote a format that plugin could not parse, every rollout
    # would score 0 while looking like it worked -- a broken reward channel of
    # exactly the kind this package exists to make impossible.
    mock_sim = pytest.importorskip("harness_evolve.simulators.mock")
    runner = MockRunner(
        mock_sim.MockSimulator(), root=tmp_path, world=MockWorld(zero_rate=0.0)
    )
    plain = make_candidate("just write something")
    helpful = make_candidate(
        "name every required section: Grid Schedule Materials Boundaries Outputs "
        "Solvers Regions, and check the materialList"
    )
    tasks = [f"t{i}" for i in range(8)]

    plain_scores = [runner.run(plain, t, 1).score for t in tasks]
    helpful_scores = [runner.run(helpful, t, 1).score for t in tasks]

    assert all(s.status == "success" for s in plain_scores + helpful_scores)
    assert all(s.value > 0.0 for s in plain_scores)
    mean = lambda xs: sum(s.value for s in xs) / len(xs)  # noqa: E731
    assert mean(helpful_scores) > mean(plain_scores)


def test_deck_author_is_an_overridable_seam(tmp_path: Path) -> None:
    from harness_evolve.runners.mock import DeckAuthor

    class Custom(DeckAuthor):
        def reference(self, task):
            return {"gt.txt": "reference"}

        def generated(self, task, outcome):
            return {"out.txt": f"quality={outcome.quality:.2f}"}

        def unparseable(self, task):
            return {"out.txt": "\x00"}

    runner = MockRunner(FakeSpec(), root=tmp_path, deck_author=Custom())
    rollout = runner.run(make_candidate(), "t1", 1)
    assert (Path(rollout.artifacts_dir) / "inputs" / "out.txt").read_text().startswith(
        "quality="
    )
    assert (tmp_path / "ground_truth" / "t1" / "gt.txt").is_file()
