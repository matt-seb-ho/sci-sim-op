"""Check-plugin tests. Offline, no simulator binaries, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_evolve.checks import (
    BUILTIN_CHECKS,
    CheckContext,
    ConstraintError,
    ConstraintSet,
    ElementView,
    load_vetted_plugins,
    render_feedback,
    run_checks,
    vet_plugin,
    vet_plugins,
)
from harness_evolve.checks.sandbox import (
    STATUS_BAD_INTERFACE,
    STATUS_EXITED_EARLY,
    STATUS_IMPORT_ERROR,
    STATUS_NO_TEST,
    STATUS_OK,
    STATUS_TEST_FAILED,
    STATUS_TIMEOUT,
    STATUS_VACUOUS_TEST,
)
from harness_evolve.simulators.base import Artifact, SimulatorSpec
from harness_evolve.types import Finding, Score

PLUGINS_DIR = Path(__file__).resolve().parents[1] / "src" / "harness_evolve" / "checks" / "plugins"

GOOD_DECK = """<Problem>
  <Solvers>
    <SinglePhaseFVM name="flow" discretization="tpfa" targetRegions="{ region }"/>
  </Solvers>
  <NumericalMethods>
    <FiniteVolume><TwoPointFluxApproximation name="tpfa"/></FiniteVolume>
  </NumericalMethods>
  <ElementRegions>
    <CellElementRegion name="region" materialList="{ water }"/>
  </ElementRegions>
  <Constitutive>
    <CompressibleSinglePhaseFluid name="water" defaultDensity="1000"/>
  </Constitutive>
</Problem>
"""


def artifact(xml: str = GOOD_DECK, name: str = "deck.xml") -> Artifact:
    return Artifact(files={name: xml})


def ctx(**kw) -> CheckContext:
    kw.setdefault("workspace", Path("."))
    return CheckContext(**kw)


# ===========================================================================
# constraints: one declaration, two surfaces
# ===========================================================================

DECL = """
# The negative half of the cheatsheet.
- kind: count
  parent: Constitutive
  child: "*"
  min: 1
  max: 2
- {kind: forbid_attr, tag: SinglePhaseFVM, attr: gravityVector, note: set it on Problem}
- kind: require_attr
  tag: CellElementRegion
  attr: materialList
- kind: forbid_tag
  tag: NullModel
"""


def test_constraints_parse_both_block_and_inline_forms() -> None:
    cs = ConstraintSet.parse(DECL)
    assert [c.kind for c in cs] == ["count", "forbid_attr", "require_attr", "forbid_tag"]
    assert cs.constraints[0].max == 2 and cs.constraints[0].min == 1
    assert cs.constraints[1].note == "set it on Problem"


def test_one_declaration_renders_as_prose_and_as_checks() -> None:
    # This is the whole design claim: a cheatsheet that only enumerates positive
    # facts trades missing_block (6 -> 3) for extra_block (9 -> 11) and
    # hallucinated_extras (4 -> 7). Stating a constraint and enforcing it must
    # be one source, because weak-tier models activate an artifact and then do
    # not follow it (arXiv:2605.30621).
    cs = ConstraintSet.parse(DECL)

    prose = cs.to_prose()
    assert "between 1 and 2 children" in prose
    assert "do NOT set `gravityVector`" in prose
    assert "must set `materialList`" in prose
    assert "do NOT introduce `<NullModel>`" in prose
    # Every declared constraint reaches the prose surface; a silent one would be
    # a rule the agent is never told about.
    assert len([ln for ln in prose.splitlines() if ln.startswith("- ")]) == len(cs)

    violating = """<Problem>
      <Solvers><SinglePhaseFVM name="f" gravityVector="0,0,-9.81"/></Solvers>
      <ElementRegions><CellElementRegion name="r"/></ElementRegions>
      <Constitutive>
        <A name="a"/><B name="b"/><NullModel name="c"/>
      </Constitutive>
    </Problem>"""
    findings = cs.findings(ElementView.of(artifact(violating)))
    sources = {f.message.split()[0] for f in findings}
    assert len(findings) == 4, [f.render() for f in findings]
    assert all(f.severity == "error" for f in findings)
    assert sources  # every violation names the offending element

    # And the identical declaration is silent on a deck that honours it.
    assert cs.findings(ElementView.of(artifact(GOOD_DECK))) == []


def test_count_constraint_enforces_both_bounds() -> None:
    cs = ConstraintSet.parse("- {kind: count, parent: Constitutive, child: '*', min: 2, max: 3}")
    too_few = artifact("<Problem><Constitutive><A name='a'/></Constitutive></Problem>")
    too_many = artifact(
        "<Problem><Constitutive><A name='a'/><B name='b'/><C name='c'/><D name='d'/>"
        "</Constitutive></Problem>"
    )
    ok = artifact("<Problem><Constitutive><A name='a'/><B name='b'/></Constitutive></Problem>")

    assert "at least 2" in cs.findings(ElementView.of(too_few))[0].message
    assert "at most 3" in cs.findings(ElementView.of(too_many))[0].message
    # The message tells the agent how many to remove, not just that it is wrong.
    assert "Remove 1" in cs.findings(ElementView.of(too_many))[0].message
    assert cs.findings(ElementView.of(ok)) == []


def test_count_constraint_can_target_a_named_child() -> None:
    cs = ConstraintSet.parse(
        "- {kind: count, parent: Constitutive, child: ElasticIsotropic, max: 1}"
    )
    deck = artifact(
        "<Problem><Constitutive><ElasticIsotropic name='a'/><ElasticIsotropic name='b'/>"
        "<NullModel name='c'/></Constitutive></Problem>"
    )
    findings = cs.findings(ElementView.of(deck))
    assert len(findings) == 1
    assert "2 <ElasticIsotropic> children" in findings[0].message


def test_exact_count_reads_as_exactly_k_no_more() -> None:
    cs = ConstraintSet.parse("- {kind: count, parent: Constitutive, min: 3, max: 3}")
    assert "exactly 3 children, no more" in cs.to_prose()


@pytest.mark.parametrize(
    "text, needle",
    [
        ("- kind: nonsense", "unknown constraint kind"),
        ("- {kind: count, parent: X}", "requires 'min' and/or 'max'"),
        ("- {kind: count, parent: X, min: 5, max: 2}", "min 5 > max 2"),
        ("- {kind: forbid_attr, tag: X}", "requires 'tag' and 'attr'"),
        ("- {kind: count, parent: X, max: two}", "must be an integer"),
        ("- {kind: count, parent: X, max: 1, colour: blue}", "unknown constraint field"),
        ("  stray: value", "before any '- ' item"),
        ("- kind count", "expected 'key: value'"),
    ],
)
def test_malformed_declarations_fail_with_a_locatable_message(text: str, needle: str) -> None:
    # These are proposer-authored. A diagnostic it cannot locate is one it
    # cannot act on, so every message carries a line number.
    with pytest.raises(ConstraintError) as exc:
        ConstraintSet.parse(text)
    assert needle in str(exc.value)
    assert "line" in str(exc.value) or "kind" in str(exc.value)


def test_empty_declaration_is_valid_and_silent() -> None:
    cs = ConstraintSet.parse("# nothing declared yet\n")
    assert len(cs) == 0
    assert cs.to_prose() == ""
    assert cs.findings(ElementView.of(artifact())) == []


# ===========================================================================
# built-ins
# ===========================================================================


def test_parse_check_flags_an_empty_workspace() -> None:
    findings = BUILTIN_CHECKS["parse"](Artifact(), ctx())
    assert len(findings) == 1 and findings[0].severity == "error"


def test_parse_check_flags_unparseable_files() -> None:
    findings = BUILTIN_CHECKS["parse"](artifact("<Problem><Solvers>"), ctx())
    assert findings[0].location == "deck.xml"
    assert "does not parse" in findings[0].message


def test_required_sections_reports_only_what_is_missing() -> None:
    context = ctx(required_sections=("Solvers", "Mesh", "Constitutive"))
    findings = BUILTIN_CHECKS["required_sections"](artifact(), context)
    assert [f.message for f in findings] == ["artifact defines no <Mesh> section"]


def test_required_sections_is_silent_without_expectations() -> None:
    assert BUILTIN_CHECKS["required_sections"](artifact(), ctx()) == []


def test_cross_section_refs_catches_a_dangling_material() -> None:
    deck = GOOD_DECK.replace('materialList="{ water }"', 'materialList="{ brine }"')
    findings = BUILTIN_CHECKS["cross_section_refs"](artifact(deck), ctx())
    assert len(findings) == 1
    # The message enumerates the defined names, which is what the agent needs.
    assert "'brine'" in findings[0].message and "water" in findings[0].message


def test_cross_section_refs_is_silent_on_a_consistent_deck() -> None:
    assert BUILTIN_CHECKS["cross_section_refs"](artifact(), ctx()) == []


def test_geosx_validate_without_a_simulator_warns_rather_than_errors() -> None:
    findings = BUILTIN_CHECKS["geosx_validate"](artifact(), ctx())
    assert [f.severity for f in findings] == ["warn"]


def test_geosx_validate_bridges_to_the_simulator() -> None:
    class Spec(SimulatorSpec):
        name = "probe"

        def parse(self, workspace):
            return Artifact()

        def validate(self, artifact_, workspace):
            return [Finding("geosx_validate", "error", "Valid attributes are: [a, b]")]

        def score(self, generated, ground_truth, task):
            return Score(task=task, value=0.0)

    findings = BUILTIN_CHECKS["geosx_validate"](artifact(), ctx(simulator=Spec()))
    assert findings[0].severity == "error"


def test_tree_shaped_checks_are_silent_on_a_non_tree_artifact() -> None:
    # A LAMMPS-style artifact is not an element tree. Inventing findings from a
    # representation the check does not understand would block the agent on
    # something it cannot fix.
    lammps = Artifact(files={"in.lj": "units lj\natom_style atomic\n"})
    context = ctx(required_sections=("Solvers",), constraints=ConstraintSet.parse(
        "- {kind: count, parent: Constitutive, max: 1}"
    ))
    assert BUILTIN_CHECKS["cross_section_refs"](lammps, context) == []
    assert BUILTIN_CHECKS["constraints"](lammps, context) == []


# ===========================================================================
# run_checks and feedback rendering
# ===========================================================================


def test_a_raising_check_degrades_to_a_warning() -> None:
    # A broken check must never trap the agent in a retry loop it cannot
    # escape: that is strictly worse than not running the check at all.
    def exploding(artifact_, context):
        raise ZeroDivisionError("nope")

    findings = run_checks(artifact(), ctx(), ["boom"], plugins={"boom": exploding})
    assert [f.severity for f in findings] == ["warn"]
    assert "ZeroDivisionError" in findings[0].message
    # Only errors block, so the agent is allowed to finish.
    assert render_feedback(findings) == ""


def test_an_unregistered_check_warns_instead_of_aborting() -> None:
    findings = run_checks(artifact(), ctx(), ["ghost"])
    assert [f.severity for f in findings] == ["warn"]
    assert render_feedback(findings) == ""


def test_run_checks_preserves_order_and_collects_everything() -> None:
    context = ctx(
        required_sections=("Solvers", "Mesh"),
        constraints=ConstraintSet.parse("- {kind: count, parent: Constitutive, max: 0}"),
    )
    findings = run_checks(artifact(), context, ["parse", "required_sections", "constraints"])
    assert [f.source for f in findings] == ["required_sections", "constraints"]


@pytest.mark.parametrize("shape", ["minimal", "structured_errors", "errors_plus_tables"])
def test_every_feedback_shape_renders(shape: str) -> None:
    findings = [Finding("parse", "error", "XML does not parse", location="deck.xml")]
    text = render_feedback(findings, shape)
    assert text
    assert ("deck.xml" in text) is (shape != "minimal")


def test_errors_plus_tables_forwards_the_validator_table() -> None:
    # geosx prints the full table of valid attributes on an unknown-attribute
    # error. That text is the richest signal the harness produces; discarding it
    # is exactly what makes a gate "static".
    findings = [
        Finding("geosx_validate", "error", "unused attribute 'foo'. Valid attributes are: [a, b]")
    ]
    text = render_feedback(findings, "errors_plus_tables")
    assert "verbatim" in text
    assert text.count("Valid attributes are") == 2  # in the list, and called out


def test_feedback_is_empty_when_nothing_blocks() -> None:
    assert render_feedback([]) == ""
    assert render_feedback([Finding("x", "warn", "meh")]) == ""
    assert render_feedback([Finding("x", "info", "fyi")]) == ""


def test_unknown_feedback_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown feedback shape"):
        render_feedback([], "chatty")


# ===========================================================================
# the plugin fence
# ===========================================================================

_PLUGIN_OK = '''
"""A plugin that behaves."""
from harness_evolve.types import Finding


def check(artifact, ctx):
    return [Finding("demo", "warn", "seen")] if artifact.files else []
'''

_TEST_OK = '''
from harness_evolve.simulators.base import Artifact
from demo import check


def main():
    assert check(Artifact(files={"a.xml": "<A/>"}), None)
    assert check(Artifact(), None) == []
'''


def _write(dirpath: Path, name: str, plugin: str, test: str | None) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / f"{name}.py"
    path.write_text(plugin)
    if test is not None:
        (dirpath / f"{name}_test.py").write_text(test)
    return path


def test_a_well_formed_plugin_is_accepted(tmp_path: Path) -> None:
    path = _write(tmp_path, "demo", _PLUGIN_OK, _TEST_OK)
    report = vet_plugin(path)
    assert report.status == STATUS_OK, report.detail
    assert report.ok


def test_a_plugin_without_a_test_is_rejected(tmp_path: Path) -> None:
    # arXiv:2603.05578: one-shot autonomous tool creation fails and interface
    # errors compound. The sibling test is the cheapest available fence, and it
    # is enforced before any rollout is spent.
    path = _write(tmp_path, "demo", _PLUGIN_OK, None)
    report = vet_plugin(path)
    assert report.status == STATUS_NO_TEST
    assert "demo_test.py" in report.detail


def test_a_failing_test_rejects_the_plugin(tmp_path: Path) -> None:
    path = _write(tmp_path, "demo", _PLUGIN_OK, "def main():\n    assert check_this_fails\n")
    report = vet_plugin(path)
    assert report.status == STATUS_TEST_FAILED
    assert "NameError" in report.detail


def test_a_test_that_never_calls_check_is_rejected(tmp_path: Path) -> None:
    # Otherwise "ship a test" is satisfiable with `assert True`, and a proposer
    # optimising against a gate will find that.
    path = _write(tmp_path, "demo", _PLUGIN_OK, "def main():\n    assert True\n")
    report = vet_plugin(path)
    assert report.status == STATUS_VACUOUS_TEST


def test_a_plugin_that_raises_on_import_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "demo", "raise RuntimeError('bad import')\n", _TEST_OK)
    report = vet_plugin(path)
    assert report.status == STATUS_IMPORT_ERROR
    assert "bad import" in report.detail


def test_a_plugin_with_the_wrong_signature_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "demo", "def check(deck):\n    return []\n", _TEST_OK)
    report = vet_plugin(path)
    assert report.status == STATUS_BAD_INTERFACE


def test_a_module_without_check_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "demo", "verify = 1\n", _TEST_OK)
    report = vet_plugin(path)
    assert report.status == STATUS_IMPORT_ERROR
    assert "check" in report.detail


def test_a_plugin_that_exits_at_import_cannot_take_the_search_down(tmp_path: Path) -> None:
    # Import happens in the vetting child, not here. "Import it to find out
    # whether importing it is safe" is not a fence.
    path = _write(tmp_path, "demo", "import sys\nsys.exit(3)\n", _TEST_OK)
    report = vet_plugin(path)
    assert report.status == STATUS_IMPORT_ERROR


def test_a_test_that_exits_early_is_not_credited(tmp_path: Path) -> None:
    # Exit code 0 from a process that never ran the assertions proves nothing.
    path = _write(tmp_path, "demo", _PLUGIN_OK, "import sys\nsys.exit(0)\n")
    report = vet_plugin(path)
    assert report.status == STATUS_EXITED_EARLY


def test_a_hanging_test_is_killed_at_the_budget(tmp_path: Path) -> None:
    # A check that cannot answer in seconds is not a check, it is a second
    # agent -- and it would be paid on every turn of every rollout.
    path = _write(tmp_path, "demo", _PLUGIN_OK, "import time\ntime.sleep(30)\n")
    report = vet_plugin(path, timeout=1.0)
    assert report.status == STATUS_TIMEOUT
    assert report.duration_s < 10


def test_load_vetted_plugins_imports_only_what_passed(tmp_path: Path) -> None:
    _write(tmp_path, "good", _PLUGIN_OK, _TEST_OK.replace("from demo", "from good"))
    _write(tmp_path, "untested", _PLUGIN_OK, None)

    plugins, reports = load_vetted_plugins(tmp_path)

    assert set(plugins) == {"good"}
    assert {r.name: r.status for r in reports} == {
        "good": STATUS_OK,
        "untested": STATUS_NO_TEST,
    }
    # A rejected plugin is evidence about the proposer, so the report survives.
    assert all(r.to_dict()["status"] for r in reports)


def test_test_files_are_not_themselves_treated_as_plugins(tmp_path: Path) -> None:
    _write(tmp_path, "good", _PLUGIN_OK, _TEST_OK.replace("from demo", "from good"))
    assert [r.name for r in vet_plugins(tmp_path)] == ["good"]


# ===========================================================================
# the shipped example plugin
# ===========================================================================


def test_shipped_plugins_pass_their_own_fence() -> None:
    # The built-in examples are not privileged: they clear the same fence a
    # candidate-authored plugin does, so they cannot rot into something the
    # fence would reject.
    reports = vet_plugins(PLUGINS_DIR)
    assert reports, f"no plugins found under {PLUGINS_DIR}"
    assert all(r.ok for r in reports), [r.render() for r in reports]


def test_lazy_ref_plugin_catches_what_the_real_validator_misses() -> None:
    # docs/GEOSX_VALIDATE.md, confirmed against the real binary: `geosx
    # --validate-input` exits 0 on discretization="TPFA_DOES_NOT_EXIST", and
    # the XSD cannot express the constraint either (groupNameRef is a plain
    # string; schema.xsd declares zero xsd:key/keyref).
    plugins, _ = load_vetted_plugins(PLUGINS_DIR)
    check = plugins["lazy_resolved_refs"]

    assert check(artifact(GOOD_DECK), ctx()) == []

    broken = GOOD_DECK.replace('discretization="tpfa"', 'discretization="TPFA_DOES_NOT_EXIST"')
    findings = check(artifact(broken), ctx())
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "tpfa" in findings[0].message  # enumerates what is defined


def test_a_vetted_plugin_runs_through_run_checks() -> None:
    plugins, _ = load_vetted_plugins(PLUGINS_DIR)
    broken = GOOD_DECK.replace('discretization="tpfa"', 'discretization="NOPE"')
    findings = run_checks(
        artifact(broken), ctx(), ["parse", "lazy_resolved_refs"], plugins=plugins
    )
    assert render_feedback(findings, "structured_errors").startswith("1 validation error")
