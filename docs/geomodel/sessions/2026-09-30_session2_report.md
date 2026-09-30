# Session 2 report: FORGE-v0 from spec to first pilot results

**Night of 2026-09-30, 00:58 → 03:45 PDT** · unattended · **Reading time:** ~5 min
Brief: [`2026-09-30_session2_BRIEF.md`](2026-09-30_session2_BRIEF.md) · Full log: [`2026-09-30_session2_worklog.md`](2026-09-30_session2_worklog.md)

## TL;DR

1. **Everything in the brief runs end to end:** blind-well truth, a leak-scanned `/site`, a scorer with 16 tests, anchored baselines, a verified sandbox, the probe, and 3 + 1 pilot runs.
2. **The model barely knows FORGE from memory.** The probe put the granite 400–2,450 m deep (it is ~960 m) and scores below the naive baseline.
3. **The agent does real geology.** On the blind-well contact, all three A seeds beat naive (258 m error). One seed (37 m) beat the 2019 expert model (61 m), by digitizing a seismic figure. Spread across seeds is large (37–177 m).
4. **Main failure mode: it quits early.** Every run stopped by itself after 50–75 of its 180 minutes, guessing that time was up. None checked the clock.
5. **One leak, found by reading transcripts:** `gdr_1146/ABOUT.txt` carries the abstract of a 2020 paper. All four runs used it, and two copied a mislabeled number from it. Fix before v0.1.

## Results (scored from files; lower is better unless marked ↑)

| | naive | probe (3) | A seed 1 | A seed 2 | A seed 3 | B seed 1 | 2018 prior | **2019 expert** | 2025 expert* |
|---|---|---|---|---|---|---|---|---|---|
| **blind-well contact MAE (m)** | 258 | 693–1339 | 92 | **37** | 177 | 123 | 123 | **61** | 20 |
| **blind-well T RMSE (°C)** | 8.8 | 58–73 | 5.3 | 5.3 | 4.9 | 8.5 | – | **6.7** | 5.0 |
| lithology bal. accuracy ↑ (vs 1205) | 0.81 | 0.50–0.68 | 0.88 | 0.94 | 0.78 | 0.99 | 0.99 | 1 | 0.99 |
| contact RMSE vs 1205 (m) | 429 | 773–1307 | 230 | 144 | 402 | 39 | 39 | 10† | 41 |
| T RMSE vs 1205 (°C) | 18 | 64–81 | 12 | 13 | 13 | 18 | – | 0 | 6.8 |
| Shmin RMSE (MPa) | 1.2 | 1.0–5.1 | 1.1 | 1.1 | 4.5 | 5.0 | – | 0 | 3.6 |
| SHmax azimuth error (°) | 25 | 15 | 5 | 5 | 5 | 0 | – | 0 | 5 |
| cost ($) / minutes used | – | 0.02 / – | 0.11 / 50 | 0.27 / 74 | 0.26 / 64 | 0.12 / 59 | – | – | – |

\* 2025 (GDR 1812) was built *with* these wells, so its blind-well score is not blind. It is the "how good can it get" reference and it validates the truth: 20 m MAE is about the spread between the sources. † The 2019 expert's 10 m is pure resampling error from the 50 m map grid.
Blind wells: 16A, 56-32, 78B-32, 16B (see [`../FORGE_BLIND_WELLS.md`](../FORGE_BLIND_WELLS.md)). The contact picks disagree by 15–40 m between sources, so differences below ~30 m mean nothing.

**Reading the table**
- **Axis B (blind wells) is the honest one.** The agent beats naive on the contact in 3/3 seeds and on temperature in 3/3. It beats the 2019 expert on temperature in 3/3 and on the contact in 1/3.
- **Axis A (vs 1205) penalizes some good answers.** All agents used Sv ≈ 25.6 kPa/m from the density log. The 1205 IC uses 21.6, but the experts' own native-state run (1160) uses ~25. The two expert files disagree by 7 MPa RMSE on Sv.
- **Expert drift, 2019 → 2025:** 41 m contact RMSE, 6.8 °C, 3.3–3.6 MPa on the stresses. An agent inside that band is doing expert-level work on that field. No run is inside it yet on axis A: the best contact RMSE is 144 m, and T is 12–13 °C.

## What the agent actually did (A seed 1, read end to end)

- **The order it looked in:** spec → all 58 `ABOUT.txt` → grid → basement depths in 59 regional wells (714) → 58-32 end-of-well report → 78-32 lithology log → gravity stations → seismic report text → stress, temperature and density logs. It wrote its own shapefile reader, and gave up on the `.gdb` and the map PDF.
- **Where the turns went:** ~45 of 65 on reading and parsing, ~12 on one `build_model.py`, ~8 on the report and checks.
- **Moments worth quoting:**
  - reconciling data like a geologist: *"Overall the residual pattern is consistent in sign with basement depth: deeper → lower gravity"*, when it cross-checked well picks against Bouguer residuals;
  - the quitting failure: *"Now — with ~25 minutes left, remaining work: MODEL_REPORT.md"*, 45 minutes into a 3-hour run;
  - seed 2's winning move: *"The figure was digitised pixel-by-pixel (yellow colour …)"*, which recovered the author's top-of-granite line from a figure in the seismic report.
- **Where it went wrong:** the contact is ~60–120 m too shallow at every blind well. Variant B kept the 2018 surface "unchanged, now verified" and never used the one genuinely new well pick (78-32).
- **Cheating attempts:** none. No network commands, and nothing outside `/site`, `/work`, `/tmp` and `/task`.
- **Outputs:** 4/4 runs wrote all six files, and all of them parse.

## Spend

OpenRouter key usage was **$0 → $0.81** (cap $10). The four pilot runs cost $0.76, the probe $0.02, and smoke and verification runs the rest. The model is slow (up to 170 s per call), not expensive.

## Decisions made overnight (full list: D1–D19 in the worklog)

- **Sandbox:** bwrap instead of Docker (no Docker access on srv9). A host-side **model gate** injects the key, allows only `chat/completions` for mimo, strips web plugins, and caps $ per run. **The key never enters the sandbox.** 37/37 checks pass (`scripts/geomodel/verify_sandbox.sh`).
- **Excluded from `/site`** (details: `forge/site_v0A_LEAKSCAN.md`): the Phase 2B Topical Report, three "from_earth_model" CSVs, a 2020 paper hidden in a 2019 submission, and the gravity density models built on the 2B surface (station data kept).
- **Stress truth** is the 1205 IC's *total* stresses. SHmax azimuth = 25°, the direction the deck applies σHmax along.
- **Naive baseline** uses only pre-cut data (the 2018 58-32 T log and contact) plus textbook stress ratios.
- **Variant B was run** (1 seed), since time and budget allowed.
- **The prompt was not changed** between seeds.

## Not done, and why

- **1397 (2022) drift:** its mesh frame has no documented transform, and a 4-well fit left ~100 m residuals. The 2025 model (1812) was done instead.
- **Only 1 seed of B**, and no axis-C (Sherman) review yet.
- **The system `python3` has no pytest.** `.venv/bin/python -m pytest tests/ -q` → **630 passed, 2 skipped**.
- **Nothing committed** (per the brief). New files are in `src/geomodel_bench/`, `tests/geomodel_bench/`, `scripts/geomodel/` and `docs/geomodel/`. Data is in `/data/matt/sci-sim-op/geomodel/forge/{truth,site_v0A,site_v0B,baselines,scores,runs}/`.

## Questions for Matt

1. **The 1146 leak.** Should I trim `gdr_1146/ABOUT.txt` (the 2020 abstract) and re-run all seeds? It changes `/site`, so tonight's runs would stop being comparable. I recommend yes, for v0.1.
2. **Early quitting.** Should the harness tell the agent the time left (e.g. a `date` hint or a per-turn clock)? That is a harness change, not answer-tuning, but it will move scores a lot, so it's your call.
3. **Which stress truth for axis A:** the 1205 IC (Sv 21.6 kPa/m) or 1160 (≈25)? Or should Sv be dropped from axis A and left to axis B plus Sherman's review?
4. **Next:** more seeds (cheap: ~$0.25 per run), or show Sherman the three model reports first (axis C)?
