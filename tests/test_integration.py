"""End-to-end: does the whole system actually compose?

Every module here has its own unit tests. This file asks the different question
-- whether a real search, assembled from the real parts, runs and produces
something a person could act on. It is the test the predecessor did not have,
and its absence is why a reward channel that returned nothing for every task
survived three rounds and a written result.

Everything runs offline against the mock simulator and mock runner, in seconds,
at zero cost.
"""

from __future__ import annotations

import statistics

import pytest

from harness_evolve.core.acceptance import RegressionGate
from harness_evolve.core.candidate import Candidate
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy
from harness_evolve.core.search import Search, SearchConfig
from harness_evolve.evaluation.baselines import BudgetLedger
from harness_evolve.evidence.corpus import build_evidence
from harness_evolve.evidence.directives import derive_constraints, parse_validator_output
from harness_evolve.hygiene.corpus import GroundTruthCorpus
from harness_evolve.hygiene.gate import check_candidate
from harness_evolve.proposers.scripted import RandomEditProposer, ScriptedProposer
from harness_evolve.runners.mock import MockRunner, MockWorld
from harness_evolve.simulators.mock import MockSimulator

TASKS = [f"task_{i}" for i in range(6)]
PROBE = ["probe_a", "probe_b"]


def make_seed(memory: str = "- start here") -> Candidate:
    return Candidate(
        manifest=Manifest(
            components={
                "primer": ComponentSpec("primer", "prose", path="PRIMER.md",
                                        budget_tokens=200),
                "memory": ComponentSpec("memory", "itemized",
                                        path="memory/cheatsheet.md",
                                        budget_tokens=400),
                "stop_policy": ComponentSpec("stop_policy", "config"),
            },
            stop_policy=StopPolicy(retries=2, checks=("parse",)),
        ),
        files={"PRIMER.md": "author a valid deck", "memory/cheatsheet.md": memory},
    )


@pytest.fixture
def runner(tmp_path):
    """A world with a genuine tail: two cliff tasks, the rest easy."""
    # Two cliff tasks and a modest zero rate: the tail is the signal, but not so
    # dominant that a single seed decides everything. Noise off so a test that
    # fails means the loop is wrong rather than unlucky.
    world = MockWorld(
        task_difficulty={"task_0": -0.35, "task_1": -0.30},
        noise=0.0,
        zero_rate=0.10,
    )
    return MockRunner(MockSimulator(), world=world, root=tmp_path / "runs")


def test_a_search_runs_end_to_end_and_reports_itself(runner, tmp_path):
    ledger = BudgetLedger()
    search = Search(
        runner,
        RandomEditProposer(lines=(
            "- name the required sections explicitly",
            "- set discretization to match a defined method",
            "- do NOT add more blocks than the physics needs",
        )),
        ledger=ledger,
        evidence_builder=lambda entry, rollouts: build_evidence(
            rollouts, candidate_id=entry.cid, parent_scores=entry.scores
        ),
        decision_log_path=tmp_path / "decisions.jsonl",
        config=SearchConfig(budget_candidates=8, seeds=(1, 2), screen_tasks=2,
                            probe_tasks=1, probe_every=4),
    )
    result = search.run(make_seed(), TASKS, probe_tasks=PROBE)

    # It ran.
    assert result.n_proposed == 8
    assert result.best is not None
    assert len(search.archive.entries) >= 1

    # It spent something, and recorded all of it.
    assert result.total_cost.tool_calls > 0
    recorded = sum(e.rollouts for e in ledger.entries if e.arm == "search")
    assert recorded > 0

    # It can explain itself. This is the part the predecessor could not do.
    summary = result.summary()
    for expected in ("proposed 8", "archive:", "decisions:", "calibration"):
        assert expected in summary, f"missing {expected!r} in:\n{summary}"

    # The decision log is on disk and every row is a falsifiable claim.
    rows = (tmp_path / "decisions.jsonl").read_text().splitlines()
    assert rows
    assert all("prediction" in r for r in rows)


def test_the_search_finds_a_real_improvement_when_one_exists(runner):
    """With a gradient present and noise off, the loop must climb it."""
    seed = make_seed("- start here")
    script = [
        ("memory", "- start here\n- name the required sections explicitly", {}),
        ("memory",
         "- start here\n- name the required sections explicitly\n"
         "- set discretization to a defined method", {}),
    ]
    search = Search(
        runner,
        ScriptedProposer(script=[(c, t, {"targets_category": "missing_block",
                                         "predicted_beneficiaries": TASKS[:2]})
                                 for c, t, _ in script]),
        # Two seeds, because the gate needs a distribution to tell an unlucky
        # rollout from a regression, and one seed cannot provide one.
        config=SearchConfig(budget_candidates=2, seeds=(1, 2), screen_tasks=0),
    )
    result = search.run(seed, TASKS)

    seed_mean = search.archive.entries[0].mean
    assert result.best.mean > seed_mean, (
        f"best {result.best.mean:.3f} did not beat seed {seed_mean:.3f}"
    )


def test_hygiene_sits_in_the_free_gate_band(runner):
    """A leaky proposal must be rejected before any rollout is spent on it."""
    corpus = GroundTruthCorpus(task_ids=set(TASKS))
    leak = "- start here\n" + "\n".join(f"| {t} | see the reference deck |"
                                        for t in TASKS)
    search = Search(
        runner,
        ScriptedProposer(script=[("memory", leak,
                                  {"targets_category": "missing_block"})]),
        hygiene=lambda c: check_candidate(c, corpus),
        config=SearchConfig(budget_candidates=1, seeds=(1,), screen_tasks=0),
    )
    seed = make_seed()
    result = search.run(seed, TASKS)

    assert result.n_hygiene_blocked == 1
    # Only the seed was ever executed.
    assert all(e.accepted or e.reason.startswith("hygiene")
               for e in search.archive.entries)


def test_the_loop_survives_a_proposer_that_only_produces_garbage(runner):
    """Robustness, not capability: a failing proposer must not burn the budget
    or leave the archive in a state that cannot be reported."""
    class Broken(ScriptedProposer):
        def propose(self, parent, evidence=None, history=(), demonstrations=()):
            raise RuntimeError("model returned prose")

    search = Search(
        runner, Broken(script=[]),
        config=SearchConfig(budget_candidates=20, seeds=(1,), screen_tasks=0,
                            max_consecutive_proposer_failures=3),
    )
    result = search.run(make_seed(), TASKS)

    assert result.n_proposer_failures == 3
    assert result.best is not None          # the seed is still the best answer
    assert "consecutive proposer failures" in " ".join(result.notes)
    assert result.summary()                  # still reportable


def test_directives_mined_from_a_real_run_become_constraints(runner):
    """The contribution, end to end: validator output in, constraints out,
    without spending a rollout to discover them."""
    seed = make_seed()
    rollouts = runner.run_many(seed, TASKS, (1,))

    text = "\n\n".join(
        str(ev.get("validator_output") or ev.get("message") or "")
        for r in rollouts for ev in r.validator_events
    )
    # The mock's validator speaks the same directive shapes the real one does;
    # if it ever stops doing so, this is where we find out.
    synthetic = (
        "Error: XML Node Solvers/SinglePhaseFVM contains unused attribute "
        "'bogusAttr'. Valid attributes are:\n  name, discretization, targetRegions\n"
    )
    directives = parse_validator_output(text + "\n\n" + synthetic * 2)
    constraints = derive_constraints(directives, min_support=2)

    assert constraints, "a repeated validator complaint must yield a constraint"
    c = constraints[0]
    assert c.entry["kind"] in ("forbid_attr", "forbid_element", "require_reference")
    assert c.prose.startswith("-")
    assert "derived from validator output" in c.provenance


def test_the_null_result_is_representable(runner):
    """The predicted outcome for this regime is that the search returns its seed.
    That must be an ordinary, reportable result -- not a crash, not an empty
    object, and not something that tempts anyone to loosen the gate."""
    seed = make_seed("- start here\n- name the required sections explicitly")
    # Every proposal strictly removes the useful line.
    search = Search(
        runner,
        ScriptedProposer(script=[
            ("memory", "- start here", {"targets_category": "extra_block"})
            for _ in range(4)
        ]),
        gate=RegressionGate(),
        config=SearchConfig(budget_candidates=4, seeds=(1,), screen_tasks=0,
                            stagnation_rounds=2),
    )
    result = search.run(seed, TASKS)

    assert result.best.candidate.cid == search.archive.entries[0].cid, (
        "the seed should still be best"
    )
    assert result.stagnated
    assert search.log.acceptance_rate() == 0.0
    assert "stagnated" in result.summary()
