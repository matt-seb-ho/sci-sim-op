"""Tests for the contamination gate.

Three layers, in increasing order of what they prove:

1. Every rule in isolation, firing and silent.
2. Integration against the two real leaky artifacts in ``repo3`` -- the
   ``.geos`` dependency filenames and the task-id lookup table. These are the
   regressions the gate exists for, so they are asserted specifically rather
   than through an aggregate "is blocked" check. Skipped, not failed, when the
   predecessor tree is absent.
3. False positives. A legitimately useful adapter must pass with no blocking
   finding, because a gate people route around is worse than no gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_evolve.hygiene.audit import audit_dir, main, read_adapter_dir
from harness_evolve.hygiene.corpus import (
    GroundTruthCorpus,
    canonical_numerics,
    canonicalize_number,
    stem_keys,
)
from harness_evolve.hygiene.gate import (
    GateConfig,
    HygieneError,
    check_candidate,
    check_texts,
    rule_blocklist,
    rule_content_overlap,
    rule_filenames,
    rule_lookup_language,
    rule_lookup_tables,
    rule_near_miss_filenames,
    rule_numeric_leakage,
    rule_path_components,
    rule_rare_token_overlap,
    rule_structural_fingerprint,
    rule_task_ids,
)
from harness_evolve.simulators.base import Artifact, ContaminationPolicy, SimulatorSpec
from harness_evolve.types import Finding, Score

REPO3 = Path("/home/agent/repo3")
V3_DIR = REPO3 / "plugin_evolving/v3"
V4_DIR = REPO3 / "plugin_evolving/_quarantine/v4"
BLOCKLIST = REPO3 / "misc/memory_artifacts/test_blocklist.json"

needs_repo3 = pytest.mark.skipif(
    not (V3_DIR.is_dir() and V4_DIR.is_dir() and BLOCKLIST.is_file()),
    reason="predecessor artifacts (repo3) not present",
)


# ---------------------------------------------------------------------------
# fixtures: a miniature ground truth
# ---------------------------------------------------------------------------

DECK_MANDEL = """<Problem>
  <Solvers>
    <SinglePhasePoromechanics name="poroSolver" flowSolverName="flowSolver"
                              targetRegions="{ Domain }">
      <LinearSolverParameters directParallel="0"/>
    </SinglePhasePoromechanics>
  </Solvers>
  <Mesh>
    <InternalMesh name="mesh1" xCoords="{ 0, 1 }" yCoords="{ 0, 0.1 }"/>
  </Mesh>
  <Constitutive>
    <ElasticIsotropic name="rockSolid" defaultBulkModulus="5.55e9"
                      defaultShearModulus="3.33e9"/>
    <BiotPorosity name="rockPorosity" defaultReferencePorosity="3.75e-1"/>
    <ConstantPermeability name="rockPerm"
                          permeabilityComponents="{ 1.0e-12, 1.0e-12, 1.0e-12 }"/>
  </Constitutive>
  <Outputs>
    <VTK name="vtkOutput"/>
  </Outputs>
</Problem>
"""

DECK_TERZAGHI = """<Problem>
  <Solvers>
    <SinglePhasePoromechanics name="poroSolver" targetRegions="{ Domain }"/>
  </Solvers>
  <Mesh>
    <InternalMesh name="mesh1" xCoords="{ 0, 10 }"/>
  </Mesh>
  <Constitutive>
    <ElasticIsotropic name="rockSolid" defaultBulkModulus="1.0e4"
                      defaultShearModulus="6.0e3"/>
    <CompressibleSinglePhaseFluid name="water" referenceViscosity="2.9e-9"/>
  </Constitutive>
  <Outputs>
    <VTK name="vtkOutput"/>
  </Outputs>
</Problem>
"""

#: Deliberately long chain of *distinctive* elements, so a candidate that
#: reproduces the ordering without copying the text is detectable.
DECK_KGD = """<Problem>
  <Solvers>
    <Hydrofracture name="hydrofracture" couplingTypeOption="FIM">
      <SurfaceGenerator name="surfaceGen" rockToughness="1.0e6"/>
      <EmbeddedSurfaceGenerator name="embeddedGen"/>
      <FluxBoundaryCondition name="injection" scale="-2.5e-3"/>
      <ContactMechanics name="contact"/>
      <SolidMechanicsLagrangianSSLE name="lagSolve"/>
      <CompositionalMultiphaseFVM name="multiphase"/>
      <ThermoPoromechanics name="thermoPoro"/>
      <InternalWellboreGenerator name="wellboreGen"/>
      <TableFunction name="kgdEdgeBasedLoading" interpolation="linear"/>
    </Hydrofracture>
  </Solvers>
  <Mesh>
    <InternalMesh name="mesh1"/>
  </Mesh>
  <Constitutive>
    <ElasticIsotropic name="rockSolid" defaultBulkModulus="2.0e10"/>
  </Constitutive>
  <Outputs>
    <VTK name="vtkOutput"/>
  </Outputs>
</Problem>
"""


@pytest.fixture()
def corpus() -> GroundTruthCorpus:
    """A corpus built directly from parts; no data volume required."""
    return GroundTruthCorpus(
        blocked_basenames={
            "poroelastic_mandel_base.xml",
            "poroelastic_terzaghi_base_direct.xml",
            "kgdvalidation_benchmark.xml",
            "time.geos",
        },
        blocked_path_parts={"poromechanics", "hydraulicfracturing"},
        task_ids={"ExampleMandel", "TutorialPoroelasticity", "kgdExperimentValidation"},
        deck_texts={
            "ExampleMandel/PoroElastic_Mandel_base.xml": DECK_MANDEL,
            "TutorialPoroelasticity/PoroElastic_Terzaghi_base_direct.xml": DECK_TERZAGHI,
            "kgdExperimentValidation/kgdValidation_benchmark.xml": DECK_KGD,
        },
    )


CFG = GateConfig()


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["1.0e-4", "1e-4", "1.0E-04", "1.0d-4", "$1.0\\times10^{-4}$", "1.0x10^-4", "1.0×10⁻⁴"],
)
def test_numeric_canonicalization_is_notation_blind(raw: str) -> None:
    assert canonicalize_number(raw) == "0.0001"


def test_canonical_numerics_suppresses_trivial_values() -> None:
    text = "Step 1 of 3: set the flag to 1.0, then loop 100 times (see section 2.0)."
    assert canonical_numerics(text) == set()


def test_canonical_numerics_finds_scientific_and_latex_forms() -> None:
    found = canonical_numerics("permeability $1.0\\times10^{-12}$ and modulus 5.55e9")
    assert found == {"1e-12", "5.55e+09"}


def test_stem_keys_strips_variant_suffixes() -> None:
    keys = stem_keys("PoroElastic_Mandel_base.xml")
    assert "poroelastic_mandel" in keys
    assert "poroelastic_mandel_base" in keys


def test_stem_keys_drops_generic_and_short_stems() -> None:
    assert stem_keys("base.xml") == set()
    assert stem_keys("kgd.xml") == set()


def test_corpus_derives_numerics_and_indexes_from_decks(corpus: GroundTruthCorpus) -> None:
    assert "1e-12" in corpus.numeric_literals
    assert corpus.n_decks == 3
    assert corpus.summary()["decks"] == 3
    # Elements every deck carries are schema boilerplate, not a fingerprint.
    assert {"Problem", "Solvers", "Mesh", "Constitutive"} <= corpus.common_elements
    assert "SurfaceGenerator" not in corpus.common_elements


def test_corpus_idf_prefers_rare_identifiers(corpus: GroundTruthCorpus) -> None:
    assert corpus.idf("kgdedgebasedloading") > corpus.idf("name")


def test_corpus_from_ground_truth_dir(tmp_path: Path) -> None:
    task = tmp_path / "ExampleMandel" / "poromechanics"
    task.mkdir(parents=True)
    (task / "PoroElastic_Mandel_base.xml").write_text(DECK_MANDEL)
    (task / "time.geos").write_text("0.0 1.0 2.0\n")

    corpus = GroundTruthCorpus.from_ground_truth_dir(tmp_path)

    assert corpus.task_ids == {"ExampleMandel"}
    assert "poroelastic_mandel_base.xml" in corpus.blocked_basenames
    assert "time.geos" in corpus.blocked_basenames
    assert "poromechanics" in corpus.blocked_path_parts
    assert corpus.deck_texts
    assert "poroelastic_mandel" in corpus.filename_stems


class _FakeSpec(SimulatorSpec):
    """Minimal spec whose policy expands variant siblings, as GEOS's does."""

    name = "fake"
    leaky_extensions = ("xml", "geos")

    def parse(self, workspace: Path) -> Artifact:  # pragma: no cover - unused
        return Artifact()

    def validate(self, artifact: Artifact, workspace: Path) -> list[Finding]:
        return []  # pragma: no cover - unused

    def score(self, generated: Path, ground_truth: Path, task: str) -> Score:
        return Score(task, 0.0)  # pragma: no cover - unused

    def contamination_policy(
        self, task: str, ground_truth_root: Path
    ) -> ContaminationPolicy:
        return ContaminationPolicy(
            blocked_basenames={"poroelastic_mandel_benchmark.xml"},
            blocked_paths={"src/docs/poromechanics/Example.rst"},
            reason="variant siblings",
        )


def test_corpus_takes_blocklist_from_the_simulator_policy(tmp_path: Path) -> None:
    """The runtime gate and the hygiene gate must not be able to drift apart."""
    task = tmp_path / "ExampleMandel"
    task.mkdir()
    (task / "PoroElastic_Mandel_base.xml").write_text(DECK_MANDEL)

    corpus = GroundTruthCorpus.from_ground_truth_dir(tmp_path, simulator=_FakeSpec())

    # The sibling is on disk nowhere; it is known only to the policy.
    assert "poroelastic_mandel_benchmark.xml" in corpus.blocked_basenames
    assert "example.rst" in corpus.blocked_basenames
    assert corpus.leaky_extensions == ("xml", "geos")


def test_corpus_from_blocklist_json(tmp_path: Path) -> None:
    payload = {
        "union_xml": ["poroelastic_mandel_base.xml"],
        "per_task_xml": {"ExampleMandel": ["poroelastic_mandel_benchmark.xml"]},
        "union_rst_relpaths": ["src/docs/poromechanics/Example.rst"],
    }
    p = tmp_path / "blocklist.json"
    p.write_text(json.dumps(payload))

    corpus = GroundTruthCorpus.from_blocklist_json(p)

    assert corpus.task_ids == {"ExampleMandel"}
    assert "poroelastic_mandel_benchmark.xml" in corpus.blocked_basenames
    assert "poromechanics" in corpus.blocked_path_parts
    assert not corpus.deck_texts


def test_empty_corpus_is_reported_as_empty() -> None:
    assert GroundTruthCorpus().is_empty


# ---------------------------------------------------------------------------
# rules, individually
# ---------------------------------------------------------------------------


def test_filenames_rule_covers_every_leaky_extension(corpus: GroundTruthCorpus) -> None:
    """Incident 1: a `.xml`-only regex let `.geos` dependency names through."""
    text = "Copy `tables/time.geos`, `tables/axialStrain.geos` and mesh.vtu first."
    findings = rule_filenames("skills/copy.md", text, corpus, CFG)

    names = {f.message for f in findings}
    assert any("time.geos" in m for m in names)
    assert any("axialStrain.geos" in m for m in names)
    assert any("mesh.vtu" in m for m in names)
    assert all(f.severity == "error" for f in findings)
    # A known ground-truth name is attributed as such; an unknown one is not.
    assert {f.source for f in findings} == {"filename", "filename_generic"}


def test_filenames_rule_ignores_bare_extensions(corpus: GroundTruthCorpus) -> None:
    text = "Base files often ship table data as .geos, .txt or .csv files."
    assert rule_filenames("PRIMER.md", text, corpus, CFG) == []


def test_filenames_rule_reports_a_line_number(corpus: GroundTruthCorpus) -> None:
    findings = rule_filenames("a.md", "intro\n\nread time.geos\n", corpus, CFG)
    assert findings[0].location == "a.md:3"


def test_path_component_rule_blocks_a_path_prefix(corpus: GroundTruthCorpus) -> None:
    """Incident 1's second half: `poromechanics/<file>` survived redaction."""
    findings = rule_path_components("PRIMER.md", "see poromechanics/Foo_base", corpus, CFG)
    assert [f.severity for f in findings] == ["error"]


def test_path_component_rule_only_warns_on_a_bare_mention(
    corpus: GroundTruthCorpus,
) -> None:
    findings = rule_path_components(
        "PRIMER.md", "files live in poromechanics/", corpus, CFG
    )
    assert [f.severity for f in findings] == ["warn"]


def test_path_component_rule_is_silent_on_ordinary_prose(
    corpus: GroundTruthCorpus,
) -> None:
    assert rule_path_components("PRIMER.md", "poroelastic problems", corpus, CFG) == []


def test_task_id_rule_blocks_a_table_of_task_ids(corpus: GroundTruthCorpus) -> None:
    """Incident 2: two or more task ids in one artifact is the v4 signature."""
    text = "| ExampleMandel | ... |\n| kgdExperimentValidation | ... |"
    findings = rule_task_ids("memory/cheatsheet.md", text, corpus, CFG)

    assert len(findings) == 1
    assert findings[0].source == "task_id_table"
    assert findings[0].severity == "error"
    assert "2 evaluation task ids" in findings[0].message


def test_task_id_rule_blocks_a_single_task_id(corpus: GroundTruthCorpus) -> None:
    findings = rule_task_ids(
        "PRIMER.md", "For ExampleMandel, use a coupled solver", corpus, CFG
    )
    assert [(f.source, f.severity) for f in findings] == [("task_id", "error")]


def test_task_id_rule_is_silent_without_task_ids(corpus: GroundTruthCorpus) -> None:
    text = "Mandel-type consolidation problems"
    assert rule_task_ids("PRIMER.md", text, corpus, CFG) == []


def test_blocklist_rule_matches_substrings(corpus: GroundTruthCorpus) -> None:
    text = "see_also_poroelastic_mandel_base.xml_and_others"
    findings = rule_blocklist("memory/cheatsheet.md", text, corpus, CFG)
    assert [f.severity for f in findings] == ["error"]


def test_content_overlap_rule_catches_a_copied_deck_fragment(
    corpus: GroundTruthCorpus,
) -> None:
    """The predecessor gate was filename-only and could not see content at all."""
    leaked = "Start from:\n" + DECK_MANDEL[:600]
    findings = rule_content_overlap("memory/cheatsheet.md", leaked, corpus, CFG)

    assert findings and findings[0].severity == "error"
    assert "PoroElastic_Mandel_base.xml" in findings[0].message


def test_content_overlap_rule_is_silent_on_independent_prose(
    corpus: GroundTruthCorpus,
) -> None:
    text = (
        "Coupled problems need a solid model, a porosity model and a permeability "
        "model, each named and referenced from the element region."
    )
    assert rule_content_overlap("PRIMER.md", text, corpus, CFG) == []


def test_numeric_rule_catches_ground_truth_values_in_any_notation(
    corpus: GroundTruthCorpus,
) -> None:
    text = (
        "Typical values: bulk 5.55e9, shear 3.33e9, porosity 3.75e-1, "
        "permeability $1.0\\times10^{-12}$, viscosity 2.9x10⁻⁹, toughness 1.0e6."
    )
    findings = rule_numeric_leakage("memory/cheatsheet.md", text, corpus, CFG)

    assert findings and findings[0].severity == "error"
    assert "6 ground-truth numeric" in findings[0].message


def test_numeric_rule_is_silent_on_trivial_numbers(corpus: GroundTruthCorpus) -> None:
    text = "Step 1: set logLevel to 1. Step 2: use 3 Newton iterations, tol 0.5."
    assert rule_numeric_leakage("PRIMER.md", text, corpus, CFG) == []


def test_near_miss_rule_catches_a_filename_family_without_its_extension(
    corpus: GroundTruthCorpus,
) -> None:
    """v3 shipped `PoroElastic_Mandel_*`, which no extension-anchored rule sees."""
    findings = rule_near_miss_filenames(
        "PRIMER.md", "look for PoroElastic_Mandel_* and PoroElastic_Terzaghi_*", corpus, CFG
    )
    assert len(findings) == 2
    assert all(f.severity == "error" for f in findings)


def test_near_miss_rule_only_warns_on_an_ambiguous_single_word_stem() -> None:
    """`TriaxialDriver` is a deck name *and* a solver class; blocking would be wrong."""
    corpus = GroundTruthCorpus(blocked_basenames={"triaxialDriver_base.xml"})
    findings = rule_near_miss_filenames(
        "PRIMER.md",
        "Use the `<TriaxialDriver>` solver for material point tests",
        corpus,
        CFG,
    )
    assert [f.severity for f in findings] == ["warn"]


def test_near_miss_rule_blocks_the_same_stem_used_as_a_path() -> None:
    corpus = GroundTruthCorpus(blocked_basenames={"triaxialDriver_base.xml"})
    findings = rule_near_miss_filenames("PRIMER.md", "under triaxialDriver/", corpus, CFG)
    assert [f.severity for f in findings] == ["error"]


def test_near_miss_rule_is_silent_on_physics_vocabulary(corpus: GroundTruthCorpus) -> None:
    text = "Poroelastic problems need a coupled solver and a constitutive block."
    assert rule_near_miss_filenames("PRIMER.md", text, corpus, CFG) == []


def test_structural_fingerprint_rule_catches_a_reproduced_element_sequence(
    corpus: GroundTruthCorpus,
) -> None:
    """An adapter can hand over a deck's skeleton while sharing no n-gram with it."""
    paraphrase = (
        "Order the blocks like this: <SurfaceGenerator>, then "
        "<EmbeddedSurfaceGenerator>, then <FluxBoundaryCondition>, then "
        "<ContactMechanics>, then <SolidMechanicsLagrangianSSLE>, then "
        "<CompositionalMultiphaseFVM>, then <ThermoPoromechanics>, then "
        "<InternalWellboreGenerator>, then <TableFunction>."
    )
    findings = rule_structural_fingerprint("memory/cheatsheet.md", paraphrase, corpus, CFG)

    assert findings and findings[0].severity == "error"
    assert "kgdValidation_benchmark.xml" in findings[0].message
    assert rule_content_overlap("memory/cheatsheet.md", paraphrase, corpus, CFG) == []


def test_structural_fingerprint_rule_ignores_schema_boilerplate(
    corpus: GroundTruthCorpus,
) -> None:
    text = (
        "Every deck needs <Problem>, <Solvers>, <Mesh>, <Constitutive> and "
        "<Outputs> blocks, in that order."
    )
    assert rule_structural_fingerprint("PRIMER.md", text, corpus, CFG) == []


def test_rare_token_rule_weights_by_inverse_document_frequency(
    corpus: GroundTruthCorpus,
) -> None:
    text = (
        "Set rockToughness on the generator, add an embeddedGen and a wellboreGen, "
        "name the loading table kgdEdgeBasedLoading, and set couplingTypeOption."
    )
    findings = rule_rare_token_overlap("memory/cheatsheet.md", text, corpus, CFG)
    assert findings and findings[0].severity in ("warn", "error")
    assert "kgdedgebasedloading" in findings[0].message


def test_rare_token_rule_is_silent_on_common_vocabulary(
    corpus: GroundTruthCorpus,
) -> None:
    text = "Every solver needs a name, a target region and an output block."
    assert rule_rare_token_overlap("PRIMER.md", text, corpus, CFG) == []


def test_lookup_table_rule_blocks_a_task_to_deck_table(corpus: GroundTruthCorpus) -> None:
    """Detects the *shape* of the v4 cheatsheet, so a renamed task set still trips."""
    text = (
        "| Problem | Start from |\n"
        "|---|---|\n"
        "| SomeUnknownWellboreCase | `wellbore/Foo_base.xml` |\n"
        "| AnotherUnknownFractureCase | `fracture/Bar_base.xml` |\n"
        "| ThirdUnknownConsolidation | `poro/Baz_base.xml` |\n"
    )
    corpus.task_ids = set()  # nothing here is a known task id
    findings = rule_lookup_tables("memory/cheatsheet.md", text, corpus, CFG)

    assert [f.severity for f in findings] == ["error"]
    assert "answer key" in findings[0].message


def test_lookup_table_rule_blocks_on_a_task_keyed_header(
    corpus: GroundTruthCorpus,
) -> None:
    text = "| Task name keyword | Canonical XML |\n|---|---|\n| Foo | bar |\n"
    findings = rule_lookup_tables("memory/cheatsheet.md", text, corpus, CFG)
    assert [f.severity for f in findings] == ["error"]


def test_lookup_table_rule_catches_the_same_mapping_as_a_list(
    corpus: GroundTruthCorpus,
) -> None:
    text = (
        "- SomeUnknownWellboreCase: `wellbore/Foo_base.xml`\n"
        "- AnotherUnknownFractureCase: `fracture/Bar_base.xml`\n"
        "- ThirdUnknownConsolidation: `poro/Baz_base.xml`\n"
    )
    corpus.task_ids = set()
    findings = rule_lookup_tables("memory/cheatsheet.md", text, corpus, CFG)
    assert [f.severity for f in findings] == ["error"]


def test_lookup_table_rule_only_warns_on_a_source_navigation_table(
    corpus: GroundTruthCorpus,
) -> None:
    """Pointing at source headers is a search shortcut, not an answer key."""
    text = (
        "| Class | Header |\n"
        "|---|---|\n"
        "| DruckerPrager | `constitutive/solid/DruckerPrager.hpp` |\n"
        "| ModifiedCamClay | `constitutive/solid/ModifiedCamClay.hpp` |\n"
        "| BiotPorosity | `constitutive/solid/porosity/BiotPorosity.hpp` |\n"
    )
    findings = rule_lookup_tables("memory/cheatsheet.md", text, corpus, CFG)
    assert [f.severity for f in findings] == ["warn"]


def test_lookup_table_rule_is_silent_on_a_conceptual_table(
    corpus: GroundTruthCorpus,
) -> None:
    text = (
        "| Solver | Physics |\n"
        "|---|---|\n"
        "| SinglePhasePoromechanics | coupled poroelasticity |\n"
        "| HydrofractureSolver | fluid-driven fracture |\n"
        "| CompositionalMultiphaseFVM | multiphase flow |\n"
    )
    assert rule_lookup_tables("memory/cheatsheet.md", text, corpus, CFG) == []


def test_lookup_language_is_advisory_alone_and_a_warning_in_company(
    corpus: GroundTruthCorpus,
) -> None:
    alone = rule_lookup_language("PRIMER.md", "Do not grep for `class`.", corpus, CFG)
    assert [f.severity for f in alone] == ["info"]

    paired = rule_lookup_language(
        "memory/cheatsheet.md",
        "Do not grep for it; read Foo_base.xml, it is already verified.",
        corpus,
        CFG,
    )
    assert [f.severity for f in paired] == ["warn"]


# ---------------------------------------------------------------------------
# report and entry points
# ---------------------------------------------------------------------------


def test_report_verdict_and_serialization(corpus: GroundTruthCorpus) -> None:
    report = check_texts({"memory/cheatsheet.md": "read tables/time.geos"}, corpus)

    assert report.blocked and not report.passed
    assert "filename" in report.by_rule()
    assert "memory/cheatsheet.md" in report.by_path()
    assert report.to_dict()["n_blocking"] == len(report.errors)
    assert "1 file(s) checked" in report.render()
    with pytest.raises(HygieneError, match="blocking hygiene finding"):
        report.raise_if_blocked()


def test_severity_overrides_retune_rather_than_disable(corpus: GroundTruthCorpus) -> None:
    texts = {"PRIMER.md": "use ExampleMandel's approach"}
    assert check_texts(texts, corpus).blocked

    relaxed = GateConfig(severity_overrides={"task_id": "warn"})
    report = check_texts(texts, corpus, config=relaxed)
    assert not report.blocked
    assert [f.severity for f in report.warnings] == ["warn"]


def test_findings_are_capped_without_dropping_a_blocking_one(
    corpus: GroundTruthCorpus,
) -> None:
    text = "\n".join(f"warn only poromechanics deck_{i}.xml" for i in range(30))
    cfg = GateConfig(max_findings_per_rule=2)
    findings = rule_filenames("PRIMER.md", text, corpus, cfg)

    assert len(findings) == 3  # two kept plus the "further hits" marker
    assert all(f.severity == "error" for f in findings)
    assert "further" in findings[-1].message


def test_check_candidate_reads_candidate_files(corpus: GroundTruthCorpus) -> None:
    class _Cand:
        files = {"memory/cheatsheet.md": "start from tables/time.geos"}

    assert check_candidate(_Cand(), corpus).blocked


# ---------------------------------------------------------------------------
# false positives: a legitimate adapter must pass cleanly
# ---------------------------------------------------------------------------

LEGIT_CHEATSHEET = """# Authoring notes

## Coupling
- Poroelastic problems need a coupled solver and a matching constitutive block:
  a solid model, a porosity model and a permeability model, each named and
  referenced from the element region that uses them.
- Thermal problems additionally need the thermal flux flag on the coupled
  solver, plus a conductivity model in the same region.

## Completeness beats cleverness
Most lost score is a missing top-level block, not a wrong value. Before
finishing, confirm every required block exists and that the solver name is
referenced by the collection targets.

## Reading validator output
An unknown attribute error prints the full table of valid attributes for that
element. Read that table instead of guessing; it is the cheapest correction
signal available.
"""

LEGIT_PRIMER = """# Interface primer

Input decks are XML. A complete deck defines <Problem>, <Solvers>, <Mesh>,
<Constitutive> and <Outputs>. Solvers reference regions by name, regions
reference constitutive models by name, and a mismatch there is the most common
validation failure.

Work in the output directory only. Re-run validation after every edit; the
validator is fast and its message names the offending element.
"""


@pytest.mark.parametrize(
    "name,text",
    [("memory/cheatsheet.md", LEGIT_CHEATSHEET), ("PRIMER.md", LEGIT_PRIMER)],
)
def test_legitimate_adapter_content_passes_cleanly(
    corpus: GroundTruthCorpus, name: str, text: str
) -> None:
    """A gate people route around is worse than no gate."""
    report = check_texts({name: text}, corpus)
    assert not report.blocked, report.render()
    assert not report.warnings, report.render()


# ---------------------------------------------------------------------------
# audit CLI
# ---------------------------------------------------------------------------


def test_read_adapter_dir_skips_scaffolding(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "hooks").mkdir()
    (tmp_path / "memory/cheatsheet.md").write_text("hello")
    (tmp_path / "hooks/verify.md").write_text("read Foo_base.xml")
    (tmp_path / "binary.bin").write_bytes(b"\x00")

    assert set(read_adapter_dir(tmp_path)) == {"memory/cheatsheet.md"}


def test_audit_dir_blocks_a_leaky_adapter(
    tmp_path: Path, corpus: GroundTruthCorpus
) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory/cheatsheet.md").write_text("copy tables/time.geos first")
    assert audit_dir(tmp_path, corpus).blocked


def test_cli_rejects_a_missing_adapter_dir(tmp_path: Path) -> None:
    code = main(["--adapter-dir", str(tmp_path / "nope"), "--blocklist-json", "x.json"])
    assert code == 2


def test_cli_refuses_to_pass_against_an_empty_corpus(tmp_path: Path) -> None:
    """An empty corpus detects nothing; reporting that as a pass is decorative."""
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "PRIMER.md").write_text("hello")
    blocklist = tmp_path / "empty.json"
    blocklist.write_text("{}")

    code = main(
        ["--adapter-dir", str(adapter), "--blocklist-json", str(blocklist)]
    )
    assert code == 2


def test_cli_passes_a_clean_adapter_and_writes_a_report(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "PRIMER.md").write_text(LEGIT_PRIMER)
    blocklist = tmp_path / "blocklist.json"
    blocklist.write_text(
        json.dumps({"per_task_xml": {"ExampleMandel": ["poroelastic_mandel_base.xml"]}})
    )
    out = tmp_path / "report.json"

    code = main(
        [
            "--adapter-dir", str(adapter),
            "--blocklist-json", str(blocklist),
            "--out", str(out),
        ]
    )

    assert code == 0
    assert json.loads(out.read_text())["passed"] is True


# ---------------------------------------------------------------------------
# integration: the two real incidents
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo3_corpus() -> GroundTruthCorpus:
    return GroundTruthCorpus.from_blocklist_json(BLOCKLIST)


@needs_repo3
def test_v3_flags_the_geos_dependency_filenames(repo3_corpus: GroundTruthCorpus) -> None:
    """Incident 1, verbatim: three `.geos` names across three files, all missed."""
    report = audit_dir(V3_DIR, repo3_corpus)

    leaked = {
        (f.location.split(":")[0], name)
        for f in report.errors
        for name in ("time.geos", "axialStrain.geos", "radialStress.geos")
        if name in f.message
    }
    assert {name for _, name in leaked} == {
        "time.geos", "axialStrain.geos", "radialStress.geos"
    }
    assert len({path for path, _ in leaked}) == 3
    assert report.blocked


@needs_repo3
def test_v3_also_flags_the_surviving_path_component(
    repo3_corpus: GroundTruthCorpus,
) -> None:
    """The other half of incident 1: `poromechanics/` survived basename redaction."""
    report = audit_dir(V3_DIR, repo3_corpus)
    assert any(
        f.source == "path_component" and "poromechanics" in f.message
        for f in report.errors
    )


@needs_repo3
def test_v4_blocks_on_the_task_id_lookup_table(repo3_corpus: GroundTruthCorpus) -> None:
    """Incident 2: a task-name -> canonical-deck table for every evaluation task."""
    report = audit_dir(V4_DIR, repo3_corpus)

    table = [f for f in report.errors if f.source == "task_id_table"]
    assert len(table) == 1
    assert "17 evaluation task ids" in table[0].message
    assert table[0].location.startswith("memory/cheatsheet.md")
    # ...and its shape is caught independently of the task names themselves.
    assert any(f.source == "lookup_table" and f.severity == "error" for f in report.errors)
    assert report.blocked


@needs_repo3
def test_cli_exits_non_zero_on_the_quarantined_adapter(tmp_path: Path) -> None:
    out = tmp_path / "v4.json"
    code = main(
        [
            "--adapter-dir", str(V4_DIR),
            "--blocklist-json", str(BLOCKLIST),
            "--out", str(out),
        ]
    )
    assert code == 1
    assert json.loads(out.read_text())["n_blocking"] > 0
