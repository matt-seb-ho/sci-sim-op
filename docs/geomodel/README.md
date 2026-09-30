# Geological-model task (follow-up item 1: depth)

**Started:** 2026-09-23 · **Owner:** Matt Ho · **Domain expert:** Chris Sherman (LLNL), every two weeks

**The goal in one line:** extend the agent from *"spec → GEOS deck"* (SIGA) back to
*"site data → geological model → GEOS deck"*, because building the geological model is
80–90% of a geoscientist's time.

## Read in this order

| # | doc | what it answers |
|---|---|---|
| 1 | [`MEETING_2026-09-11_sherman_notes.md`](MEETING_2026-09-11_sherman_notes.md) | what Sherman told us and what follows from it |
| 2 | [`WHAT_IS_A_GEOLOGICAL_MODEL.md`](WHAT_IS_A_GEOLOGICAL_MODEL.md) | what the artifact is, how people build it, how it is judged |
| 3 | [`FORGE_DATA_INVENTORY.md`](FORGE_DATA_INVENTORY.md) | what public Utah FORGE data exists, what we downloaded, and which file *is* the model |
| 4 | [`TASK_FORGE_v0.md`](TASK_FORGE_v0.md) | the first task: inputs, outputs, scoring |
| — | [`papers/`](papers/) | one-page summaries of the five papers Sherman sent |
| — | [`TERMINOLOGY.md`](TERMINOLOGY.md) | what the sources call the models, and the questions to ask Sherman |
| — | [`FORGE_v0_OUTPUT_SPEC.md`](FORGE_v0_OUTPUT_SPEC.md), [`FORGE_v0_AGENT_PROMPT.md`](FORGE_v0_AGENT_PROMPT.md), [`FORGE_BLIND_WELLS.md`](FORGE_BLIND_WELLS.md) | what the agent must write, what it is told, and the blind-well truth |
| — | [`sessions/`](sessions/) | per-session reports, handoffs and briefs (date-stamped) |

## Plan

| step | what | status |
|---|---|---|
| 1 | Download the five papers Sherman linked | ✅ done: all open-access copies on OSTI |
| 2 | Summarize each one in about a page | ✅ [`papers/`](papers/) |
| 3 | Report: what a geological model is, how it's built, how it's evaluated | ✅ [`WHAT_IS_A_GEOLOGICAL_MODEL.md`](WHAT_IS_A_GEOLOGICAL_MODEL.md) |
| 4 | Enumerate and download the public Utah FORGE data | ✅ 392 submissions catalogued; 1,036 files (117 GB) downloaded; 53 large files + 5 S3 links (~148 TB, mostly raw DAS) deferred |
| 5 | Partition it into **agent inputs**, **the model to produce**, and **held-out observations** | ✅ draft: time cut at 2019-09 ([`TASK_FORGE_v0.md`](TASK_FORGE_v0.md) §3) |
| 6 | Write the starter task for FORGE only | ✅ draft |
| 6b | Extract the blind-well truth, build `/site/`, write the scorer, score the baselines, run a pilot agent | ✅ session 2 (2026-09-30): see [`sessions/2026-09-30_session2_report.md`](sessions/2026-09-30_session2_report.md) |
| 7 | Take the partition and scoring to Sherman for correction | next meeting |
| later | Gulf Coast site (easy) and San Emidio (hard), for a 3-site difficulty ladder | — |

## The findings so far, in five lines

1. The **model GEOS actually runs on is thin**: FORGE ≈ uniform granite + stress, pressure and temperature gradients + fracture planes. It is much simpler than the site's geologic model.
2. The **FORGE expert model is public** as versioned exports (2018 surfaces → 2019 block model → 2022 → 2025), but there is no native Leapfrog project.
3. **Experts judge models by matching observations**, but many models fit the same data, and the experts' own models fit only partly. We need several scoring axes.
4. A **time cut** gives a clean partition. Wells drilled after the 2019 model make **blind-well tests** that need no GEOS runs.
5. San Emidio's GEOS inputs and 2022 model are **not public**. That site needs Sherman's help.

## Where things live

| what | where |
|---|---|
| papers (PDF + text) | `/data/matt/sci-sim-op/geomodel/papers/` |
| FORGE data and manifest | `/data/matt/sci-sim-op/geomodel/forge/` (`manifest.json`, `raw/<gdr_id>/`) |
| truth, `/site`, baselines, runs | `/data/matt/sci-sim-op/geomodel/forge/{truth,site_v0A,baselines,scores,runs}/` |
| scorer | [`src/geomodel_bench/`](../../src/geomodel_bench/) (`python -m geomodel_bench score DIR`) |
| sandbox runner | [`scripts/geomodel/run_pi_agent.sh`](../../scripts/geomodel/run_pi_agent.sh) (+ `verify_sandbox.sh`) |
| downloader | [`scripts/geomodel/forge_download.py`](../../scripts/geomodel/forge_download.py) |

Data is kept outside git because it is large. The manifest can rebuild it.
