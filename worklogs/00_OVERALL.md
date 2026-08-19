# Overall work log — harness-evolve (repo4)

One entry per session. Per-workstream logs are `worklogs/W*_*.md`.

---

## 2026-08-19 — session 1: rebuild decision, scaffold, fan-out

### Context

Subgoal (3) of the SIGA follow-up: pick and adopt a harness-evolution method.
The decision document is `repo3/docs/2026-08-19_method-adoption-plan.md`; the
first implementation pass landed on `repo3` branch `feat/siga-evolve-v2`
(commit 9183110, 42 tests). User then asked for a fresh repo — repo3 has
accumulated a lot of one-off scripts — so the work moves here and repo3's
branch stays as the record of the audit plus the quarantine of a contaminated
artifact.

### Methods adopted (the answer to "which method do we reimplement")

| Method | What we take | Why this task specifically |
|---|---|---|
| **Self-Harness** arXiv:2606.09498 | weakness mining → *minimal* proposal → regression-gated validation | supplies the selection operator v1 had none of; minimality suits a 775-token always-on artifact under a hard efficiency constraint |
| **AHE** arXiv:2604.25850 | component / experience / decision observability | evidence layer is the acute deficiency; its ablation (structure > prose) is the argument for widening the search space past prose |
| **GEPA** arXiv:2507.19457 | Pareto archive, acceptance hook, budget — **as a library** | sample efficiency is the binding constraint; Pareto over per-task scores is right when the whole effect is two tail rescues |
| **ACE** arXiv:2510.04618 | itemized delta updates incl. *delete*, for the memory component only | names the exact pathologies we measured (brevity bias, context collapse); its playbook scale is rejected on efficiency grounds |

Claimed as novel rather than imported: **binding-constraint discovery** (probe an
unseen simulator, infer whether the completeness gate or knowledge injection
binds, allocate search budget accordingly) and **EFC as a search objective**
(dense per-trajectory signal where task score gives one sparse scalar per
expensive rollout).

Rejected: DGM/Hyperagents-style open-ended archive over whole harness programs
(needs cheap plentiful evals; requires unfreezing the base harness); any
retrieval-gated memory module (the local zero-call result on an equivalent MCP
tool is decisive — import update mechanisms, deliver content always-on).

### Decisions this session

- **D1. Fresh repo `~/repo4`, package `harness_evolve`.** Matches the
  repo1→repo2→repo3 generational convention. repo3 is not modified further.
- **D2. Simulator is a plugin (`SimulatorSpec`), not a hardcoding.** Follows
  directly from the interface-dependence finding, and it is what makes
  subgoal (1) — breadth across simulators — an implementation rather than a
  fork.
- **D3. Three runner implementations, one protocol.** Real / cached-replay /
  mock. The mock runner exists so the search loop is testable end-to-end; not
  being testable end-to-end is a large part of why v1's missing reward signal
  went unnoticed.
- **D4. Run-and-score is one call, never two.** v1's scoring step was a separate
  shell invocation that was simply never made.
- **D5. Anchor / probe / held-out slice discipline** baked into the loop rather
  than left to launcher scripts.

### Progress

- [x] repo scaffolded, `pyproject.toml`, package layout
- [x] `types.py` — Score (failures-as-zero explicit), Cost, Rollout, Finding
- [x] three protocols: `SimulatorSpec`, `RolloutRunner`, `Proposer`
- [x] `core/manifest.py`, `core/candidate.py` ported from the repo3 branch
- [x] `docs/ARCHITECTURE.md`
- [ ] workstreams W1–W6 (fanned out below)

### Fan-out

| WS | Scope | Owns |
|---|---|---|
| W1 | archive, acceptance, decision log, search loop | `core/` |
| W2 | GEOS + mock simulators | `simulators/` |
| W3 | evidence corpus, diagnostics, EFC | `evidence/` |
| W4 | hygiene / contamination gate | `hygiene/` |
| W5 | evaluation protocol: baselines, paired stats, reports | `evaluation/` |
| W6 | runners (mock/cached/real) + check plugins | `runners/`, `checks/` |

Disjoint directories by construction, so parallel work cannot collide. Shared
contracts (`types.py`, the three `base.py` files, `core/manifest.py`,
`core/candidate.py`) are frozen for the duration of the fan-out; changes to
them go through this log.
