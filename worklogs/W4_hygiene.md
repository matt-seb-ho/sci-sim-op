# W4 — hygiene / contamination gate

Owns `src/harness_evolve/hygiene/` and `tests/test_hygiene.py`. Nothing else
was touched.

---

## 2026-08-19 — session 1: port, then extend

### Why the predecessor gate failed, restated as requirements

Two incidents, both re-verified by pointing this gate at the real artifacts:

1. **`.xml`-only regex.** `reflect.py:248` and `scripts/memory/hygiene_audit.py:41`
   used the same pattern, so the durable audit gate had the same blind spot as
   the redactor. `tables/time.geos`, `tables/radialStress.geos` and
   `tables/axialStrain.geos` reached `plugin_evolving/v3` across three files.
   The redaction also left directory components behind (`poromechanics/<file>`),
   which still names the physics family and the directory to search.
2. **`_quarantine/v4/memory/cheatsheet.md`** — a task-name → canonical-deck
   table covering all 17 evaluation tasks, wired into a launcher and found only
   by a later audit. Nothing in the filename gate could see content.

So: the leak surface is (a) every extension the *simulator* declares, not one
hardcoded extension; (b) paths, not just basenames; (c) content, not just
names; (d) the *shape* of an answer key, not just the strings in it.

### Module layout

| File | Contents |
|---|---|
| `corpus.py` | `GroundTruthCorpus` + text canonicalization. All expensive indexing (n-gram sets, element sequences, document frequencies, numerics) happens once per run here. |
| `gate.py` | 11 rules, each an independently testable function `(path, text, corpus, cfg) -> list[Finding]`; `GateConfig`; `HygieneReport`. |
| `audit.py` | CLI over an on-disk adapter directory. Exit 1 on a blocking finding, 2 on usage error *or an empty corpus*. |

Findings are `types.Finding` (not a private dataclass), so hygiene output
merges with check/validator output in the same report surface. `source` is the
rule name, `location` is `path:line` where a line is meaningful.
`severity="error"` is the only blocking level, matching the contract in
`types.py`.

`GroundTruthCorpus` builds three ways: from a ground-truth tree, from a
precomputed blocklist JSON (`repo3/misc/memory_artifacts/test_blocklist.json`
shape), or directly from parts. The blocklist path exists because there is no
`/data` volume in this environment and a retro-audit is exactly the situation
where the tree is not mounted — the case in which the v3 leaks went unnoticed
for three versions. When a `SimulatorSpec` is supplied, blocked basenames come
from its `contamination_policy`, so the runtime gate (what is hidden from the
agent) and the hygiene gate (what may not appear in an adapter) cannot drift
apart. That drift is the root cause of incident 1.

### Rules implemented

Ported from `repo3/src/evolve/hygiene.py` (rules 1–6), then extended.

| Rule | Severity | Rationale |
|---|---|---|
| `filename` / `filename_generic` | error | Every leaky extension. A filename that is *not* known ground truth still blocks: the v3 leak was precisely a name absent from the blocklist being checked, so "known GT" is not a safe precondition for blocking. |
| `path_component` | warn / **error** as a path prefix | `poromechanics` in prose is a physics word; `poromechanics/Foo` is a pointer. |
| `task_id` / `task_id_table` | error | ≥2 ids reported as one finding, so the report says what the artifact *is*. |
| `blocklist` | error | Substring match; needs no tokenization, so it fires where the regex cannot. Ties the verdict to the runner's own list. |
| `content_overlap` | warn ≥1, error ≥3 shared 8-grams | The capability the predecessor lacked entirely. |
| `numeric_leak` | warn ≥3, error ≥6 | Value correctness is the residual failure mode (LAMMPS-binding case), so memorised GT values are teaching the answer. Notation-blind: `1e-4` / `1.0E-04` / `1.0d-4` / `$1.0\times10^{-4}$` / `1.0×10⁻⁴` all canonicalize alike. Trivial values suppressed. |
| `near_miss_filename` | **error** exact stem, warn fuzzy | New. v3 shipped `PoroElastic_Mandel_*` and `PoroElastic_Terzaghi_*` — no extension, so no extension-anchored rule can see them. Variant-suffix stripping collapses `_base`/`_benchmark`/`_smoke` families to one key; `difflib` ratio ≥0.86 catches the rest, prefiltered on a shared 5-char prefix. |
| `structural_fingerprint` | warn ≥2, error ≥4 | New. An adapter can hand over a deck's element ordering while sharing no n-gram with it. Fingerprints are built only from elements *not* common to most decks, so the schema-mandated top-level ordering (which every deck shares) does not count. |
| `rare_token_overlap` | warn ≥4, error ≥8 rare tokens | New. IDF over the GT decks. A paraphrased leak reorders the same rare identifiers into prose and slips under any contiguity threshold; raw n-gram counting weights `name` and `kgdEdgeBased` equally. |
| `lookup_table` | error (task-shaped key → deck file), warn (→ other path) | New. Detects the *shape* of the v4 artifact with no dependence on the task names, so a renamed task set, a held-out split the corpus was not built with, or a bullet-list phrasing of the same mapping is still caught. |
| `lookup_language` | info, warn in company | New. "skip the search", "already verified", "canonical XML". Non-blocking by design: telling the agent not to waste greps is legitimate under the efficiency constraint. It earns its place by making a lookup-table finding immediately legible.

### Calibration, and the false-positive budget

The governing constraint is that a gate people route around is worse than no
gate. Concretely:

- Rules that fire on ordinary domain prose are **non-blocking**. A bare
  `poromechanics` mention, a near-miss stem, a source-navigation table, and
  shortcut language are all warn/info.
- Two rules block on ambiguous evidence, deliberately: any simulator-artifact
  filename, and a single task id. Both are things a *useful* adapter never
  needs — interface guidance does not name decks or tasks — and both are the
  known-leak shapes.
- `near_miss_filename` has a special case: a single-word stem (`triaxialdriver`)
  is ambiguous with the solver class it is named after, so it blocks only when
  written as a path or a glob, and downgrades when the artifact also uses it as
  an element (`<TriaxialDriver>`). A compound stem (`poroelastic_terzaghi`) has
  no innocent reading and always blocks.
- `_cap()` truncates a rule's output per file, keeping blocking findings in
  preference to warnings and inheriting the worst dropped severity. Truncation
  must never turn a blocking report into a passing one.
- `GateConfig.severity_overrides` exists so an operator retunes a rule instead
  of deleting the gate call. Thresholds are config fields, not constants,
  because the right value depends on how much the corpus actually carries — a
  blocklist-built corpus has no deck text, so the content rules are inert and
  the name rules carry the whole load.

Measured against the real artifacts (corpus from the repo3 blocklist, so
content/numeric/structural/rare-token rules are all inert):

- **v3**: 11 blocking, 16 warnings. All three `.geos` names across all three
  files; `poromechanics/` as a path prefix; `PoroElastic_{Mandel,Terzaghi}_*`
  stems.
- **v4**: 33 blocking, 28 warnings. `task_id_table` (17 ids), `lookup_table`
  (header), 14 filename hits, 9 blocklist hits. The constitutive-class →
  header-path table warns rather than blocks, which is the intended split: it
  is a search shortcut, not an answer key.
- Two hand-written legitimate artifacts (a coupling/completeness cheatsheet and
  an interface primer, both using real domain vocabulary and angle-bracket
  element names) produce **zero findings at any severity** against a corpus with
  decks, numerics, stems and task ids all populated.

### Rules considered and rejected

- **Whole-file hashing / exact-duplicate detection.** Strictly weaker than
  `content_overlap`; a copied deck is already a maximal n-gram match.
- **Embedding or semantic similarity.** Best tool for paraphrase, but the
  package is stdlib-only by policy and this must run before every rollout.
  `rare_token_overlap` is the cheap approximation that keeps most of the value.
- **Homoglyph / zero-width obfuscation detection.** Partly covered by NFKC
  normalization. Full adversarial resistance is not the threat model: the leak
  path is a proposer mining trajectories, not an adversary evading a filter.
  If the proposer ever becomes adversarial, the gate is the wrong layer.
- **Separate RST/tutorial-path rule.** The tutorial an example was mined from
  is a real leak surface, but it folds into `blocklist` + `path_component`
  once the corpus ingests `union_rst_relpaths`, which it does.
- **Blocking on `lookup_language` alone.** Rejected: it would punish exactly
  the efficiency guidance the adapter is supposed to contain, and the
  over-specification gate already covers verbosity.
- **Per-task corpora (gate a candidate only against the tasks it will run).**
  Rejected: the adapter is always-on across every task, so any task's ground
  truth is contamination for the run as a whole.
- **Auto-redaction (the predecessor's `re.sub` to `<file>`).** Rejected
  outright. Redaction is what produced v3: it made a leaking artifact *look*
  clean, hid the signal from review, and left the directory components in
  place. This gate rejects; it never rewrites.

### What could not be checked without the real ground-truth tree

No `/data` volume here, so:

- `content_overlap`, `numeric_leak`, `structural_fingerprint` and
  `rare_token_overlap` are exercised only against a synthetic three-deck corpus
  in the tests. Their **thresholds are unvalidated against real GEOS decks** —
  in particular, real decks share far more boilerplate with each other than the
  fixtures do, so `rare_token_df_fraction` (currently 0.1) and `ngram_error`
  (3) should be re-checked on the first run with the tree mounted, by gating a
  known-clean adapter and looking at the warning volume.
- `COMMON_ELEMENT_FRACTION = 0.6` was chosen so that a full GEOS deck's
  top-level ordering counts as boilerplate. With 50+ decks this is probably
  right; with a handful of decks the floor of 2 decks does the work instead.
- Variant expansion is only as good as the simulator's `contamination_policy`.
  The `VARIANT_SUFFIXES` list here mirrors the runner's, but the authoritative
  one belongs to W2's GEOS spec; if they disagree, the spec wins and this list
  should be deleted in favour of asking the spec.

### Open questions / notes for the integrator

- **Where this hooks in.** `check_candidate(candidate, corpus)` is the free-gate
  call, next to manifest validation and budgets, before any rollout. Build the
  corpus once per run and pass it down. Measured cost: ~0.15 s to index 50
  decks (~385 KB), ~0.13 s per candidate over 6 files — i.e. free relative to a
  ~25-minute task-run.
- **A gate run against an empty corpus proves nothing.** The CLI refuses to
  report a pass in that case (exit 2). The library exposes
  `GroundTruthCorpus.is_empty`; the search loop should refuse to start rather
  than silently gate against nothing.
- **`ContaminationPolicy.blocked_paths` is untyped as to what it holds** —
  this treats entries as source-relative paths (basename + directory parts both
  ingested). If W2 intends something else, say so and I will adjust the reader.
- **Possibly too aggressive**: `task_id_severity="error"` on a *single* task
  id, and `unknown_filename_severity="error"`. Both are defensible on the
  evidence but they are the two rules most likely to annoy someone writing a
  legitimate adapter that mentions one example by name. Both are one config
  field away from `warn`, and the override is the intended response.
- **Possibly too lax**: `path_component` only warns on a bare directory
  mention, so an adapter that lists every ground-truth directory by name
  without a slash blocks on nothing. Considered escalating on ≥3 distinct
  components in one file; not implemented because the fixtures cannot tell me
  whether that fires on a legitimate "where things live" primer. Revisit with
  the real tree.
- The `.reflection_meta.json`-style metadata files *are* audited (`.json` is in
  the default extension set) but scaffolding directories are not, since they
  are resolved from the live plugin and are not candidate-owned.
- **A second redactor exists.** `proposers/demonstrations.py:sanitize()` carries
  its own artifact-extension list, its own task-id check, and *redacts*
  (`<reference artifact>`) rather than rejecting. Two independent lists is the
  precise mechanism behind incident 1, and redaction is what produced v3: it
  makes a leaking artifact look clean while leaving directory components,
  extension-less stems and content untouched, and it hides the signal from
  review. Recommend it take its leak surface from `GroundTruthCorpus`
  (`leak_pattern()`, `task_ids`, `filename_stems`) and run `check_texts` over
  the sanitized result as a post-condition, so a demonstration that still
  carries a leak is dropped rather than trimmed. Out of my scope to change.
