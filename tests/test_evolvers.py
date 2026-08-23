"""Can four evolution strategies be compared honestly at one enforced budget?

Every test here runs offline against the mock simulator and mock runner, in
seconds, at zero cost — the pattern ``tests/test_integration.py`` established.

What is being tested is not "does each method improve the score". At this sample
size no test could establish that, and a test suite that asserted it would be
asserting the thing the whole package exists to leave open. What is tested is
that the *comparison* is sound: that the budget is a cap rather than a
suggestion, that spend is counted including the candidates a method threw away,
that the methods differ in the ways they claim to differ, and — the one that
matters most — that a sophisticated method losing to random search is an outcome
this code can produce and report rather than one it structurally excludes.
"""

from __future__ import annotations

import pytest

from harness_evolve.core.acceptance import RegressionGate
from harness_evolve.core.candidate import Candidate
from harness_evolve.core.decision import DecisionLog, DecisionRecord, EditType, Prediction
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy
from harness_evolve.core.search import SearchConfig
from harness_evolve.evolvers import (
    AHEStyleEvolver,
    Evolver,
    BudgetExhausted,
    BudgetMismatch,
    BudgetedRunner,
    EditVocabulary,
    EvolverResult,
    EvolverTrace,
    RandomSearchEvolver,
    RolloutBudget,
    SearchEvolver,
    SkillOptEvolver,
    TaskSlices,
    compare_evolvers,
    default_schedule,
    evaluate_on,
)
from harness_evolve.proposers.scripted import RandomEditProposer
from harness_evolve.runners.mock import MockRunner, MockWorld
from harness_evolve.simulators.mock import MockSimulator

TASKS: tuple[str, ...] = tuple(f"task_{i}" for i in range(6))

#: Phrases the mock world rewards. The adapter has a gradient only because these
#: exist, and the vocabulary below is the only way to reach them.
MARKERS: tuple[str, ...] = ("alpha rule", "beta rule", "gamma rule")

#: The shared bounded move set. Three lines that help, two that do nothing —
#: so "the method found the useful line" and "the method added something" are
#: distinguishable outcomes.
LINES: tuple[str, ...] = (
    "- alpha rule applies here",
    "- beta rule applies here",
    "- gamma rule applies here",
    "- filler one",
    "- filler two",
)


def make_seed(memory: str = "- start here", primer: str = "author a valid deck") -> Candidate:
    """A two-text-component adapter: an itemized cheatsheet and a prose primer."""
    return Candidate(
        manifest=Manifest(
            components={
                "primer": ComponentSpec("primer", "prose", path="PRIMER.md",
                                        budget_tokens=300),
                "memory": ComponentSpec("memory", "itemized",
                                        path="memory/cheatsheet.md",
                                        budget_tokens=400),
                "stop_policy": ComponentSpec("stop_policy", "config"),
            },
            stop_policy=StopPolicy(retries=2, checks=("parse",)),
        ),
        files={"PRIMER.md": primer, "memory/cheatsheet.md": memory},
    )


def make_world(task_difficulty: dict[str, float] | None = None, **overrides) -> MockWorld:
    """A world with a clean, monotone gradient in the marker count.

    ``retry_quality_gain`` is off and noise and the zero rate are zero, so a
    failing test means a method is wrong rather than unlucky. The stop hook's
    repair gain is disabled specifically because it *compensates* for a weak
    adapter — a candidate with one fewer marker earns one more retry — which is
    a faithful thing for the mock to model and a terrible thing to build a
    determinism assumption on.
    """
    return MockWorld(
        helpful_markers=MARKERS,
        marker_gain=0.15,
        retry_quality_gain=0.0,
        noise=0.0,
        zero_rate=0.0,
        task_difficulty=(
            {"task_1": -0.25, "task_2": -0.20}
            if task_difficulty is None
            else task_difficulty
        ),
        **overrides,
    )


@pytest.fixture
def runner(tmp_path):
    return MockRunner(MockSimulator(), world=make_world(), root=tmp_path / "runs")


@pytest.fixture
def vocabulary() -> EditVocabulary:
    return EditVocabulary(lines=LINES, components=("memory",))


@pytest.fixture
def slices() -> TaskSlices:
    return TaskSlices.of(TASKS)


def all_arms(vocabulary: EditVocabulary):
    """One instance of every strategy, all drawing on the same move set."""
    return [
        SearchEvolver(proposer_factory=lambda: RandomEditProposer(lines=LINES)),
        SkillOptEvolver(vocabulary=vocabulary),
        AHEStyleEvolver(vocabulary=vocabulary),
        RandomSearchEvolver(vocabulary=vocabulary),
    ]


# ---------------------------------------------------------------------------
# the budget is a cap, not a suggestion
# ---------------------------------------------------------------------------


def test_every_arm_satisfies_the_protocol_without_declaring_it(vocabulary):
    """Structural, so an arm written elsewhere plugs in without importing us."""
    for arm in all_arms(vocabulary):
        assert isinstance(arm, Evolver), arm
    assert not isinstance(object(), Evolver)


def test_the_budget_refuses_the_rollout_that_would_cross_the_cap(runner):
    """Enforcement, at the only place a rollout can happen."""
    budget = RolloutBudget(cap=5)
    paid = BudgetedRunner(runner, budget, note="probe")
    seed = make_seed()

    for i in range(5):
        paid.run(seed, TASKS[i % len(TASKS)], seed=1)
    assert budget.spent == 5
    assert budget.exhausted

    with pytest.raises(BudgetExhausted):
        paid.run(seed, TASKS[0], seed=1)

    # The refused rollout was refused, not merely uncounted.
    assert budget.spent == 5
    assert budget.rollouts_by_note == {"probe": 5}
    assert budget.cost.tool_calls > 0


def test_a_batch_that_crosses_the_cap_keeps_what_it_spent(runner):
    """A refusal mid-batch must leave an honest ledger, not a rolled-back one."""
    budget = RolloutBudget(cap=4)
    paid = BudgetedRunner(runner, budget)

    with pytest.raises(BudgetExhausted):
        paid.run_many(make_seed(), TASKS, seeds=(1,))

    assert budget.spent == 4, "the four rollouts that ran are still spent"


def test_spend_counts_the_candidates_a_method_threw_away(runner, vocabulary, slices):
    """A method that counts only its successes understates its budget.

    SkillOpt is forced to reject everything here, so every rollout past the
    seed's belongs to a candidate that was discarded. All of it must appear in
    the ledger.
    """
    budget = RolloutBudget(cap=72)
    result = SkillOptEvolver(
        vocabulary=vocabulary, min_improvement=1.0
    ).evolve(make_seed(), slices, runner, budget)

    rejected = [e for e in result.archive.entries if not e.accepted]
    assert rejected, "the setup is wrong if nothing was rejected"
    assert result.returned_the_seed

    seed_cost = len(slices.split_anchor(hold_out=2).validation) * 2
    assert budget.spent == 72
    assert budget.spent > seed_cost
    # Both halves of a round are on the ledger, under their own labels.
    assert {"propose", "validate"} <= set(budget.rollouts_by_note)


def test_slices_refuse_to_overlap():
    """Selecting on a task that is also serving as evidence is not representable."""
    with pytest.raises(ValueError, match="overlap"):
        TaskSlices.of(TASKS, probe=(TASKS[0],))
    with pytest.raises(ValueError, match="overlap"):
        TaskSlices.of(TASKS, validation=(TASKS[1],))

    split = TaskSlices.of(TASKS).split_anchor(hold_out=2)
    assert not set(split.anchor) & set(split.validation)
    assert len(split.validation) == 2


# ---------------------------------------------------------------------------
# matched comparison
# ---------------------------------------------------------------------------


def test_every_method_runs_at_the_same_enforced_budget(runner, vocabulary, slices):
    """The comparison is only worth anything if the arms spent the same."""
    comparison = compare_evolvers(
        all_arms(vocabulary), make_seed(), slices, runner, budget_rollouts=96
    )

    assert comparison.matched
    assert set(comparison.spends) == {
        "gated_search", "skillopt", "ahe_component_wise", "random_search"
    }
    assert all(spent == 96 for spent in comparison.spends.values()), comparison.spends

    # Each arm can say why it chose what it chose, and the measurement that
    # ranks them was taken outside the search budget.
    for outcome in comparison.outcomes:
        assert outcome.result.trace.selection_reason
        assert outcome.common_score is not None
    assert comparison.measurement_budget is not None
    assert comparison.winner() is not None
    assert "MATCHED" in comparison.render()


class _EarlyStopper:
    """An arm that evaluates the seed and gives up. The failure being tested for."""

    name = "early_stopper"

    def evolve(self, seed, slices, runner, budget):
        paid = BudgetedRunner(runner, budget, note="seed")
        from harness_evolve.core.archive import Archive, ArchiveEntry

        archive = Archive()
        scores = evaluate_on(paid, seed, slices.anchor, (1,))
        entry = archive.add(ArchiveEntry(seed, scores=dict(scores.by_task), reason="seed"))
        return EvolverResult(
            method=self.name,
            selected=entry,
            archive=archive,
            budget=budget,
            trace=EvolverTrace(method=self.name, selection_reason="stopped early"),
        )


def test_the_comparison_refuses_when_one_arm_underspends(runner, vocabulary, slices):
    """An unmatched comparison is exactly the failure arXiv:2607.12227 names."""
    arms = [RandomSearchEvolver(vocabulary=vocabulary), _EarlyStopper()]

    with pytest.raises(BudgetMismatch) as caught:
        compare_evolvers(arms, make_seed(), slices, runner, budget_rollouts=96)

    # The refusal still hands back the diagnosis; re-running four searches to
    # find out which arm was short would cost the whole budget again.
    comparison = caught.value.comparison
    assert comparison.spends["early_stopper"] < comparison.spends["random_search"]
    assert not comparison.matched
    assert comparison.spread > comparison.tolerance


def test_an_unmatched_comparison_cannot_quietly_become_a_verdict(
    runner, vocabulary, slices
):
    """Waiving the refusal must not also waive the conclusion."""
    arms = [RandomSearchEvolver(vocabulary=vocabulary), _EarlyStopper()]
    comparison = compare_evolvers(
        arms, make_seed(), slices, runner, budget_rollouts=96, strict=False
    )

    assert not comparison.matched
    assert any("UNMATCHED" in n or "unmatched" in n for n in comparison.notes)
    with pytest.raises(BudgetMismatch):
        comparison.winner()


# ---------------------------------------------------------------------------
# SkillOpt: strict improvement on a slice that did not choose the edit
# ---------------------------------------------------------------------------


def test_skillopt_decides_on_a_slice_that_did_not_choose_the_edit(
    runner, vocabulary, slices
):
    """The separation is the method. It has to be real, not asserted."""
    budget = RolloutBudget(cap=96)
    result = SkillOptEvolver(vocabulary=vocabulary).evolve(
        make_seed(), slices, runner, budget
    )
    meta = result.trace.metadata

    propose, validation = set(meta["propose_tasks"]), set(meta["validation_tasks"])
    assert propose and validation
    assert not propose & validation
    assert meta["validation_source"] == "split_from_anchor"

    # Every score the archive selects on comes from the validation slice; the
    # propose slice never enters a selection decision.
    for entry in result.archive.entries:
        assert set(entry.scores) <= validation, entry.scores

    # And both halves were actually paid for, under their own labels.
    assert budget.rollouts_by_note["propose"] > 0
    assert budget.rollouts_by_note["validate"] > 0

    # Acceptance is strict: nothing lateral got in.
    for step in result.trace.steps:
        if step.phase == "validate" and step.accepted:
            assert step.metrics["gain"] > 0.0


def test_skillopt_returns_its_seed_when_nothing_strictly_improves(tmp_path, vocabulary):
    """The predicted outcome in a near-ceiling regime, reported as a result."""
    flat = MockRunner(
        MockSimulator(),
        world=MockWorld(helpful_markers=(), noise=0.0, zero_rate=0.0),
        root=tmp_path / "runs",
    )
    budget = RolloutBudget(cap=72)
    result = SkillOptEvolver(vocabulary=vocabulary).evolve(
        make_seed(), TaskSlices.of(TASKS), flat, budget
    )

    assert result.returned_the_seed
    assert len(result.archive.entries) > 1, "it looked, it just did not find anything"
    assert budget.spent == 72, "a null result still costs the full budget"
    assert "strict gain" in result.trace.selection_reason


# ---------------------------------------------------------------------------
# AHE: an explicit component schedule, predictions, consolidation
# ---------------------------------------------------------------------------


def test_ahe_visits_components_in_its_declared_schedule(runner, slices):
    """Component-wise, in a stated order — not wherever a proposer felt like."""
    vocab = EditVocabulary(lines=LINES)  # both text components in range
    seed = make_seed()
    assert default_schedule(seed, vocab) == ("memory", "primer"), (
        "list-structured components come before prose, per the ablation"
    )

    budget = RolloutBudget(cap=120)
    result = AHEStyleEvolver(
        vocabulary=vocab,
        component_schedule=("memory", "primer"),
        reorder_by_prediction=False,
        consolidate=False,
    ).evolve(seed, slices, runner, budget)

    visited = [
        s.component for s in result.trace.steps if s.phase in ("evaluate", "skip")
    ]
    assert len(visited) >= 4
    assert visited[:4] == ["memory", "primer", "memory", "primer"], visited
    assert result.trace.metadata["initial_schedule"] == ["memory", "primer"]
    assert result.trace.metadata["cycles"] >= 1


def test_ahe_reorders_the_schedule_by_prediction_accuracy():
    """Attention goes to the component the method has a working model of."""
    evolver = AHEStyleEvolver(vocabulary=EditVocabulary(lines=LINES))
    log = DecisionLog()
    for component, delta in (("primer", 0.2), ("memory", 0.0)):
        log.append(
            DecisionRecord(
                candidate_id=f"c_{component}",
                parent_id="seed",
                component=component,
                edit_type=EditType.ADD,
                prediction=Prediction(
                    component=component,
                    targets_category="missing_block",
                    predicted_beneficiaries=("task_0",),
                ),
                observed_deltas={"task_0": delta},
                accepted=True,
            )
        )

    trace = EvolverTrace(method="ahe")
    reordered = evolver._reorder(["memory", "primer"], log, trace, RolloutBudget(cap=1))

    assert reordered == ["primer", "memory"], (
        "primer predicted correctly and memory did not, so primer goes first"
    )
    assert any(s.phase == "reorder" for s in trace.steps)


def test_ahe_reordering_does_not_bury_a_component_it_has_never_visited():
    """An unmeasured component is not a badly-predicted one."""
    evolver = AHEStyleEvolver(vocabulary=EditVocabulary(lines=LINES))
    log = DecisionLog()
    log.append(
        DecisionRecord(
            candidate_id="c1", parent_id="seed", component="memory",
            edit_type=EditType.ADD,
            prediction=Prediction(component="memory", targets_category="missing_block",
                                  predicted_beneficiaries=("task_0",)),
            observed_deltas={"task_0": 0.0}, accepted=True,
        )
    )
    order = evolver._reorder(
        ["memory", "primer"], log, EvolverTrace(method="ahe"), RolloutBudget(cap=1)
    )
    assert order == ["primer", "memory"], (
        "the never-visited component outranks one measured to predict badly"
    )


def test_ahe_consolidation_declines_when_the_shorter_document_measures_worse(
    tmp_path, slices
):
    """The pruning pass is a measurement, not a policy of deleting things.

    Two of the six tasks are dead here — no adapter reaches them — so they are
    permanently the weakest, every edit predicts them, and every accepted edit
    is therefore *unearned* even when it raised the mean on tasks it never
    named. That is the hard case for a prune-the-unearned rule, and the right
    answer is to measure the stripped document and keep the incumbent.
    """
    world = make_world({"task_4": -1.0, "task_5": -1.0})
    runner = MockRunner(MockSimulator(), world=world, root=tmp_path / "runs")

    budget = RolloutBudget(cap=144)
    result = AHEStyleEvolver(
        vocabulary=EditVocabulary(lines=LINES, components=("memory",)),
        component_schedule=("memory",),
    ).evolve(make_seed(), slices, runner, budget)

    assert result.trace.metadata["unearned_edits"] > 0
    step = next(s for s in reversed(result.trace.steps) if s.phase == "consolidate")
    assert "stripped" in step.detail
    assert step.accepted is False
    assert step.metrics["mean_delta"] < 0
    assert not result.returned_the_seed, (
        "the run still improved; consolidation declined, it did not undo the search"
    )


def test_ahe_consolidation_strips_an_addition_that_earned_nothing_and_cost_nothing(
    tmp_path, slices
):
    """The other half of the same decision: an inert addition does not survive.

    Driven through :meth:`_consolidate` directly with a hand-built lineage,
    because reaching this state from a live run means winning a tie-break — the
    archive prefers the earlier of two candidates with equal means, which is
    itself the right behaviour and the reason the situation is rare.
    """
    from harness_evolve.core.archive import Archive, ArchiveEntry
    from harness_evolve.evolvers.base import apply_move
    from harness_evolve.proposers.edits import Edit, Op

    flat = MockRunner(
        MockSimulator(),
        world=MockWorld(helpful_markers=(), noise=0.0, zero_rate=0.0),
        root=tmp_path / "runs",
    )
    budget = RolloutBudget(cap=96)
    paid = BudgetedRunner(flat, budget)

    seed = make_seed()
    padded = apply_move(seed, Edit("memory", Op.ADD, text="- filler one")).child
    assert padded is not None

    archive = Archive()
    archive.add(ArchiveEntry(seed, scores=dict(
        evaluate_on(paid, seed, TASKS, (1,)).by_task), reason="seed"))
    scores = evaluate_on(paid, padded, TASKS, (1,))
    selected = archive.add(
        ArchiveEntry(padded, scores=dict(scores.by_task), accepted=True,
                     reason="lateral", generation=padded.generation)
    )

    log = DecisionLog()
    log.append(
        DecisionRecord(
            candidate_id=padded.cid, parent_id=seed.cid, component="memory",
            edit_type=EditType.ADD,
            prediction=Prediction(component="memory", targets_category="missing_block",
                                  predicted_beneficiaries=("task_0",)),
            observed_deltas={"task_0": 0.0}, accepted=True,
        )
    )
    assert log.unearned_edits()

    trace = EvolverTrace(method="ahe")
    evolver = AHEStyleEvolver(
        vocabulary=EditVocabulary(lines=LINES, components=("memory",)), seeds=(1,)
    )
    kept = evolver._consolidate(
        paid, archive, selected, log,
        {padded.cid: Edit("memory", Op.ADD, text="- filler one")},
        TASKS, trace, [], budget,
    )

    assert kept is not selected, "the shorter document measured no worse and wins"
    assert "- filler one" not in kept.candidate.files["memory/cheatsheet.md"]
    step = next(s for s in trace.steps if s.phase == "consolidate")
    assert step.accepted is True


def test_ahe_consolidation_ignores_edits_that_are_not_in_the_winner(tmp_path):
    """A rejected branch's unearned addition is not in the winning document.

    Deleting by fuzzy anchor is forgiving on purpose, which makes stripping an
    edit the winner never absorbed a real hazard: it can match a different line
    that merely reads like it.
    """
    from harness_evolve.core.archive import Archive, ArchiveEntry
    from harness_evolve.proposers.edits import Edit, Op

    flat = MockRunner(
        MockSimulator(),
        world=MockWorld(helpful_markers=(), noise=0.0, zero_rate=0.0),
        root=tmp_path / "runs",
    )
    budget = RolloutBudget(cap=96)
    paid = BudgetedRunner(flat, budget)
    seed = make_seed()

    archive = Archive()
    selected = archive.add(ArchiveEntry(seed, scores=dict(
        evaluate_on(paid, seed, TASKS, (1,)).by_task), reason="seed"))

    log = DecisionLog()
    log.append(
        DecisionRecord(
            candidate_id="cand_not_in_lineage", parent_id=seed.cid, component="memory",
            edit_type=EditType.ADD,
            prediction=Prediction(component="memory", targets_category="missing_block",
                                  predicted_beneficiaries=("task_0",)),
            observed_deltas={"task_0": 0.0}, accepted=True,
        )
    )

    trace = EvolverTrace(method="ahe")
    spent_before = budget.spent
    kept = AHEStyleEvolver(
        vocabulary=EditVocabulary(lines=LINES), seeds=(1,)
    )._consolidate(
        paid, archive, selected, log,
        {"cand_not_in_lineage": Edit("memory", Op.ADD, text="- filler one")},
        TASKS, trace, [], budget,
    )

    assert kept is selected
    assert budget.spent == spent_before, "nothing to strip must cost nothing"
    assert "no unearned addition survives" in trace.steps[-1].detail


# ---------------------------------------------------------------------------
# random search: the control, and the outcome that matters most
# ---------------------------------------------------------------------------


def test_random_search_keeps_what_a_gate_would_have_refused(runner, vocabulary, slices):
    """No gating is the definition of this arm, so it must be observable."""
    seed = make_seed("\n".join(LINES[:3]))
    budget = RolloutBudget(cap=96)
    result = RandomSearchEvolver(vocabulary=vocabulary).evolve(
        seed, slices, runner, budget
    )

    assert all(e.accepted for e in result.archive.entries)
    assert result.trace.metadata["gate"] is None

    root = result.archive.entries[0]
    worse = [e for e in result.archive.entries[1:] if e.mean < root.mean - 1e-9]
    assert worse, "deleting a useful line must be reachable, or this is a straw man"
    verdict = RegressionGate().evaluate(worse[0].scores, root.scores)
    assert not verdict.accepted, "the setup is wrong if the gate would have kept it"

    # Kept anyway, in the pool the final selection reads from.
    assert result.archive.get(worse[0].cid) is not None


def test_a_method_can_lose_to_random_search(tmp_path, vocabulary):
    """The single most important outcome this code must be able to produce.

    The construction is not a trick, it is the honest failure mode of holding
    data out at n=6. SkillOpt splits two tasks off the anchor to decide on, and
    here those two are already at ceiling — so no edit can ever show a strict
    gain on them and the method correctly, by its own rule, returns its seed.
    Random search selects on all six tasks, four of which have headroom, and
    finds the useful lines.

    Holding out is the right thing to do when there is data to hold out. This
    test is the record that in a sample-starved regime it can cost more than it
    buys, and that the comparison harness will say so.
    """
    split = TaskSlices.of(TASKS).split_anchor(hold_out=2)
    at_ceiling = {t: 0.60 for t in split.validation}
    world = make_world({**at_ceiling, "task_1": -0.25, "task_2": -0.20})
    runner = MockRunner(MockSimulator(), world=world, root=tmp_path / "runs")

    comparison = compare_evolvers(
        [SkillOptEvolver(vocabulary=vocabulary), RandomSearchEvolver(vocabulary=vocabulary)],
        make_seed(),
        TaskSlices.of(TASKS),
        runner,
        budget_rollouts=96,
    )

    assert comparison.matched, comparison.spends
    winner = comparison.winner()
    assert winner.name == "random_search", comparison.render()

    skillopt = next(o for o in comparison.outcomes if o.name == "skillopt")
    assert skillopt.returned_the_seed
    assert winner.common_score > skillopt.common_score


# ---------------------------------------------------------------------------
# the arm that wraps the loop this repository already had
# ---------------------------------------------------------------------------


def test_the_gated_search_arm_reports_the_loop_it_wraps(runner, slices, tmp_path):
    """Wrapping must not lose the accounting the search loop already produced."""
    budget = RolloutBudget(cap=96)
    result = SearchEvolver(
        proposer_factory=lambda: RandomEditProposer(lines=LINES),
        config=SearchConfig(budget_candidates=50, seeds=(1, 2), screen_tasks=2),
        decision_log_path=tmp_path / "decisions.jsonl",
    ).evolve(make_seed(), slices, runner, budget)

    assert budget.spent == 96
    assert len(result.archive.entries) > 1
    assert result.trace.phases()[0] == "seed"
    assert set(result.trace.phases()) & {"accept", "reject"}
    assert "calibration" in result.trace.metadata
    assert "gate" in result.trace.metadata

    # The decision log the loop writes is still written.
    rows = (tmp_path / "decisions.jsonl").read_text().splitlines()
    assert rows and all("prediction" in r for r in rows)


def test_the_gated_search_arm_stops_on_the_cap_rather_than_dying_on_it(runner, slices):
    """The cap is a normal operating condition, not an error."""
    budget = RolloutBudget(cap=20)
    result = SearchEvolver(
        proposer_factory=lambda: RandomEditProposer(lines=LINES)
    ).evolve(make_seed(), slices, runner, budget)

    assert budget.spent == 20
    assert result.selected is not None
    assert any("cap" in n for n in result.notes)
    assert result.summary()
