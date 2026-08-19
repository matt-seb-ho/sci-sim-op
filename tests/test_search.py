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
