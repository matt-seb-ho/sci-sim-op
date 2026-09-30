#!/usr/bin/env python3
"""Build the agent's read-only input folder for FORGE-v0 (variant A).

    python3 scripts/geomodel/build_site.py [--out DIR] [--dry-run]

Selection (TASK_FORGE_v0.md §3, session-2 brief Phase 2):
  role_guess == "input" and date_published < 2019-09-01, minus the model /
  prior-model / excluded ids, minus files over 2 GB, minus the per-file and
  per-submission exclusions decided by the leak scan (EXCLUDE_* below; each
  one is justified in site_v0A_LEAKSCAN.md).

Layout: <out>/gdr_<id>/{ABOUT.txt, <files as downloaded>} and
<out>/grid/{cells.csv,nodes.csv}. Files are copied, never symlinked. Zips are
left packed. No manifest, no role labels, no meta/.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import textwrap
import zipfile
from pathlib import Path

FORGE = Path("/data/matt/sci-sim-op/geomodel/forge")
RAW = FORGE / "raw"
CUT = "2019-09-01"
MAX_BYTES = 2_000_000_000  # "files over 2 GB" (decimal)

# Spec §3: expert answer, prior model, later versions, and write-ups. None of
# these pass the role/date filter today; listed so a manifest edit can't let
# one slip in.
EXCLUDE_IDS = {
    "1205", "1160", "1315",            # expert answer
    "1107", "1108", "1036",            # Phase 2B earth model (prior model) + its video
    "1397", "1812", "1222", "1317", "1646", "1750", "1554",  # later versions
    "mp169",                           # UGS MP-169 write-up
}

# Leak-scan decisions (see site_v0A_LEAKSCAN.md). Keys are (gdr_id, filename).
EXCLUDE_FILES: dict[tuple[str, str], str] = {
    ("1111", "well_lithology_from_earth_model.csv"): "lithology sampled from the Phase 2B earth model (prior model)",
    ("1111", "well_location_from_earth_model.csv"): "exported from the Phase 2B earth model (prior model)",
    ("1111", "well_survey_from_earth_model.csv"): "exported from the Phase 2B earth model (prior model)",
    ("1146", "Moore_UtahFORGE_overview_Stanford_2020.pdf"): "Feb-2020 Stanford paper (post-cut): summarises the site model, incl. a top-of-granitoid cross-section, the contact dip and the 58-32 stress gradients",
}
# v0.1 (2026-09-30): the GDR later rewrote or re-uploaded some pre-cut
# submissions. 1139's zip was replaced with 2018-2021 data in Oct 2021.
EXCLUDE_FILES[("1139", "NMV GWGeochem (1).zip")] = "re-uploaded Oct 2021 with 2018-2021 data (post-cut); the 2019 xlsx stays"

# GDR descriptions that are post-cut text. 1146's description is the abstract of
# the Feb-2020 Stanford paper excluded above (stress gradients, SHmax azimuth, BHT).
ABOUT_OVERRIDE = {
    "1146": ("Conference paper on the 2017 and 2019 stimulations of well 58-32. The paper and its "
             "abstract are not included here (they were published after August 2019). The "
             "stimulation data are in gdr_1149."),
}

# More per-file / per-submission ("*") exclusions from the leak scan live in
# site_v0A_excludes.json next to the site (a list of {id, file, reason}).

# Zips repacked with a subset of their members (same file name). Only used
# where a zip mixes raw data with a model product derived from the prior
# (Phase 2B) earth model. Key -> (members-to-keep prefixes, reason).
REPACK: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("1144", "FORGE_3D_gravity (1).zip"): (
        ("FORGE_3D_gravity/FORGE_2C_finalCBGA.txt", "FORGE_3D_gravity/FORGE_2C_finalCBGA.xls"),
        "keep the gravity station data only; drop the density models built on the Phase 2B "
        "top-granite surface ('Original'/'Modified_Top_Granite'), the .geoh5 holding them, and "
        "the report describing them",
    ),
}

GRID_SRC = FORGE / "work1205" / "Mesh Files"


def load_extra_excludes(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    out = {}
    for row in json.loads(path.read_text()):
        out[(row["id"], row["file"])] = row["reason"]
    return out


# Variant B (TASK_FORGE_v0 §3): variant A plus the Phase 2B earth model (the prior
# model) and its write-ups, which variant A withholds.
PRIOR_IDS = {"1107", "1108"}
PRIOR_DATE = "2018-12-07"  # 1107/1108 publication date; later submissions are "new"
B_RESTORE = {  # per-file exclusions of variant A that exist only to hide the prior model
    ("1039", "Utah FORGE Phase 2B Topical Report.pdf"), ("1052", "Utah FORGE Phase 2B Topical Report.pdf"),
    ("1111", "well_lithology_from_earth_model.csv"), ("1111", "well_location_from_earth_model.csv"),
    ("1111", "well_survey_from_earth_model.csv"),
}


def select_records(variant: str = "A") -> list[dict]:
    m = json.loads((FORGE / "manifest.json").read_text())
    recs = []
    for r in m["records"]:
        d = r.get("date_published")
        if variant == "B" and r["id"] in PRIOR_IDS:
            recs.append(r)
            continue
        if r.get("role_guess") != "input" or not d or d >= CUT:
            continue
        if r["id"] in EXCLUDE_IDS:
            continue
        recs.append(r)
    return sorted(recs, key=lambda r: int(r["id"]))


def about_text(r: dict) -> str:
    if r["id"] in ABOUT_OVERRIDE:
        r = dict(r, description=ABOUT_OVERRIDE[r["id"]])
    authors = "; ".join(
        a["name"] + (f" ({a['affiliation']})" if a.get("affiliation") else "")
        for a in r.get("authors") or []
    )
    desc = "\n".join(textwrap.fill(p, 90) for p in (r.get("description") or "").split("\n"))
    links = [f"  - {f.get('name')}: {f.get('url')}" for f in r.get("files", []) if f.get("kind") == "external_link"]
    s = f"Title: {r['title']}\nPublished: {r['date_published']}\nAuthors: {authors}\n\nDescription:\n{desc}\n"
    if links:
        s += "\nExternal links listed by the submission (not included here; there is no network):\n" + "\n".join(links) + "\n"
    return s


def write_grid(out: Path) -> dict:
    g = out / "grid"
    g.mkdir(parents=True, exist_ok=True)
    stats = {}
    for src, dst, idname in [
        (GRID_SRC / "2019.08.21_global_cell.csv", g / "cells.csv", "cell_id"),
        (GRID_SRC / "2019.06.06_global_node.csv", g / "nodes.csv", "node_id"),
    ]:
        n = 0
        with open(src, newline="") as fi, open(dst, "w", newline="") as fo:
            rows = (line for line in fi if not line.startswith("#"))
            rd = csv.reader(rows)
            hdr = next(rd)
            ix = [hdr.index(c) for c in ("Id", "X", "Y", "Z")]
            w = csv.writer(fo, lineterminator="\n")
            w.writerow([idname, "x", "y", "z"])
            for row in rd:
                if not row or not row[0].strip():
                    continue
                w.writerow([row[ix[0]], row[ix[1]], row[ix[2]], row[ix[3]]])
                n += 1
        stats[dst.name] = n
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(FORGE / "site_v0A"))
    ap.add_argument("--extra-excludes", default=str(FORGE / "site_v0A_excludes.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--variant", choices=["A", "B"], default="A")
    a = ap.parse_args()
    if a.variant == "B" and a.out == str(FORGE / "site_v0A"):
        a.out = str(FORGE / "site_v0B")
    out = Path(a.out)
    excl = dict(EXCLUDE_FILES)
    excl.update(load_extra_excludes(Path(a.extra_excludes)))
    if a.variant == "B":
        for k in B_RESTORE:
            excl.pop(k, None)
        REPACK.clear()
    excl_ids = {k[0] for k, v in excl.items() if k[1] == "*"}

    if out.exists() and not a.dry_run:
        shutil.rmtree(out)
    log = {"included": {}, "skipped": []}
    for r in select_records(a.variant):
        rid = r["id"]
        if rid in excl_ids:
            log["skipped"].append({"id": rid, "file": "*", "reason": excl[(rid, "*")]})
            continue
        src = RAW / rid
        files = sorted(p for p in src.iterdir() if p.is_file()) if src.is_dir() else []
        kept = []
        for p in files:
            if p.stat().st_size > MAX_BYTES:
                log["skipped"].append({"id": rid, "file": p.name, "reason": f"over 2 GB ({p.stat().st_size} B)"})
                continue
            if (rid, p.name) in excl:
                log["skipped"].append({"id": rid, "file": p.name, "reason": excl[(rid, p.name)]})
                continue
            kept.append(p)
        dst = out / f"gdr_{rid}"
        if not a.dry_run:
            dst.mkdir(parents=True, exist_ok=True)
            (dst / "ABOUT.txt").write_text(about_text(r))
            for p in kept:
                if (rid, p.name) in REPACK:
                    keep, _ = REPACK[(rid, p.name)]
                    with zipfile.ZipFile(p) as zi, zipfile.ZipFile(dst / p.name, "w", zipfile.ZIP_DEFLATED) as zo:
                        for info in zi.infolist():
                            if info.filename.startswith(keep):
                                zo.writestr(info, zi.read(info))
                    log["skipped"].append({"id": rid, "file": p.name, "reason": "repacked: " + REPACK[(rid, p.name)][1]})
                else:
                    shutil.copy2(p, dst / p.name)
        log["included"][rid] = {"files": [p.name for p in kept], "bytes": sum(p.stat().st_size for p in kept)}
    if not a.dry_run:
        log["grid"] = write_grid(out)
        if a.variant == "B":
            recs = select_records("B")
            new = [r for r in recs if r["date_published"] > PRIOR_DATE and r["id"] in log["included"]]
            (out / "NEW_DATA.txt").write_text(
                "Submissions published after the previous earth model (Phase 2B, gdr_1107 and gdr_1108,\n"
                f"published {PRIOR_DATE}). This is the data that is new since that model was built.\n\n"
                + "".join(f"gdr_{r['id']}  {r['date_published']}  {r['title']}\n" for r in new))
        # No .git, no symlinks anywhere.
        bad = [str(p) for p in out.rglob("*") if p.is_symlink() or p.name == ".git"]
        assert not bad, bad
    n_files = sum(len(v["files"]) for v in log["included"].values())
    tot = sum(v["bytes"] for v in log["included"].values())
    log["summary"] = {"submissions": len(log["included"]), "data_files": n_files, "bytes": tot}
    print(json.dumps(log["summary"]))
    (Path(str(out) + "_build.json")).write_text(json.dumps(log, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
