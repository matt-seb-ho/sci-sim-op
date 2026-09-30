# Session 2 worklog (overnight 2026-09-30)

Brief: [`2026-09-30_session2_BRIEF.md`](2026-09-30_session2_BRIEF.md). Newest entries at the bottom of each section.

## Timeline

- 00:58 PDT start. Host `sn4622116169` (srv9). Read handoff + README, TASK_FORGE_v0, DATA_INVENTORY, WHAT_IS, TERMINOLOGY, CONTAMINATION doc, session-1 report.
- 00:59 OpenRouter key usage baseline: **usage = 0** (USD; limit 250).

- 01:00 Phase 1 (blind wells) delegated to a background fork (writes its own section at the end).
- 01:02 Phase 2: `scripts/geomodel/build_site.py` → `site_v0A/` (58 submissions, 146 files, 9.97 GB before leak-scan exclusions). Leak scan `scripts/geomodel/leak_scan.py` running.
- 01:03 Phase 4: Node 22.23.3 (official tarball, sha256 checked) + pi 0.99.1 (`@earendil-works/pi-coding-agent`) + a standalone CPython 3.12.14 with the tool stack, all under `/data/matt/sci-sim-op/geomodel/sandbox/`.
- 01:05 Sandbox verified: 37/37 PASS (`scripts/geomodel/verify_sandbox.sh`, log `sandbox/verify_20260930T010516.log`).
- 01:08 Truth built: `geomodel_bench.truth` → `forge/truth/{lithology,state_1205ic,state_1160}.csv, summary.json, grid.json`. IC xlsx has cached formula values.
- 01:14 Leak scan #1 reviewed → 6 exclusions/repacks (D10–D12). Final scan 01:21–01:27: PASS. Doc: `forge/site_v0A_LEAKSCAN.md`.
- 01:19 Scorer `src/geomodel_bench/` + 16 tests pass. Baselines naive / expert2019 / expert2019-with-1160-state scored → `forge/scores/`.
- 01:21 Output spec frozen (`FORGE_v0_OUTPUT_SPEC.md`); agent prompt written (`FORGE_v0_AGENT_PROMPT.md`).
- 01:22 Probe attempt 1 hit `max_tokens` 16k inside reasoning (no answer) → relaunched with 60k + reasoning effort medium (same as pi's). Cost of failed attempt ≈ $0.01.
- 01:28 Smoke run of pi in the sandbox (`runs/smoke_012824`): tools work, curl google → "Could not resolve host", 4 API calls $0.0006.
- 01:29 First launch of A1 was killed after ~20 s by my own `pkill -f` (it matched my shell) → kept as `runs/aborted_A1_seed1_relaunch` ($0.002). Relaunched detached with `setsid nohup` (the Bash tool's background limit is 2 h < 3 h run).
- 01:35 **Expert drift** (1205 → 1812) done in ~25 min: 1812's own `lpToMOOSEWellLocalCoordSys.py` gives the UTM→local map (rotate +20° about (335343.707, 4263012.44), translate (−335345.48, −4263010.66, +1150)); it reproduces 58-32 at (91.0, 61.8) vs the file's (91.1, 61.7). `scripts/geomodel/expert2025_submission.py` resamples mesh60m units (point-in-tet) and the 40 m THM samples (IDW-8) onto the 1205 grid. The first SHmax azimuth from eigenvectors (9°) was wrong-signed; the deck applies σHmax on ymin/ymax → local y → **N20E**. 1397 (2022) not done: its mesh frame has no documented transform, and a 4-well fit left ~100 m residuals.
- Sanity: 1812 (which saw the post-2019 wells) hits the blind-well contacts with MAE 20 m (≤ source spread) → blind-well truth and frame transform both look right.
- 01:56 **Probe done** (3 samples, $0.022 total, 6–14 min each: the model reasons ~20k tokens). All three say "confidence: low". Contact at 58-32: 2450 / 400 / 400 m (truth ≈ 960 m); T gradient 40–50 °C/km (1205 ≈ 63); SHmax 40°/10°/10° (truth 25°); stress gradients generic Basin-and-Range. Probe 1 hallucinates 58-32 as "a 2007 slim-hole well". Worse than naive on geology and T, similar on stress. → **little site-specific contamination.**
- 02:19 **A1_seed1 finished by itself** after 50 min (65 model calls, 103 tool calls, $0.11). Trace: `runs/A1_seed1/trace.txt` (made by `scripts/geomodel/read_transcript.py`). Read end to end:
  - *Looked at:* spec → all 58 ABOUT.txt → grid → 714 (basement depths in 59 wells), 1006 EOWR (58-32 strat column: alluvium 0–3176 ft, rhyolite 3176–3196, granite below), 1153 78-32 lithology log (granite at 2610 ft), 1144 gravity stations (used both for ground elevation and a Bouguer-residual check of basement depths), 1141 seismic report text ("granite surface continuous, undulatory"), 1032/1162 stress (Sv 1.13 psi/ft, SHmax 0.77, Shmin 0.62; normal), 1101 + 1052 T logs (picked the most equilibrated), 1111 density/sonic/conductivity logs, 713 lineaments (for the optional fractures.json).
  - *Where turns went:* ~45 turns reading/parsing (wrote its own shapefile/DBF reader; tried and gave up on the .gdb and the geology-map PDF), ~12 building and debugging one `build_model.py`, ~8 report/validation.
  - *Where it went wrong:* (1) **stopped at 50 min of 3 h** believing time was nearly up ("~25 minutes left", "Time is nearly up") — it never ran `date`; (2) dropped three 714 wells near 58-32 whose basement depths conflicted (reasonable), but its surface is still ~100 m too shallow at every blind well (+63…+118 m); (3) used Sv = 25.6 kPa/m from the density log, which the 1205 IC does not (21.6) but 1160 does (≈25) — axis A penalises it.
  - *Cheating:* none. No network commands, no paths outside /site,/work,/tmp,/task (3 regex flags are false positives: `/ABOUT.txt`, `/ft2m`, `/attrlabl`). It did `find -iname '*top*gran*'` (legit search). It read `gdr_1146/ABOUT.txt`, whose GDR description **repeats the abstract of the excluded 2020 paper** (58-32 stress gradients, SHmax NNE). Those are 2017–19 test results, not model output, but it is a site-construction inconsistency (flag for Matt).
  - *Outputs:* all 6 required files + fractures.json parse; 0 parse errors in the scorer.
  - *Harness bugs:* none found → seeds 2 and 3 launched at 02:20 in parallel. Prompt unchanged.
- 02:25 **Variant B built** (`build_site.py --variant B` → `site_v0B/`: A + gdr_1107, gdr_1108, the 2B Topical Report, 1111's `*_from_earth_model.csv`, the full 1144 zip; still without 1146's 2020 paper). `NEW_DATA.txt` lists the 10 submissions published after 2018-12-07. Leak scan B: new hits are all prior-model content (expected; incl. "Granitiod" in 1111's 2B-model lithology — the Leapfrog typo predates 1205) or binary/PDF-object noise → PASS for variant B. Prompt B = prompt A + one paragraph (`FORGE_v0_AGENT_PROMPT_B.md`). B_seed1 launched 02:24.
- 02:27 **Prior-model baseline** (`scripts/geomodel/prior2018_submission.py`): the 1107 surface alone scores contact RMSE vs 1205 = 39 m, blind-well contact MAE = 123 m (1205: 61; A1: 92).
- 03:34 **A seeds 2–3 and B seed 1 finished by themselves** (74, 64, 59 min; $0.27, $0.26, $0.12). All outputs parse. Scores in `forge/scores/*.json`; traces in `runs/*/trace.txt`.
  - A2: best run. Digitised the author's top-of-granite line from a figure in the 1141 seismic report (legit input) → blind-well contact MAE **37 m** (1205: 61). Checked: no blind-well name appears anywhere in its trace or report.
  - A3: took Shmin 16.9 kPa/m from the `gdr_1146/ABOUT.txt` abstract (mislabelled; really the SHmax range) → Shmin RMSE 4.5 MPa; contact 300 m too shallow at 16A/16B.
  - B1: kept the 2B contact **unchanged** ("verified" vs seismic + gravity) and ignored the new 78-32 pick → blind-well contact identical to the prior (123 m). Also took Shmin 17.15 from the 1146 abstract.
  - All 4 runs cite `gdr_1146/ABOUT.txt`. Cheating: none (all FLAGs are regex false positives on relative paths/Python attributes).
  - Recurrent: agents guess elapsed time and stop early (none ran `date`); A1 thought it was near 3 h at 50 min, B1 "maybe 2h20m" at ~60 min.
- 03:40 Spend: key usage **$0.814** (baseline 0) — gate $0.761 + probes $0.022 + failed probe/verify/smoke ≈ $0.03. Tests: `.venv/bin/python -m pytest tests/ -q` → 630 passed, 2 skipped (system `python3` has no pytest).

## Decisions

| # | decision | why |
|---|---|---|
| D1 | Sandbox = **bwrap `--unshare-all`** + unix-socket bridge, not Docker | `docker ps` → permission denied (matt not in docker group on srv9) |
| D2 | The bridge is **not** a CONNECT proxy but a key-injecting **model gate** (`llm_gate.py`): only `POST chat/completions` for `xiaomi/mimo-v2.6-flash`; key added on the host | with a CONNECT proxy the key must live inside the sandbox, where the agent's bash can read it and call OpenRouter itself (incl. `:online` web-search models / `plugins`). The gate removes both routes and enforces the $3 cap per run |
| D3 | pi uses its **built-in `openrouter` provider** with `baseUrl` overridden to the in-sandbox relay (`http://127.0.0.1:8080/api/v1`) | keeps pi's OpenRouter-specific request handling; dummy key in the sandbox |
| D4 | Node 22 installed from nodejs.org into the sandbox dir | system node is v18; pi 0.99 needs ≥ 22.19 |
| D5 | Thinking level `medium` (pi default), tools `read,bash,edit,write,grep,find,ls`, `--offline`, telemetry off, project trust `never` | defaults; no tuning |
| D6 | "Files over 2 GB" = decimal 2,000,000,000 B → drops `gdr_1015/2D_seismic_data.zip` (2.06 GB). Processed stacks (1.1 GB) stay | conservative literal reading |
| D7 | Scorer is **pure stdlib Python** (no numpy) | repo `.venv` has only pytest; `python3 -m pytest tests/` must pass without adding deps |
| D9 | Stress truth = **total** stress from the 1205 IC `disp_*_bc` columns (Sv = −disp_k_bc, SHmax = −disp_j_bc, Shmin = −disp_i_bc); the `vertical/h_max/h_min` columns are effective (total + P, compression negative). SHmax azimuth = 25° (j axis of the grid, where FALCON applies σHmax) | from the xlsx formulas and 1315 `PTM2.i` BCs |
| D10 | **Excluded** the Phase 2B Topical Report (in 1039 and 1052) and 1111's three `*_from_earth_model.csv` | write-ups / samples of the prior (2B) earth model; variant A withholds it |
| D11 | **Excluded** 1146 `Moore_UtahFORGE_overview_Stanford_2020.pdf` | Feb-2020 paper inside a 2019 submission: top-of-granitoid section, contact dip, 58-32 stress gradients |
| D12 | **Repacked** 1144 gravity zip to the station data only | the density models use the 2B top-granite surface + a modified one; README says "taken from the FORGE data page" |
| D13 | Axis-A properties truth: E, ν, density, conductivity from 1315 `.i`; k and φ = per-unit median of 1160 per-cell values (k = geometric mean of Kii,Kjj,Kkk). Density has two expert values (TH deck 2400/2640, TM deck 2500/2750): score against the nearer | the expert files disagree with each other |
| D14 | Contact metrics compare **elevations**, both sides clipped to the grid's z range; the expert's own map-grid resampling costs ≈ 10 m RMSE | 1205 contact is only defined inside the grid |
| D15 | Blind-well T: 16B's T log is DTS 2025 (low confidence) → scored per well but **excluded from the pooled** B.T_rmse | fork's caveat |
| D16 | Naive baseline: flat contact at 58-32 (724 m elev.); T = linear fit to the **2018-11-08** 58-32 log (GDR 1101, an input); hydrostatic P; Sv 25 kPa/m, SHmax 0.8 Sv, Shmin 0.6 Sv, SHmax N–S; textbook properties | spec §5 floor; only pre-cut data. (The 58-32 contact pick itself comes from the 1006 mud log, an input.) |
| D17 | Probe = one direct API call per sample (seed 1–3), JSON answer → planar contact + linear gradients below the 58-32 ground level, scored with the same scorer. The prompt gives only the 58-32 location/ground elevation | needed to place the answer on the grid; no geology given |
| D18 | Seeds = OpenRouter `seed` set by the gate on every request (1, 2, 3) | pi has no seed flag |
| D19 | Ran variant B (1 seed) in parallel with A seeds 2–3 | brief allows B "if time and budget remain": spend was $0.15 of $10 at 02:24 |
| D8 | Grid given to the agent: `cells.csv` from `2019.08.21_global_cell.csv` and `nodes.csv` from `2019.06.06_global_node.csv`, columns `cell_id/node_id,x,y,z` (UTM, elevation), header and labels stripped. `dX,dY,dZ` dropped (constant 50) | brief: labels, Leapfrog header, property columns removed |

## Verifications

- **Sandbox (01:05)**: network: curl gdr.openei.org / google.com / 1.1.1.1 / openrouter.ai direct / pip all fail; no interfaces but `lo`. Model API through the gate: 200 ("pong", $0.000007). Other model (`:online`), `GET /key`, `/responses` → 403. No key in env or visible files. `/data`, `/home/matt`, repo, `/root`, `/mnt`, `/srv` absent; `/` = bin dev etc home lib lib64 opt proc run sbin site task tmp usr work. `/site` ro, `/work` rw. All 10 Python packages import; pdftotext, unzip, pi present.

## Problems / blocked

## Phase 1: blind-well truth (fork; appended ~01:30)

Outputs: `/data/.../forge/truth/blind_wells.json` (4 blind wells in `wells`, 58-32 in `reference_wells`), `docs/geomodel/FORGE_BLIND_WELLS.md`, `scripts/geomodel/extract_blind_wells.py` (run with the scratch venv at `/data/.../forge/scratch_phase1/venv`: needs lasio, h5py, openpyxl, pyproj, scipy). Scratch unpacks are in `/data/.../forge/scratch_phase1/` (raw/ untouched).

| well | top granitoid MD ft | z m NAVD88 | spread | T log |
|---|---|---|---|---|
| 16A | 4520 | 282 | 34 m | CBL 2021-08-16 (216 d) |
| 56-32 | 3180 | 702 | 40 m | CBL 2021-08-17 (162 d) |
| 78B | 2700 | 891 | 15 m | CBL 2021-10-06 (67 d) |
| 16B | 4390 | 323 | 18 m | DTS 2025-08-17 frame 0 (low conf.) |
| 58-32 (ref) | 3175 | 724 | 8 m | DiDrill 2021-06-28 (1371 d) |

Decisions (Phase 1):
- P1-D1 Pick rule = first granitoid in cuttings (dominant where logs give %); granite wash / reworked granite = basin fill. Every other source value is kept in the JSON; spread >10 m flagged (all 4 blind wells are flagged: 15–40 m).
- P1-D2 No OCR tool (no tesseract): image-only mud logs (1292 16A, 1295 56-32 compiled, 1330 78B, 1006 58-32, 1516 16B) were rendered with pdftoppm and read by eye, ±10 ft. Cited by page.
- P1-D3 78B GL: reported 5536 ft (EOWR, CBL) is 58-32's value; used 1107 DEM 1704.5 m. 78B mud-log header coords are also 58-32's: ignored.
- P1-D4 16A wellhead: survey header usft coords (= Woolsey land survey), not the 1216 planned wellhead (16 m off).
- P1-D5 16B has no pre-stimulation equilibrated T log locally; used the first frame of the 1826 DTS (Aug 2025), cut at the fibre end (10080 ft), marked confidence low. 6–15 °C warmer than 16A at the same TVD.
- P1-D6 58-32: used 2021 DiDrill log (1371 d recovery, but after the 2019 stimulation); GL from 1268 GPS (EOWR GL is 8 ft higher). Early morning-report granite at 2150 ft marked superseded.
- P1-D7 Trajectory extrapolated along the last survey segment where a T log runs deeper than the survey (58-32).

Verification: T profiles equal GDR 1421's compiled sheets to 0.00 °C (4 wells). 1205 grid frame checked against the local-cell file. Quick nearest-column 1205 contact vs truth: 56-32 −2 m, 78B +9, 58-32 −24, 16A −82, 16B −123 (not the scorer).
Leak-scan note for Phase 2: "GRANITIOD" also occurs in 1516's 16B photo log (post-cut, so not in /site), so the canary is not unique to 1205.

## Definition of Done (checked 03:47)

- [x] `forge/truth/blind_wells.json` + `docs/geomodel/FORGE_BLIND_WELLS.md`
- [x] `forge/site_v0A/` with a passing, documented leak scan (`forge/site_v0A_LEAKSCAN.md`); residual issue: 1146 ABOUT.txt (found by transcript reading, see report Q1)
- [x] output spec, scorer + 16 tests passing, baselines scored (naive, expert2019, expert2019-1160-state, expert2025 drift, prior2018)
- [x] sandbox verified (37/37; `sandbox/verify_20260930T010516.log`)
- [x] probe scored (3 samples); A1 read end to end and scored; 3 A seeds + 1 B seed scored
- [x] morning report + README/spec status updated + DONE file

## Follow-up (2026-09-30 morning, with Matt)

- 09:45 **Leak fix → site v0.1** (`site_v0A1`, `site_v0B1`; `build_site.py` `ABOUT_OVERRIDE` + exclusion): `gdr_1146/ABOUT.txt` description (the Feb-2020 abstract) replaced by a neutral stub; `gdr_1139/NMV GWGeochem (1).zip` dropped (GDR re-uploaded it in Oct 2021 with 2018–2021 data; the 2019 xlsx stays). Sweep of all archive member dates and PDF creation dates: 1006's EOWR (2022) and dipole-sonic (2021) zips are only re-packaged 2017–18 files (no 2019+ text) → kept. Leak scan v0A1: nothing new, only the dropped zip's hits gone → PASS.
- 09:52 Re-runs (A01 seeds 1–3, B01 seeds 1–2) **all failed within 1–15 min**: OpenRouter returned 402 `in_flight_budget_exhausted` ("exceed your available credits"). The **account** has $3,725 of credits with $3,724.97 used (shared with other keys); our key's $250 limit is not the binding one. Runs renamed `runs/failed402_*`, not scored. Needs credits added before re-running.
