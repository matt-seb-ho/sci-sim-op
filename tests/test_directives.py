"""Repair-directive mining.

The distinguishing property being tested: a simulator's validator output names
the *legal action space* at the point of failure, not merely the fact of
failure. Everything here is about extracting that and turning it into a
constraint that is true by construction rather than proposed and then paid for
with a full evaluation round.
"""

from __future__ import annotations

import pytest

from harness_evolve.evidence.directives import (
    KIND_DANGLING_REFERENCE, KIND_UNKNOWN_ATTRIBUTE, KIND_UNKNOWN_ELEMENT,
    RepairDirective, derive_constraints, directives_from_events,
    parse_validator_output, render_constraints, summarize,
)

# Shapes taken from the validator behaviour recorded against the real binary.
UNKNOWN_ATTR = """
Error: XML Node Solvers/SinglePhaseFVM contains unused attribute 'totallyBogusAttribute'. Valid attributes are:
  cflFactor, discretization, initialDt, logLevel, name, targetRegions, temperature
"""

UNKNOWN_TAG = """
Error: The tag 'ImmiscibleMultiphaseFlowBogus' is invalid within Solvers. All available tags are: {AcousticSEM, CompositionalMultiphaseFVM, ImmiscibleMultiphaseFlow, SinglePhaseFVM}
"""

DANGLING = """
Error: No child named 'region' found. The children of elementRegionsGroup are: { region_renamed }
"""


def test_unknown_attribute_yields_the_legal_set():
    d = parse_validator_output(UNKNOWN_ATTR)[0]
    assert d.kind == KIND_UNKNOWN_ATTRIBUTE
    assert d.offender == "totallyBogusAttribute"
    assert "discretization" in d.alternatives
    assert "targetRegions" in d.alternatives
    assert d.context == "Solvers/SinglePhaseFVM"
    assert d.is_actionable


def test_unknown_element_yields_the_legal_set():
    d = parse_validator_output(UNKNOWN_TAG)[0]
    assert d.kind == KIND_UNKNOWN_ELEMENT
    assert d.offender == "ImmiscibleMultiphaseFlowBogus"
    assert "SinglePhaseFVM" in d.alternatives
    assert d.context == "Solvers", "trailing punctuation must not enter the tag name"


def test_dangling_reference_names_what_was_defined():
    d = parse_validator_output(DANGLING)[0]
    assert d.kind == KIND_DANGLING_REFERENCE
    assert d.offender == "region"
    assert d.alternatives == ("region_renamed",)


def test_near_miss_and_misconception_are_distinguished():
    """A typo wants a correction; a misconception wants the legal set named."""
    typo = parse_validator_output(UNKNOWN_TAG)[0]
    assert typo.is_near_miss
    assert typo.nearest == "ImmiscibleMultiphaseFlow"

    misconception = parse_validator_output(UNKNOWN_ATTR)[0]
    assert not misconception.is_near_miss


def test_a_verdict_without_alternatives_is_not_actionable():
    """Most verifiers only offer this, and it constrains nothing."""
    d = RepairDirective(kind=KIND_UNKNOWN_ATTRIBUTE, offender="x")
    assert not d.is_actionable
    assert d.nearest is None
    assert derive_constraints([d, d]) == []


def test_all_three_shapes_parse_from_one_run():
    ds = parse_validator_output(UNKNOWN_ATTR + "\n\n" + UNKNOWN_TAG + "\n\n" + DANGLING)
    assert {d.kind for d in ds} == {
        KIND_UNKNOWN_ATTRIBUTE, KIND_UNKNOWN_ELEMENT, KIND_DANGLING_REFERENCE
    }


def test_alternatives_parse_through_punctuation_variants():
    """GEOS wraps these in braces, brackets, or nothing; none of that is promised."""
    braced = parse_validator_output(UNKNOWN_TAG)[0]
    plain = parse_validator_output(UNKNOWN_ATTR)[0]
    assert all("{" not in a and "," not in a for a in braced.alternatives)
    assert all(a.isidentifier() for a in plain.alternatives)


# ---------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------

def test_one_off_errors_do_not_become_constraints():
    """A single slip is one agent's slip. Encoding it is over-specification, and
    over-specification in an always-on artifact is paid for on every rollout."""
    ds = parse_validator_output(UNKNOWN_ATTR)
    assert derive_constraints(ds, min_support=2) == []


def test_a_repeated_error_becomes_a_constraint():
    ds = parse_validator_output(UNKNOWN_ATTR) * 2
    cs = derive_constraints(ds, min_support=2)
    assert len(cs) == 1
    assert cs[0].kind == "forbid_attr"
    assert cs[0].entry["attr"] == "totallyBogusAttribute"
    assert "discretization" in cs[0].entry["valid"]
    assert cs[0].support == 2


def test_derived_constraint_is_prose_and_a_machine_entry():
    """One source, two surfaces: the model reads the prose, the hook runs the entry."""
    cs = derive_constraints(parse_validator_output(UNKNOWN_TAG) * 2)
    c = cs[0]
    assert c.entry["kind"] == "forbid_element"
    assert "ImmiscibleMultiphaseFlow" in c.prose
    assert "Solvers." not in c.prose


def test_near_miss_constraint_names_the_correction():
    cs = derive_constraints(parse_validator_output(UNKNOWN_TAG) * 2)
    assert "you mean" in cs[0].prose


def test_misconception_constraint_enumerates_the_legal_set():
    cs = derive_constraints(parse_validator_output(UNKNOWN_ATTR) * 2)
    assert "Do NOT set" in cs[0].prose
    assert "valid attributes are" in cs[0].prose


def test_long_alternative_lists_are_truncated_in_prose_but_not_in_the_entry():
    """The prose shares a hard token budget; the machine check does not."""
    alts = ", ".join(f"attr{i}" for i in range(40))
    text = (
        "Error: XML Node Solvers/X contains unused attribute 'bogus'. "
        f"Valid attributes are:\n  {alts}\n"
    )
    cs = derive_constraints(parse_validator_output(text) * 2,
                            max_alternatives_in_prose=5)
    assert cs[0].prose.count("`attr") == 5
    assert "..." in cs[0].prose
    assert len(cs[0].entry["valid"]) == 40


def test_constraints_render_highest_support_first():
    ds = parse_validator_output(UNKNOWN_ATTR) * 5 + parse_validator_output(UNKNOWN_TAG) * 2
    text = render_constraints(derive_constraints(ds))
    assert text.index("totallyBogusAttribute") < text.index("ImmiscibleMultiphase")


def test_empty_input_is_handled_everywhere():
    assert parse_validator_output("") == []
    assert derive_constraints([]) == []
    assert render_constraints([]) == ""
    assert "no repair directives" in summarize([])


def test_events_are_mined_across_field_names():
    """The event schema is not fixed across runners; a directive missed for want
    of a key name is a silently weaker constraint set."""
    events = [
        {"stdout": UNKNOWN_ATTR},
        {"validator_output": UNKNOWN_TAG},
        {"message": DANGLING},
        {"unrelated": "nothing here"},
    ]
    ds = directives_from_events(events)
    assert len(ds) == 3


def test_summary_reports_actionability_not_just_count():
    ds = parse_validator_output(UNKNOWN_ATTR + "\n\n" + UNKNOWN_TAG)
    s = summarize(ds)
    assert "naming a legal alternative set" in s
    assert "near-misses" in s
