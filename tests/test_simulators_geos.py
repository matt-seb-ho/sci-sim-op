"""GEOS simulator: TreeSim numeric parity, failures-as-zero, contamination.

Runs offline. The two geosx-dependent behaviours are covered without a real
binary: :meth:`GeosSimulator.validate`'s verbatim-output contract is tested
against a stub script that prints a realistic GEOS attribute table, and the
one test that needs the real thing is skipped unless ``GEOSX_EXECUTABLE`` is
set.
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from harness_evolve.simulators.geos import (
    GeosSimulator,
    entry_files,
    evaluate_directories,
    expand_with_variants,
    load_and_resolve_dir,
    tree_sim,
    tree_sim_section_scores,
    values_equivalent,
    variant_stem_keys,
    worst_subtrees,
)

from _repo3_path import REPO3  # resolves $REPO3_PATH or a conventional location

REPO3_JUDGE = REPO3 / "src/eval/judge_geos.py"


# ------------------------------------------------------------- fixtures

GT_A = """<Problem>
  <Solvers>
    <SolidMechanicsLagrangianSSLE name="lagsolve" timeIntegrationOption="QuasiStatic" logLevel="1"/>
  </Solvers>
  <Mesh>
    <InternalMesh name="mesh1" elementTypes="{C3D8}" xCoords="{0, 10}" nx="{10}"/>
  </Mesh>
  <Events maxTime="1.0e6">
    <PeriodicEvent name="solverApplications" forceDt="1e5" target="/Solvers/lagsolve"/>
    <PeriodicEvent name="outputs" timeFrequency="1e5" target="/Outputs/vtkOutput"/>
  </Events>
  <Constitutive>
    <ElasticIsotropic name="rock" defaultDensity="2700" defaultBulkModulus="1e9" defaultShearModulus="0.5e9"/>
  </Constitutive>
</Problem>"""

#: Same deck with: logLevel wrong, maxTime written differently (equivalent),
#: one PeriodicEvent dropped, Constitutive missing, one section hallucinated.
GEN_A = """<Problem>
  <Solvers>
    <SolidMechanicsLagrangianSSLE name="lagsolve" timeIntegrationOption="QuasiStatic" logLevel="2"/>
  </Solvers>
  <Mesh>
    <InternalMesh name="mesh1" elementTypes="{C3D8}" xCoords="{0, 10}" nx="{10}"/>
  </Mesh>
  <Events maxTime="1000000">
    <PeriodicEvent name="solverApplications" forceDt="1e5" target="/Solvers/lagsolve"/>
  </Events>
  <Debug note="scratch"/>
</Problem>"""

#: Repeated same-tag children, reordered, one renamed. Exercises the bipartite
#: matching and the extras penalty in isolation.
GT_B = """<Problem>
  <Events>
    <PeriodicEvent name="a" forceDt="1"/>
    <PeriodicEvent name="b" forceDt="2"/>
    <PeriodicEvent name="c" forceDt="3"/>
  </Events>
</Problem>"""

GEN_B = """<Problem>
  <Events>
    <PeriodicEvent name="c" forceDt="3"/>
    <PeriodicEvent name="a" forceDt="1"/>
    <PeriodicEvent name="zzz" forceDt="9"/>
  </Events>
</Problem>"""


def _write(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return directory


# ------------------------------------------------------- TreeSim parity

def test_treesim_matches_the_pinned_value_for_case_a():
    # Pinned against repo3/src/eval/judge_geos.py at port time. A change here
    # is a metric change and invalidates every previously scored candidate.
    result = tree_sim_section_scores(ET.fromstring(GT_A), ET.fromstring(GEN_A))
    assert result["treesim"] == 0.5842
    assert result["section_scores"] == {
        "Constitutive": 0.0,
        "Events": 0.65,
        "Mesh": 1.0,
        "Solvers": 0.7667,
    }


def test_treesim_matches_the_pinned_value_for_case_b():
    result = tree_sim_section_scores(ET.fromstring(GT_B), ET.fromstring(GEN_B))
    assert result["treesim"] == 0.7492
    assert result["section_scores"] == {"Events": 0.7492}


def test_treesim_constants_are_the_ported_ones():
    from harness_evolve.simulators import geos

    assert (geos.TREESIM_ALPHA, geos.TREESIM_BETA, geos.NUMERIC_RTOL) == (
        0.3, 0.1, 1e-6
    )


def test_identical_trees_score_one():
    root = ET.fromstring(GT_A)
    score, _ = tree_sim(root, ET.fromstring(GT_A))
    assert score == 1.0
    assert root.tag == "Problem"


def test_numerically_equivalent_attribute_values_are_equal():
    assert values_equivalent("1e6", "1000000")
    assert values_equivalent("{1, 2}", "{1.0, 2.0}")
    assert values_equivalent("QuasiStatic", "quasistatic")
    assert not values_equivalent("1e6", "1e5")
    assert not values_equivalent("{1, 2}", "{1, 2, 3}")


def test_extra_elements_are_penalised_by_beta():
    gt = ET.fromstring("<Problem><Events><PeriodicEvent name='a'/></Events></Problem>")
    gen = ET.fromstring(
        "<Problem><Events><PeriodicEvent name='a'/>"
        "<PeriodicEvent name='x'/></Events></Problem>"
    )
    score, _ = tree_sim(gt, gen)
    # Events: 1 matched of 1 GT child, 1 extra -> 1.0 - beta * (1/2) = 0.95.
    # Problem: its one interior child blends alpha * own attrs with the subtree
    # -> 0.3 * 1.0 + 0.7 * 0.95 = 0.965.
    assert score == pytest.approx(0.965)


@pytest.mark.skipif(
    not REPO3_JUDGE.exists(), reason="repo3 source not present in this environment"
)
def test_treesim_is_numerically_identical_to_the_repo3_implementation():
    spec = importlib.util.spec_from_file_location("repo3_judge_geos", REPO3_JUDGE)
    original = importlib.util.module_from_spec(spec)
    sys.modules["repo3_judge_geos"] = original
    spec.loader.exec_module(original)

    tags = [
        "Solvers", "Mesh", "Events", "Constitutive", "PeriodicEvent",
        "FieldSpecification", "CellElementRegion", "ElasticIsotropic",
    ]
    values = ["1", "1.0", "1e0", "{1, 2}", "{1.0000001, 2}", "Foo", "foo"]

    def build(rng: random.Random, depth: int = 0) -> ET.Element:
        elem = ET.Element(rng.choice(tags))
        if rng.random() < 0.8:
            elem.set("name", rng.choice(["a", "b", "c", "d"]))
        for key in rng.sample(["x", "y", "z", "logLevel", "targetRegions"], rng.randint(0, 4)):
            elem.set(key, rng.choice(values))
        if depth < 3:
            for _ in range(rng.randint(0, 3)):
                elem.append(build(rng, depth + 1))
        return elem

    for i in range(120):
        rng = random.Random(i)
        gt, gen = build(rng), build(rng)
        assert tree_sim(gt, gen)[0] == original.tree_sim(gt, gen)[0]
        assert (
            tree_sim_section_scores(gt, gen)["section_scores"]
            == original.tree_sim_section_scores(gt, gen)["section_scores"]
        )


# ------------------------------------------------------- loading / includes

def test_included_files_are_spliced_into_the_deck(tmp_path):
    _write(
        tmp_path,
        {
            "main.xml": (
                "<Problem><Included><File name='mesh.xml'/></Included>"
                "<Events/></Problem>"
            ),
            "mesh.xml": "<Problem><Mesh><InternalMesh name='m'/></Mesh></Problem>",
        },
    )
    root = load_and_resolve_dir(tmp_path)
    assert {c.tag for c in root} == {"Mesh", "Events"}


def test_geos_extension_dependencies_are_resolved_too(tmp_path):
    # `.geos` include targets are real; treating them as invisible is what let
    # their basenames reach a shipped adapter in the previous system.
    _write(
        tmp_path,
        {
            "main.xml": (
                "<Problem><Included><File name='dep.geos'/></Included></Problem>"
            ),
            "dep.geos": "<Problem><Constitutive/></Problem>",
        },
    )
    assert {c.tag for c in load_and_resolve_dir(tmp_path)} == {"Constitutive"}


def test_include_cycles_terminate(tmp_path):
    _write(
        tmp_path,
        {
            "a.xml": "<Problem><Included><File name='b.xml'/></Included></Problem>",
            "b.xml": "<Problem><Included><File name='a.xml'/></Included><Mesh/></Problem>",
        },
    )
    root = load_and_resolve_dir(tmp_path)
    assert any(c.tag == "Mesh" for c in root.iter())


def test_entry_files_excludes_included_fragments(tmp_path):
    _write(
        tmp_path,
        {
            "main.xml": "<Problem><Included><File name='mesh.xml'/></Included></Problem>",
            "mesh.xml": "<Problem><Mesh/></Problem>",
        },
    )
    assert [p.name for p in entry_files(tmp_path)] == ["main.xml"]


def test_multiple_entry_files_merge_rather_than_error(tmp_path):
    _write(tmp_path, {"a.xml": "<Problem><Mesh/></Problem>",
                      "b.xml": "<Problem><Events/></Problem>"})
    assert {c.tag for c in load_and_resolve_dir(tmp_path)} == {"Mesh", "Events"}


# --------------------------------------------------------------- scoring

def test_score_reproduces_the_pinned_treesim_from_directories(tmp_path):
    sim = GeosSimulator()
    gt = _write(tmp_path / "gt", {"deck.xml": GT_A})
    gen = _write(tmp_path / "gen", {"deck.xml": GEN_A})
    score = sim.score(gen, gt, "caseA")
    assert score.value == 0.5842
    assert score.status == "success"
    assert score.detail["gen_sections"] == ["Debug", "Events", "Mesh", "Solvers"]


def test_empty_workspace_scores_zero_not_absent(tmp_path):
    sim = GeosSimulator()
    gt = _write(tmp_path / "gt", {"deck.xml": GT_A})
    empty = tmp_path / "gen"
    empty.mkdir()
    score = sim.score(empty, gt, "caseA")
    assert score.value == 0.0
    assert score.status == "empty_workspace"
    assert score.is_zero and score.is_failure


def test_unparseable_deck_scores_zero(tmp_path):
    sim = GeosSimulator()
    gt = _write(tmp_path / "gt", {"deck.xml": GT_A})
    gen = _write(tmp_path / "gen", {"deck.xml": "<Problem><Mesh></Problem>"})
    score = sim.score(gen, gt, "caseA")
    assert score.value == 0.0
    assert score.status == "parse_error"


def test_missing_ground_truth_is_distinguishable_from_an_empty_workspace(tmp_path):
    sim = GeosSimulator()
    gen = _write(tmp_path / "gen", {"deck.xml": GT_A})
    assert sim.score(gen, tmp_path / "nope", "caseA").status == "missing_ground_truth"


def test_parse_records_geos_files_and_never_raises(tmp_path):
    sim = GeosSimulator()
    _write(tmp_path, {"deck.xml": GT_A, "dep.geos": "<Problem/>"})
    artifact = sim.parse(tmp_path)
    assert set(artifact.files) == {"deck.xml", "dep.geos"}
    assert artifact.parses
    assert sim.parse(tmp_path / "absent").parse_errors


def test_present_sections_and_completeness_gate(tmp_path):
    sim = GeosSimulator()
    _write(tmp_path, {"deck.xml": GEN_A})
    artifact = sim.parse(tmp_path)
    assert sim.present_sections(artifact) == {"Solvers", "Mesh", "Events", "Debug"}
    missing = [f.message for f in sim.check_completeness(artifact)]
    assert any("Constitutive" in m for m in missing)
    assert any("ElementRegions" in m for m in missing)


# ------------------------------------------------------------- diagnosis

def test_diagnose_reports_sections_subtrees_and_a_category(tmp_path):
    sim = GeosSimulator()
    gt = _write(tmp_path / "gt", {"deck.xml": GT_A})
    gen = _write(tmp_path / "gen", {"deck.xml": GEN_A})
    diagnosis = sim.diagnose(gen, gt, "caseA")
    assert diagnosis.section_scores["Constitutive"] == 0.0
    assert diagnosis.weakest_sections(1) == [("Constitutive", 0.0)]
    assert "ElasticIsotropic" in diagnosis.missing_elements
    assert "Debug" in diagnosis.extra_elements
    assert diagnosis.category == "missing_block"
    assert any("required sections absent" in n for n in diagnosis.notes)


def test_worst_subtrees_rank_by_impact_not_by_score():
    _, detail = tree_sim(ET.fromstring(GT_A), ET.fromstring(GEN_A))
    ranked = worst_subtrees(detail, k=3)
    assert [entry["path"] for entry in ranked[:2]] == ["/Problem", "/Problem/Events"]
    assert ranked[0]["impact"] > ranked[1]["impact"]
    assert ranked[0]["missing_child_count"] == 1


def test_attribute_mismatches_are_surfaced_as_evidence(tmp_path):
    result = evaluate_directories(
        _write(tmp_path / "gt", {"d.xml": GT_A}),
        _write(tmp_path / "gen", {"d.xml": GEN_A}),
    )
    assert any("logLevel" in note for note in result["attr_mismatches"])


# ---------------------------------------------------------- contamination

def test_leaky_extensions_include_geos():
    # The `.xml`-only gate in the previous system is how ground-truth `.geos`
    # dependency filenames reached a shipped adapter.
    sim = GeosSimulator()
    assert set(sim.leaky_extensions) == {"xml", "geos"}
    pattern = sim.leak_pattern()
    assert pattern.search("copy buckleyLeverett_base.xml")
    assert pattern.search("also see tableFunctions.geos")


def test_contamination_expands_variant_siblings(tmp_path):
    source = tmp_path / "geos_src"
    _write(
        source / "examples",
        {
            "buckleyLeverettProblem_base.xml": "<Problem/>",
            "buckleyLeverettProblem_benchmark.xml": "<Problem/>",
            "buckleyLeverettProblem_smoke.xml": "<Problem/>",
            "unrelatedCompaction_base.xml": "<Problem/>",
        },
    )
    gt_root = tmp_path / "gt"
    _write(gt_root / "buckleyLeverettProblem",
           {"buckleyLeverettProblem_base.xml": "<Problem/>"})

    sim = GeosSimulator(geos_source_dir=source)
    policy = sim.contamination_policy("buckleyLeverettProblem", gt_root)
    assert "buckleyleverettproblem_benchmark.xml" in policy.blocked_basenames
    assert "buckleyleverettproblem_smoke.xml" in policy.blocked_basenames
    assert "unrelatedcompaction_base.xml" not in policy.blocked_basenames


def test_contamination_expansion_also_covers_geos_siblings(tmp_path):
    source = tmp_path / "geos_src"
    _write(source, {
        "buckleyLeverettProblem_base.xml": "<Problem/>",
        "buckleyLeverettProblem_benchmark.geos": "<Problem/>",
    })
    gt_root = tmp_path / "gt"
    _write(gt_root / "buckleyLeverettProblem",
           {"buckleyLeverettProblem_base.xml": "<Problem/>"})
    policy = GeosSimulator(geos_source_dir=source).contamination_policy(
        "buckleyLeverettProblem", gt_root
    )
    assert "buckleyleverettproblem_benchmark.geos" in policy.blocked_basenames


def test_generic_stems_do_not_expand(tmp_path):
    # Blocking every `base.xml` in the GEOS tree would hide most of the corpus.
    assert variant_stem_keys("base.xml") == set()
    assert variant_stem_keys("input.xml") == set()
    assert variant_stem_keys("shortname.xml") == set()
    # Suffix stripping is transitive, so an `_iterative` variant of a `_base`
    # deck blocks the plain stem, the `_base` sibling, and itself.
    assert variant_stem_keys("buckleyLeverettProblem_base_iterative.xml") == {
        "buckleyleverettproblem",
        "buckleyleverettproblem_base",
        "buckleyleverettproblem_base_iterative",
    }


def test_expansion_without_a_source_tree_keeps_the_exact_names(tmp_path):
    gt_root = tmp_path / "gt"
    _write(gt_root / "someLongTaskName", {"someLongTaskName_base.xml": "<Problem/>"})
    policy = GeosSimulator(geos_source_dir=None).contamination_policy(
        "someLongTaskName", gt_root
    )
    assert policy.blocked_basenames == {"somelongtaskname_base.xml"}
    assert "no variant expansion" in policy.reason


def test_expand_with_variants_is_a_noop_for_a_missing_source_dir(tmp_path):
    assert expand_with_variants(
        {"buckleyLeverettProblem_base.xml"}, tmp_path / "nope"
    ) == {"buckleyleverettproblem_base.xml"}


# ------------------------------------------------------------- validation

#: Abridged from a real `geosx --validate-input` unknown-attribute failure. The
#: valid-attribute table is the payload the harness exists to route back to the
#: agent, so the test asserts it survives verbatim.
GEOSX_ERROR = """\
***** ERROR
***** LOCATION: /path/to/xmlWrapper.cpp:198
***** Controlling expression (should be false): true
XML Node ImmiscibleMultiphaseFlow with name=FlowSolver contains unused attribute 'totallyBogusAttribute'.
Valid attributes are:
{cflFactor, discretization, initialDt, logLevel, name, targetRegions, ...}
"""


def _stub_geosx(tmp_path: Path, *, exit_code: int, stderr: str = "") -> Path:
    script = tmp_path / "geosx_stub.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"cat >&2 <<'EOF'\n{stderr}EOF\n"
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    return script


def test_validate_returns_the_validator_output_verbatim(tmp_path):
    workspace = _write(tmp_path / "ws", {"deck.xml": GEN_A})
    sim = GeosSimulator(
        geosx_executable=str(_stub_geosx(tmp_path, exit_code=1, stderr=GEOSX_ERROR))
    )
    findings = sim.validate(sim.parse(workspace), workspace)
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 1
    assert errors[0].message == GEOSX_ERROR.strip()
    assert "Valid attributes are:" in errors[0].message
    assert errors[0].location == "deck.xml"


def test_validate_passing_deck_reports_info(tmp_path):
    workspace = _write(tmp_path / "ws", {"deck.xml": GT_A})
    sim = GeosSimulator(geosx_executable=str(_stub_geosx(tmp_path, exit_code=0)))
    findings = sim.validate(sim.parse(workspace), workspace)
    assert [f.severity for f in findings] == ["info"]


def test_validate_without_a_binary_degrades_to_info(tmp_path):
    # An `error` here would block on something the agent cannot act on.
    workspace = _write(tmp_path / "ws", {"deck.xml": GT_A})
    sim = GeosSimulator(geosx_executable="")
    findings = sim.validate(sim.parse(workspace), workspace)
    assert [f.severity for f in findings] == ["info"]
    assert "GEOSX_EXECUTABLE" in findings[0].message


def test_validate_reports_xml_parse_errors_before_reaching_geosx(tmp_path):
    workspace = _write(tmp_path / "ws", {"deck.xml": "<Problem><Mesh></Problem>"})
    sim = GeosSimulator(geosx_executable="")
    findings = sim.validate(sim.parse(workspace), workspace)
    assert findings[0].source == "xml_parse"
    assert findings[0].location == "deck.xml"


def test_validate_only_targets_entry_decks(tmp_path):
    workspace = _write(
        tmp_path / "ws",
        {
            "main.xml": "<Problem><Included><File name='mesh.xml'/></Included></Problem>",
            "mesh.xml": "<Problem><Mesh/></Problem>",
        },
    )
    sim = GeosSimulator(geosx_executable=str(_stub_geosx(tmp_path, exit_code=0)))
    findings = sim.validate(sim.parse(workspace), workspace)
    assert [f.location for f in findings] == ["main.xml"]


def test_preflight_reports_a_missing_binary_rather_than_raising():
    assert GeosSimulator(geosx_executable="").preflight() == [
        "GEOSX_EXECUTABLE is not set; geosx --validate-input unavailable"
    ]
    assert GeosSimulator(geosx_executable="/nonexistent/geosx").preflight() == [
        "geosx binary not found at /nonexistent/geosx"
    ]


@pytest.mark.skipif(
    not os.environ.get("GEOSX_EXECUTABLE"), reason="no geosx binary available"
)
def test_validate_runs_the_real_geosx_binary(tmp_path):
    workspace = _write(tmp_path / "ws", {"deck.xml": GT_A})
    sim = GeosSimulator()
    assert sim.preflight() == []
    findings = sim.validate(sim.parse(workspace), workspace)
    assert findings and all(f.source == "geosx_validate" for f in findings)


def test_geos_table_data_is_collected_but_not_xml_parsed(tmp_path):
    """`.geos` files are columns of numbers, not XML.

    Measured 2026-08-26 on ExampleIsothermalLeakyWell (the best-scoring rollout
    in the GEOS pool, 0.9802): it wrote pressure.geos / xlin.geos / ylin.geos /
    zlin.geos alongside a valid deck, and every one produced
    "syntax error: line 1, column 0". A stop policy running the `parse` check
    would have blocked a near-perfect deck on its own legitimate output.
    """
    from harness_evolve.simulators.base import SimulatorRegistry

    (tmp_path / "deck.xml").write_text(
        '<Problem>\n  <Mesh name="m"/>\n</Problem>\n'
    )
    (tmp_path / "pressure.geos").write_text("3.086e7\n3.086e7\n")
    (tmp_path / "xlin.geos").write_text("-500\n500\n")

    artifact = SimulatorRegistry.get("geos").parse(tmp_path)

    # Collected -- a hygiene check that cannot see them cannot flag them.
    assert "pressure.geos" in artifact.files
    assert "xlin.geos" in artifact.files
    # But not reported as broken XML.
    assert artifact.parse_errors == {}
    assert artifact.parses


def test_a_genuinely_broken_deck_still_reports_a_parse_error(tmp_path):
    from harness_evolve.simulators.base import SimulatorRegistry

    (tmp_path / "deck.xml").write_text("<Problem><Mesh></Problem>\n")
    (tmp_path / "table.geos").write_text("1.0\n")

    artifact = SimulatorRegistry.get("geos").parse(tmp_path)
    assert "deck.xml" in artifact.parse_errors
    assert "table.geos" not in artifact.parse_errors


def test_the_parse_check_passes_a_deck_with_table_data(tmp_path):
    """End to end: the check the stop policy runs must not fire on this."""
    from harness_evolve.checks.api import CheckContext, run_checks
    from harness_evolve.simulators.base import SimulatorRegistry

    sim = SimulatorRegistry.get("geos")
    (tmp_path / "deck.xml").write_text('<Problem>\n  <Mesh name="m"/>\n</Problem>\n')
    (tmp_path / "pressure.geos").write_text("3.086e7\n")

    artifact = sim.parse(tmp_path)
    ctx = CheckContext.from_simulator(sim, tmp_path)
    assert run_checks(artifact, ctx, ["parse"]) == []
