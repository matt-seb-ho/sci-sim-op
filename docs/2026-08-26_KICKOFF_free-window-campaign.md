# KICKOFF — free-window self-evolution campaign

**Paste this whole file as the first message of a fresh
`claude --dangerously-skip-permissions` session, run from `~/projects/sci-sim-op`.**

---

You are picking up the SIGA follow-up on serv6. Read these three files before you
touch anything — they are short and they will stop you repeating work:

1. `~/projects/sci-sim-op/docs/2026-08-26_followup-goals.md` — the goals and the ordering.
2. `~/projects/siga/docs/2026-08-19_method-adoption-plan.md` — the technical basis. §2
   (which methods and why), §3 (the v2 design), §4 (evaluation protocol), §7 (kill
   criteria). Long; skim §0 and §8 first.
3. `~/projects/siga/docs/2026-08-26_migration-reconciliation.md` — what is canonical on
   this machine and what was deliberately left out.

## The situation

SIGA's published self-evolution loop never received a reward signal, and the paper's own
held-out table shows the self-evolved cell is within noise of the hand-designed one. We
are rebuilding the loop properly using 2026 methods (Self-Harness, AHE, GEPA, ACE) and
measuring which ingredients actually matter for scientific-simulator configuration,
against our existing GEOS / OpenFOAM / LAMMPS setups.

The work is time-boxed by an external fact: `stealth/ox-alpha` and a roster of ~20 other
strong models are currently served **free**, and self-evolution is inference-heavy. That
window is the reason to run the expensive ablations now. It is also demonstrably closing —
OpenRouter reclassified `tencent/hy3:free` to paid before we even started.

## Ground truth about the providers, measured 2026-08-26

Credentials are in `~/projects/sci-sim-op/.env` (gitignored, mode 600). Do not commit them, do
not echo them into logs, do not put them in a URL. Raw measurements accumulate in
`.evolve/ratelimits.jsonl` and `.evolve/provider_ledger.jsonl`; re-run
`scripts/ratelimit_probe.py` rather than trusting these numbers if a day has passed.

### Free models only — and that is not the constraint it looks like

**Matt's standing constraint: use free models only.** `tencent/hy3` is therefore **out** —
its free window closed on OpenRouter and the Nous `:free` slug bills. Do not call it.
Probing it cost $0.12 total; that is the entire spend on this campaign and it should stay
that way.

The reflex worry is that this caps us, because `stealth/ox-alpha` has **exactly one**
upstream endpoint (`Stealth`) and is capacity-starved:

| concurrency | ok / requests | goodput | note |
|---|---|---|---|
| 4 | 7/12 | 5.2/min | |
| 8 | 18/24 | 10.1/min | ~25% of requests 429 |
| 16 | — | **12.3/min (peak)** | ~738 completions/hr |

And because that one pool is shared, **pointing three provider accounts at ox-alpha adds
nothing** — OpenRouter, Nous and Venice all resolve to `Stealth` and all report
`provider: "Stealth"` in the response. The widely-repeated claim that OpenRouter rate
limits can be dodged through another intermediary is false for this model.

**Focus on ox-alpha anyway.** It is free, strong, 1M-context, and the closing window is
the entire reason this is urgent. Run it continuously at concurrency ~8–16 with patient
backoff, and make the search resumable so throttling costs time rather than work.

**Do not spray across the other free slugs by default.** OpenRouter serves ~20, but most
are low-throughput or too weak to produce an informative result, and a panel of weak
models manufactures noise rather than evidence. **Quality bar for adopting any second
free model: an Artificial Analysis intelligence index at or very near
`deepseek-v4-flash-0420` — the older 0420 release, not 0731.** Check the index before
adopting, and record which models were checked and what was found. Candidates worth
checking first, on context and tool support: `minimax/minimax-m3:free` (1M),
`nvidia/nemotron-3-ultra-550b-a55b:free` (1M), `thinkingmachines/inkling:free` (1M),
`z-ai/glm-5.2:free` (256k). Nous adds `stepfun/step-3.7-flash:free` and
`upstage/solar-pro4:free`.

A model that clears the bar earns a place in the cross-model panel, which the
method-adoption plan makes load-bearing: which inference model you run on partly
determines the measured gain (arXiv:2605.30621), and Self-Harness's first stage is
*model-specific* weakness mining. Capability first, capacity second.

**Hard rule: never call a model whose `usage.cost` comes back non-zero.** Check it on the
first response from any model you add, and drop the model if it bills. That is the entire
budget policy.

### Per-provider notes

- **OpenRouter** — `$10` balance, `usage: 0` at campaign start. `stealth/ox-alpha` free;
  `tencent/hy3:free` **no longer exists** (the endpoint answers *"This model is
  unavailable for free. The paid version is available now"*), so hy3 is out entirely.
  Roughly 20 other free slugs are live — that roster is the capacity story. Do **not**
  pin a single upstream provider on any model; let OpenRouter load-balance.
- **Nous portal** — general-purpose OpenAI-compatible access; **not** hermes-agent-only,
  and no spoofing is needed. But its edge **403s the default Python UA string**
  (`Python-urllib/3.12`) outright. Any other value passes, including no UA header at all.
  Confirmed by controlled test: `Python-urllib/3.12` → 403/403/403, `sci-sim-op/0.1` →
  200/200/429. Account allowance is generous and **not** the binding constraint —
  180 rpm, 7560 rph, 720k tpm, 30.24M tph, exposed on every response as
  `x-ratelimit-*`. Its `tencent/hy3:free` slug serves but **bills** (~$5e-5/call) — do not
  use it. Nous does have genuinely free slugs of its own: `stepfun/step-3.7-flash:free`,
  `upstage/solar-pro4:free`, `poolside/laguna-{s,xs}-2.1:free`.
- **Venice** — credits added 2026-08-26, `accessPermitted: true`, `$1` balance.
  `stealth-ox-alpha` is priced at $0 with a 1000 RPM account limit, but returns
  *"The model is currently overloaded"* under load — same `Stealth` pool, same ceiling.
  Treat it as a third door onto the same room, useful for failover, not for capacity.

**On "hit it as hard as we can":** the intent is to extract maximum experimental value
from the free window, and the topology above means that is a *routing* problem, not a
concurrency problem. Hammering ox-alpha past ~16 concurrent produces 429s and nothing
else. Build for sustained hours — per-route adaptive concurrency, backoff with jitter,
durable resume — and spread volume across the free roster rather than stacking it on one
model.

`python3 scripts/provider_watch.py` probes each pair with a real completion and reads back
`usage.cost`; exit 2 means something stopped being free. It treats 429 as *unknown* rather
than *not free*, so our own saturation does not raise a false alarm. Run it on a cron
(`--watch 900`) for the duration of any long run.

## Gates — in order, and nothing downstream is believable until these pass

**G1. R1: make the reward channel observable, then prove it.**
`repo3/src/runner/docker_cmd.py:195-196` forwards `GEOS_EVOLVE_FEEDBACK_SHAPE` and
`GEOS_EVOLVE_CHECKS` across the container boundary, but `repo3/plugin/hooks/verify_outputs.py`
**reads neither**. Verified by grep on 2026-08-26. So the stop policy is a searchable
component with no consumer.

Make the hook honour both names. Then verify the way `INTEGRATION_REQUIREMENTS` demands:
run one task with `feedback_shape=minimal` and one with `errors_plus_tables` and **diff the
hook's own event log**. If the feedback text is identical, R1 is *not* satisfied no matter
what the config reports. Do not proceed on a config-level check.

This is the exact failure class that produced the reward-free v1. Treat it as blocking.

**G2. Harden the provider layer.**
`src/harness_evolve/proposers/backends.py:OpenRouterBackend` is dependency-free raw HTTP and
is missing three things this campaign needs: no `User-Agent` (so it cannot talk to Nous at
all), no retry/backoff on 429 (so it dies on the first throttle), and it discards the `usage`
block (so we cannot tell when free ends). Add all three, keep it stdlib-only, keep the
existing tests green. A Nous target is the same class with a different base URL and key env.

**G3. Confirm the contamination quarantine holds.**
`plugin_evolving/_quarantine/v4` must stay quarantined — its cheatsheet is a
task→ground-truth lookup table for all 17 val tasks. Reproduce before running anything:
```
python3 scripts/siga_evolve/audit_lineage.py --adapter-dir plugin_evolving/_quarantine/v4 \
  --task-list-from scripts/self_evolving/run_full_evolution.sh
```
The hygiene gate is blocking and runs **before any rollout is spent**, not after.

## Then, the work

4. **De-risk experiment first** (plan item 0): S+X+M vs SE, paired per-task, n=5 on
   `X_eval`. ~2h, needs no new code, and it settles the framing of everything else.
   Prediction on record: the paired CI on `SE − S+X+M` spans zero. Record the outcome
   either way before building on it.
5. **Then the search**, with **compute-matched baselines budgeted in from the start**
   (plan §4.1, arXiv:2607.12227) — not added afterwards. An unmatched win is not a win.
6. **Then the ablations**, which are what the free window is actually for: regression gate
   / evidence richness / Pareto archive / delta updates, individually, across GEOS,
   OpenFOAM and LAMMPS. The deliverable is *which ingredient carries the gain and whether
   that answer is the same on all three simulators* — not a leaderboard number.

## Standing constraints

- **The null result is a first-class outcome** and is pre-registered as a kill criterion
  (plan §7.1). Published evidence predicts a search in this regime returns its seed.
  Report it as a result; do not tune until something looks positive.
- **Do not build a DGM/Hyperagents-style open-ended archive.** Reasoning in plan §8.3.
- **Do not reintroduce retrieval-gated memory.** The `memory_lookup` MCP tool was called
  **zero** times across every test-set run while verified functional. Deliver content
  always-on; import update *mechanisms* only.
- **Do not modify `repo3/src/runner/` or `repo3/src/eval/`** beyond the R1 hook fix —
  everything else is additive and calls them.
- **`docker_cmd.py` rendering is pinned byte-for-byte** by `tests/test_container_spec.py`.
  Re-apply changes on top of the `ContainerSpec` refactor; never revert to the old literal.
- **Containers are enroot, not docker.** `export REPO3_CONTAINER_BACKEND=enroot`; see
  `repo3/docs/ENROOT.md`. The image is already built and verified on this box.
- **~50 files hardcode `/home/matt/sci/repo3`**, a path that exists on no current machine.
  Pre-existing debt. Fix the ones you actually hit; the pattern to copy is
  `constants.py`'s `REPO_ROOT = Path(__file__).resolve().parents[2]`.

## Operating notes

- Log decisions as you go, in `worklogs/`, following the existing convention.
- Prefer measuring over asserting — the reconciliation doc's most useful property is that
  every claim in it was checked, and several "known facts" from the handoffs were stale.
- Another session may still be finishing the migration reconciliation. Do not write into
  `~/migration/mac-snapshot/` or `~/migration/xfer/`.
- Start by running, in `sci-sim-op`:
  ```
  export PATH="$HOME/.local/bin:$PATH"
  uv run python -m pytest tests/ -q      # expect: 523 passed, 2 skipped
  python3 scripts/provider_watch.py      # stdlib-only, runs outside the venv
  ```
  Note `pytest` is **not** installed for the system python — bare `python3 -m pytest`
  fails with `No module named pytest`. Use `uv run`. Verified 2026-08-26.
  If either command disagrees with this document, say so before proceeding.
