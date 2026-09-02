"""Write-through recording: resume and offline re-analysis.

A search at a credible budget is 16 to 37 hours against a container, an external
API, and a machine that may reboot. A crash that forces a restart from zero does
not merely cost the hours -- it makes the experiment something nobody wants to
attempt twice, which is how protocols get quietly relaxed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_evolve.core.candidate import Candidate
from harness_evolve.core.manifest import ComponentSpec, Manifest
from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.runners.cached import CacheMiss
from harness_evolve.runners.recording import RecordingRunner
from harness_evolve.types import Cost, Rollout, Score

TASKS = ["t0", "t1", "t2"]


def make_candidate(text: str = "seed") -> Candidate:
    return Candidate(
        manifest=Manifest(
            components={"primer": ComponentSpec("primer", "prose", path="P.md")}
        ),
        files={"P.md": text},
    )


class CountingRunner(RolloutRunner):
    """Records how many times it was actually asked to do work."""

    def __init__(self, value: float = 0.7) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.value = value

    @property
    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(deterministic=True, usd_per_task_run=0.07)

    def run(self, candidate, task, seed=1):
        self.calls.append((candidate.cid, task, seed))
        return Rollout(
            task=task, candidate_id=candidate.cid, seed=seed,
            score=Score(task, self.value), cost=Cost(tool_calls=10.0),
            validator_events=[{"validator_output": f"note about {task}"}],
        )


class ExplodingRunner(CountingRunner):
    """Fails after ``n`` rollouts, the way a container or a quota does."""

    def __init__(self, fail_after: int) -> None:
        super().__init__()
        self.fail_after = fail_after

    def run(self, candidate, task, seed=1):
        if len(self.calls) >= self.fail_after:
            raise RuntimeError("container died")
        return super().run(candidate, task, seed)


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------

def test_a_restart_replays_instead_of_re_executing(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()

    first = CountingRunner()
    r1 = RecordingRunner(first, corpus)
    original = [r1.run(c, t, 1) for t in TASKS]
    assert len(first.calls) == 3
    assert r1.stats.executed == 3

    second = CountingRunner()
    r2 = RecordingRunner(second, corpus)
    replayed = [r2.run(c, t, 1) for t in TASKS]

    assert second.calls == [], "a resume must not re-execute recorded work"
    assert r2.stats.replayed == 3
    assert [x.score.value for x in replayed] == [x.score.value for x in original]


def test_a_crash_keeps_everything_completed_before_it(tmp_path):
    """The case this class exists for: the run dies partway and the completed
    rollouts must survive it."""
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()

    r1 = RecordingRunner(ExplodingRunner(fail_after=2), corpus)
    done = []
    for t in TASKS:
        try:
            done.append(r1.run(c, t, 1))
        except RuntimeError:
            break
    assert len(done) == 2

    survivor = CountingRunner()
    r2 = RecordingRunner(survivor, corpus)
    assert len(r2) == 2
    for t in TASKS:
        r2.run(c, t, 1)
    assert len(survivor.calls) == 1, "only the un-completed rollout should re-run"
    assert survivor.calls[0][1] == "t2"


def test_a_truncated_final_line_is_survivable(tmp_path):
    """A half-written last line is what an interrupted write looks like. It is
    the expected state after a crash, not an exceptional one."""
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    r1 = RecordingRunner(CountingRunner(), corpus)
    r1.run(c, "t0", 1)
    r1.run(c, "t1", 1)

    with corpus.open("a") as fh:
        fh.write('{"task": "t2", "candidate_id": "x", "se')  # torn write

    r2 = RecordingRunner(CountingRunner(), corpus)
    assert len(r2) == 2
    assert any("unreadable line" in n for n in r2.stats.notes)


def test_validator_events_survive_the_round_trip(tmp_path):
    """Stop-hook decisions are the evidence half the stop-policy search rests on;
    a corpus that drops them cannot support an offline re-analysis of it."""
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    RecordingRunner(CountingRunner(), corpus).run(c, "t0", 1)

    replayed = RecordingRunner(CountingRunner(), corpus).run(c, "t0", 1)
    assert replayed.validator_events
    assert "note about t0" in json.dumps(replayed.validator_events)


def test_a_different_candidate_is_not_confused_with_a_recorded_one(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    inner = CountingRunner()
    r = RecordingRunner(inner, corpus)
    r.run(make_candidate("seed"), "t0", 1)
    r.run(make_candidate("edited"), "t0", 1)
    assert len(inner.calls) == 2, "content-addressed ids must not collide"


def test_replay_can_be_turned_off_for_a_deliberate_re_measurement(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    RecordingRunner(CountingRunner(), corpus).run(c, "t0", 1)

    inner = CountingRunner()
    r = RecordingRunner(inner, corpus, replay=False)
    r.run(c, "t0", 1)
    assert len(inner.calls) == 1


# ---------------------------------------------------------------------------
# durability and honesty
# ---------------------------------------------------------------------------

def test_a_failed_write_keeps_the_rollout_and_counts_the_failure(tmp_path):
    """Losing the record of a completed rollout is bad; throwing away the rollout
    itself is worse. The default keeps the result and says so loudly."""
    corpus = tmp_path / "sub" / "rollouts.jsonl"
    r = RecordingRunner(CountingRunner(), corpus)
    corpus.parent.chmod(0o500)  # read-only directory
    try:
        out = r.run(make_candidate(), "t0", 1)
        assert out.score.value == 0.7, "the rollout itself must survive"
        assert r.stats.write_failures == 1
        assert "not resumable" in r.stats.summary()
    finally:
        corpus.parent.chmod(0o700)


def test_strict_writes_raises_when_resumability_matters_more(tmp_path):
    corpus = tmp_path / "sub" / "rollouts.jsonl"
    r = RecordingRunner(CountingRunner(), corpus, strict_writes=True)
    corpus.parent.chmod(0o500)
    try:
        with pytest.raises(Exception):
            r.run(make_candidate(), "t0", 1)
    finally:
        corpus.parent.chmod(0o700)


def test_preflight_reports_an_unwritable_corpus(tmp_path):
    corpus = tmp_path / "sub" / "rollouts.jsonl"
    r = RecordingRunner(CountingRunner(), corpus)
    corpus.parent.chmod(0o500)
    try:
        reasons = r.preflight()
        assert any("not writable" in x for x in reasons), reasons
        assert any("resumable" in x for x in reasons)
    finally:
        corpus.parent.chmod(0o700)


def test_resume_is_reported_rather_than_silent(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    RecordingRunner(CountingRunner(), corpus).run(c, "t0", 1)

    r = RecordingRunner(CountingRunner(), corpus)
    assert any("resuming from 1 recorded" in n for n in r.stats.notes)
    r.run(c, "t0", 1)
    assert "replayed from the corpus" in r.summary()


# ---------------------------------------------------------------------------
# offline re-analysis
# ---------------------------------------------------------------------------

def test_the_corpus_becomes_a_replay_only_runner(tmp_path):
    """The handoff to offline analysis: the rollouts are the expensive part, so
    every statistic computed from them should be free to recompute."""
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    r = RecordingRunner(CountingRunner(), corpus)
    for t in TASKS:
        r.run(c, t, 1)

    cached = r.as_cached()
    assert len(cached) == 3
    assert not cached.capabilities.can_execute
    assert cached.run(c, "t0", 1).score.value == 0.7
    with pytest.raises(CacheMiss):
        cached.run(c, "never_run", 1)


def test_coverage_answers_what_is_left(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    r = RecordingRunner(CountingRunner(), corpus)
    r.run(c, "t0", 1)
    r.run(c, "t0", 2)
    assert r.coverage(c.cid, TASKS, [1, 2]) == (2, 6)


# --------------------------------------------------------------------------
# The inference model is part of a rollout's identity.
#
# Found 2026-09-02 (worklog F1): the corpus carried 18 rollouts produced by
# `stealth/ox-alpha`, whose free window closed, and the replay key was
# (candidate, task, seed). A campaign on `z-ai/glm-5.3-flash` would therefore
# have replayed every one of them, reported them as glm-5.3-flash results, and
# looked completely normal doing it -- the seed baseline the whole search is
# measured against would have been another model's numbers. That is this
# project's characteristic defect (a plausible number, not a crash), so the
# behaviour is pinned in four directions rather than argued about.
# --------------------------------------------------------------------------


def test_a_rollout_recorded_on_another_model_is_not_replayed(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()

    old = RecordingRunner(CountingRunner(0.9), corpus, model="stealth/ox-alpha")
    old.run(c, "t0", 1)
    assert old.stats.executed == 1

    inner = CountingRunner(0.2)
    new = RecordingRunner(inner, corpus, model="z-ai/glm-5.3-flash")
    rollout = new.run(c, "t0", 1)

    assert new.stats.replayed == 0, "an ox-alpha rollout was replayed as glm"
    assert new.stats.executed == 1
    assert rollout.score.value == 0.2
    assert len(inner.calls) == 1


def test_a_rollout_recorded_on_the_same_model_is_still_replayed(tmp_path):
    # The resume must keep working -- the fix is a narrowing, not a disabling.
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    RecordingRunner(CountingRunner(0.9), corpus, model="z-ai/glm-5.3-flash").run(c, "t0", 1)

    inner = CountingRunner(0.2)
    resumed = RecordingRunner(inner, corpus, model="z-ai/glm-5.3-flash")
    rollout = resumed.run(c, "t0", 1)

    assert resumed.stats.replayed == 1
    assert resumed.stats.executed == 0
    assert rollout.score.value == 0.9
    assert inner.calls == []


def test_the_unreplayable_rows_are_reported_not_silently_ignored(tmp_path):
    # Silence here would be indistinguishable from the bug: the run would just
    # cost more than expected, with no statement of why.
    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    old = RecordingRunner(CountingRunner(), corpus, model="stealth/ox-alpha")
    for t in TASKS:
        old.run(c, t, 1)

    new = RecordingRunner(CountingRunner(), corpus, model="z-ai/glm-5.3-flash")
    note = "\n".join(new.stats.notes)
    assert "stealth/ox-alpha" in note
    assert "will NOT be replayed" in note
    assert new.coverage(c.cid, TASKS, [1]) == (0, 3)


def test_a_corpus_holding_two_models_refuses_to_guess(tmp_path):
    # Offline re-analysis defaults to ANY_MODEL for convenience on a
    # single-model corpus. On a mixed one it must not pick a condition.
    from harness_evolve.runners.cached import AmbiguousReplay, CachedRunner

    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    RecordingRunner(CountingRunner(0.9), corpus, model="stealth/ox-alpha").run(c, "t0", 1)
    RecordingRunner(CountingRunner(0.2), corpus, model="z-ai/glm-5.3-flash").run(c, "t0", 1)

    from harness_evolve.runners.cached import RolloutRecord

    both = CachedRunner(
        records=[
            RolloutRecord.from_dict(json.loads(line))
            for line in corpus.read_text().splitlines()
        ]
    )
    assert both.models() == ["stealth/ox-alpha", "z-ai/glm-5.3-flash"]
    with pytest.raises(AmbiguousReplay, match="recorded under 2 models"):
        both.run(c, "t0", 1)
