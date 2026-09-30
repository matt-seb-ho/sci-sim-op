#!/usr/bin/env python3
"""Download the Utah FORGE files listed in the manifest (idempotent, resumable).

    python3 scripts/geomodel/forge_download.py                 # run everything
    python3 scripts/geomodel/forge_download.py --dry-run       # plan only
    python3 scripts/geomodel/forge_download.py --only 1107,1205 --workers 2
    python3 scripts/geomodel/forge_download.py --status        # progress summary

Policy
  * Files <= --max-file (default 2 GiB) are downloaded; larger ones, and S3
    data-lake prefixes, are recorded as "deferred" and never fetched.
  * A hard cap (--cap, default 300 GB) on bytes on disk under raw/: nothing new is
    started once completed + in-flight bytes would exceed it.
  * Order: manifest priority (1 = geologic/DFN/native-state/wells/stress/reports),
    then smallest file first, so the model artifacts finish early.
  * Resume: data streams to <name>.part and continues with an HTTP Range request.
    A file whose final size matches the server's Content-Length is skipped.
  * Politeness: a few concurrent connections (default 3), retries with backoff.

Outputs (under /data/matt/sci-sim-op/geomodel/forge/):
  raw/<gdr_id>/<filename>       downloaded files
  meta/download.log             append-only log
  meta/download_status.json     per-file status (done/deferred/failed/skipped_cap)
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path("/data/matt/sci-sim-op/geomodel/forge")
MANIFEST = ROOT / "manifest.json"
RAW = ROOT / "raw"
LOG = ROOT / "meta" / "download.log"
STATUS = ROOT / "meta" / "download_status.json"
UA = "sci-sim-op FORGE inventory downloader (research use)"
GiB = 1024**3

lock = threading.Lock()
state: dict[str, dict] = {}
inflight_bytes = 0


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with lock:
        with LOG.open("a") as f:
            f.write(line + "\n")
    print(line, flush=True)


def save_state() -> None:
    with lock:
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(STATUS)


def safe(s: str) -> str:
    return re.sub(r"[^\w.()+,@ -]", "_", s).strip() or "file"


def plan(manifest: dict, only: set[str] | None) -> list[dict]:
    jobs = []
    for rec in manifest["records"]:
        if only and rec["id"] not in only:
            continue
        seen: set[str] = set()
        for f in rec.get("files", []):
            if f["kind"] not in ("gdr_file", "direct_file", "s3_prefix"):
                continue
            name = safe(f.get("filename") or f["name"])
            base, n = name, 1
            while name in seen:
                n += 1
                name = f"{Path(base).stem}__{n}{Path(base).suffix}"
            seen.add(name)
            jobs.append({
                "key": f"{rec['id']}/{name}",
                "rec_id": rec["id"],
                "category": rec.get("category"),
                "priority": rec.get("priority") or 3,
                "url": f["url"],
                "kind": f["kind"],
                "dest": str(RAW / safe(rec["id"].replace(":", "_")) / name),
                "approx": f.get("size_bytes_approx"),
            })
    jobs.sort(key=lambda j: (j["priority"], j["approx"] or 0))
    return jobs


def disk_bytes() -> int:
    return sum(p.stat().st_size for p in RAW.rglob("*") if p.is_file())


def fetch(job: dict, sess: requests.Session, max_file: int, cap: int) -> None:
    global inflight_bytes
    key, dest = job["key"], Path(job["dest"])
    if job["kind"] == "s3_prefix":
        state[key] = {"status": "deferred", "reason": "S3 data-lake prefix", "approx": job["approx"], "url": job["url"]}
        return
    if job["approx"] and job["approx"] > max_file:
        state[key] = {"status": "deferred", "reason": f">{max_file/GiB:.0f} GiB (listed size)", "approx": job["approx"], "url": job["url"]}
        return
    prev = state.get(key, {})
    if prev.get("status") == "done" and dest.exists() and dest.stat().st_size == prev.get("bytes"):
        return
    for attempt in range(5):
        try:
            h = sess.head(job["url"], allow_redirects=True, timeout=60)
            total = int(h.headers.get("Content-Length", 0)) if h.status_code == 200 else 0
            if h.status_code == 404:
                state[key] = {"status": "failed", "reason": "HTTP 404", "url": job["url"]}
                log(f"FAIL 404 {key}")
                return
            if total > max_file:
                state[key] = {"status": "deferred", "reason": f">{max_file/GiB:.0f} GiB (Content-Length)", "bytes_remote": total, "url": job["url"]}
                log(f"DEFER {key} {total/GiB:.2f} GiB")
                return
            if dest.exists() and total and dest.stat().st_size == total:
                state[key] = {"status": "done", "bytes": total, "url": job["url"]}
                return
            need = total or (job["approx"] or 0)
            with lock:
                on_disk = state.get("_disk_bytes", 0)
                if on_disk + inflight_bytes + need > cap:
                    state[key] = {"status": "skipped_cap", "bytes_remote": total, "url": job["url"]}
                    log(f"CAP  {key} would exceed {cap/1e9:.0f} GB")
                    return
                inflight_bytes += need
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_name(dest.name + ".part")
                have = part.stat().st_size if part.exists() else 0
                hdr = {"Range": f"bytes={have}-"} if have and total and have < total else {}
                if not hdr:
                    have = 0
                t0 = time.time()
                with sess.get(job["url"], headers=hdr, stream=True, timeout=120) as r:
                    if r.status_code not in (200, 206):
                        raise requests.HTTPError(f"HTTP {r.status_code}")
                    if r.status_code == 200:
                        have = 0
                    with part.open("ab" if have else "wb") as out:
                        # raw bytes: GDR labels some files (e.g. .fabgz) Content-Encoding: x-gzip,
                        # and decoding them would change the file and break the size check.
                        for chunk in r.raw.stream(1 << 20, decode_content=False):
                            out.write(chunk)
                size = part.stat().st_size
                if total and size != total:
                    raise IOError(f"short read {size}/{total}")
                part.replace(dest)
                with lock:
                    state["_disk_bytes"] = state.get("_disk_bytes", 0) + size
                state[key] = {"status": "done", "bytes": size, "url": job["url"], "category": job["category"]}
                log(f"OK   {key} {size/1e6:.1f} MB in {time.time()-t0:.0f}s")
                return
            finally:
                with lock:
                    inflight_bytes -= need
        except Exception as e:  # noqa: BLE001
            log(f"RETRY{attempt} {key}: {e}")
            time.sleep(10 * (attempt + 1))
    state[key] = {"status": "failed", "reason": "retries exhausted", "url": job["url"]}
    log(f"FAIL {key}")


def status_report() -> None:
    st = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    agg: dict[str, list] = {}
    for k, v in st.items():
        if k.startswith("_"):
            continue
        a = agg.setdefault(v["status"], [0, 0])
        a[0] += 1
        a[1] += v.get("bytes") or v.get("bytes_remote") or v.get("approx") or 0
    for s, (n, b) in sorted(agg.items()):
        print(f"{s:12s} {n:5d} files {b/1e9:10.2f} GB")
    parts = list(RAW.rglob("*.part"))
    print(f"on disk: {disk_bytes()/1e9:.2f} GB; in-progress .part files: {len(parts)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-file", type=float, default=2.0, help="GiB")
    ap.add_argument("--cap", type=float, default=300.0, help="GB on disk under raw/")
    ap.add_argument("--only", help="comma-separated record ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if a.status:
        return status_report()
    manifest = json.loads(MANIFEST.read_text())
    jobs = plan(manifest, set(a.only.split(",")) if a.only else None)
    max_file, cap = int(a.max_file * GiB), int(a.cap * 1e9)
    if STATUS.exists():
        state.update(json.loads(STATUS.read_text()))
    state["_disk_bytes"] = disk_bytes() - sum(p.stat().st_size for p in RAW.rglob("*.part"))
    auto = [j for j in jobs if j["kind"] != "s3_prefix" and not (j["approx"] and j["approx"] > max_file)]
    print(f"{len(jobs)} files; {len(auto)} eligible (~{sum(j['approx'] or 0 for j in auto)/1e9:.1f} GB listed); "
          f"{len(jobs)-len(auto)} deferred; on disk {state['_disk_bytes']/1e9:.1f} GB; cap {cap/1e9:.0f} GB")
    if a.dry_run:
        for j in jobs[:40]:
            print(j["priority"], j["key"], j["approx"])
        return
    log(f"START {len(jobs)} jobs, workers={a.workers}")
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=a.workers + 2))
    stop = threading.Event()

    def saver():
        while not stop.wait(30):
            save_state()

    threading.Thread(target=saver, daemon=True).start()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(lambda j: fetch(j, sess, max_file, cap), jobs))
    stop.set()
    save_state()
    log("DONE")
    status_report()


if __name__ == "__main__":
    sys.exit(main())
