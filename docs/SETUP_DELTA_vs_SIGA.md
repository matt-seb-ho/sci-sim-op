# Setup delta — this pipeline vs the SIGA main experiments

**Measured 2026-09-09** by inspecting a real rollout workspace from each, not from
documentation. Reference run: `siga/runs/t1_cc_deepseek/TutorialSneddon` (2026-04-16)
against `.evolve/p0_screen/.../AdvancedExampleCasedContactThermoElasticWellbore` (today).

**Why this document exists:** on **byte-identical task specifications** (`instructions.txt`,
6998 B, literally the same file), like-for-like using each harness's own counters:

| | SIGA `t1_cc_deepseek` (n=36) | here (n=80) | ratio |
|---|---|---|---|
| **tool calls / rollout** | **25.1** (median 28, max 55) | **59.7** (median 56, max 111) | **2.4×** |
| **wall-clock / rollout** | **521 s** (max 900 = its cap) | **1453 s** (max 1792) | **2.8×** |

The gap is not the model. It is four differences in everything around it, and three of them
push the same way.

> Earlier drafts of this comparison quoted 31 vs 103–162 "turns". That compared SIGA's
> `cc_result.json:num_turns` against a count of transcript records carrying a `usage`
> block — **two different quantities**. The table above uses `tool_count` and
> `total_tool_calls`, which both harnesses emit and which do measure the same thing. The
> real gap is 2.4×, not 3–5×.

---

## 1. The four differences that matter

| # | axis | SIGA main | here | direction |
|---|---|---|---|---|
| **D1** | **Primer in the system prompt** | **38,916 B** | **270 B** | 144× smaller |
| **D2** | **Searchable GEOS corpus** | **231 files / 872 KB** | **4,462 files / 1.2 GB** | 19× more files |
| **D3** | **Stop hook** | **absent** (no hook-event file exists in any t1_cc rollout) | **present**, 5 checks | added |
| **D4** | GEOS location | `./GEOS/` inside the writable workspace | `/geos_lib` read-only mount | outside cwd |

D1 and D2 compound: **we removed the map and enlarged the territory.** The agent must
discover by search what SIGA's agent was told, and each search costs more because the tree
is 19× larger. That is a sufficient explanation for a 3× turn count without invoking the
model at all.

### D1 — the primer

SIGA's 39,947 B system prompt is 1,031 B of base instruction plus a **38,916 B GEOS
Primer**: table of contents, core characteristics, typical workflow, solver catalogue, mesh
support, numerical methods, quick start. It names the RAG tools (16 mentions) and points at
the inputFiles tree directly.

Ours is `GEOS_PRIMER_absolute_min.md` — 270 B, five lines, byte-identical to SIGA's
**ablation** primer. The seed's whole adapter is ~1,018 tokens (primer 75, cheatsheet 823,
constraints 120) under a manifest cap of 400 tokens for the primer.

> **This is the finding with the largest consequence.** We have been running the search
> seeded from **SIGA's minimal-primer ablation condition, not SIGA's shipped adapter**, and
> inside a token cap ~40× smaller than the artifact SIGA actually published.
>
> The cap is deliberate — v1's pathology was 12× monotone growth of an always-on artifact,
> and ACE-style budgeting is one of the four adopted ingredients. But RLMOpt (2608.10471)
> reports that **gains are set by seed headroom**, and a 400-token ceiling may simply leave
> no room for the search to find anything. That is a testable confound sitting underneath
> every null we have reported, and it should be tested before the null is believed.

### D2 — the corpus

| | SIGA workspace `GEOS/` | our `/geos_lib` |
|---|---|---|
| total files | **231** | **4,462** |
| `inputFiles/` | 158 | 1,310 |
| `src/` | 49 | 2,331 |
| `.xml` | 112 | 789 |
| `.rst` / `.md` | 13 | 196 |
| C++ (`.cpp`/`.hpp`) | ~0 | **1,539** |
| size | 872 KB | 435 MB |

SIGA handed the agent a **curated tree**: example decks plus a handful of source files.
We hand it a near-complete GEOS checkout including 1,539 C++ sources it can spend turns
reading. Both are "filtered" in the contamination sense — ground-truth decks are removed
from both — but *filtered* and *curated* are different operations and only one of them
bounds search cost.

### D3 — the stop hook and its checks

SIGA's `t1_cc_*` arm ran with `stop_hook_enabled: False`; no `.verify_hook_events.jsonl`
exists in any of its 36 rollouts. Ours runs the hook with **five** checks:

```
checks = ["parse", "geosx_validate", "required_sections", "constraints", "cross_section_refs"]
```

`parse` and `geosx_validate` are long-standing; `required_sections`, `constraints` and
`cross_section_refs` were vendored on 2026-09-02 (decision D2 in that worklog) and have
never been priced. Each is another way the Stop hook can block turn-end and send the agent
round again. Measured on 6 rollouts the hook blocked only twice, so this is **not** the
dominant term — but it is additive and it was added without measurement.

## 2. What is the same

Worth stating, because it narrows the search:

- **Task specification: byte-identical.** Same `instructions.txt`, 6998 B, literally the
  same file on disk. Ruled out.
- **Driver: identical.** Both run `siga/scripts/run_experiment.py`.
- **RAG: present in both.** SIGA's primer names `search_navigator` / `search_schema` /
  `search_technical`; ours mounts the same `geos-rag` MCP server against the same vector DB.
- **xmllint MCP: present in both** (SIGA's primer mentions it).
- **Disallowed tools: same** — `Skill`, `AskUserQuestion`, `Task`, `Agent`, `TaskCreate`.
- **Ground truth: mounted in neither.** Contamination hygiene holds in both.

## 3. Where everything lives

| | SIGA | here |
|---|---|---|
| workspace root | `<run>/<task>/` (host) → container cwd | `/workspace` |
| task prompt | `<task>/instructions.txt`, mounted | passed as argv; `data/eval/experiments/<task>/instructions.txt` |
| deck output | `inputs/` | `/workspace/inputs/` |
| solver output | `outputs/` | `/workspace/outputs/` |
| GEOS source | `./GEOS/` (in cwd, writable, 231 files) | `/geos_lib` (ro mount, 4,462 files) |
| GEOS docs | `GEOS/src/docs`, `.rst` ×13 | `/geos_lib/geos/src/docs`, `.rst` ×196 |
| example decks | `GEOS/inputFiles` ×158 | `/geos_lib/geos/inputFiles` ×1,310 |
| geosx binary | *not mounted* (added 2026-07-27) | `/opt/geosx-install/bin/geosx`, **validation-gated wrapper** |
| adapter/plugin | baked into the system prompt | `/plugins/repo3` (ro) |
| vector DB | `/data/shared/.../vector_db` | same |
| system prompt | `.cc_system_prompt.md`, 39,947 B | `PRIMER.md`, 270 B + base |
| hook | none | `Stop` → `/plugins/repo3/hooks/verify_outputs.py` |

## 4. Getting the turn count back

Ordered by expected effect. **These are confounds, not just costs**: every one of them
changes what the agent must do, so a comparison against SIGA's numbers is not currently
like-for-like.

| lever | change | expect |
|---|---|---|
| **L1** | Seed from a **SIGA-scale primer** and raise the manifest cap | largest. Restores the map; also tests the seed-headroom confound |
| **L2** | **Curate `/geos_lib`** to the SIGA-shaped 231-file tree (inputFiles + docs, drop C++) | large. Shrinks the territory |
| **L3** | Price the three checks vendored on 2026-09-02; drop any that do not earn their turns | small but unmeasured |
| **L4** | Turn cap | **not yet effective — see §5** |

**Recommended probe (~$1.6, 12 rollouts):** a 2×2 on L1 × L2 over three tasks at one seed.
It attributes the gap and it doubles as the seed-headroom test, which is the more important
of the two questions.

## 5. Resolved: the turn cap is fine; the metric was wrong

`--max-turns 100` is passed and reaches the CLI. The alarming "mean 162 turns, max 801"
came from `measure_rollouts.py`, which counts every transcript record carrying a `usage`
block — assistant messages, tool results and sub-steps alike. That is **not** the CLI's
notion of a turn and **not** what SIGA's `num_turns` records.

On the harness's own counter the picture is orderly: **59.7 tool calls, max 111**, against
SIGA's 25.1/55. Wall-clock also improved from 1888 s to **1453 s** across the scope note,
the validation gate and the cap together.

**Rule: quote `total_tool_calls` / `tool_count` and `elapsed_seconds`, never the
transcript-derived turn count.** `measure_rollouts.py`'s `turns` field is useful for cost
attribution and misleading for anything else; it should be renamed.
