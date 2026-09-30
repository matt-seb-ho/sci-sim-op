#!/usr/bin/env python3
"""Leak scan for the FORGE-v0 /site/ folder (blocking check before any agent run).

    python3 scripts/geomodel/leak_scan.py SITE_DIR [--out hits.json] [--jobs 16]

Looks, in every file and recursively inside zips / xlsx / docx, in file and
member *names*, raw bytes (also UTF-16LE), and the text of PDFs (pdftotext),
for:
  - answer canaries: Granitiod, GM_8_19_2019, 1205, MP-169, native state, and
    the GDR 1107 (Phase 2B earth model) file names;
  - write-up markers, for human review: earth model, Leapfrog, Phase 2C,
    geologic model, block model, 3D model, native-state.
Hits of "1205" inside numbers (next to a digit, '.', or on a mostly-numeric
line) are tagged `numeric` so they can be dismissed as incidental in bulk.
Also fails on any .git directory or symlink.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CANARIES = ["Granitiod", "GM_8_19_2019", "1205", "MP-169", "native state",
            "top_granitoid_vertices", "land_surface_vertices", "Opal_Mound_Fault_vertices",
            "Negro_Mag_Fault_vertices", "175C_vertices", "225C_vertices"]
WRITEUP = ["earth model", "Leapfrog", "Phase 2C", "geologic model", "block model",
           "3D model", "3-D model", "native-state"]
TERMS = [(t, "canary") for t in CANARIES] + [(t, "writeup") for t in WRITEUP]

def _pat(enc: str) -> re.Pattern:
    alts = []
    for t, _ in TERMS:
        alts.append(re.escape(t.encode(enc)))
    return re.compile(b"|".join(alts), re.IGNORECASE)

PAT8 = _pat("utf-8")
PAT16 = _pat("utf-16-le")
LOOKUP = {t.lower(): (t, kind) for t, kind in TERMS}
ZIPLIKE = {".zip", ".xlsx", ".xlsm", ".docx", ".pptx", ".kmz"}
CHUNK = 64 << 20
MAX_CTX = 6


def classify_1205(buf: bytes, s: int, e: int) -> str:
    before = buf[s - 1:s] if s > 0 else b""
    after = buf[e:e + 1]
    if (before and (before.isdigit() or before == b".")) or (after and (after.isdigit() or after == b".")):
        return "numeric"
    ls = buf.rfind(b"\n", max(0, s - 400), s) + 1
    le = buf.find(b"\n", e, e + 400)
    line = buf[ls:le if le > 0 else e + 80]
    num = sum(ch in b"0123456789.,-+eE \t;" for ch in line)
    return "numeric" if line and num / len(line) > 0.8 else "text"


def scan_bytes(buf: bytes, where: str, hits: list, utf16: bool = True) -> None:
    for pat, enc in ((PAT8, "utf-8"), (PAT16, "utf-16-le")) if utf16 else ((PAT8, "utf-8"),):
        for m in pat.finditer(buf):
            raw = m.group(0).decode(enc, "replace")
            term, kind = LOOKUP.get(raw.lower(), (raw, "canary"))
            sub = "text"
            if term == "1205":
                sub = classify_1205(buf, m.start(), m.end()) if enc == "utf-8" else "text"
            ctx = buf[max(0, m.start() - 80):m.end() + 80].decode(enc if enc == "utf-8" else "latin-1", "replace")
            if enc != "utf-8":
                ctx = buf[max(0, m.start() - 160):m.end() + 160].decode("utf-16-le", "replace")
            hits.append({"where": where, "term": term, "kind": kind, "sub": sub, "enc": enc,
                         "ctx": re.sub(r"\s+", " ", ctx)[:260]})


def scan_name(name: str, where: str, hits: list) -> None:
    scan_bytes(name.encode(), where + " [name]", hits, utf16=False)


def pdf_text(data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        r = subprocess.run(["pdftotext", "-q", f.name, "-"], capture_output=True, timeout=600)
        return r.stdout


def scan_stream(fobj, where: str, hits: list) -> None:
    tail = b""
    while True:
        chunk = fobj.read(CHUNK)
        if not chunk:
            break
        buf = tail + chunk
        local: list = []
        scan_bytes(buf, where, local)
        # drop hits entirely inside the overlap already scanned
        hits.extend(local)
        tail = buf[-400:]
    # de-duplicate overlap double counts
    seen = set()
    uniq = []
    for h in hits:
        k = (h["where"], h["term"], h["ctx"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    hits[:] = uniq


def scan_member(name: str, opener, size: int, where: str, hits: list, depth: int) -> None:
    ext = os.path.splitext(name)[1].lower()
    scan_name(name, where, hits)
    if ext in ZIPLIKE and depth < 4:
        if size < (1 << 31):
            with opener() as f:
                data = f.read()
            try:
                scan_zip(zipfile.ZipFile(io.BytesIO(data)), where, hits, depth + 1)
                return
            except zipfile.BadZipFile:
                scan_bytes(data, where, hits)
                return
    if ext == ".pdf":
        with opener() as f:
            data = f.read()
        scan_bytes(pdf_text(data), where + " [pdftext]", hits, utf16=False)
        scan_bytes(data, where + " [pdfraw]", hits, utf16=False)
        return
    with opener() as f:
        scan_stream(f, where, hits)


def scan_zip(z: zipfile.ZipFile, where: str, hits: list, depth: int) -> None:
    for info in z.infolist():
        w = f"{where}::{info.filename}"
        if info.is_dir():
            scan_name(info.filename, w, hits)
            if ".git/" in info.filename or info.filename.rstrip("/").endswith(".git"):
                hits.append({"where": w, "term": ".git", "kind": "canary", "sub": "text", "enc": "-", "ctx": "git dir in zip"})
            continue
        if "/.git/" in "/" + info.filename:
            hits.append({"where": w, "term": ".git", "kind": "canary", "sub": "text", "enc": "-", "ctx": "git dir in zip"})
        try:
            scan_member(info.filename, lambda i=info: z.open(i), info.file_size, w, hits, depth)
        except Exception as e:  # noqa: BLE001 - record and continue
            hits.append({"where": w, "term": "ERROR", "kind": "error", "sub": "", "enc": "", "ctx": repr(e)[:200]})


def scan_file(path: str, root: str) -> dict:
    hits: list = []
    rel = os.path.relpath(path, root)
    try:
        scan_member(rel, lambda: open(path, "rb"), os.path.getsize(path), rel, hits, 0)
    except Exception as e:  # noqa: BLE001
        hits.append({"where": rel, "term": "ERROR", "kind": "error", "sub": "", "enc": "", "ctx": repr(e)[:200]})
    return {"file": rel, "hits": hits}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--out", default=None)
    ap.add_argument("--jobs", type=int, default=16)
    a = ap.parse_args()
    root = os.path.abspath(a.site)
    files, bad = [], []
    for dp, dns, fns in os.walk(root, followlinks=False):
        for d in dns:
            if d == ".git" or os.path.islink(os.path.join(dp, d)):
                bad.append(os.path.join(dp, d))
        for f in fns:
            p = os.path.join(dp, f)
            if os.path.islink(p):
                bad.append(p)
            else:
                files.append(p)
    files.sort(key=lambda p: -os.path.getsize(p))
    with ProcessPoolExecutor(a.jobs) as ex:
        results = list(ex.map(scan_file, files, [root] * len(files)))
    summary: dict = {}
    for r in results:
        for h in r["hits"]:
            key = (r["file"], h["term"], h["sub"])
            summary[key] = summary.get(key, 0) + 1
    out = {"root": root, "n_files": len(files), "bad_paths": bad,
           "summary": [{"file": k[0], "term": k[1], "sub": k[2], "n": v} for k, v in sorted(summary.items())],
           "results": [r for r in results if r["hits"]]}
    for r in out["results"]:  # keep the file small: a few contexts per (term, sub)
        per: dict = {}
        keep = []
        for h in r["hits"]:
            k = (h["term"], h["sub"], h["where"])
            per[k] = per.get(k, 0) + 1
            if per[k] <= MAX_CTX:
                keep.append(h)
        r["hits"] = keep
    txt = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    n_canary_text = sum(s["n"] for s in out["summary"] if s["sub"] != "numeric" and s["term"] in CANARIES)
    print(json.dumps({"files": len(files), "bad_paths": len(bad), "canary_hits_non_numeric": n_canary_text,
                      "errors": sum(s["n"] for s in out["summary"] if s["term"] == "ERROR")}))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
