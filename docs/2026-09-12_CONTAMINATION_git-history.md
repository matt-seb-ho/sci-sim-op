# The corpus mount is a git checkout, and the agent found out

**Found 2026-09-12** while building the qualification kit, by reading one
rollout transcript from the 2026-09-11 screen. Nothing in any score showed it.

---

## What happens

`/geos_lib` is built by `create_filtered_geos_copy()`, which hardlink-copies the
**entire** GEOS tree and omits a block list. `/data/shared/geophysics_agent_data/data/GEOS/.git`
exists, so it is copied too. A deck removed from the working tree is then one
command away:

```
$ cd /geos_lib && git show HEAD:inputFiles/compositionalMultiphaseFlow/benchmarks/SPE11/b/spe11b_vti_source_base.xml
<?xml version="1.0" ?>
<Problem>
  <Solvers>
    <CompositionalMultiphaseFVM
      name="compositionalMultiphaseFlow"
      targetRegions="{ reservoir1, reservoir2, ... }"
```

`git ls-files` is worse than `git show`: it returns the paths of the files that
were removed, which is a map straight to the answer for an agent that has not
yet thought to look.

## How often

Measured over all 80 rollouts of `.evolve/p0_screen`:

| | |
|---|---|
| rollouts that ran a git command against `/geos_lib` | **59 of 80** |
| tasks where a git command naming one of that task's **own blocked decks** returned deck XML | **29 of 40** |

The second row is the load-bearing one. It is not "the agent used git"; it is
"the agent asked git for a file we had deliberately removed, and git gave it
back".

## What it probably explains

The twelve tasks the screen reported at a flat **1.000 at both seeds** were read
as a ceiling effect, and that reading is in
[`STATUS.md`](STATUS.md) ("two of six known tasks are unusable and one is at
ceiling") and drove the study-set selection. Almost all of them are in the
recovery list:

```
AdvancedExampleViscoDruckerPrager          1.000/1.000   7 recoveries
AdvancedExampleCasedElasticWellbore        1.000/1.000   5
AdvancedWellboreExample...ThermalConduct.  1.000/1.000   4
ExampleTFrac                               1.000/1.000   4
pknViscosityDominated                      1.000/1.000   4
AdvancedExampleDeviatedPoroElasticWellbore 1.000/1.000   3
AdvancedWellboreExample...HeatCapacity     1.000/1.000   3
ExampleKirschWellbore                      1.000/1.000   3
AdvancedExampleThermoPoroElasticWellbore   1.000/1.000   2
kgdExperimentValidation                    1.000/1.000   2
pennyFracToughnessDominated                1.000/1.000   2
```

**"At ceiling" and "read the answer" are not the same finding**, and we recorded
the first. This is the same failure mode as the other eight: it does not crash,
it returns a plausible number.

## What is established and what is not

**Established.** `.git` is in the mount. `git show HEAD:<blocked path>` returns
full deck text. 59/80 rollouts ran git against the mount. On 29 tasks a git
command naming a blocked deck returned deck XML.

**Not established.** How much of any given score is attributable to it. Access
is not the same as use: `ExampleSPE11b` recovered its own three blocked decks
and still scored 0.506, so the agent does not simply paste what it finds. The
honest statement is that the leading explanation for the flat-1.000 set is no
longer a ceiling effect, and that no score from a git-enabled mount can be
called a measurement of authoring until it is re-run.

## What to do

1. **Stop copying `.git`.** One line in `create_filtered_geos_copy`'s `_ignore`.
   Cheapest fix, and it should go in before any further rollout.
2. **Do not trust the filter that way at all.** The qualification kit takes the
   other approach and it is the better one: assemble the corpus from an explicit
   include list rather than filtering a checkout, so blocked files are never
   written rather than written and deleted. `.gitattributes`, `.github/`, build
   artifacts and anything else archival come out for free. See
   `geos-harness-qual/src/qualkit/corpus.py`.
3. **Re-run the screen.** The study-set selection rests on it, and the pool of
   "no headroom" tasks may be much smaller than twelve.
4. **Re-check anything else that quotes a screen number**, including the seed
   baselines and the `+0.116 [−0.083, +0.314]` paired result if its cells came
   from a git-enabled mount.
5. **Audit for the general shape.** The rule that would have caught this, and
   caught the geosx binary five weeks earlier: *make it unreachable, not
   forbidden*. Anything removed but recoverable is not removed. Worth one pass
   over every mount the container gets.

## How it was found

By running `qual inspect` — a transcript reader written for the student kit — on
one rollout, and reading the trace:

```
  11  Bash   cd /geos_lib && git log --all --oneline --diff-filter=A -- '*spe11b*'
  12  Bash   cd /geos_lib && git show HEAD:inputFiles/.../spe11b_vti_source_00840x00120.xml
  13  Bash   cd /geos_lib && git show HEAD:inputFiles/.../spe11b_vti_source_base.xml
  14  Bash   cd /geos_lib && git show HEAD:inputFiles/.../include/kr.xml
```

Which is the through-line of every defect this project has found: **run it and
read the output.** None of the nine were found by reading code.
