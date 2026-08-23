# W8 — independent infrastructure and correctness review

**Date:** 2026-08-23. **Reviewer:** external agent, read-only mandate.
**Output:** `docs/REVIEW_2026-08-23_infra.md`. No source file was modified.

## What I was asked for

Correctness (highest priority, focused on paths the mock cannot reach),
over-engineering, infrastructure gaps for a 16–37 hour run, and claims-vs-code
consistency.

## Method

1. Read `README.md`, `docs/ARCHITECTURE.md`, `docs/WHY_V1_FAILED.md`,
   `worklogs/00_OVERALL.md` end to end before opening any source.
2. Ran the suite before starting: **453 passed, 2 skipped** at 17:34.
3. Read in full, myself: `runners/subprocess.py`, `runners/recording.py`,
   `runners/cached.py` (record layer), `runners/base.py`, `core/search.py`,
   `core/acceptance.py`, `core/archive.py`, `core/candidate.py` (validate /
   with_edits / materialize), `core/manifest.py` (StopPolicy),
   `simulators/geos.py`, `hygiene/corpus.py`, `hygiene/gate.py`,
   `checks/sandbox.py`, `evaluation/budget.py` (cost model), `scripts/evolve.py`.
4. Delegated two parallel audits with the same hostile brief:
   - `evaluation/` — stats, baselines, protocol, report, slices, budget;
   - `evidence/` + `proposers/` + the remaining `core/` modules.
5. Wrote reproductions under `/tmp/hrev/` for everything I claim as confirmed.
   Every item in the "confirmed" section of the review has a script that
   demonstrates the failure. Nothing is listed as confirmed on reading alone
   unless the review says so explicitly and gives the line.
6. Ran `python3 scripts/evolve.py demo` end to end and read its output against
   the claims in the worklog.
7. Re-ran the suite at the end.

## The working tree moved under me

Partway through the review the repository was being written to by another
process. Timestamps observed at 17:43:12:

```
17:40:39  src/harness_evolve/evaluation/amortization.py   (new, untracked)
17:41:45  src/harness_evolve/evaluation/zero_marginal.py  (new, untracked)
17:42:18  src/harness_evolve/evaluation/report.py         (modified, uncommitted)
17:42:20  src/harness_evolve/evolvers/base.py             (new, untracked)
17:43:06  src/harness_evolve/evolvers/search.py           (new, untracked)
17:38:58  tests/test_integration.py                       (modified)
```

By 17:56 the concurrent work had added `tests/test_evolvers.py`, fixed both
package maps, and committed the three modules — the suite is **520 passed,
2 skipped** at the end of the review. The red window closed on its own.

Consequences for this review, stated so the reader can discount appropriately:

- The suite went 453 passed (17:34) -> **452 passed, 2 failed** (17:44) ->
  520 passed (17:56). Both failures were
  `test_docs_consistency.py::test_package_map_lists_every_module_directory`,
  caused by `evolvers/` being absent from both package maps. The guard added in
  pass 10 worked exactly as designed.
- **Every finding in the review was re-run against the tree at 17:56 and still
  reproduces.** The concurrent work touched none of them. The reproduction
  scripts are in `/tmp/hrev/`, `/tmp/rev/` and `/tmp/hr/`.
- `evolvers/` (~870 lines), `amortization.py` (693) and `zero_marginal.py` (396)
  arrived after I had planned my reading. I read `evolvers/base.py`'s design
  rationale and `evolvers/search.py`'s header, and I did not audit any of the
  three for correctness. They are covered in the review only as a scope and
  process observation, not as a correctness finding.

## What I could not check

- **Anything requiring the real environment.** No Docker, no `geosx`, no
  ground-truth tree, no `/data`, no API key. `SubprocessRunner`,
  `GeosSimulator.validate`, `expand_with_variants` against a real source tree,
  and `GroundTruthCorpus.from_ground_truth_dir` against real data are all
  reviewed by reading plus synthetic reproduction only.
- **`run_experiment.py`'s CLI contract.** repo3 is not present here, so I could
  not verify that `--include`, `--plugin-dir`, `--results-root-dir` and
  `--ground-truth-dir` exist with those spellings and semantics, nor that
  results land at `<results_root>/<agent>/<run>/<task>/inputs`. A mismatch in
  any of these produces a uniform 0.0 across every task, which is the v1 failure
  mode exactly; the review flags it as the highest-value thing to test first and
  the one I could not settle.
- **Hygiene threshold calibration.** Every threshold in `GateConfig` and the
  `MIN_STEM_LEN` / `MIN_PATH_PART_LEN` constants are uncalibrated against real
  filenames. I could show that two rule sets disagree; I could not show which is
  right.
- **Real GEOS validator output.** `evidence/directives.py` parses stderr shapes
  nobody in this environment can produce. Delegated, but the same limit applies.
- **`evaluation/amortization.py`, `evaluation/zero_marginal.py`, `evolvers/`** —
  see above.
- **Whether the 2 skipped tests would pass.** They need `geosx` / `lmp`.

## Things I checked that turned out to be fine

Recorded so the next reviewer does not repeat them:

- `Search._evaluate` / `_probe` slice discipline: the anchor refusal and the
  probe "no scores dict" design both hold, and probe rollouts are re-tagged on
  every path including replay.
- `Archive.best()` cannot return a gate-rejected candidate in practice: the seed
  is always accepted, so `self.accepted` is never empty. (It is still selected
  by mean — see the review.)
- `resolve_included` cycle-breaking works; `_ancestors` is threaded correctly.
- `values_equivalent` numeric/list/notation handling is correct on the cases I
  tried.
- `_cap` in `hygiene/gate.py` cannot turn a blocking report into a passing one.
- `RegressionGate` per-*step* noise tolerance does what its docstring says. The
  problem is the root clause, not this one.
- The vetting child correctly rejects `sys.exit`, vacuous tests, and bad
  signatures. Its weakness is what it does not fence, not what it does.
