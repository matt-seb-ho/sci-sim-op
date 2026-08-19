"""Simulator protocol, mock simulator, and the two honest stubs.

Everything here runs offline: no GEOS binary, no LAMMPS binary, no OpenFOAM
environment, no `/data` volume. That is the point of the mock simulator, and
the stubs are asserted to *refuse* rather than to invent numbers.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from harness_evolve.simulators import SimulatorRegistry
from harness_evolve.simulators.lammps import (
    ATOM_DEFINITION_COMMANDS,
    LammpsSimulator,
    ScriptModel,
    parse_script,
)
from harness_evolve.simulators.mock import (
    DECK_SUFFIX,
    MockConfig,
    MockDeck,
    MockSimulator,
)
from harness_evolve.simulators.openfoam import OpenFoamSimulator, case_root, read_case

SRC = str(Path(__file__).resolve().parents[1] / "src")


# ---------------------------------------------------------------- registry

def test_registry_exposes_every_builtin_simulator():
    assert SimulatorRegistry.names() == ["geos", "lammps", "mock", "openfoam"]


def test_registry_rejects_unknown_name():
    with pytest.raises(KeyError, match="unknown simulator"):
        SimulatorRegistry.get("fluent")


def test_registry_forwards_constructor_kwargs():
    sim = SimulatorRegistry.get("mock", zero_rate=0.5)
    assert isinstance(sim, MockSimulator)
    assert sim.config.zero_rate == 0.5


# ------------------------------------------------------------ mock: basics

def _deterministic() -> MockSimulator:
    """A mock with every source of randomness that is not the seed removed."""
    return MockSimulator(help_strength=1.0, noise=0.0, zero_rate=0.0, base_quality=0.3)


def test_mock_config_rejects_incoherent_zero_rates():
    with pytest.raises(ValueError, match="zero_rate_floor"):
        MockConfig(zero_rate=0.1, zero_rate_floor=0.5).validate()


def test_mock_is_deterministic_in_candidate_task_seed(tmp_path):
    sim = MockSimulator()
    first = sim.simulate("cand_a", "primer text", "task1", 3, tmp_path / "a")
    second = sim.simulate("cand_a", "primer text", "task1", 3, tmp_path / "b")
    assert first.score.value == second.score.value
    assert first.score.status == second.score.status
    assert first.cost.tool_calls == second.cost.tool_calls
    assert (tmp_path / "a").exists()


def test_mock_determinism_survives_a_different_process_hash_seed(tmp_path):
    # `hash()` is salted per process; anything keyed on it would give a
    # different search problem on every run and make a cached runner incoherent.
    prog = (
        "import sys, tempfile, pathlib;"
        f"sys.path.insert(0, {SRC!r});"
        "from harness_evolve.simulators.mock import MockSimulator;"
        "s = MockSimulator();"
        "d = pathlib.Path(tempfile.mkdtemp());"
        "print(s.task_for('task1').required_sections,"
        " s.simulate('cand_a', 'primer', 'task1', 3, d).score.value)"
    )
    outs = []
    for salt in ("0", "1"):
        env = dict(os.environ, PYTHONHASHSEED=salt)
        outs.append(
            subprocess.run(
                [sys.executable, "-c", prog], env=env, capture_output=True, text=True,
                check=True,
            ).stdout
        )
    assert outs[0] == outs[1]


def test_mock_seed_changes_the_outcome(tmp_path):
    sim = MockSimulator()
    values = {
        sim.simulate("cand_a", "", "task1", s, tmp_path / str(s)).score.value
        for s in range(8)
    }
    assert len(values) > 1


# ------------------------------------------- mock: the controllable optimum

def test_mock_adapter_naming_required_sections_reaches_the_known_optimum(tmp_path):
    sim = _deterministic()
    task = sim.task_for("task1")
    primer = "Always define: " + ", ".join(task.required_sections)
    values = [
        sim.simulate("cand_a", primer, "task1", s, tmp_path / f"g{s}").score.value
        for s in range(10)
    ]
    assert values == [1.0] * 10


def test_mock_empty_adapter_scores_strictly_worse(tmp_path):
    sim = _deterministic()
    task = sim.task_for("task1")
    primer = "Always define: " + ", ".join(task.required_sections)
    good = statistics.mean(
        sim.simulate("c", primer, "task1", s, tmp_path / f"g{s}").score.value
        for s in range(10)
    )
    bare = statistics.mean(
        sim.simulate("c", "", "task1", s, tmp_path / f"b{s}").score.value
        for s in range(10)
    )
    assert good > bare


def test_mock_help_strength_zero_makes_adapter_content_inert(tmp_path):
    sim = MockSimulator(help_strength=0.0, noise=0.0, zero_rate=0.0)
    task = sim.task_for("task1")
    primer = ", ".join(task.required_sections)
    with_primer = sim.simulate("c", primer, "task1", 1, tmp_path / "a")
    without = sim.simulate("c", "", "task1", 1, tmp_path / "b")
    assert with_primer.score.value == without.score.value


def test_mock_over_budget_adapter_is_penalised(tmp_path):
    sim = MockSimulator(help_strength=1.0, noise=0.0, zero_rate=0.0, token_budget=50)
    task = sim.task_for("task1")
    short = ", ".join(task.required_sections)
    bloated = short + "\n" + ("filler prose that buys nothing. " * 200)
    lean = statistics.mean(
        sim.simulate("c", short, "task1", s, tmp_path / f"s{s}").score.value
        for s in range(10)
    )
    fat = statistics.mean(
        sim.simulate("c", bloated, "task1", s, tmp_path / f"f{s}").score.value
        for s in range(10)
    )
    assert fat < lean


def test_mock_over_budget_adapter_costs_more_tool_calls(tmp_path):
    sim = MockSimulator(noise=0.0, token_budget=50)
    lean = sim.simulate("c", "short", "task1", 1, tmp_path / "a").cost
    fat = sim.simulate("c", "x" * 5000, "task1", 1, tmp_path / "b").cost
    assert fat.tool_calls > lean.tool_calls


# ---------------------------------------------------- mock: zero-rate control

def test_mock_zero_rate_one_makes_every_rollout_unscorable(tmp_path):
    sim = MockSimulator(zero_rate=1.0, zero_rate_floor=1.0)
    outcomes = [
        sim.simulate("c", "", "task1", s, tmp_path / str(s)) for s in range(12)
    ]
    assert all(o.zeroed for o in outcomes)
    assert all(o.score.is_zero for o in outcomes)
    assert {o.score.status for o in outcomes} == {"empty_workspace", "parse_error"}


def test_mock_zero_rate_zero_never_produces_a_catastrophic_rollout(tmp_path):
    sim = MockSimulator(zero_rate=0.0)
    outcomes = [
        sim.simulate("c", "", "task1", s, tmp_path / str(s)) for s in range(12)
    ]
    assert not any(o.zeroed for o in outcomes)


def test_mock_grounding_removes_zeros_down_to_the_floor(tmp_path):
    sim = MockSimulator(zero_rate=0.6, zero_rate_floor=0.0, help_strength=1.0)
    task = sim.task_for("task1")
    primer = ", ".join(task.required_sections)
    bare = [sim.simulate("c", "", "task1", s, tmp_path / f"b{s}") for s in range(40)]
    grounded = [
        sim.simulate("c", primer, "task1", s, tmp_path / f"g{s}") for s in range(40)
    ]
    assert sum(o.zeroed for o in bare) > 0
    assert sum(o.zeroed for o in grounded) == 0


# --------------------------------------------------- mock: failures-as-zero

def test_mock_empty_workspace_scores_zero_with_a_status(tmp_path):
    sim = MockSimulator()
    gt = sim.write_ground_truth(tmp_path / "gt", "task1")
    empty = tmp_path / "gen"
    empty.mkdir()
    score = sim.score(empty, gt, "task1")
    assert score.value == 0.0
    assert score.status == "empty_workspace"
    assert score.is_zero and score.is_failure


def test_mock_unparseable_deck_scores_zero_not_absent(tmp_path):
    sim = MockSimulator()
    gt = sim.write_ground_truth(tmp_path / "gt", "task1")
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / f"deck{DECK_SUFFIX}").write_text("[Grid\nbroken")
    score = sim.score(gen, gt, "task1")
    assert score.value == 0.0
    assert score.status == "parse_error"


def test_mock_missing_ground_truth_scores_zero(tmp_path):
    sim = MockSimulator()
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / f"deck{DECK_SUFFIX}").write_text("[Grid]\np0 = 1\n")
    assert sim.score(gen, tmp_path / "nope", "task1").status == "missing_ground_truth"


# ------------------------------------------------- mock: scoring internals

def test_mock_section_scores_are_reported_per_section(tmp_path):
    sim = MockSimulator()
    gt = sim.write_ground_truth(tmp_path / "gt", "task1")
    task = sim.task_for("task1")
    gen = tmp_path / "gen"
    gen.mkdir()
    # Reproduce exactly one ground-truth section verbatim, drop the rest.
    gt_deck = MockDeck.parse((gt / f"deck{DECK_SUFFIX}").read_text())
    keep = task.required_sections[0]
    kept = MockDeck(sections={keep: gt_deck.sections[keep]})
    (gen / f"deck{DECK_SUFFIX}").write_text(kept.render())

    score = sim.score(gen, gt, "task1")
    section_scores = score.detail["section_scores"]
    assert section_scores[keep] == 1.0
    assert all(v == 0.0 for k, v in section_scores.items() if k != keep)
    assert score.value == pytest.approx(1 / len(task.required_sections))


def test_mock_hallucinated_sections_cost_score(tmp_path):
    sim = MockSimulator()
    gt = sim.write_ground_truth(tmp_path / "gt", "task1")
    gt_text = (gt / f"deck{DECK_SUFFIX}").read_text()

    exact = tmp_path / "exact"
    exact.mkdir()
    (exact / f"deck{DECK_SUFFIX}").write_text(gt_text)

    padded = tmp_path / "padded"
    padded.mkdir()
    (padded / f"deck{DECK_SUFFIX}").write_text(gt_text + "[Scratch]\np0 = 0\n")

    assert sim.score(exact, gt, "task1").value == 1.0
    padded_score = sim.score(padded, gt, "task1")
    assert padded_score.value < 1.0
    assert padded_score.detail["n_extra"] == 1


def test_mock_validate_flags_missing_required_sections(tmp_path):
    sim = MockSimulator()
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / f"deck{DECK_SUFFIX}").write_text("[Schedule]\np0 = 1\n")
    findings = sim.validate(sim.parse(gen), gen)
    messages = [f.message for f in findings if f.severity == "error"]
    assert any("'Grid'" in m for m in messages)


def test_mock_diagnose_names_the_missing_sections(tmp_path):
    sim = MockSimulator()
    gt = sim.write_ground_truth(tmp_path / "gt", "task1")
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / f"deck{DECK_SUFFIX}").write_text("[Grid]\np0 = 1\n")
    diagnosis = sim.diagnose(gen, gt, "task1")
    assert "Schedule" in diagnosis.missing_elements
    assert diagnosis.category == "missing_block"


def test_mock_contamination_blocks_the_task_ground_truth(tmp_path):
    sim = MockSimulator()
    sim.write_ground_truth(tmp_path / "gt", "task1")
    policy = sim.contamination_policy("task1", tmp_path / "gt")
    assert f"deck{DECK_SUFFIX}" in policy.blocked_basenames


def test_mock_preflight_is_always_clean():
    assert MockSimulator().preflight() == []


# ------------------------------------------------------------- openfoam

def _write_case(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


CAVITY = {
    "system/controlDict": "application icoFoam;\nendTime 0.5;\n",
    "system/fvSchemes": "ddtSchemes { default Euler; }\n",
    "system/fvSolution": "solvers { p { solver PCG; } }\n",
    "constant/transportProperties": "nu 0.01;\n",
    "0/U": "internalField uniform (0 0 0);\n",
    "0/p": "internalField uniform 0;\n",
}


def test_openfoam_present_sections_reads_the_case_layout(tmp_path):
    sim = OpenFoamSimulator()
    _write_case(tmp_path, CAVITY)
    artifact = sim.parse(tmp_path)
    assert sim.present_sections(artifact) == set(sim.required_sections)
    assert sim.check_completeness(artifact) == []


def test_openfoam_missing_dictionary_fails_completeness(tmp_path):
    sim = OpenFoamSimulator()
    partial = {k: v for k, v in CAVITY.items() if k != "system/fvSolution"}
    _write_case(tmp_path, partial)
    findings = sim.check_completeness(sim.parse(tmp_path))
    assert [f.severity for f in findings] == ["error"]
    assert "system/fvSolution" in findings[0].message


def test_openfoam_case_root_descends_into_a_single_nested_case(tmp_path):
    _write_case(tmp_path / "cavity", CAVITY)
    assert case_root(tmp_path) == tmp_path / "cavity"


def test_openfoam_score_is_file_coverage(tmp_path):
    sim = OpenFoamSimulator()
    gt = _write_case(tmp_path / "gt", CAVITY)
    partial = {k: v for k, v in CAVITY.items() if k != "0/p"}
    gen = _write_case(tmp_path / "gen", partial)
    score = sim.score(gen, gt, "cavity")
    assert score.value == pytest.approx(5 / 6)
    assert score.detail["missing"] == ["0/p"]
    assert score.detail["scoring"] == "file_coverage_only"


def test_openfoam_score_ignores_file_contents(tmp_path):
    # Documented limitation, asserted so nobody mistakes coverage for accuracy.
    sim = OpenFoamSimulator()
    gt = _write_case(tmp_path / "gt", CAVITY)
    wrong = _write_case(tmp_path / "gen", {k: "nonsense;\n" for k in CAVITY})
    assert sim.score(wrong, gt, "cavity").value == 1.0


def test_openfoam_empty_workspace_scores_zero(tmp_path):
    sim = OpenFoamSimulator()
    gt = _write_case(tmp_path / "gt", CAVITY)
    empty = tmp_path / "gen"
    empty.mkdir()
    assert sim.score(empty, gt, "cavity").status == "empty_workspace"


def test_openfoam_validate_refuses_rather_than_guessing(tmp_path):
    sim = OpenFoamSimulator()
    _write_case(tmp_path, CAVITY)
    with pytest.raises(NotImplementedError, match="foamDictionary"):
        sim.validate(sim.parse(tmp_path), tmp_path)


def test_openfoam_leak_pattern_catches_extensionless_dict_names():
    pattern = OpenFoamSimulator().leak_pattern()
    assert pattern.search("copy the settings from controlDict")
    assert pattern.search("see blockMeshDict for the grading")
    assert pattern.search("open case.foam in ParaView")


def test_openfoam_contamination_blocks_paths_not_basenames(tmp_path):
    sim = OpenFoamSimulator()
    _write_case(tmp_path / "cavity", CAVITY)
    policy = sim.contamination_policy("cavity", tmp_path)
    assert "cavity/system/controlDict" in policy.blocked_paths
    # A basename block would hide every tutorial in the corpus.
    assert policy.blocked_basenames == set()


def test_openfoam_preflight_reports_the_unimplemented_validator():
    reasons = OpenFoamSimulator().preflight()
    assert any("validate is not implemented" in r for r in reasons)


# --------------------------------------------------------------- lammps

MELT = """\
# 3d Lennard-Jones melt
units           lj
atom_style      atomic
lattice         fcc 0.8442
region          box block 0 10 0 10 0 10
create_box      1 box
create_atoms    1 box
mass            1 1.0
pair_style      lj/cut 2.5
pair_coeff      1 1 1.0 1.0 &
                2.5
fix             1 all nve
run             250
"""


def test_lammps_parser_handles_comments_and_continuations():
    directives = parse_script(MELT, "in.melt")
    commands = [d.command for d in directives]
    assert commands[0] == "units"
    assert "pair_coeff" in commands
    pair_coeff = next(d for d in directives if d.command == "pair_coeff")
    assert pair_coeff.args == ("1", "1", "1.0", "1.0", "2.5")


def test_lammps_present_sections_are_real_commands(tmp_path):
    sim = LammpsSimulator()
    (tmp_path / "in.melt").write_text(MELT)
    artifact = sim.parse(tmp_path)
    assert sim.present_sections(artifact) == set(sim.required_sections)
    assert sim.check_completeness(artifact) == []


def test_lammps_completeness_enforces_the_atom_definition_alternatives(tmp_path):
    sim = LammpsSimulator()
    (tmp_path / "in.bad").write_text(
        "units lj\natom_style atomic\npair_style lj/cut 2.5\nrun 100\n"
    )
    findings = sim.check_completeness(sim.parse(tmp_path))
    message = next(f.message for f in findings if "defines no atoms" in f.message)
    assert all(cmd in message for cmd in ATOM_DEFINITION_COMMANDS)


def test_lammps_score_refuses_rather_than_inventing_a_metric(tmp_path):
    sim = LammpsSimulator()
    with pytest.raises(NotImplementedError, match="parameter values"):
        sim.score(tmp_path, tmp_path, "melt")


def test_lammps_diagnose_refuses_too(tmp_path):
    with pytest.raises(NotImplementedError):
        LammpsSimulator().diagnose(tmp_path, tmp_path, "melt")


def test_lammps_directive_coverage_is_near_one_for_a_wrong_script(tmp_path):
    # The reason coverage is exposed as a diagnostic and never as `score`.
    sim = LammpsSimulator()
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "in.melt").write_text(MELT)
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "in.melt").write_text(MELT.replace("0.8442", "0.1").replace("250", "1"))
    assert sim.directive_coverage(gen, gt) == 1.0


def test_lammps_leak_pattern_catches_prefix_named_files():
    pattern = LammpsSimulator().leak_pattern()
    assert pattern.search("start from in.melt")
    assert pattern.search("read data.polymer first")
    assert pattern.search("see melt.lmp")


def test_lammps_validate_without_a_binary_reports_info_not_error(tmp_path):
    sim = LammpsSimulator(lammps_executable="")
    (tmp_path / "in.melt").write_text(MELT)
    findings = sim.validate(sim.parse(tmp_path), tmp_path)
    assert [f.severity for f in findings] == ["info"]
    assert "LAMMPS_EXECUTABLE" in findings[0].message


@pytest.mark.skipif(
    not os.environ.get("LAMMPS_EXECUTABLE"), reason="no LAMMPS binary available"
)
def test_lammps_validate_runs_the_real_binary(tmp_path):
    sim = LammpsSimulator()
    (tmp_path / "in.melt").write_text(MELT)
    findings = sim.validate(sim.parse(tmp_path), tmp_path)
    assert findings and findings[0].source == "lammps_validate"


# ------------------------------------------------------- protocol coverage

@pytest.mark.parametrize("name", ["geos", "lammps", "mock", "openfoam"])
def test_every_simulator_declares_a_usable_leak_pattern(name):
    sim = SimulatorRegistry.get(name)
    assert sim.leaky_extensions
    assert sim.leak_pattern().groups >= 1
    assert sim.describe().startswith(name)


@pytest.mark.parametrize("name", ["geos", "lammps", "mock", "openfoam"])
def test_preflight_reports_reasons_and_never_raises(name):
    assert isinstance(SimulatorRegistry.get(name).preflight(), list)
