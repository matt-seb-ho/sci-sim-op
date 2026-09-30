# FORGE blind wells: the truth the model is scored against

**Written:** 2026-09-30 (session 2, phase 1) · **Reading time:** ~3 min
**Data:** `/data/matt/sci-sim-op/geomodel/forge/truth/blind_wells.json` · **Script:** [`extract_blind_wells.py`](../../scripts/geomodel/extract_blind_wells.py)
Every number in the JSON carries its file and page or row.

## Top of granitoid (basin fill → granitoid)

| well | drilled | MD (ft / m) | TVD (m) | elevation (m NAVD88) | sources disagree by | in 1205 grid |
|---|---|---|---|---|---|---|
| **16A(78)-32** | 2020–21 | 4520 / 1378 | 1378 | **282** | 34 m ⚠ | yes |
| **56-32** | 2021 | 3180 / 969 | 969 | **702** | 40 m ⚠ | yes |
| **78B-32** | 2021 | 2700 / 823 | 823 | **891** | 15 m ⚠ | yes |
| **16B(78)-32** | 2023 | 4390 / 1338 | 1338 | **323** | 18 m ⚠ | yes |
| 58-32 (input, reference) | 2017 | 3175 / 968 | 968 | 724 | 8 m | yes |

- **Pick rule:** the first depth where the cuttings are granitoid (granite, granodiorite,
  or rhyolite dykes within them). "Granite wash", "reworked granite" and weathered-granite
  sand count as basin fill. MD is from each well's rig floor (RKB).
- **Why sources disagree:** reports round ("about 3,110 ft"), daily reports log the first
  granite chips, and final mud logs log the first dominant granite. The JSON keeps every
  value. The spread (15–40 m) is **the floor on contact-depth error**: no score finer than
  that means anything.
- The contact is at 700–900 m elevation in the east and ~300 m at 16A/16B, 1 km west.

## Temperature logs

| well | log | date | recovery | confidence | points (10 m) | in 1205 grid |
|---|---|---|---|---|---|---|
| 16A(78)-32 | CBL mud temp (1292) | 2021-08-16 | ~216 d | high | 325, to 3270 m MD | 88% |
| 56-32 | CBL mud temp (1295) | 2021-08-17 | ~162 d | high | 276, to 2770 m | 85% |
| 78B-32 | CBL mud temp (1330) | 2021-10-06 | 67 d | medium | 256, to 2590 m | 83% |
| 16B(78)-32 | DTS fibre, first frame (1826) | 2025-08-17 | post-stimulation | **low** | 307, to 3070 m | 87% |
| 58-32 (ref) | DiDrill PT (1326) | 2021-06-28 | 1371 d | high | 230, to 2300 m | 81% |

Each point has MD, TVD, x, y, elevation and T (°C). The 16A, 56-32, 78B and 58-32 profiles match
the GDR 1421 compilation to 0.00 °C. The top ~400 m of each log is above the grid (top 1250 m).

## Caveats (read before trusting a score)

1. **78B-32 ground level is wrong in its own reports.** The EOWR and CBL say 5,536 ft,
   which is 58-32's value, and 56 ft below the terrain there. I used the 10 m DEM in
   GDR 1107 (1704.5 m). With the reported value the contact would sit 17 m lower.
2. **16B temperature is weak.** No equilibrated pre-stimulation log is local. The 2025
   DTS baseline reads 6–15 °C warmer than 16A at the same depth, which may be heat left
   from producing 16B. Report 16B temperature separately, or leave it out.
3. **Four contact picks come from image-only mud logs,** read by eye from rendered pages
   (±10 ft). The page is cited for each.
4. **58-32's morning reports put granite at 2,150 ft;** the final mud log and EOWR say
   ~3,175–3,200 ft. The final log is used, and the early value is marked superseded.
5. **Leak-scan note:** the misspelling "GRANITIOD" also appears in the 16B cuttings photo
   log (1516, 2023). The canary is not unique to 1205. That doesn't matter here (1516 is
   after the cut), but a canary hit is not proof of a 1205 leak.

## Preliminary check against the 1205 model

Not the scorer: nearest 1205 column, midpoint of the lowest basin-fill and highest granitoid
cells. 1205 − truth: 56-32 **−2 m**, 78B **+9**, 58-32 −24, 16A **−82**, 16B **−123** (model too deep).
The expert model is good near its data (the east wells) and 80–120 m off 1 km west, so there is
room between the expert ceiling and a naive flat contact.
