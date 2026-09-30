# Sherman meeting, 2026-09-11: notes and what we take from it

**Who:** Chris Sherman (LLNL computational geoscientist, GEOS developer) · Matt Ho
**Raw notes:** [`misc/sherman_meeting_sep11.md`](../../misc/sherman_meeting_sep11.md) · **Prep doc:** [`../2026-09-11_MEETING_sherman.md`](../2026-09-11_MEETING_sherman.md)
**Cadence agreed:** a meeting every two weeks.

---

## The five things that matter

1. **The geological model is where the time goes.** Building a model of the site takes
   80–90% of the effort. Running it in GEOS is the easy 10–20%: find the closest example
   in `inputFiles/`, copy it, and change the sizes, properties, boundary conditions and
   wells. *Our SIGA task was the 10–20%.*
2. **He thinks an LLM agent can reasonably do this task.** It gets hard fast when
   structural geology is involved (many faults and layers), but he thinks skills plus
   external tools could make it tractable.
3. **Sites come in three difficulty classes.** These are a ready-made curriculum:

   | case | site | geology | difficulty |
   |---|---|---|---|
   | 2 | Gulf Coast (old oil and gas wells) | "pancake" layers of sediment: variation with depth, little sideways | easiest |
   | 1 | **Utah FORGE** | fairly uniform granite host rock plus a network of natural fractures | middle, **our start** |
   | 3 | San Emidio (WHOLESCALE) | 24 faults, 5 layers, on the boundary of two tectonic regimes | capstone: **took him a year** |

4. **A model is judged by whether it reproduces what was observed.** Examples: the L2
   misfit of a pressure time series at a monitoring well, where microseismicity is
   predicted versus where it occurred (counted as false and true positives), and DAS
   fiber strain. Calibration is an inversion problem, for example ESMDA ensembles.
5. **The data is public.** Utah FORGE has its own dashboard, and its data lives in the
   Geothermal Data Repository (GDR). Two more public sources: California's GeoSteam
   well records and the Texas RRC oil and gas records.

## What he said AI would be good or bad at

| confident | less confident |
|---|---|
| parsing planning and engineering documents, tables and images into a plug-and-play format (e.g. well data) | initial conditions and property fields in structurally complex settings |
| picking and combining the closest GEOS example, especially with a self-built searchable taxonomy of the example catalogue | anything that needs structural geology (faults and layers) without tools |
| **sensitivity analysis** (tweak one thing and re-run) | |
| **data incorporation**: "here is new data on this site, update the model to match" | |

He also described **three levels of subsurface modeling**:
- **L1:** a well's latitude, longitude and depth, with a generic material such as "shale".
- **L2:** well logs, giving the actual material at each depth.
- **L3:** a full model.

This matches the difficulty ladder we would build.

## LLNL deployment constraints (these bind later, and bind hard)

- Agents run inside **"Blackhole"**, LLNL's hardened version of the *bubblewrap*
  sandbox. The agent sees only a root folder and its children, with ports and internet
  locked down.
- Models come from an LLNL API endpoint or are self-hosted open weights. **No Chinese
  models.** Our current campaign runs `glm-5.3-flash` and `deepseek-v4-flash`, so
  **nothing we measure on those models is deployable at LLNL.** Any "for real use"
  claim needs a non-Chinese model, and that choice should be made before the next paid
  campaign.
- He is interested in **static resources**: precomputed tables, and cached literature
  from arXiv and Google Scholar. Without internet, an agent must study ahead of time.
  That is our T1 "open-book exam" framing, arrived at independently. We have a shared
  interest here.
- "Skills are everything." With internet access, agents organize themselves and build
  skills well. That is our continual-learning and self-evolution thread.

## My read: implications for the project

- **Item 1 (depth) is now unblocked, and the target is clear:** the agent builds the
  geological model of a site. That step feeds the GEOS deck, so SIGA becomes the last
  stage of a longer pipeline rather than being thrown away.
- **The target is not "a deck" but a model, and a model has no single right answer.**
  Matching observations is the evaluation experts use, but it cannot be the only one:
  - many different models fit the same pressure curve (non-uniqueness);
  - it needs GEOS forward runs, which we have been avoiding because of cost;
  - the observations at FORGE come from specific injection tests.

  We will want (a) a comparison of the artifact against the published expert model,
  (b) a match to held-out observations, and (c) his judgment on a small sample. See
  [`WHAT_IS_A_GEOLOGICAL_MODEL.md`](WHAT_IS_A_GEOLOGICAL_MODEL.md).
- **Small n is fine here, but it changes the statistics.** With fewer than 10 sites the
  claims will be case studies with repeated seeds, not benchmark means. Depth replaces
  breadth. That is the right call, and the paper should say so up front.
- **Contamination is a real risk.** The FORGE geologic model is described in many papers
  that are likely in training data (e.g. the granite surface dipping west, the Opal Mound
  fault). A time-based split, where the agent gets only data published before a model
  version, and a probe of what the model already "knows" about FORGE should both be
  planned from the start.
- **His two suggested AI tasks, sensitivity analysis and data incorporation, are
  cheaper follow-on tasks on the same sites.** Data incorporation is literally continual
  learning ("new data arrived, update the model"), which makes it a natural bridge to our
  method tenet (2).

## Questions for the next meeting (~2026-09-25)

1. Is the Phase 2C/3 FORGE geologic model (once we have identified the files) what *he*
   would call "the geological model"? Is the model GEOS actually consumed that one, or a
   simplified derivative?
2. Which inputs would he expect a person to be handed on day 1 of a FORGE-like project,
   and which would they have to go find?
3. For FORGE, which observation is the best judge of model fitness: pressure during the
   2022/2024 stimulations, microseismic locations, or DAS?
4. How would he grade an agent-built model in 10 minutes? What would he look at first?
5. The scale of our ask: can he spare ~1 hour per site to review agent outputs?
6. Can the Blackhole constraints be emulated outside LLNL (bubblewrap with no network),
   so we build for them from day one?
