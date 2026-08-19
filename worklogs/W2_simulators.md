# W2 — simulators

Owner scope: `src/harness_evolve/simulators/`, `tests/test_simulators*.py`.
Nothing outside those paths was touched. `types.py`, `simulators/base.py`,
`core/` and every other workstream's directory are unmodified.

Delivered: `mock.py`, `geos.py`, `openfoam.py`, `lammps.py`, `__init__.py`
(registration), `tests/test_simulators.py` (50 tests),
`tests/test_simulators_geos.py` (35 tests). 83 pass, 2 skip (they need a real
geosx / lmp binary).

---

## Read pass

`docs/ARCHITECTURE.md`, `types.py`, `simulators/base.py`,
`repo3/src/eval/judge_geos.py`, `repo3/docs/GEOSX_VALIDATE.md`,
`repo3/src/runner/contamination.py`, `repo3/scripts/bottleneck/extract.py`.

---

## Decisions

**D-W2-1. TreeSim is vendored, and parity is pinned by test.**
repo3 is not a dependency of this repo, and a metric that changes underneath a
Pareto archive of already-scored candidates makes every round-over-round
comparison meaningless. The recursion, the greedy bipartite matching, its
tie-break, and the constants (α=0.3, β=0.1, rtol=1e-6) are behaviourally
identical. Verified two ways:

- *During development*: 400 random tree pairs scored by both implementations —
  headline score, per-section scores, and the serialized detail dict all
  identical, zero mismatches.
- *In the test suite*: two hand-built cases pinned to exact numbers
  (`treesim == 0.5842` / `0.7492` with their section breakdowns), plus a
  120-pair randomized differential test against `repo3/src/eval/judge_geos.py`
  that **skips** when repo3 is not present, so the suite still runs anywhere.

**D-W2-2. The legacy dimension scores are not ported.**
`score_structural_completeness` / `score_element_type_match` /
`score_attribute_accuracy` / `score_tag_coverage` and their `WEIGHTS` were
already labelled "retained for diagnostic backward compat" in repo3, nothing
downstream consumed them, and the weight vector no longer corresponds to any
headline metric. Same for `score_ordering` (Kendall tau over `PeriodicEvent`
order): computed in repo3, reported, never used in the headline. If the
evidence layer turns out to want ordering, it is ~40 lines to restore.

**D-W2-3. `match_trees` *is* ported, for one reason: attribute-level evidence.**
TreeSim returns scores, not "which attribute was wrong". `bad_attribute_value`
is a named category in `types.FailureCategory`, so `diagnose()` has to be able
to say `logLevel: GT='1' GEN='2'`. Those strings land in `Diagnosis.notes`
(capped at 20) since `Diagnosis` has no attribute-mismatch field.

**D-W2-4. `worst_subtrees` operates on the `TreeSimDetail` dataclass, not on the
depth-3-truncated dict.** repo3's `extract.py` ran it over the output of
`_detail_to_dict(detail, max_depth=3)`, so anything deeper than three levels was
invisible to the drill-down. Ranking is unchanged (`impact = (1-score) *
(n_gt_children+1)`, leaves excluded); it just sees the whole tree now.

**D-W2-5. `.geos` is in `leaky_extensions` and in the variant-expansion glob.**
The base class comment says the v1 gate hardcoded `.xml`. The same bug is in
`repo3/src/runner/contamination.py`: `_expand_blocked_xml_with_variants` and
`_collect_gt_xml_basenames` both glob `*.xml` only, so a `.geos` dependency file
of a blocked deck stayed readable. `expand_with_variants` here takes the
extension list from `leaky_extensions`, and `parse()` records `.geos` files in
`Artifact.files` — a hygiene check cannot flag a file it cannot see.

**D-W2-6. The mock's generative model is documented arithmetic, not a black box.**
`mention` (fraction of the task's required sections named in the adapter text)
is the *only* channel by which adapter content acts. It drives two things:
`zero_p` falls from `zero_rate` to `zero_rate_floor`, and `quality` rises from
`base_quality`; token overage subtracts from `quality` and adds to `Cost`.
That mirrors the one effect the real system claims — adapters buy reliability,
not quality — and it makes a known optimum constructible: with
`help_strength=1.0, noise=0.0, zero_rate_floor=0.0`, an adapter naming every
required section scores exactly 1.0 on every seed and an empty one does not.
Both are asserted.

`sqrt(quality)` is used for section inclusion and per-key correctness because
they are independent draws; without it E[score] is quadratic in `quality` and
every knob reads twice as strong as its name suggests.

**D-W2-7. Mock rollouts score through `score()`, never through the internal
quality draw.** So the failures-as-zero path (`empty_workspace` /
`parse_error`) is on the hot path of every mock rollout rather than being a
branch only tests reach. This is the specific thing v1 got wrong.

**D-W2-8. Determinism is `blake2b`, never `hash()`.** `hash()` is salted per
process, so anything keyed on it gives a different search problem every run and
makes a cached runner incoherent. There is a test that runs the mock in two
subprocesses with different `PYTHONHASHSEED` and compares.

**D-W2-9. The simulators package is a leaf.** It imports `types` and its own
`base` and nothing else from the project — in particular not `core`. So
`MockSimulator.simulate` takes `candidate_id: str` and
`candidate_files: str | Mapping[str, str] | Sequence[str]` (pass
`Candidate.files` directly) rather than a `Candidate`. Token estimation is a
`MockConfig` field (`chars_per_token = 3.6`, same value `core.candidate` uses)
rather than an import, so a future `core` → `simulators` import cannot close a
cycle.

**D-W2-10. GEOS validator output is returned verbatim, capped at 20 000 chars.**
Per `GEOSX_VALIDATE.md` the unknown-attribute error carries the *complete table
of valid attributes* for the offending element and the unknown-tag error carries
the full list of ~50 legal solver types; that text is the highest-value feedback
this harness produces and summarizing it is what turns a live validator into a
static gate. The cap exists only so a runaway message cannot be pasted
wholesale into an agent's context; it appends an explicit truncation marker.
Tested offline against a stub script that prints a real abridged GEOS error.

**D-W2-11. Missing binaries produce `info` findings, never `error`.**
`Finding` docs say `error` is the only blocking level and blocking on something
the agent cannot act on is worse than not checking. So "geosx unavailable" is
`info` and shows up in `preflight()` instead.

**D-W2-12. OpenFOAM contamination blocks *paths*, not basenames.**
The base-class default (block GT basenames) is correct for GEOS and actively
destructive for OpenFOAM: every tutorial case in the tree has a `controlDict`,
a `fvSchemes` and a `0/U`, so a basename block hides the entire corpus.

**D-W2-13. LAMMPS `score()` and `diagnose()` raise `NotImplementedError`.**
See "what I deliberately did not do".

---

## What I found in repo3 that looks wrong or surprising

1. **`scripts/bottleneck/extract.py::gt_size` is dead and self-contradictory.**
   It computes `n = 1 + n_gt_children`, then loops adding `gt_size(c) - 1` with
   a comment about not double-counting, then a second comment says "simpler
   approach: count only this node + recursive children listed" and the return
   ignores the distinction. Nothing calls it — `worst_subtrees` uses
   `n_gt_children + 1` directly. Not ported.

2. **`contamination.py` variant expansion is `.xml`-only** (see D-W2-5). This is
   the same class of bug the base-class docstring already calls out for the leak
   gate, in a second place.

3. **`MIN_STEM_LENGTH = 10` is an unexplained magic number.** repo3 drops any
   normalized stem shorter than 10 characters to avoid generic collisions.
   Ported for parity and labelled as a heuristic, but it silently disables
   variant blocking for any genuinely short example name. Worth measuring
   against the real task list before trusting it.

4. **`_bipartite_match` ties break toward higher indices.** `scores.sort(reverse=True)`
   on `(sim, i, j)` tuples means equal-similarity candidates are resolved by
   preferring later elements. Arbitrary, but load-bearing for reproducibility, so
   preserved exactly.

5. **`evaluate_geos` blends an LLM judge into the headline at 0.6/0.4** when
   enabled. Not ported: the headline here is TreeSim, full stop, and a blended
   score would make `Score.value` mean two different things depending on a flag.

6. **repo3 scales TreeSim ×10 "for backward compat with downstream consumers".**
   Dropped. `Score.value` is [0,1] and failures-as-zero only reads cleanly on
   that scale.

7. `GEOSX_VALIDATE.md` records that the Sphinx docs' `--validate-only` flag does
   not exist and crashes; `--validate-input` is the real one. Encoded in the
   code, and the doc's residual gap (name references GEOS resolves lazily past
   the load phase, e.g. `discretization=`) is repeated in the module docstring
   so nobody reads a clean validation as a correctness guarantee.

---

## What I deliberately did NOT do

- **No LAMMPS scoring or diagnosis.** Both raise `NotImplementedError` with a
  message naming what would be needed. The binding constraint on LAMMPS is
  parameter *values*, and every cheap proxy measures something else while
  looking like a score: directive coverage sits at ~1.0 for correct and
  incorrect scripts alike (there is a test asserting exactly that), and text
  similarity to the reference rewards transcription, which would turn the
  benchmark into a retrieval test. An honest implementation needs a behavioural
  comparison of thermo output against a reference `lmp` run, or a per-task
  rubric naming which parameters matter. **Consequence the integrator must
  know: the search loop cannot currently run on LAMMPS.** Everything structural
  — parse, required commands, the atom-definition alternatives rule, `validate`,
  the leak surface — does work.
- **No OpenFOAM `validate`.** It raises, with the three commands it would need
  named (`foamDictionary` per dictionary, `blockMesh -dry-run`/`checkMesh` for
  the mesh, a solver-specific field/patch consistency check) and why they are
  not available here.
- **No OpenFOAM dictionary-content scoring.** `score()` is file coverage only,
  explicitly labelled `"scoring": "file_coverage_only"` in `Score.detail`, and
  there is a test asserting that a case with every path present but nonsense
  contents scores 1.0 — so the limitation is pinned, not just documented.
- **No RST blocking in `contamination_policy`.** repo3's
  `_load_example_rst_mappings` reads `example_pairs.jsonl` off `/data` to block
  the tutorial page a task was mined from. It is real and it matters, but the
  file is not available here, and "which corpus documents are off limits" reads
  more like W4's hygiene corpus than a simulator property. The logic is ~25
  lines in `repo3/src/runner/contamination.py` if W4 wants it; `ContaminationPolicy`
  already has `blocked_paths` for it.
- **No filtered-tree materialization** (`create_filtered_geos_copy`). That is
  enforcement, i.e. W4/W6; `contamination_policy` only states the policy.
- **`load_and_resolve_dir` still discovers entry points from `*.xml` only.**
  `.geos` files are resolved when a deck `<Included>`s them (there is a test),
  but a workspace containing *only* `.geos` files scores as empty. Changed
  behaviour here would break TreeSim parity, so it stayed; flagged as a known
  edge.
- **No caching of parsed decks.** `score()` and `diagnose()` each re-parse. Fine
  at ~17 tasks; revisit if the evidence layer starts calling `diagnose` in a
  loop.

---

## Open questions for the integrator

1. **`MockSimulator.simulate()` is the contract W6's mock runner needs** —
   `simulate(candidate_id, candidate_files, task, seed, workspace,
   ground_truth_root=None) -> MockOutcome`, where `MockOutcome` carries
   `score`, `cost`, `workspace`, `zeroed`, `quality`, `zero_probability`,
   `mention`. Also `task_for(task_id)` and `write_ground_truth(root, task_id)`.
   If W6 wants a different shape, say so and I will change it here rather than
   have the runner reach into internals.
2. **The mock `Cost` model is invented** (`base_tool_calls=30`, inflated by
   token overage). It exists so the efficiency gate is trippable in an offline
   search. If W6 has its own cost model, drop mine — nothing depends on it.
3. **`preflight()` for `openfoam` and `lammps` is never empty**, because
   `validate`/`score` genuinely are not implemented. Any caller written as
   `if not sim.preflight(): run()` will therefore always degrade for those two.
   That is the intended signal, but it means `preflight` is doing double duty as
   both "environment missing" and "capability missing". If the core loop wants
   to distinguish them, that is a `base.py` change and belongs to whoever owns
   it.
4. **LAMMPS `validate` uses `lmp -in <script> -log none -skiprun`.** The flag
   and its semantics come from the LAMMPS command-line documentation, **not from
   an observed run in this environment** — there is no `lmp` here. It is
   guarded by `preflight()` and skipped in tests unless `LAMMPS_EXECUTABLE` is
   set. Confirm against a real binary before trusting a green result.
5. **`geosx --validate-input` timeout is 120 s** (`GEOSX_VALIDATE_TIMEOUT`
   overrides). `GEOSX_VALIDATE.md` is explicit that this number is a guess, not
   a measurement, and was only ever timed at 2–3 s on one small deck.
6. **`GeosSimulator` reads `GEOSX_EXECUTABLE` and `GEOS_SOURCE_DIR` from the
   environment** when not passed explicitly, matching repo3's convention. If the
   manifest is meant to own that configuration instead, it is a constructor
   change.
7. Full-suite state at hand-off: `python3 -m pytest tests/ -q` from
   `/home/agent/repo4` is **247 passed, 2 skipped**. The two skips are mine and
   are deliberate: they need a real `geosx` / `lmp` binary
   (`GEOSX_EXECUTABLE`, `LAMMPS_EXECUTABLE`).
