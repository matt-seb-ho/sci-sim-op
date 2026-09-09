"""The split boundary is the experiment's main validity claim, so it is tested."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness_evolve.splits import (
    FAMILY_KEYWORDS, SPLIT_OF_FAMILY, assign, family_of, sealed_ground_truth, split_of,
)

GT = Path("/home/matt/projects/siga/data/eval/experiments_gt")
POOL = sorted(os.listdir(GT)) if GT.is_dir() else []
needs_pool = pytest.mark.skipif(not POOL, reason="GEOS ground-truth tree not mounted")


def test_every_family_has_a_split():
    for fam, _ in FAMILY_KEYWORDS:
        assert fam in SPLIT_OF_FAMILY
    assert "wellbore" in SPLIT_OF_FAMILY


def test_wellbore_wins_over_the_physics_keyword_inside_its_name():
    """A wellbore whose name contains another family's keyword is still a wellbore.

    Its mesh, boundary and solver stanzas are shared with the other wellbores, not
    with ExampleMandel. Getting this wrong leaks a family across the boundary.
    """
    for t in ("AdvancedExampleThermoPoroElasticWellbore",
              "AdvancedExampleDeviatedPoroElasticWellbore",
              "ExampleVerticalPoroElastoPlasticWellbore"):
        assert family_of(t) == "wellbore", t
        assert split_of(t) == "TRAIN", t


def test_genuine_family_members_still_classify():
    assert family_of("ExampleMandel") == "poroelastic"
    assert family_of("TutorialPoroelasticity") == "poroelastic"
    assert family_of("kgdToughnessDominated") == "fracture"
    assert family_of("TutorialSneddon") == "fracture"
    assert family_of("buckleyLeverettProblem") == "flow"
    assert family_of("triaxialDriverExample") == "driver"


@needs_pool
def test_splits_are_disjoint_and_cover_the_pool():
    a = assign(POOL)
    allocated = [t for v in a.values() for t in v]
    assert sorted(allocated) == POOL
    assert len(set(allocated)) == len(allocated)


@needs_pool
def test_no_family_straddles_a_split():
    """The whole point. A family in two splits is the leak we are preventing."""
    seen: dict[str, str] = {}
    for t in POOL:
        fam, sp = family_of(t), split_of(t)
        assert seen.setdefault(fam, sp) == sp, f"{fam} straddles {seen[fam]} and {sp}"


@needs_pool
def test_every_split_is_non_empty():
    a = assign(POOL)
    for split, tasks in a.items():
        assert tasks, f"{split} is empty"


@needs_pool
def test_seal_withholds_test_and_records_what_it_did(tmp_path):
    m = sealed_ground_truth(GT, tmp_path / "sealed", visible=("TRAIN", "DEV"))
    dest = Path(m.tree)
    present = {p.name for p in dest.iterdir()}

    # the load-bearing assertion: no path to test ground truth exists
    for t in POOL:
        if split_of(t) == "TEST":
            assert t not in present, f"{t} leaked into the visible tree"
            assert not (dest / t).exists()
        else:
            assert t in present

    assert m.sealed == ("TEST",)
    assert m.n_visible_tasks == len(present)
    assert set(m.withheld_tasks) == {t for t in POOL if split_of(t) == "TEST"}
    assert len(m.tree_sha256) == 16


@needs_pool
def test_seal_is_idempotent_and_hash_is_stable(tmp_path):
    a = sealed_ground_truth(GT, tmp_path / "s", visible=("TRAIN",))
    b = sealed_ground_truth(GT, tmp_path / "s", visible=("TRAIN",))
    assert a.tree_sha256 == b.tree_sha256
    c = sealed_ground_truth(GT, tmp_path / "s", visible=("TRAIN", "DEV"))
    assert c.tree_sha256 != a.tree_sha256, "hash must change when visibility changes"
