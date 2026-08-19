"""Demonstrations must help the proposer without handing it the answer."""

from __future__ import annotations

import json

import pytest

from harness_evolve.proposers.base import Demonstration
from harness_evolve.proposers.demonstrations import (
    anonymize, from_browser_history, load_jsonl, render_all, sanitize,
)

TASKS = ["buckleyLeverettProblem", "ExampleMandel", "TutorialSneddon"]


def test_reference_filenames_are_stripped():
    """An expert's notes name the deck they copied from. That is the answer."""
    demo = Demonstration(
        task="buckleyLeverettProblem",
        summary="used buckleyLeverett_1d.xml as a structural template, then "
                "adjusted the mesh",
    )
    clean, rep = sanitize(demo, task_ids=TASKS)
    assert clean.kept if hasattr(clean, "kept") else True
    assert "buckleyLeverett_1d.xml" not in clean.summary
    assert "<reference artifact>" in clean.summary
    assert "buckleyLeverett_1d.xml" in rep.removed_filenames
    # The transferable part survives.
    assert "structural template" in clean.summary


def test_ground_truth_values_are_stripped():
    demo = Demonstration(
        task="ExampleMandel",
        summary="looked up the bulk modulus",
        notes="settled on 66.667 MPa after reading the docs",
    )
    clean, rep = sanitize(demo, task_ids=TASKS, numeric_blocklist=["66.667"])
    assert "66.667" not in clean.notes
    assert "66.667" in rep.removed_numerics


def test_demo_naming_another_benchmark_task_is_dropped_not_trimmed():
    """Trimming would leave a half-leak; dropping is the honest response."""
    demo = Demonstration(
        task="buckleyLeverettProblem",
        summary="this is much like ExampleMandel, reuse that structure",
    )
    _, rep = sanitize(demo, task_ids=TASKS)
    assert not rep.kept
    assert "ExampleMandel" in rep.reason


def test_own_task_id_is_allowed():
    """The task label is not a leak; it is how the demonstration is addressed."""
    demo = Demonstration(
        task="ExampleMandel", summary="ExampleMandel needed a coupled solver"
    )
    clean, rep = sanitize(demo, task_ids=TASKS)
    assert rep.kept
    assert "coupled solver" in clean.summary


def test_urls_collapse_to_documentation_areas():
    demo = from_browser_history(
        [
            "https://docs.example.com/en/latest/coreComponents/physicsSolvers/PhysicsSolvers.html",
            "https://docs.example.com/en/latest/coreComponents/physicsSolvers/PhysicsSolvers.html",
            "https://docs.example.com/en/latest/coreComponents/fileIO/doc/InputXMLFiles.html",
        ],
        task="buckleyLeverettProblem",
    )
    joined = " ".join(demo.sources_consulted)
    assert "https://" not in joined
    assert "PhysicsSolvers.html" not in joined
    assert "x2" in joined  # repeat visits are counted, which is the signal
    assert "physicsSolvers" in joined


def test_participants_are_anonymized():
    demo = from_browser_history(["https://d/a/b.html"], task="t", participant_index=1)
    assert "Expert 2" in demo.summary
    assert anonymize("Liam", 0) == "Expert 1"


def test_load_jsonl_reports_every_drop(tmp_path):
    p = tmp_path / "demos.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps({"task": "ExampleMandel", "summary": "read the solver docs"}),
                json.dumps({"task": "TutorialSneddon",
                            "summary": "copied from ExampleMandel"}),
                "{not json",
            ]
        )
    )
    demos, reports = load_jsonl(p, task_ids=TASKS)
    assert len(demos) == 1
    assert len(reports) == 3
    assert sum(1 for r in reports if not r.kept) == 2


def test_render_respects_a_budget():
    demos = [Demonstration(task=f"t{i}", summary="x" * 900) for i in range(10)]
    out = render_all(demos, max_chars=2000)
    assert len(out) <= 2200  # separators aside
    assert out.count("expert demonstration") < 10


def test_empty_set_renders_honestly():
    assert "no expert demonstrations" in render_all([])
