# Raw project intent: verbatim note from Matt, 2026-09-23

**This is a verbatim transcript.** It is the source for the 2026-09-23 section of
[`PROJECT_PRIMER.md`](PROJECT_PRIMER.md) §1 and for [`geomodel/`](geomodel/README.md).
It follows [`2026-09-02_PROJECT_INTENT_raw.md`](2026-09-02_PROJECT_INTENT_raw.md).

---

this is a follow up project to SIGA (which about doing domain adaptation for coding agent -> operating GEOS simulator to help geoscientists accelerate their efforts). The method we settled on for the initial paper was light weight agent adapters. We can but don't need to include this idea for this follow-up work. The main tenants we want from a method side are (1) domain adaptation (2) continual learning (3) harness self evolution. From an objective side all we want is to (a) accelerate science and help scientists by making tools for them to help automate parts of their work to free them up from menial tasks and allow them to work on a higher managerial, ideas, etc. level.

So there are 3 objectives in this follow up work:
1. increase depth: in the original we had a narrow scope of "user already has a complete simulation specification, our method is just the translation layer into the simulation deck". We want to expand this and have the agent take on more responsibility to take on more of the pipeline of work so to speak. So you can imagine that a scientist work flow is a -> b -> c ... and in our case we were handling a small component of "translate simulation intent into input deck and thus sim result by extension/execution". We want to handle more of it, not just 'b' but a -> b -> c
2. increase breadth: in the original we looked at 3 domains/simulators: GEOS, LAMMPS, and OpenFOAM. We want to expand this.
3. implement and evaluate latest methods and produce new insights/analyses about them and develop new, improved methods: agent self evolution has been extremely popular in the past months and while our original work implemented a very rudimentary version, we want to take the next steps and fully understand how the field has progressed, implement/test and adopt the best ideas to build on top of and then develop our own new ideas for our specific task (but hopefully generalizes)

items 1/2 require more domain expertise, so we started on 3 first. We established a biweekly (1 in 2 weeks) meeting with a real domain expert, a computational geoscientist at LLNL Chris Sherman who also helped to develop the GEOS simulator tool. With his domain expertise on geoscience we can pursue item 1 in earnest.

[Session tasks]
- since he explained that creating a geological model of a site is the step that precedes running GEOS simulations and the one that takes 80-90% of his time, we should target this for a new task
- he mentioned several sites along with public data sources that we can pull from so that gives us a small handful ~3 starter sites maybe total <10 that we can examine. This is honestly fine, we'll aim to evaluate in great depth on this very hard task for a very small sample. It's not ideal but it's realistic for the granularity/depth we want to target. We should start with Utah Forge
- I also made sure to ask and he confirmed that creating the geological model is a reasonable target task for LLM agents.
- broadly speaking I think we try to download all the data relevant to the target site, identify which piece is the actual geological model and partition our data from "inputs to the agent" and "outputs to be produced"
- I think an even earlier step should be to download and read all the papers he linked so we can develop an understanding of "what a geological model is precisely" and how it is produced by humans and evaluated.
- (1) download all the papers he linked (2) read and summarize each (make a concise markdown summary) (3) write a markdown report on what a geological model is, how it's created (what inputs, what is the general process), and how it's evaluated (I think this one is the one I can answer myself: it just needs to match/produce the observations collected from the actual site (4) download utah forge data (5) partition into input/output (6) formulate starter task around just the utah forge site.
- markdown reports should be extremely human readable (and not too long, reading is slow for us humans!).
