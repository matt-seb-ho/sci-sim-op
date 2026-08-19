"""The model-driven proposer and its bounded edit vocabulary.

Most of these are guards rather than features. A proposer sits between an
expensive evaluation budget and a model that will occasionally produce something
malformed, over-long, or leaky; every guard here turns one of those into a free
rejection instead of a spent round.
"""

from __future__ import annotations

import json

import pytest

from harness_evolve.core.candidate import CandidateError, Candidate
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy
from harness_evolve.proposers.base import Demonstration, ProposerError
from harness_evolve.proposers.edits import (
    ANCHOR_MATCH_FLOOR, Edit, EditError, Op, apply_edit, find_anchor, parse_edits,
)
from harness_evolve.proposers.llm import LLMProposer, LLMProposerConfig

MEMORY = "- alpha handling\n- beta handling\n- gamma handling"


def make_candidate(memory: str = MEMORY, budget: int = 200) -> Candidate:
    return Candidate(
        manifest=Manifest(
            components={
                "memory": ComponentSpec("memory", "itemized", path="m.md",
                                        budget_tokens=budget),
                "primer": ComponentSpec("primer", "prose", path="p.md",
                                        budget_tokens=100),
                "stop_policy": ComponentSpec("stop_policy", "config"),
            },
            stop_policy=StopPolicy(checks=("parse",)),
        ),
        files={"m.md": memory, "p.md": "seed primer"},
    )


def response(op="add", component="memory", anchor="", text="- delta handling",
             prediction=None):
    pred = prediction if prediction is not None else {
        "targets_category": "missing_block",
        "predicted_beneficiaries": ["t1"],
        "predicted_delta": 0.03,
        "rationale": "evidence showed a missing block",
    }
    anchor_attr = f' anchor="{anchor}"' if anchor else ""
    body = "" if prediction is False else f"<prediction>{json.dumps(pred)}</prediction>"
    return (
        f'<edit component="{component}" op="{op}"{anchor_attr}>{text}</edit>\n{body}'
    )


def propose(resp: str, candidate: Candidate | None = None, **kw):
    return LLMProposer(call=lambda p: resp, **kw).propose(candidate or make_candidate())


# ---------------------------------------------------------------------------
# edit vocabulary
# ---------------------------------------------------------------------------

def test_add_delete_replace_all_work():
    assert apply_edit(MEMORY, Edit("memory", Op.ADD, text="- delta")).endswith("- delta")
    assert "beta" not in apply_edit(MEMORY, Edit("memory", Op.DELETE,
                                                 anchor="- beta handling"))
    out = apply_edit(MEMORY, Edit("memory", Op.REPLACE, anchor="- beta handling",
                                  text="- beta, revised"))
    assert "beta, revised" in out and out.count("\n") == MEMORY.count("\n")


def test_anchor_tolerates_reformatting_but_not_a_different_line():
    """A model asked to quote a line back will re-wrap or re-punctuate it.
    Failing the proposal over a stray space wastes a call; silently editing a
    different assertion is far worse."""
    lines = MEMORY.splitlines()
    assert find_anchor(lines, "beta  handling.") == 1
    assert find_anchor(lines, "- BETA HANDLING") == 1
    assert find_anchor(lines, "- an entirely unrelated assertion") == -1


def test_a_missing_anchor_raises_rather_than_no_ops():
    """A silent no-op would be evaluated and gated as a real proposal, spending
    a full round to discover the artifact never changed."""
    with pytest.raises(EditError, match="anchor not found"):
        apply_edit(MEMORY, Edit("memory", Op.DELETE, anchor="- not present"))


def test_duplicate_add_is_refused():
    with pytest.raises(EditError, match="duplicates"):
        apply_edit(MEMORY, Edit("memory", Op.ADD, text="- alpha handling"))


def test_empty_replace_is_refused_in_favour_of_delete():
    with pytest.raises(EditError, match="use delete"):
        apply_edit(MEMORY, Edit("memory", Op.REPLACE, anchor="- beta handling"))


def test_parse_edits_reads_all_three_ops():
    ops = {e.op for e in parse_edits(
        '<edit component="m" op="add">x</edit>'
        '<edit component="m" op="delete" anchor="y"></edit>'
        '<edit component="m" op="replace" anchor="y">z</edit>'
    )}
    assert ops == {Op.ADD, Op.DELETE, Op.REPLACE}


# ---------------------------------------------------------------------------
# proposer guards
# ---------------------------------------------------------------------------

def test_a_well_formed_proposal_produces_a_child():
    child = propose(response())
    assert child.files["m.md"].endswith("- delta handling")
    assert child.predictions[0].predicted_beneficiaries == ("t1",)
    assert child.parent_id is not None


def test_deletion_is_available_to_the_proposer():
    """A vocabulary that cannot delete is how an always-on artifact only grows."""
    child = propose(response(op="delete", anchor="- beta handling", text=""))
    assert "beta" not in child.files["m.md"]


def test_more_than_one_edit_is_refused():
    with pytest.raises(ProposerError, match="exactly one"):
        propose(response() + response(text="- epsilon"))


def test_a_missing_prediction_is_refused():
    with pytest.raises(ProposerError, match="falsifiable"):
        propose(response(prediction=False))


def test_malformed_prediction_json_is_refused():
    resp = '<edit component="memory" op="add">- x</edit><prediction>{oops}</prediction>'
    with pytest.raises(ProposerError, match="not valid JSON"):
        propose(resp)


def test_prose_response_is_refused_loudly():
    """The predecessor silently inherited the parent here, burning the call."""
    with pytest.raises(ProposerError, match="no <edit> block"):
        propose("I think you should probably make the cheatsheet longer.")


def test_unknown_component_is_refused():
    with pytest.raises(ProposerError, match="unknown component"):
        propose(response(component="not_a_component"))


def test_config_component_cannot_be_edited_as_text():
    with pytest.raises(ProposerError, match="through the manifest"):
        propose(response(component="stop_policy"))


def test_budget_overrun_is_refused_before_any_rollout():
    small = make_candidate(budget=20)
    with pytest.raises(CandidateError, match="token budget"):
        propose(response(text="- " + "word " * 200), small)


def test_a_bad_anchor_becomes_a_proposer_error_not_a_crash():
    with pytest.raises(ProposerError, match="anchor not found"):
        propose(response(op="delete", anchor="- never written", text=""))


# ---------------------------------------------------------------------------
# what the prompt carries
# ---------------------------------------------------------------------------

def test_prompt_shows_budget_headroom():
    p = LLMProposer(call=lambda _: response())
    text = p.build_prompt(make_candidate(), None, [], [])
    assert "tokens of headroom" in text
    assert "tokens used" in text


def test_prompt_says_at_budget_when_full():
    p = LLMProposer(call=lambda _: response())
    text = p.build_prompt(make_candidate(budget=9), None, [], [])
    assert "AT BUDGET" in text
    assert "delete before you can add" in text


def test_prompt_hands_over_validator_constraints_as_settled():
    """The point of deriving constraints is that the model does not spend an
    edit rediscovering what the simulator already said."""
    from harness_evolve.evidence.directives import derive_constraints, parse_validator_output

    ds = derive_constraints(parse_validator_output(
        "Error: The tag 'Foo' is invalid within Solvers. "
        "All available tags are: {Bar, Baz}"
    ) * 2)
    p = LLMProposer(derived_constraints=ds, call=lambda _: response())
    text = p.build_prompt(make_candidate(), None, [], [])
    assert "already stated" in text
    assert "`Bar`" in text


def test_prompt_carries_demonstrations_and_calibration_record():
    p = LLMProposer(call=lambda _: response())
    text = p.build_prompt(
        make_candidate(),
        None,
        [{"component": "memory", "edit_type": "add", "accepted": False,
          "reasons": ["per-task regression on t2"], "prediction_hit_rate": 0.0}],
        [Demonstration("t1", "worked from narrative documentation")],
    )
    assert "narrative documentation" in text
    assert "REJECTED" in text
    assert "prediction hit rate 0%" in text


def test_prompt_is_honest_when_there_is_nothing_to_show():
    p = LLMProposer(call=lambda _: response())
    text = p.build_prompt(make_candidate(), None, [], [])
    assert "first proposal" in text
    assert "no expert demonstrations" in text
    assert "has not repeated itself" in text


def test_missing_api_key_fails_before_the_call():
    import os

    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        with pytest.raises(ProposerError, match="is not set"):
            LLMProposer(config=LLMProposerConfig()).propose(make_candidate())
    finally:
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved
