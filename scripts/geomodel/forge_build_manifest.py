#!/usr/bin/env python3
"""Enumerate every public Utah FORGE dataset on the Geothermal Data Repository
(GDR) and write a classified manifest.

How the enumeration works (no official JSON search API exists on GDR):
  1. https://gdr.openei.org/data.json  -- the DCAT (Project Open Data) catalog of
     all GDR submissions, with projectNumber. Utah FORGE's DOE award is
     EE0007080. The catalog lags the site by ~40 recent submissions.
  2. https://gdr.openei.org/sitemap.xml -- every submission id (complete).
  3. https://gdr.openei.org/search?q=EE0007080 and ?q=Utah+FORGE (HTML,
     paginated by from=N) -- catches recent submissions missing from data.json
     and FORGE-funded R&D projects filed under other award numbers.
  4. Each candidate submission page is fetched once (cached) and parsed: its
     schema.org JSON-LD block (title, description, date, authors, orgs) and the
     resource list (file name, URL, human-readable size).
  A submission is kept if its DOE project number is EE0007080, or its text
  mentions Utah FORGE / Milford FORGE wells.

Also records non-GDR sources (OEDI S3 data lake prefix FORGE/, UGS reports).

    python3 scripts/geomodel/forge_build_manifest.py            # uses page cache
    python3 scripts/geomodel/forge_build_manifest.py --refresh  # refetch pages
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import requests

OUT = Path("/data/matt/sci-sim-op/geomodel/forge")
PAGES = OUT / "meta" / "pages"
GDR = "https://gdr.openei.org"
UA = {"User-Agent": "sci-sim-op FORGE inventory (research; contact matt.seb.ho@gmail.com)"}
S = requests.Session()
S.headers.update(UA)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_overrides import EXCLUDE, OVERRIDES, EXTRA_SOURCES  # noqa: E402


def get(url, **kw):
    for i in range(4):
        try:
            r = S.get(url, timeout=120, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            print("retry", url, e, file=sys.stderr)
        time.sleep(2 * (i + 1))
    return None


# ---------------------------------------------------------------- enumeration
def search_ids(q: str) -> set[int]:
    ids: set[int] = set()
    first = get(f"{GDR}/search?q={q}")
    m = re.search(r"Showing results \d+ - \d+ of (\d+)", first.text)
    total = int(m.group(1)) if m else 0
    for frm in range(0, total, 25):
        r = first if frm == 0 else get(f"{GDR}/search?q={q}&from={frm}")
        ids |= {int(x) for x in re.findall(r"submissions/(\d+)", r.text)}
        time.sleep(0.3)
    ids.discard(1)  # the GDR help submission linked from every page header
    return ids


def page(sid: int, refresh: bool) -> str | None:
    f = PAGES / f"{sid}.html"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8", errors="replace")
    r = get(f"{GDR}/submissions/{sid}")
    if r is None:
        return None
    f.write_text(r.text, encoding="utf-8")
    time.sleep(0.3)
    return r.text


# ---------------------------------------------------------------- parsing
UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def parse_size(s: str | None) -> int | None:
    if not s:
        return None
    m = re.match(r"([\d.,]+)\s*([KMGT]?B)", s.strip(), re.I)
    return int(float(m.group(1).replace(",", "")) * UNITS[m.group(2).upper()]) if m else None


def txt(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_page(sid: int, t: str) -> dict:
    ld = {}
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
        except json.JSONDecodeError:
            ld = {}
    title = ld.get("name") or txt(re.search(r"<title>GDR:(.*?)</title>", t, re.S).group(1))
    proj = re.search(r"Project Name</span>\s*<strong>(.*?)</strong>", t, re.S)
    pnum = re.search(r"Project Number</span>\s*<strong>(.*?)</strong>", t, re.S)
    files = []
    blocks = t.split('<div class="sub-resource"')[1:]
    for b in blocks:
        name = re.search(r'<div class="resource-name" title="([^"]*)"', b)
        desc = re.search(r'data-full-desc="([^"]*)"', b)
        link = re.search(r"class='downloadlink[^']*' href='([^']*)'", b)
        size = re.search(r"<small class='text-muted'>\s*([^<]*?)\s*</small>", b)
        if not link:
            emb = re.search(r"download-ban[^<]*</i></span>\s*(Available[^<]*)", b)
            if name:
                files.append({"name": html.unescape(name.group(1)), "filename": None, "url": None,
                              "kind": "embargoed" if emb else "unavailable",
                              "available": emb.group(1).strip() if emb else None,
                              "size_str": None, "size_bytes_approx": None,
                              "description": html.unescape(desc.group(1))[:500] if desc else ""})
            continue
        href = html.unescape(link.group(1))
        url = urljoin(GDR, href) if href.startswith("/") else href
        is_gdr = url.startswith(f"{GDR}/files/")
        fname = unquote(url.rsplit("/", 1)[-1]) if is_gdr else None
        files.append({
            "name": html.unescape(name.group(1)) if name else fname,
            "filename": fname,
            "url": quote(url, safe=":/%?=&()'+,;@!$*~") if is_gdr else url,
            "kind": "gdr_file" if is_gdr else ("s3_prefix" if "s3_viewer" in url else "external_link"),
            "size_str": size.group(1).strip() if size else None,
            "size_bytes_approx": parse_size(size.group(1)) if size else None,
            "description": html.unescape(desc.group(1))[:500] if desc else "",
        })
    authors = [
        {"name": c.get("name"), "affiliation": c.get("affiliation")}
        for c in (ld.get("creator") or [])
    ]
    orgs = [o.get("name") for o in (ld.get("sourceOrganization") or []) if o.get("name")]
    total = re.search(r"Download All Resources</span>\s*<span[^>]*>([^<&]*)", t)
    return {
        "id": str(sid),
        "source": "gdr",
        "title": html.unescape(title).strip(),
        "url": f"{GDR}/submissions/{sid}",
        "doi": ld.get("identifier") if "doi.org" in str(ld.get("identifier")) else None,
        "date_published": ld.get("datePublished"),
        "authors": authors,
        "organizations": [o for o in orgs if o not in ("Geothermal Data Repository",)],
        "doe_project": txt(proj.group(1)) if proj else None,
        "doe_project_number": txt(pnum.group(1)) if pnum else None,
        "keywords": ld.get("keywords") or [],
        "description": (ld.get("description") or "").strip(),
        "total_size_str": total.group(1).strip() if total else None,
        "files": files,
    }


# ---------------------------------------------------------------- classification
# Ordered: first match wins. Title is matched first, then title+description.
RULES = [
    ("native_state_or_reservoir_model", r"native[ -]state|reference (reservoir |numerical )?model|thermal[- ]hydrolog|reservoir model|stress model"),
    ("dfn_model", r"\bdfn\b|discrete fracture network|fracture network model"),
    ("geologic_model", r"earth model|geologic(al)? model|3-?d (geologic|earth|structural)|leapfrog|petrel|mesh data|surfaces|geologic framework|structural model|litholog(y|ic) model"),
    ("fiber_das_dts", r"\bdas\b|\bdts\b|\bdss\b|fiber|fibre|distributed (acoustic|temperature|strain)"),
    ("microseismic", r"micro-?seismic|seismicity|earthquake|\bmeq\b|event catalog|seismic (monitoring|events|catalog)|geophone|seismometer|induced seism|moment tensor|nodal"),
    ("stimulation_injection", r"stimulation|injection|circulation|hydraulic fractur|frac(ture)? treatment|pumping|flow test|tracer|production test|interwell|inter-well"),
    ("image_logs", r"\bfmi\b|image log|borehole image|televiewer|\bubi\b|\buxpl\b|\babi\b|fracture (picks|interpretation)|natural fractures in"),
    ("stress_tests", r"\bdfit\b|mini-?frac|in[- ]situ stress|stress (test|measure|magnitude|orientation|data)|breakout|leak-?off|\bxlot\b|fracture closure"),
    ("core_lab", r"\bcore\b|cores|xrd|x-ray diffraction|thin section|petrograph|laborator|triaxial|permeability measure|rock mechanic|mechanical propert|geochem|cuttings|mineralog|thermal conductivity|samples?"),
    ("temperature", r"temperature|thermal gradient|heat flow|geotherm(al)? gradient"),
    ("seismic_reflection", r"seismic reflection|reflection seismic|3-?d seismic|2-?d seismic|seg-?y|\bvsp\b|vertical seismic|seismic survey|seismic velocity|tomograph"),
    ("potential_fields", r"gravity|magnetic|magnetotelluric|\bmt\b|resistivity|electromagnetic|aeromag"),
    ("geodesy", r"insar|\bgps\b|\bgnss\b|geodetic|surface deformation|tiltmeter|\blidar\b"),
    ("well_logs", r"well log|\blogs?\b|logging|drilling data|mud log|\blas\b|wireline|sonic|drilling|well data|wellbore|trajectory|survey data|completion|end of well"),
    ("maps_gis", r"\bmaps?\b|\bgis\b|shapefile|\bdem\b|geologic map|geospatial|kmz"),
    ("simulation_outputs", r"simulat|numerical|model(l)?ing|modeled|benchmark|machine learning"),
    ("reports", r"report|presentation|paper|webinar|workshop|proceedings|poster|video|newsletter|quarterly|annual|summary|overview|slides|publication|manuscript|thesis"),
]
ROLE = {
    "geologic_model": "model", "dfn_model": "model", "native_state_or_reservoir_model": "model",
    "well_logs": "input", "image_logs": "input", "core_lab": "input", "stress_tests": "input",
    "temperature": "input", "seismic_reflection": "input", "potential_fields": "input",
    "maps_gis": "input", "microseismic": "eval", "stimulation_injection": "eval",
    "fiber_das_dts": "eval", "geodesy": "eval", "reports": "context",
    "simulation_outputs": "context", "other": "context",
}
ROLE_REASON = {
    "model": "interpreted/derived model artifact (surfaces, fractures, property/state fields)",
    "input": "raw site characterization an expert would interpret to build the model",
    "eval": "reservoir response to drilling/injection/stimulation that a model should reproduce",
    "context": "documentation, reports or third-party simulations; not a primary observation",
}


PRESENTATION = r"workshop|presentation|annual report|final report|slides|webinar|video|status report|topical report"
TIER = {
    "geologic_model": 1, "dfn_model": 1, "native_state_or_reservoir_model": 1, "well_logs": 1,
    "stress_tests": 1, "image_logs": 1, "reports": 1, "temperature": 2, "maps_gis": 2,
    "core_lab": 2, "potential_fields": 2, "seismic_reflection": 2,
}


def classify(rec: dict) -> tuple[str, str]:
    t = rec["title"].lower()
    if re.search(PRESENTATION, t):
        return "reports", "keyword rule (title): presentation/report"
    full = (t + " " + rec["description"].lower())
    for text, how in ((t, "title"), (full, "title+description")):
        for cat, rx in RULES:
            if re.search(rx, text):
                return cat, f"keyword rule ({how}): /{rx.split('|')[0]}.../"
    return "other", "no rule matched"


def phase(rec: dict) -> dict:
    text = rec["title"] + " " + rec["description"]
    m = re.findall(r"phase\s*(1|2A|2B|2C|3|I{1,3}|2)\b", text, re.I)
    explicit = sorted({x.upper().replace("III", "3").replace("II", "2").replace("I", "1") for x in m})
    d = rec.get("date_published") or ""
    if not d or d < "1990":
        by_date = None
    elif d < "2017-01":
        by_date = "1/2A"
    elif d < "2018-07":
        by_date = "2B"
    elif d < "2020-04":
        by_date = "2C"
    elif d < "2023-01":
        by_date = "3A"
    else:
        by_date = "3B"
    return {
        "date_published": d or None,
        "phase_mentioned": explicit or None,
        "phase_by_date": by_date,
        "note": "phase_by_date uses publication date with approximate FORGE phase boundaries "
        "(1/2A <2017; 2B 2017-mid 2018: 58-32 drilled, Phase 2B earth model; 2C mid 2018-early 2020: "
        "native-state v1; 3A 2020-2022: 16A drilled + 2022 stimulation; 3B 2023-: 16B, 2024 stimulation, circulation). "
        "Data may predate publication.",
    }


def is_forge(rec: dict) -> tuple[bool, str]:
    if rec["id"] in EXCLUDE:
        return False, ""
    if rec.get("doe_project_number") == "EE0007080":
        return True, "DOE project number EE0007080 (Utah FORGE)"
    blob = " ".join([rec["title"], rec["description"], " ".join(rec["keywords"])]).lower()
    if re.search(r"utah ?forge|forge site|milford|16a\(78\)|16b\(78\)|58-32|78b-32|56-32|roosevelt hot springs", blob):
        if not re.search(r"fallon|coso|newberry|snake river", (rec.get("doe_project") or "").lower()):
            return True, "text mentions Utah FORGE site/wells (other DOE award)"
    return False, ""


# ---------------------------------------------------------------- S3 data lake
def s3_prefix_summary(bucket: str, prefix: str) -> dict:
    tok, n, total, by_sub = None, 0, 0, {}
    while True:
        u = f"https://{bucket}.s3.amazonaws.com/?list-type=2&prefix={quote(prefix)}"
        if tok:
            u += "&continuation-token=" + quote(tok)
        r = get(u)
        root = ET.fromstring(r.content)
        ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
        for c in root.findall("s:Contents", ns):
            key = c.find("s:Key", ns).text
            sz = int(c.find("s:Size", ns).text)
            n += 1
            total += sz
            sub = "/".join(key.split("/")[:4])
            a = by_sub.setdefault(sub, [0, 0])
            a[0] += 1
            a[1] += sz
        t = root.find("s:NextContinuationToken", ns)
        if t is None:
            break
        tok = t.text
    return {"objects": n, "bytes": total, "by_subprefix": {k: {"objects": v[0], "bytes": v[1]} for k, v in sorted(by_sub.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    PAGES.mkdir(parents=True, exist_ok=True)

    dcat = get(f"{GDR}/data.json").json()["dataset"]
    (OUT / "meta" / "gdr_data.json").write_text(json.dumps(dcat))
    dcat_ids = {int(x["identifier"].rstrip("/").split("/")[-1]) for x in dcat}
    sitemap = {int(x) for x in re.findall(r"submissions/(\d+)", get(f"{GDR}/sitemap.xml").text)}
    cand = {int(x["identifier"].rstrip("/").split("/")[-1]) for x in dcat
            if x.get("projectNumber") == "EE0007080"
            or re.search(r"utah ?forge|milford", json.dumps(x).lower())}
    s1, s2 = search_ids("EE0007080"), search_ids("Utah+FORGE")
    cand |= s1 | s2 | (sitemap - dcat_ids)
    print(f"dcat={len(dcat_ids)} sitemap={len(sitemap)} candidates={len(cand)} "
          f"(search EE0007080={len(s1)}, 'Utah FORGE'={len(s2)})", file=sys.stderr)

    with cf.ThreadPoolExecutor(a.workers) as ex:
        pages = dict(zip(sorted(cand), ex.map(lambda i: page(i, a.refresh), sorted(cand))))

    records = []
    for sid, t in pages.items():
        if not t:
            continue
        rec = parse_page(sid, t)
        ok, why = is_forge(rec)
        if not ok:
            continue
        rec["selection_reason"] = why
        cat, creason = classify(rec)
        ov = OVERRIDES.get(str(sid), {})
        rec["category"] = ov.get("category", cat)
        rec["role_guess"] = ov.get("role_guess", ROLE[rec["category"]])
        rec["role_reason"] = ov.get("reason") or ROLE_REASON[rec["role_guess"]]
        rec["classified_by"] = "manual review" if ov else creason
        rec["priority"] = ov.get("priority") or (
            TIER.get(rec["category"], 3) if rec["role_guess"] != "context" or rec["category"] == "reports" else 3)
        rec["phase_or_date"] = phase(rec)
        if ov.get("phase"):
            rec["phase_or_date"]["phase_reviewed"] = ov["phase"]
        records.append(rec)

    extra = []
    for x in EXTRA_SOURCES:
        x = dict(x)
        if x.get("s3"):
            x["s3_summary"] = s3_prefix_summary(*x["s3"])
        extra.append(x)

    man = {
        "site": "Utah FORGE (Milford, UT)",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "enumeration": {
            "method": __doc__.split("How the enumeration works")[1].split("Also records")[0].strip(),
            "dcat_catalog_size": len(dcat_ids),
            "sitemap_size": len(sitemap),
            "candidates_checked": len(cand),
            "forge_submissions": len(records),
        },
        "records": sorted(records, key=lambda r: int(r["id"])) + extra,
    }
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1))
    print(f"wrote {OUT/'manifest.json'}: {len(records)} GDR records + {len(extra)} extra", file=sys.stderr)


if __name__ == "__main__":
    main()
