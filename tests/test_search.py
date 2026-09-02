"""End-to-end tests for the search loop.

The predecessor system was never tested end-to-end, and as a direct consequence
ran three rounds of "self-evolution" with a reward channel that returned nothing
for every task -- a fact recoverable from its own committed metadata, but which
no test and no report would have surfaced. These tests exist so that class of
failure cannot recur silently: the loop is exercised against a fully synthetic
problem with a *known* optimum, using local fakes rather than the real runner or
simulator, so it runs offline in milliseconds.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import pytest

from harness_evolve.core.acceptance import RegressionGate
from harness_evolve.core.candidate import Candidate
from harness_evolve.core.decision import EditType, classify_edit, content_hash
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy
from harness_evolve.core.search import Search, SearchConfig
from harness_evolve.proposers.base import Demonstration, ProposerError
from harness_evolve.proposers.scripted import RandomEditProposer, ScriptedProposer
from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import Cost, Rollout, Score

TASKS = ["t_alpha", "t_beta", "t_gamma", "t_delta"]

#: The synthetic problem: each task is "solved" by a keyword appearing in the
#: adapter. A task whose keyword is absent scores low and can terminate at zero,
#: which is what makes this a tail-driven problem rather than a smooth one.
KEYWORDS = {"t_alpha": "alpha", "t_beta": "beta", "t_gamma": "gamma", "t_delta": "delta"}


def make_manifest(memory_budget: int = 200) -> Manifest:
    return Manifest(
        components={
            "primer": ComponentSpec("primer", "prose", path="PRIMER.md",
                                    budget_tokens=100),
            "memory": ComponentSpec("memory", "itemized", path="memory/cheat.md",
                                    budget_tokens=memory_budget),
            "stop_policy": ComponentSpec("stop_policy", "config"),
        },
        stop_policy=StopPolicy(retries=2, checks=("parse",)),
    )


def make_seed(memory: str = "- general advice") -> Candidate:
    return Candidate(
        manifest=make_manifest(),
        files={"PRIMER.md": "seed", "memory/cheat.md": memory},
    )


@dataclass
class FakeRunner(RolloutRunner):
    """Deterministic scorer: keyword coverage, with a zero-score tail.

    ``zero_without_keyword`` is the knob that makes this a reliability problem.
    When set, a task whose keyword is missing does not merely score low -- it
    terminates at zero, mirroring the empty/unparseable outputs that the real
    adapters exist to prevent and that drive the whole variance story.
    """

    zero_without_keyword: bool = True
    cost_per_token: float = 0.01
    calls: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(deterministic=True, usd_per_task_run=0.0)

    def run(self, candidate: Candidate, task: str, seed: int = 1) -> Rollout:
        self.calls.append((candidate.cid, task, seed))
        text = " ".join(candidate.files.values()).lower()
        has = KEYWORDS[task] in text
        if has:
            value = 0.9
        elif self.zero_without_keyword:
            value = 0.0
        else:
            value = 0.4
        # Longer adapters cost more, so the efficiency clause has something to
        # bite on -- an adapter that wins by bloating must be rejectable.
        tokens = len(text) / 4
        return Rollout(
            task=task,
            candidate_id=candidate.cid,
            seed=seed,
            score=Score(task, value, "success" if value else "failed_no_outputs"),
            cost=Cost(tool_calls=10 + tokens * self.cost_per_token,
                      wall_seconds=60.0),
        )


# ---------------------------------------------------------------------------
# the loop finds the thing
# ---------------------------------------------------------------------------

def test_search_finds_the_improvement():
    runner = FakeRunner()
    # Each scripted edit adds one keyword; every one should be accepted.
    script = [
        ("memory", "- general advice\n- alpha handling",
         {"targets_category": "missing_block", "predicted_beneficiaries": ["t_alpha"]}),
        ("memory", "- general advice\n- alpha handling\n- beta handling",
         {"targets_category": "missing_block", "predicted_beneficiaries": ["t_beta"]}),
    ]
    search = Search(
        runner, ScriptedProposer(script=script),
        config=SearchConfig(budget_candidates=2, seeds=(1,), screen_tasks=0),
    )
    result = search.run(make_seed(), TASKS)

    assert result.n_proposed == 2
    assert result.best is not None
    assert result.best.mean > search.archive.entries[0].mean
    assert search.log.acceptance_rate() == 1.0


def test_regression_is_rejected_even_when_the_mean_rises():
    """The tail-driven criterion, on a case where a mean gate would say yes."""
    runner = FakeRunner()
    seed = make_seed("- general advice\n- alpha handling\n- beta handling")
    # Drops beta (a zero-score regression) while adding gamma and delta.
    script = [(
        "memory",
        "- general advice\n- alpha handling\n- gamma handling\n- delta handling",
        {"targets_category": "missing_block",
         "predicted_beneficiaries": ["t_gamma", "t_delta"]},
    )]
    search = Search(
        runner, ScriptedProposer(script=script),
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0),
    )
    result = search.run(seed, TASKS)

    rec = search.log.records[-1]
    assert not rec.accepted
    assert any("failures-as-zero" in r or "per-task regression" in r
               for r in rec.reasons)
    # The mean genuinely improved; the gate rejected anyway. That is the point.
    child = [e for e in search.archive.entries if not e.accepted][-1]
    assert child.mean > search.archive.entries[0].mean


def test_screening_saves_rollouts():
    """A clearly-bad child must die on the cheap pass, not the full one."""
    seed = make_seed("- general advice\n- alpha handling\n- beta handling\n"
                     "- gamma handling\n- delta handling")
    script = [("memory", "- general advice",
               {"targets_category": "extra_block",
                "predicted_beneficiaries": ["t_alpha"]})]

    screened = Search(
        FakeRunner(), ScriptedProposer(script=list(script)),
        config=SearchConfig(budget_candidates=1, seeds=(1, 2), screen_tasks=2,
                            screen_seeds=(1,)),
    )
    screened_result = screened.run(seed, TASKS)
    assert screened_result.n_screened_out == 1

    unscreened = Search(
        FakeRunner(), ScriptedProposer(script=list(script)),
        config=SearchConfig(budget_candidates=1, seeds=(1, 2), screen_tasks=0),
    )
    unscreened.run(seed, TASKS)

    n_screened = len(screened.runner.calls)
    n_unscreened = len(unscreened.runner.calls)
    assert n_screened < n_unscreened, (
        f"screening spent {n_screened} rollouts vs {n_unscreened} unscreened"
    )


def test_pareto_frontier_retains_a_specialist():
    """A candidate that is best on exactly one task must stay selectable."""
    runner = FakeRunner()
    seed = make_seed("- general advice\n- alpha handling")
    script = [
        # Trades alpha for beta: not better on average, but uniquely best on beta.
        ("memory", "- general advice\n- beta handling",
         {"targets_category": "missing_block", "predicted_beneficiaries": ["t_beta"]}),
    ]
    search = Search(
        runner, ScriptedProposer(script=script),
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0,
                            stagnation_rounds=99),
    )
    search.run(seed, TASKS)
    # Rejected by the gate, so not on the accepted frontier -- but the archive
    # keeps it, which is what makes recombination possible later.
    assert len(search.archive.entries) == 2


def test_hygiene_block_costs_no_rollouts():
    """A contaminated proposal must die before anything is spent on it."""

    class Blocked:
        blocked = True
        findings = ["names 17 task ids: looks like a task->answer lookup table"]

    runner = FakeRunner()
    script = [("memory", "- leak", {"targets_category": "missing_block"})]
    search = Search(
        runner, ScriptedProposer(script=script),
        hygiene=lambda c: Blocked(),
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0),
    )
    seed = make_seed()
    result = search.run(seed, TASKS)

    assert result.n_hygiene_blocked == 1
    # Only the seed's own evaluation ran.
    assert {cid for cid, _, _ in runner.calls} == {seed.cid}


def test_proposer_failures_do_not_burn_the_budget():
    search = Search(
        FakeRunner(), ScriptedProposer(script=[]),
        config=SearchConfig(budget_candidates=20, seeds=(1,), screen_tasks=0,
                            max_consecutive_proposer_failures=3),
    )
    result = search.run(make_seed(), TASKS)
    assert result.n_proposer_failures == 3
    assert result.n_proposed == 3
    assert any("consecutive proposer failures" in n for n in result.notes)


def test_stagnation_is_detected():
    """A strict gate makes 'nothing accepted' the steady state; say so."""
    seed = make_seed("- general advice\n- alpha handling\n- beta handling\n"
                     "- gamma handling\n- delta handling")
    script = [
        ("memory", f"- general advice\n- alpha handling\n- pad {i}",
         {"targets_category": "extra_block"})
        for i in range(4)
    ]
    search = Search(
        FakeRunner(), ScriptedProposer(script=script),
        config=SearchConfig(budget_candidates=4, seeds=(1,), screen_tasks=0,
                            stagnation_rounds=2),
    )
    result = search.run(seed, TASKS)
    assert result.stagnated
    assert search.log.acceptance_rate() == 0.0


def test_empty_anchor_is_refused():
    search = Search(FakeRunner(), ScriptedProposer(script=[]))
    with pytest.raises(ValueError, match="anchor slice is empty"):
        search.run(make_seed(), [])


def test_random_proposer_respects_the_interface():
    """The control condition must be a real control: same rules, no judgement."""
    search = Search(
        FakeRunner(), RandomEditProposer(lines=["- alpha handling", "- beta handling"]),
        config=SearchConfig(budget_candidates=6, seeds=(1,), screen_tasks=0),
    )
    result = search.run(make_seed(), TASKS)
    assert result.n_proposed == 6
    assert len(search.log.records) >= 1
    for rec in search.log.records:
        assert rec.prediction is not None
        assert rec.component in ("primer", "memory")


def test_demonstrations_reach_the_proposer():
    seen: list[int] = []

    class Recording(ScriptedProposer):
        def propose(self, parent, evidence=None, history=(), demonstrations=()):
            seen.append(len(demonstrations))
            return super().propose(parent, evidence, history, demonstrations)

    search = Search(
        FakeRunner(),
        Recording(script=[("memory", "- general advice\n- alpha handling",
                           {"targets_category": "missing_block"})]),
        demonstrations=[Demonstration("t_alpha", "expert used an analogous deck")],
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0),
    )
    search.run(make_seed(), TASKS)
    assert seen == [1]


# ---------------------------------------------------------------------------
# accounting
# ---------------------------------------------------------------------------

def test_cost_is_accounted():
    runner = FakeRunner()
    search = Search(
        runner, ScriptedProposer(script=[("memory", "- general advice\n- alpha handling",
                                          {"targets_category": "missing_block"})]),
        config=SearchConfig(budget_candidates=1, seeds=(1, 2), screen_tasks=0),
    )
    result = search.run(make_seed(), TASKS)
    # Seed (4 tasks x 2 seeds) + child (4 x 2) = 16 rollouts, all accounted.
    assert len(runner.calls) == 16
    assert result.total_cost.tool_calls > 0
    assert result.total_cost.wall_seconds == pytest.approx(16 * 60.0)


def test_cycling_is_detected():
    """Search that re-proposes discarded content is oscillating, not exploring."""
    a = "- general advice"
    b = "- general advice\n- alpha handling"
    assert classify_edit(a, b) is EditType.ADD
    assert classify_edit(b, a, seen_hashes=[content_hash(a)]) is EditType.REVERT


def test_unearned_edit_is_flagged():
    runner = FakeRunner(zero_without_keyword=False)
    # Claims to help t_beta; actually adds alpha. Accepted, prediction missed.
    script = [("memory", "- general advice\n- alpha handling",
               {"targets_category": "missing_block",
                "predicted_beneficiaries": ["t_beta"]})]
    search = Search(
        runner, ScriptedProposer(script=script),
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0),
    )
    search.run(make_seed(), TASKS)
    rec = search.log.records[-1]
    assert rec.accepted
    assert rec.prediction_hit_rate == 0.0
    assert rec.is_unearned
    assert search.log.unearned_edits()


# ---------------------------------------------------------------------------
# slice discipline
# ---------------------------------------------------------------------------

def test_probe_rollouts_never_reach_selection():
    """Probe exists to show the proposer fresh failures, not to be scored on.

    Selecting on data that was also handed to the proposer as evidence produces
    a search that looks like it is improving and has only memorised its own
    feedback -- a failure no downstream metric surfaces.
    """
    runner = FakeRunner()
    search = Search(
        runner,
        ScriptedProposer(script=[("memory", "- general advice\n- alpha handling",
                                  {"targets_category": "missing_block"})]),
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0,
                            probe_tasks=1, probe_every=1),
    )
    result = search.run(make_seed(), TASKS[:2], probe_tasks=TASKS[2:])

    assert result.n_probe_rollouts == 1
    for entry in search.archive.entries:
        # Only anchor tasks may carry scores that a gate can read.
        assert set(entry.scores) <= set(TASKS[:2])


def test_overlapping_slices_are_refused():
    search = Search(FakeRunner(), ScriptedProposer(script=[]))
    with pytest.raises(ValueError, match="overlap"):
        search.run(make_seed(), TASKS[:2], probe_tasks=TASKS[1:3])


def test_a_non_anchor_rollout_cannot_be_scored():
    """Belt-and-braces: even a misbehaving runner cannot smuggle one in."""
    from dataclasses import replace as _replace

    class MislabelingRunner(FakeRunner):
        def run(self, candidate, task, seed=1):
            return _replace(super().run(candidate, task, seed), slice="held_out")

    search = Search(MislabelingRunner(), ScriptedProposer(script=[]))
    # _evaluate re-tags to "anchor", so the guard is not reachable through the
    # normal path -- assert the guard itself rather than pretending otherwise.
    from harness_evolve.types import Rollout, Score
    bad = Rollout("t", "c", 1, Score("t", 0.9), slice="probe")
    assert not bad.selectable


def test_search_records_every_rollout_including_rejected_ones():
    """A search that counts only its successes understates its own budget, which
    is the accounting error that makes "evolution beat the baseline" mean
    "evolution had more inference compute"."""
    from harness_evolve.evaluation.baselines import BudgetLedger

    ledger = BudgetLedger()
    runner = FakeRunner()
    seed = make_seed("- general advice\n- alpha handling\n- beta handling\n"
                     "- gamma handling\n- delta handling")
    # A strictly worse child: will be rejected, but its rollouts were still spent.
    search = Search(
        runner,
        ScriptedProposer(script=[("memory", "- general advice",
                                  {"targets_category": "extra_block"})]),
        ledger=ledger,
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0),
    )
    result = search.run(seed, TASKS)

    assert not search.log.records[-1].accepted
    recorded = sum(e.rollouts for e in ledger.entries if e.arm == "search")
    assert recorded == len(runner.calls), (
        f"ledger recorded {recorded} of {len(runner.calls)} rollouts actually run"
    )


def test_gate_tolerates_an_unlucky_seed_but_not_a_real_cliff():
    """With stochastic zero-score terminations, every candidate acquires a fresh
    zero somewhere by chance. A gate reading seed means treats that as a
    property of the adapter and rejects nearly everything, including real
    improvements -- which is what the integration test surfaced."""
    from harness_evolve.core.acceptance import RegressionGate

    gate = RegressionGate()
    # Child is better at its best seed; one unlucky rollout dragged the mean.
    noisy = gate.evaluate(
        {"a": 0.90, "b": 0.45}, {"a": 0.80, "b": 0.85},
        child_by_seed={"a": [0.90, 0.90], "b": [0.90, 0.0]},
        parent_by_seed={"a": [0.80, 0.80], "b": [0.85, 0.85]},
    )
    assert noisy.accepted, noisy.reason
    assert "b" in noisy.metrics.get("tolerated_as_noise", [])
    # Judged on achievable quality, with reliability handled separately.
    assert noisy.metrics["aggregate_basis"] == "best-of-seeds"

    # Child fails at every seed on a task the parent always handled.
    real = gate.evaluate(
        {"a": 0.90, "b": 0.0}, {"a": 0.80, "b": 0.85},
        child_by_seed={"a": [0.90, 0.90], "b": [0.0, 0.0]},
        parent_by_seed={"a": [0.80, 0.80], "b": [0.85, 0.85]},
    )
    assert not real.accepted


def test_without_per_seed_data_the_gate_stays_conservative():
    """'Cannot tell' must read as 'assume real' for a gate whose job is
    preventing catastrophic regressions."""
    from harness_evolve.core.acceptance import RegressionGate

    r = RegressionGate().evaluate({"a": 0.9, "b": 0.45}, {"a": 0.8, "b": 0.85})
    assert not r.accepted


def test_cumulative_drift_from_the_seed_is_bounded():
    """Per-step gating does not bound where a lineage ends up.

    Each step here is individually acceptable against its immediate parent, and
    the sequence walks reliability steadily downhill. This is not hypothetical:
    the first end-to-end run produced a winner whose zero rate was four times the
    seed's, with every accepted candidate having passed its parent comparison.
    """
    from harness_evolve.core.acceptance import RegressionGate

    gate = RegressionGate()
    root = {"a": 0.90, "b": 0.90, "c": 0.90}
    # The lineage has already drifted on c; this step drifts a little further
    # while gaining elsewhere, so it passes every parent-relative clause.
    parent = {"a": 0.90, "b": 0.90, "c": 0.835}
    child = {"a": 0.95, "b": 0.95, "c": 0.790}

    without_root = gate.evaluate(child, parent)
    assert without_root.accepted, "each step is fine against its parent"

    with_root = gate.evaluate(child, parent, root_scores=root)
    assert not with_root.accepted
    assert "cumulative regression vs seed" in with_root.reason


def test_a_lineage_may_not_end_with_more_zeros_than_it_started_with():
    """Suppressing zero-score terminations is the entire point of the adapter.
    A lineage that ends with more of them has lost the plot whatever its mean
    did."""
    from harness_evolve.core.acceptance import RegressionGate

    r = RegressionGate().evaluate(
        {"a": 0.95, "b": 0.0}, {"a": 0.60, "b": 0.0},
        root_scores={"a": 0.60, "b": 0.60},
    )
    assert not r.accepted
    assert "cumulative reliability drift" in r.reason


def test_ordinary_progress_is_not_blocked_by_the_root_guard():
    from harness_evolve.core.acceptance import RegressionGate

    r = RegressionGate().evaluate(
        {"a": 0.95, "b": 0.88}, {"a": 0.90, "b": 0.86},
        root_scores={"a": 0.80, "b": 0.85},
    )
    assert r.accepted, r.reason


def test_the_root_guard_tolerates_noise_like_the_per_step_guard():
    """The cumulative clause compared seed means with no noise tolerance, so a
    single unlucky rollout anywhere in a lineage rejected candidates that were
    behaviourally identical to accepted ones — including genuine tail rescues,
    which is the effect the search exists to find."""
    from harness_evolve.core.acceptance import RegressionGate

    gate = RegressionGate()
    root = {"a": 0.90, "b": 0.90}
    parent = {"a": 0.90, "b": 0.88}
    # Child is better than root at its best seed on b; one unlucky draw dragged
    # the mean well below the cumulative limit.
    child = {"a": 0.95, "b": 0.45}

    verdict = gate.evaluate(
        child, parent, root_scores=root,
        child_by_seed={"a": [0.95, 0.95], "b": [0.92, 0.0]},
        parent_by_seed={"a": [0.90, 0.90], "b": [0.88, 0.88]},
        root_by_seed={"a": [0.90, 0.90], "b": [0.90, 0.90]},
    )
    assert verdict.accepted, verdict.reason
    assert any("vs root" in x for x in verdict.metrics.get("tolerated_as_noise", []))


def test_the_root_guard_still_catches_a_real_cumulative_regression():
    from harness_evolve.core.acceptance import RegressionGate

    verdict = RegressionGate().evaluate(
        {"a": 0.95, "b": 0.45}, {"a": 0.90, "b": 0.50},
        root_scores={"a": 0.90, "b": 0.90},
        child_by_seed={"a": [0.95, 0.95], "b": [0.45, 0.45]},
        parent_by_seed={"a": [0.90, 0.90], "b": [0.50, 0.50]},
        root_by_seed={"a": [0.90, 0.90], "b": [0.90, 0.90]},
    )
    assert not verdict.accepted
    assert "cumulative regression vs seed" in verdict.reason


def test_a_hygiene_rejection_names_the_finding_that_actually_blocked():
    """Warnings never block, so reporting findings[0] points at the wrong file.

    Observed live on 2026-08-26: a candidate blocked by a task-id leak in
    `memory/cheatsheet.md` was logged as "names ground-truth directory component
    'inputs'" in `PRIMER.md` -- a benign warning from whichever rule happened to
    run first. The decision log is the audit trail; pointing it at the wrong
    cause is worse than saying nothing.
    """
    from harness_evolve.types import Finding

    @dataclass
    class Report:
        findings: list = field(default_factory=list)

        @property
        def errors(self):
            return [f for f in self.findings if f.severity == "error"]

        @property
        def blocked(self):
            return bool(self.errors)

    report = Report(findings=[
        Finding("path_component", "warn", "names 'inputs'", location="PRIMER.md:6"),
        Finding("task_id", "error", "names evaluation task id 'kgdToughnessDominated'",
                location="memory/cheatsheet.md:31"),
        Finding("rare_token_overlap", "error", "23 rare ground-truth identifiers",
                location="memory/cheatsheet.md"),
    ])

    search = Search(
        FakeRunner(),
        RandomEditProposer(lines=("- a new line",)),
        hygiene=lambda c: report,
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=1,
                            probe_tasks=0),
    )
    result = search.run(make_seed(), list(KEYWORDS)[:2])
    assert result.n_hygiene_blocked == 1
    reason = [e for e in search.archive.entries if not e.accepted][0].reason
    assert "task_id" in reason
    assert "rare_token_overlap" in reason
    assert "path_component" not in reason
