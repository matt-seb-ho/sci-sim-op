# BRIEF: session 2 (overnight 2026-09-30): FORGE-v0 from spec to first pilot results

You are running **unattended overnight**. Matt is asleep: **do not ask questions or stop
to check in.** When a decision is needed, make the conservative choice, record it under
"Decisions" in your worklog, and keep going. Work until the Definition of Done holds or
you are truly blocked, then write the morning report either way.

**Repo:** `/home/matt/projects/sci-sim-op` · **Data:** `/data/matt/sci-sim-op/geomodel/`
**Worklog (keep it current as you go):** `docs/geomodel/sessions/2026-09-30_session2_worklog.md`
**Morning report (the deliverable Matt reads):** `docs/geomodel/sessions/2026-09-30_session2_report.md`

## Phase 0: orient (≤ 30 min)

1. Read the handoff [`2026-09-30_0100_handoff.md`](2026-09-30_0100_handoff.md) and every
   doc it lists, in order. [`../TASK_FORGE_v0.md`](../TASK_FORGE_v0.md) is the spec.
2. Record the OpenRouter usage baseline for the key (`GET $OPENROUTER_BASE_URL/key` or
   `https://openrouter.ai/api/v1/key` with the key from `.env`). Log **only the usage
   number**, never the key.

## Phase 1: blind-well truth (spec §8.1)

For **16A(78)-32, 56-32, 78B-32 and 16B(78)-32**, extract:
- the **top of granitoid** (basin fill → granitoid contact): measured depth, TVD, and
  its x, y, elevation (UTM 12N / NAVD88) using the trajectories;
- **temperature vs depth** from the most equilibrated log available, with its date.

Rules:
- Cite the file (and page or row) for every number.
- Where two sources exist (e.g. mud log vs drilling report), record both and flag
  disagreements over 10 m.
- State whether each well point falls **inside the 1205 grid**.

Output:
- `/data/matt/sci-sim-op/geomodel/forge/truth/blind_wells.json`;
- a short `docs/geomodel/FORGE_BLIND_WELLS.md` (≤ 60 lines).

## Phase 2: build the agent's input folder `/site/` (spec §3, §8.2)

- Build `/data/matt/sci-sim-op/geomodel/forge/site_v0A/`: **copies** (not symlinks) of
  every submission with `role_guess=input` and `date_published < 2019-09-01`. Minus the
  model, prior-model and excluded ids in spec §3, and minus files over 2 GB.
- Per-submission layout: `gdr_<id>/` with `ABOUT.txt` (title, date, authors, GDR
  description) and the files. **No manifest, no role labels, no `meta/`.** Leave zips
  as-is: unpacking is the agent's job.
- Add `grid/cells.csv` and `grid/nodes.csv`: the 1205 geometry with **labels, the
  Leapfrog comment header and any property columns removed**.
- **Leak scan (blocking):**
  - grep every text-like file, and the text inside PDFs, zips and xlsx, for the canaries
    `Granitiod`, `GM_8_19_2019`, `1205`, `MP-169`, `native state`, `Native State`, and
    the 1107 file names;
  - also look for documents that are *write-ups of the FORGE earth model itself*
    (Phase 2B/2C model descriptions).
  
  Exclude anything that hits, unless it is clearly incidental, and justify each
  decision in `site_v0A/../site_v0A_LEAKSCAN.md`. No `.git` anywhere.
- Record the final contents: submission ids, file count, size.

## Phase 3: output spec + scorer + baselines (spec §4, §5, §8.3)

1. Freeze the agent-facing output spec as `docs/geomodel/FORGE_v0_OUTPUT_SPEC.md`: exact
   file names, columns, units and coordinate frames. Base it on spec §4, but make it
   unambiguous. The agent receives this file.
2. Put the scorer in a new package, `src/geomodel_bench/` (`truth.py`, `score.py`, a
   CLI), with tests in `tests/geomodel_bench/`. The **axis A and axis B metrics are as in
   spec §5**, and every metric reports the naive baseline next to it. Unit-test it on
   synthetic cases, including a perfect submission, a flipped-label submission, and
   missing files (these must score as missing, never crash, and never count as 0 error).
3. Score these **before any agent runs**, to anchor the scale:
   - **naive:** flat contact at the 58-32 contact depth, linear gradients from 58-32
     only, textbook granite/sediment properties;
   - **expert 2019** (1205 + 1160/1315) on axis B, since it is trivially perfect on A;
   - **expert drift**, 1205 vs 1397/1812 on axis A, if the frame transform is tractable
     within about 1 h (otherwise record why not).

## Phase 4: sandboxed pi + OpenRouter harness (spec §6)

**Harness:** [pi](https://pi.dev) coding agent. **Provider:** OpenRouter via `.env`.
**Model:** `xiaomi/mimo-v2.6-flash`. Read pi's docs to learn how to configure an
OpenRouter provider and model, and pass the key via env, never on a command line that
gets logged.

**Sandbox requirements (verify each one, and log the verification):**
- The agent's tools **cannot reach the internet**: `curl https://gdr.openei.org` and
  `curl https://www.google.com` must fail from inside. The model API **must** work.
  - Suggested: a Docker container on an internal network, with an allowlisting egress
    proxy (only `openrouter.ai`).
  - Alternative: bwrap `--unshare-net` plus a small Python unix-socket CONNECT bridge.
  
  Choose one, and make it one script: `scripts/geomodel/run_pi_agent.sh` (or `.py`).
- `/site` is mounted read-only; `/work` is writable and is the output dir. **Nothing else
  from the host is visible**: not the repo, not `/data/.../raw`, not the home directory.
- Tools inside the sandbox: Python 3 with numpy, scipy, pandas, openpyxl, lasio, dlisio,
  shapely, pyproj, matplotlib, pyvista (best effort), plus `pdftotext` and `unzip`.
- Limits: **3 h wall clock** and **$3 per run**. Save the full pi transcript (JSON/JSONL)
  and the final `/work` for every run under
  `/data/matt/sci-sim-op/geomodel/forge/runs/<run_id>/`.

**Agent prompt:** `docs/geomodel/FORGE_v0_AGENT_PROMPT.md`. It holds the §1 scenario
paragraph from the spec, points to the output spec, and states the tools, time and
offline setup. **It must not hint at the answer:** no contact depths, gradients or
property values.

## Phase 5: contamination probe (spec §6)

Same model, via OpenRouter, **no data and no tools**. Ask it to produce the output-spec
values it can from memory (contact depth near 58-32, T/P/stress gradients, SHmax
azimuth, unit properties). Score the answer with the same scorer on whatever it can be
scored on. Run 3 samples.

## Phase 6: pilot runs

1. **One run of variant A.** Then **read the transcript end to end** before anything
   else. Record:
   - what it looked at;
   - where it spent its turns;
   - where it went wrong;
   - whether it tried to reach the network or leave `/site` (cheating attempts);
   - whether its outputs parse.
2. Fix *harness* bugs only. Do not tune the prompt toward the answer.
3. If the harness is sound: **2 more seeds** (3 total). Variant B only if time and budget
   remain.
4. Score all runs.

## Phase 7: morning report + tidy

`docs/geomodel/sessions/2026-09-30_session2_report.md`: **short and very human-readable**
(≤ 120 lines; Matt reads slowly). It has:
- a TL;DR of 5 lines;
- a results table: naive / probe / each agent seed / expert 2019 on blind wells;
- what the agent actually did and its failure modes, with 2–3 quoted moments;
- spend (the key-usage delta);
- decisions made overnight;
- what is not done and why;
- questions for Matt.

Also:
- update the plan statuses in `docs/geomodel/README.md` and spec §8;
- run `python3 -m pytest tests/ -q` and report the result;
- create `docs/geomodel/sessions/2026-09-30_session2_DONE` containing one line.

## Rules

- **Never print or log the API key.** **Spend cap: $10 total** tonight. Stop launching
  runs at $8.
- **Do not commit, push, or rewrite git history.** Don't touch `.evolve/`. Don't delete
  downloaded data.
- Prefer measuring to asserting. A score you did not recompute from files is not a score.
- The dangerous bugs are the ones that produce a plausible number. Sanity-check every
  metric against the naive baseline and the expert model.
- If a phase is blocked, write down exactly why, skip to the next phase that can run, and
  come back.

## Definition of Done

- [ ] `blind_wells.json` + `FORGE_BLIND_WELLS.md`
- [ ] `site_v0A/`, with a passing, documented leak scan
- [ ] output spec, scorer + tests passing, baselines scored
- [ ] sandbox verified (no internet from tools, API works, host invisible)
- [ ] probe scored; ≥ 1 pilot run read end to end and scored (3 if the harness is sound)
- [ ] morning report + README/spec status updated + DONE file
