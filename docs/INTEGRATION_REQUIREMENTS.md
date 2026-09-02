# Integration requirements against repo3

`harness-evolve` runs the agent through repo3's containerised runner
(`SubprocessRunner`). Two changes are required there before a real search means
anything. Both are the same failure class, and it is the one that killed the
predecessor loop: **a knob that appears to vary something while the consumer
sees a constant.**

## R1 — forward the stop-policy environment into the container (**SATISFIED 2026-08-26**)

> **Status: satisfied, and mechanically re-checked.** Both fixes landed on
> 2026-08-26. `repo3/plugin/hooks/verify_outputs.py` now reads both names (env
> first, `stop_policy.env` from the plugin mount second) and records the resolved
> policy on every event it logs. Verified the way this section demands — by
> diffing the hook's own event log inside the real container, with a control arm
> that strips the two `--env` forwards back out:
>
> | feedback shape | block text |
> |---|---|
> | `minimal` | 86 chars |
> | `structured_errors` | 1212 chars |
> | `errors_plus_tables` | 3038 chars (adds all 57 legal tag names) |
> | *control, forwards stripped* | 151 chars, **identical across both shapes** |
>
> Reproduce: `REPO3_CONTAINER_BACKEND=enroot python3
> repo3/scripts/verify_r1_feedback_channel.py --out .evolve/r1_verification`.
> It writes `receipt.json` naming the **SHA-256 of the hook it verified**, and
> `harness_evolve.integration.check_r1()` checks that SHA against the hook on
> disk — so editing the hook turns `evolve.py preflight` red until it is
> re-verified. Details and the two defects this surfaced: `worklogs/2026-08-26_overnight.md` §2.
>
> One gap remains open and is **not** covered by the receipt: the hook implements
> `parse` and `geosx_validate` only. A stop policy may legally name
> `required_sections`, `constraints`, or `cross_section_refs`; those are skipped
> and recorded per-event as `checks_unsupported`. **Until `checks/` is vendored
> into the plugin mount, the searchable check set must stay
> `{parse, geosx_validate}`** — otherwise the search varies check names nothing
> runs, which is this section's own failure class.

The original requirement, for the record:


`repo3/src/runner/docker_cmd.py` forwards a fixed `-e GEOS_HOOK_*` allowlist to
the container. `StopPolicy.to_env()` emits two names outside it:

```
GEOS_EVOLVE_FEEDBACK_SHAPE   minimal | structured_errors | errors_plus_tables
GEOS_EVOLVE_CHECKS           comma-separated active check names
```

Both are dropped at the container boundary today.

**Why this is blocking rather than a nice-to-have.** The stop policy is a
searchable component; feedback shape is the surface the "static gates raise the
floor, actionable feedback raises the ceiling" claim is *about*. If those two
variables never reach the hook, the search will dutifully propose, evaluate, and
accept or reject candidates that differ only in a setting nothing reads. Every
result would be run-to-run noise wearing the label of a mechanism — and it would
look completely normal in the logs, because the candidates really are different
and the scores really do differ.

That is precisely how the predecessor produced three rounds of "self-evolution"
from a reward channel that returned nothing.

**Required:**

1. Add `GEOS_EVOLVE_FEEDBACK_SHAPE` and `GEOS_EVOLVE_CHECKS` to the forwarded
   allowlist in `docker_cmd.py`.
2. Have `plugin/hooks/verify_outputs.py` read them and honour them.

`SubprocessRunner` also writes `stop_policy.env` into the mounted adapter
directory as a second path in, so the hook can pick it up from disk if the
env-var route is not taken. Only one path needs to work — but **at least one
must, and it must be verified rather than assumed.**

**Verification before any aggregate is believed:** run one task with a stop
policy of `feedback_shape=minimal` and one with `errors_plus_tables`, and
diff the hook's own event log. If the two runs produce identical feedback text,
R1 is not satisfied, regardless of what the config says.

## R2 — check-name registry (done here, noted for repo3)

`core/manifest.py` no longer hardcodes the set of valid check names; it resolves
them from the live registry via `resolve_known_checks()`. Previously a stop
policy naming `cross_section_refs` — a real, shipped check — was rejected as
invalid, so the search space silently excluded every check beyond four
hardcoded names.

Nothing is required in repo3 for this. It is recorded because the shape is worth
recognising: a validation list that is a *snapshot* of a registry will always
drift toward silently truncating the thing it validates.

## R3 — unexecuted surface (informational)

`SubprocessRunner` has never run in this environment: no Docker daemon, no
`/data` volume, no GEOS container. Every branch except the four-line process
launcher is tested against an injected fake.

**First real use should be a single task with `--dry-run`**, then a single task
for real, with the resulting `Rollout` inspected by hand, before any aggregate
number is treated as meaningful.

## R4 — contamination re-audit (blocking before any run that mines evidence)

The evidence layer surfaces validator output and trajectory excerpts to the
proposer, and the demonstrations channel carries expert authoring sessions. Both
widen the leakage surface relative to what repo3 audited.

The gate in `hygiene/` is a strict superset of repo3's and runs before any
rollout is spent, but its content, numeric, structural, and rare-token
thresholds were calibrated against synthetic fixtures plus two real leaked
artifacts — **not against the real ground-truth tree**, which is not mounted
here. Re-check `rare_token_df_fraction` and `ngram_error` on the first run with
the tree available.
