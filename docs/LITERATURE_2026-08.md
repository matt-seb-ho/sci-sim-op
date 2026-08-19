# Verified literature sweep — August 2026

**Date:** 2026-08-19 · **Scope:** what is current for `harness-evolve` as of Aug 2026, emphasis Jun–Aug 2026.
**Verification:** every arXiv ID below was fetched from `https://arxiv.org/abs/<id>` in this session; the
title, submission date, subject line and abstract text were read before anything was written about it.
Papers I could *not* verify are listed in `worklogs/W7_literature.md`, not here.
**Prior shortlist (not re-verified here, per brief):** GEPA 2507.19457 · AHE 2604.25850 ·
Self-Harness 2606.09498 · ACE 2510.04618, plus the 30-paper set already confirmed in
`repo3/docs/2026-08-19_method-adoption-plan.md`.

Regime constants used for every fit judgement: **frozen model + frozen base harness**; **~17 tasks ×
2–3 seeds, ~25 min / ~$0.07 per task-run**; **in-distribution scores 0.86–0.92 with no headroom, the
whole held-out effect being 2 catastrophic-failure rescues out of 10**; **efficiency is a gate, not a
metric**; **a strong non-gold verifier exists** (`geosx --validate-input`, which prints valid-attribute
tables inline); **retrieval-gated memory is a known local negative** (the `memory_lookup` MCP tool was
called zero times while verified functional).

---

## 1. Verified table

`Code?` = a GitHub (or other) URL present on the abs page or in the abstract. Not a claim that it runs.

| ID | Title | Date | One-line claim | Code? | Fit |
|---|---|---|---|---|---|
| **2605.23904** | SkillOpt: Executive Strategy for Self-Evolving Agent Skills | 2026-05-22 (v2 05-25) | Text-space optimizer that trains **one skill document** as the external state of a frozen agent via bounded add/delete/replace edits, accepting an edit only when it strictly improves held-out validation; zero extra inference-time calls; evaluated inside Claude Code. | yes — `aka.ms/skillopt` → `microsoft.github.io/SkillOpt` | **high** — it optimizes exactly our artifact class under exactly our frozen-model, efficiency-gated constraints |
| **2608.11079** | SkillZip: Evaluation-Free Skill Compression for Self-Evolving Agents by Discovering Reusable Structure | 2026-08-11 (v2 08-16) | Compresses a skill by minimum-description-length over a typed skill contract with a **hard coverage constraint** per trigger/workflow-edge/tool-requirement/obligation/output-field, so rare rules survive; one-shot and continual "Zip-on-Write" modes, **no rollouts**. | no | **high** — the only budget-enforcement mechanism found that costs zero rollouts and provably preserves rare negative constraints |
| **2608.10471** | RLMOpt: Adaptive Prompt Optimization via Recursive Language Models | 2026-08-11 | LM-driven search policy over a deterministic harness (objective scoring, Pareto selection, regression constraints); beats GEPA on 9/11 matched runs, **never produced a prompt below its seed** (GEPA did twice), prompts 27–79% of GEPA's size; concludes gains are set by **seed headroom, not search budget**. | no | **high** — the no-regression floor and the headroom finding are written for our near-ceiling, tail-driven objective |
| **2607.00871** | Self-Evolving Agents with Anytime-Valid Certificates | 2026-07-01 | Confines self-modification to a **steering adapter + versioned harness around a frozen base**, and admits each modification only through an **anytime-valid statistical gate** emitting an auditable certificate against a fixed error budget; five verifier-in-the-loop mechanisms supply dense **grader-free** signal. | no | **high** — an acceptance rule with a validity guarantee at small n is precisely what n=2–3 seeds needs; caveat: its own results are single-run |
| **2608.05810** | When Self-Evolution Backfires: Pre-Commit Gating against Skill Contamination in LLM Agents | 2026-08-06 | Skill accumulation is non-monotonic past a critical pool size and the damage is **structurally irreversible** (post-hoc removal recovers little); Verifier-as-Gatekeeper filters each skill pre-commit with three critics (structural validity, behavioural harmlessness, semantic consistency) plus marginal-gain subset selection → 72% pass@1 on Terminal-Bench 2 with a ~5× smaller pool. | no | **high** — argues acceptance must be *pre-commit*; our validator is a ready-made structural critic |
| **2608.07545** | DarwinX: Evolving Agent Harnesses Through Natural Selection | 2026-07-31 | Population-based harness selection with the model frozen; a **preserve-and-extend contract** admits only variants that extend coverage without regressing, archive keeps lineages, and **fitness comes from each benchmark's own verifier — no gold solutions**. | no | **medium-high** — the contract and verifier-only fitness are directly adoptable; the population + recombination loop is too rollout-hungry for 17 tasks |
| **2608.11095** | Why Does CLAUDE.md Keep Growing? Catastrophic Remembering in Agentic Coding | 2026-08-11 | Across 247,694 instruction lifetimes in 1,867 repos, agentic prompt files grow +226% over their lifetime and old instructions get *less* likely to be deleted; the cause is that deleting an instruction whose rationale is lost costs O(2^\|D\|). **Prompt comments carrying the latent rationale removed 99.3% of excess instructions** in verifiable worlds and improved WildIFEval instruction-following by up to 23.1%. | no | **high** — names and fixes the exact pathology our v1 showed (12× monotone growth of an always-on artifact) |
| **2608.02636** | Rethinking Self-Evolving Agent Skills: Feedback Dynamics over Multiple Rounds | 2026-07-31 | Controlled 42-run study: **only 55 of 388 candidates** produced a byte-distinct validation best; all 11 selected skills came from feedback conditions **containing failed trajectories**; test-time-scaling controls recover the gain on one benchmark but are 30.96 points behind on another. Self-evolution is "sparse, validation-filtered search", not steady improvement. | yes (`HKUST-KnowComp/rethinkskill`) | **high** — the reference protocol for reporting a sparse, low-n evolution result honestly |
| **2608.18066** | On the Fragility of Self-Improving Agents: Variance, Task Order, and Underspecification | 2026-08-18 | Re-evaluation of two memory-based self-improving methods across **multiple runs and shuffled task order**: agent evaluation is inherently noisy, the self-improving loop **amplifies** that noise, and gains depend heavily on task order because default orderings impose a hidden curriculum. Underspecification is a partial explanation; rubrics + environment feedback close only part of the gap. | yes (`SalesforceAIResearch/self-improve-fragility`) | **high** — the newest and most direct statement of our two biggest measurement risks (n=2–3 seeds; v1's per-round task slices) |
| **2607.13083** | Phantom Guardrails: When Self-Improving Agent Harnesses Fix Failures That Never Happened | 2026-07-13 | A deterministic micro-lab where the correct edit is *do nothing*: the proposer **invents a violation in 15/60 runs** when the input contains a rule-shaped but legal pattern, enabling a guardrail for a failure class that provably never occurs; inside an add-only accept loop the phantom re-enters and persists. | no | **high** — a cheap, pre-registrable audit for our negative-constraint artifact class, where a byte-exact oracle (the validator) exists |
| **2608.14036** | Demystifying Agent Skills: Why They Work—Until They Don't | 2026-08-14 | Controlled + contrastive study over 8,135 trials: skills work mainly as **procedural anchors (65.7% of cases) rather than knowledge injection (4.5%)**; **retrieval is a separate bottleneck — actual-use precision falls from 29.6% to 3.3% as the pool grows from 5 to 100**; skills beat Workflow Memory by 6.06 points in matched comparison. | no | **high** — independent external confirmation of our local retrieval-gated-memory negative result, and of why an always-on artifact wins |
| **2606.01139** | SkillRevise: Improving LLM-Authored Agent Skills via Trace-Conditioned Skill Revision | 2026-05-31 (v3 06-17) | Execution-grounded cold-start skill repair: diagnose defects from execution evidence, retrieve repair principles, apply execution-anchored edits, and **retain the first verifier-passing candidate** within the revision budget, falling back to empirical utility only if none passes. SkillsBench 36.05% → 61.63%; skills transfer across executors. | no | **high** — "first verifier-passing candidate wins" is the cheapest possible acceptance rule and it is exactly what our validator can adjudicate |
| **2608.15089** | StateM: Reaching 95.3% Raw Accuracy … on Terminal-Bench 2.1 via Harness Scaling | 2026-08-15 | Agent-native runtime built on durable states, phase-local context, checked transitions, **recoverable runbooks and versioned procedural practices**; turns postmortem findings into persistent, executable preconditions. Raises DeepSeek-V4 Flash 82.7 → 88.1 for **<$38 of adaptation**; frozen profiles transfer across models. | yes (`github.com/henryqin1997/statem`) | **medium-high** — "make the learned control an enforced precondition, not prose" is our constraints-as-checks idea, demonstrated at our price point and on our proposer model family |
| **2605.22166** | Adapting the Interface, Not the Model: Runtime Harness Adaptation for Deterministic LLM Agents (Life-Harness) | 2026-05-21 (v2 05-27) | Converts recurring interaction failures from training trajectories into reusable interventions across **environment contracts, procedural skills, action realization, trajectory regulation**; the harness is then **frozen for evaluation**. Improves 116/126 model×environment settings; harnesses evolved from one 4B model transfer to 17 others. | yes (`Tianshi-Xu/Life-Harness`) | **medium-high** — a component taxonomy for deterministic, rule-governed domains, which is what a simulator input language is |
| **2608.01918** | HarnessCompass: Guiding Automatic Harness Evolution toward Generalizable and Effective Agent Harnesses | 2026-08-03 | Three ideas against AHE's overfitting: **global constraints** restricting edits to task-agnostic changes, **proactive first-person feedback** from the agent about harness usage, and **component-wise optimization then consolidation** to avoid cross-component interference. SWE-bench Verified 54% → 66% in 5 iterations with GPT-5.4. | no | **medium-high** — supersedes AHE on generalization; component-wise decoupling matches our per-component manifest, but 5 iterations × SWE-bench is still more rollouts than we have |
| **2608.08466** | Hierarchical Self-Improvement: A Framework for Task-Specific Evolvable Agent Harnesses | 2026-08-09 | One frozen LLM across three scopes (task harness / evolver / meta-evolver) with a fixed task-injection seam; large gains on moderate tasks, **none on tasks beyond the backbone's capability**; states two explicit limits: a **feedback-fidelity bound** and a **backbone capability bound**. Backbone is DeepSeek-V4-Flash-Preview. | yes (`TailinZhou/hsi`) | **medium** — same frozen backbone as us and the honest bounds are quotable; the meta-evolver tier doubles the search space we cannot afford |
| **2608.15071** | Evo-Harness: Context-to-Harness Skill Compilation for Self-Evolving Agents | 2026-08-15 | Formulates **online harness learning** — a frozen agent updating a structured harness across sequential tasks with only a **one-shot opportunity per task**; "context-to-harness skill compilation" distils noisy single-shot executions into reusable skill harnesses. Five benchmarks incl. TerminalBench2, SWE-bench, WebArena-Infinity. | yes (`A-EVO-Lab/a-evolve`) | **medium-high** — the one-shot-per-task formulation is the closest published match to our per-task budget |
| **2608.09629** | Rethinking Self-Evolving Agents: Do We Still Need Prescribed Optimization Pipelines? | 2026-08-10 | Open-Ended Optimization: fix objective, budget, data boundary and evaluation, let a frontier optimizer compose the improvement process. **12 wins / 1 tie / 1 narrow loss vs SkillOpt and GEPA over 14 comparisons**, using a median 34.3% of SkillOpt's target-interaction token budget — but SkillOpt **wins with a medium optimizer**, and a weak optimizer cannot use the interface at all. | no | **medium** — establishes SkillOpt+GEPA as the two reference prescribed pipelines; the delegation itself is gated on optimizer capability we may not want to pay for |
| **2606.06324** | From Failed Trajectories to Reliable LLM Agents: Diagnosing and Repairing Harness Flaws (HarnessFix) | 2026-06-04 (v2 07-02) | Compiles traces + harness artifacts into a **Harness-aware Trace IR** with step-level data/control flow aligned to the harness artifacts that shaped them, attributes failures to responsible steps and artifacts, consolidates recurring diagnoses into flaw records, and accepts patches under **regression-aware validation**. +6.3–18.4%. | no | **medium-high** — a concrete schema for AHE pillar 2, which the brief says is a day of wiring for us |
| **2607.26598** | Living-Harness Is an Interactive-Agent Evolver | 2026-07-29 (v2 08-11) | Evolution-SOP-guided bounded harness updates writing two forms of procedural knowledge — episodic memory (trigger, failure pattern, recovery action) and a state graph (nodes, repair edges, transitions) — with **tools and base context frozen**. +10.07 / +9.91 pp on τ²-Bench and MultiWOZ. | yes (`anotherbricki/Living-Harness`, "soon") | **medium** — good bounded-update discipline, but the evolved state is **retrieved** to guide future interactions, which is our known local failure |
| **2606.20638** | RIZZ: Routing Interactions to Near Zero-Interference Zones for Continual Adaptation of Black-Box Agents | 2026-06-02 | Continual black-box adaptation via **verifier-gated memory**: only verified interactions may update memory, promote rules, demote harmful rules, or create **anti-patterns**; a router selects memory branches compiled into a **bounded prompt**. | no | **medium** — verifier-gated writes and anti-patterns are adoptable; branch routing and retrieval are not. Its Appendix C is the load-bearing evidence against ACE (see §8) |
| **2608.07449** | SkillProx: Self-Evolving Agent Skills via Proximal Textual Gradient Descent | 2026-08-07 | Forward stage re-executes diagnosis-driven edits on the same batch and **rolls back regressions**; backward stage decomposes the skill into auditable knowledge units and estimates each unit's contribution with a **frozen leave-one-out utility audit**, then consolidates/demotes/removes under a validation gate. +3.0 pp over the strongest gradient-based baseline. | no | **medium** — the per-unit LOO audit is the right answer to "which cheatsheet line pays", but costs |units| × rollouts; only affordable if the audit runs against the validator, not TreeSim |
| **2608.00303** | CrystalMem: Elastic Memory for Self-Evolving LLM Agents via Knowledge Crystallization | 2026-07-31 | Identifies **memory hysteresis** — after a byte-budget squeeze-and-recover cycle the agent settles below its pre-squeeze level — proves a residual-deficit floor for keep-or-drop policies, and demotes entries across four fidelity states with verified recrystallization. | no | **low-medium** — our budget is fixed, not elastic; the hysteresis proof is a good argument for *never* hard-truncating without keeping the rationale |
| **2607.07436** | The Blind Curator: How a Biased Judge Silently Disables Skill Retirement in Self-Evolving Agents | 2026-07-08 (v2 08-18) | A **false-pass**-biased judge does not just add noise — past a sharp threshold (0.45 here) it **switches contribution-based skill retirement off entirely**, and the failure is invisible in aggregate metrics; only near-zero-false-pass, **verifier-like graders** are spared. Offers a cheap defect-injection audit. | no | **high (as a constraint)** — direct argument for using the simulator, not an LLM judge, as the retirement signal |
| **2608.09096** | Evo-Bench: Can Language Models Improve Agent Harness? | 2026-08-10 (v2 08-11) | Benchmark isolating a model's intrinsic harness-evolving capability via auxiliary-task evolution to find framework-sensitive tasks plus sensitivity-aware stratified splitting; top models gain up to 16.6 points; analysis exposes **early saturation** and shows synthesized harnesses transfer across policy models. | no | **medium** — "early saturation" is a named phenomenon we should test for; the benchmark itself is not our domain |
| **2607.05202** | EvoAgentBench: Benchmarking Agent Self-Evolution via Ability Transfer | 2026-07-06 | Trace-grounded "Abilities" canonicalized into operational units and linked in domain Ability Graphs, with every test task backed by verified training-side Ability support. Curated Ability content transfers across model families, but **no current automatic method sustains positive gain in all settings**. | yes (HF dataset) | **medium** — the "curated transfers, automatic does not" result is the cleanest existing framing of what a self-evolution paper must beat |
| **2608.00155** | AgentStream: How Well Do Self-Evolving LLM Agents Perform Under Streaming Tasks? | 2026-07-31 | Evaluates five self-evolving methods × three models under Isolated/Sequential/Interleaved task streams; reliability varies by stream, benefit is **gated by model capability and non-monotonic in model strength**, and **no single method dominates**. | yes (`Jasper-Yan/AgentStream`) | **medium** — replicates 2605.30621's non-monotonicity and justifies our cross-model panel |
| **2607.03691** | Don't Blame the Large Language Model: How Agent Harness Evolution Shapes Coding Agent Quality | 2026-07-04 (v2 07-20) | First controlled longitudinal study fixing the model and varying only the harness across **35 sequential Qwen Code releases** on 50 stratified SWE-bench Verified tasks, tracing quality fluctuations to specific development patterns and PRs. | no | **medium** — the canonical citation that harness deltas, not model deltas, drive observed regressions |
| **2607.13285** | Harness Handbook: Making Evolving Agent Harnesses Readable, Navigable, and Editable | 2026-07-14 | Behaviour-centric representation synthesized from a harness codebase (static analysis + LLM structuring) linking behaviours to source, plus Behaviour-Guided Progressive Disclosure; improves behaviour localization and edit-plan quality **with fewer planner tokens**. | no | **low-medium** — solves "where do I edit" for large production harnesses; our adapter manifest already makes the action space explicit |
| **2603.00214** | Agentic Scientific Simulation: Execution-Grounded Model Construction and Reconstruction (JutulGPT) | 2026-02-27 | Model construction as an **execution-grounded interpret–act–validate loop with the simulator as the authoritative arbiter of physical validity**; detects and logs underspecified modelling choices; finds a structural limit — **choices resolved tacitly through simulator defaults are invisible to the assumption log**. Reservoir simulation (JutulDarcy). | abstract says all code/prompts/logs public; no GitHub URL on abs page | **high (as prior art)** — nearest neighbour to our problem; the tacit-default blind spot is a threat we inherit |
| **2608.14441** | PACE-Bench: Benchmarking Physics Adaptation via Code Evolution in Dynamic Environments | 2026-08-14 | 144 simulator-grounded source→target adaptation pairs over six physics domains with diagnostic sandbox feedback under an attempt budget; ten self-evolving methods compared. **Simulator-grounded reflection is more reliable than unverified self-revision, while memory anchors agents to early designs** and broad tree search fails to converge. Far from saturated. | yes (`thunlp/PACE-Bench`) | **high** — an external, simulator-grounded benchmark whose headline finding is our thesis, and a possible transfer target |
| **2608.15881** | Deploying Frontier Agentic Technology in MOOSEnger, a Multiphysics-Capable AI Assistant | 2026-08-16 | Harness for the MOOSE multiphysics finite-element framework: retrieves repo context, **validates and diagnoses the input through the simulation executable**, and extracts lessons into persistent memory. 8 physics categories × 25 cases; MOOSEnger-GPT-5.2 90% vs 5% for the bare model. | no | **high (as prior art / baseline)** — the closest published system to our GEOS setting; note the enormous harness effect on a bare-model baseline |
| **2607.20346** | IteraSim RAG: A Multi-Stage Retrieval-Augmented Agentic Back-End for OpenFOAM-Based CFD | 2026-07-22 | Query expansion into physics/solver-keyword/troubleshooting variants + RRF + MMR over an HNSW store, a deterministic keyword router, and Architect/InputWriter/**Reviewer** split; 28-case benchmark, mean retrieval coverage 77.9%, all six reference configurations run to completion, corrupted cases repaired **from the solver log alone**. | benchmark/scripts released; no GitHub URL on abs page | **medium-high** — OpenFOAM is one of our target simulators and this is the baseline to beat; note it is retrieval-heavy and hand-designed, not evolved |
| **2607.00436** | PHREEQC-MCQ-200: A Diagnostic Benchmark for Tool-Augmented Scientific Simulator Agents | 2026-07-01 | 200 MCQs from 21 validated PHREEQC scenarios requiring agents to construct simulator inputs, execute, and inspect outputs. Simulator access helps in aggregate but **not monotonically — tool-augmented agents lose items they got right without tools**; output-access protocol matters and helps strong models while hurting mid-tier ones. Argues for reporting item-level retention. | no | **high (as evaluation discipline)** — "report item-level retention, not aggregate accuracy" is the same statement as our per-task cliff gate, from the scientific-simulator side |
| **2608.11224** | Harnessing agent memory to build lifelong AI partners for materials scientists | 2026-07-25 | Self-evolving memory storing scientific experience as **inspectable facts and executable skills**; nearly doubles GPT-5.2 success on 49 materials-tool-use questions, converts a wavefunction-initialization failure into a **pre-execution guardrail** (22/1/4 → 25/2/0 Correct/Partial/Error, 92% of repeated errors avoided), and **halves token burden while cutting tool calls by >2×** by round three. | no | **high** — the only paper found where evolved memory *improves* rather than inflates efficiency, which is our hard gate |
| **2607.17352** | Self-Modifying Lean Proof Agents with Verifier-Grounded Benchmark Coevolution | 2026-07-19 | Small trusted runtime wraps a fully mutable workspace (workflow, prompts, tools); **all evolution stays inside a Lean-grounded verification loop** — a success counts only if the behaviour yields Lean-verified proofs under a trusted snapshot — and the champion coevolves a mastery-throttled curriculum with single-anchor recalibration. 45.1% held-out vs 32.0% fixed-benchmark. | no | **medium-high** — the cleanest existing template for "the checker is the reward"; the coevolving curriculum is a good analogue for our probe slice |
| **2606.31763** | A Self-Evolving Agentic System for Automated Generation and Execution of Biological Protocols (ProtoPilot) | 2026-06-30 (v2 07-02) | Layer-wise verifiability + device-level validity gates + a runtime-updated skill library converting protocol text into SDK-compliant code; 89.5% protocol-to-code gate pass rate, 88.24% Opentrons pass vs 32.35% for OpenTrons-AI, with wet-lab confirmation. | no | **medium** — same shape (natural language → validated executable configuration), different domain |
| **2606.23127** | Managing Procedural Memory in LLM Agents: Control, Adaptation, and Evaluation (AFTER) | 2026-06-22 | 382-task enterprise benchmark with controlled local-improvement / cross-task / cross-role / cross-model settings; **a single refinement round gives 3.7–6.7 points**, and skills evolved from **diverse multi-model traces** hit 73.1% cross-model accuracy, beating every single-model trace source. | no | **medium-high** — "one round is most of the gain" and "multi-model traces beat single-model traces" are both directly actionable at our budget |
| **2607.11944** | MAGE: Understanding Stability–Performance Trade-offs in Multi-component Prompt Optimization | 2026-07-11 | Names the **Prompt Optimization Coupling Effect**: stacking stochastic optimization signals in a closed loop raises mean *and* amplifies variance (n=3→5 candidates: +21.6% accuracy, **3.7× variance**). Failure-grounded reflection is essential; **POCE is headroom-dependent and vanishes at high base accuracy**; and **at N_train=30 a well-designed fixed prompt beats every reflective optimizer**. | no | **high (as a warning)** — our N is 17 and our objective is variance; this is the paper most likely to describe our failure mode |
| **2605.14553** | Efficient Multi-objective Prompt Optimization via Pure-exploration Bandits | 2026-05-14 | Casts prompt selection as multi-objective pure-exploration bandits (Pareto set recovery and best-*feasible*-arm identification) with identification-error guarantees in the linear case. | no | **medium** — "best feasible arm" is literally our acceptance shape (maximize score *subject to* an efficiency constraint); needs more pulls than we have unless the validator is the cheap arm |
| **2604.15034** | Autogenesis: A Self-Evolving Agent Protocol | 2026-04-16 (v5 06-20) | Separates *what* evolves (prompts, agents, tools, environments, memory as versioned protocol resources) from *how* (a closed-loop propose/assess/commit operator interface with **auditable lineage and rollback**). | yes (`DVampire/Autogenesis`) | **medium** — a ready-made vocabulary for our manifest + decision log; adopt the interface, not the multi-agent system |
| **2605.18747** | Code as Agent Harness (survey) | 2026-05-18 | Survey framing code as the operational substrate for agent reasoning, acting, environment modelling and **execution-based verification**; names open challenges incl. evaluation beyond final task success, **verification under incomplete feedback**, and **regression-free harness improvement**. | yes (paper list) | **medium** — useful for positioning; its open-challenges list is close to our contribution claims |
| **2608.03392** | Self-Evolving Coding Agents (survey) | 2026-08-04 | Object-centred taxonomy of what evolves, plus when evolution occurs and what software-specific evidence drives it; identifies executable feedback and repository context as SE's distinctive advantage, and feedback reliability / benchmark overfitting / cost as the open problems. | yes (paper list) | **medium** — the current map of the field; good for related work |
| **2607.02882** | Diagnosis-Driven Automatic Repair for Agentic Workflow via Symbolic Inference (FlowFixer) | 2026-07-03 | Symbolic traces → executable behavioural specifications → failure attribution → targeted patches, with a **multi-dimensional pre-execution assessment that filters infeasible repairs before dynamic verification**. 71.3% repair success. | no | **medium** — the pre-execution filter is our "free gates before spending rollouts" idea, independently derived |
| **2601.15808** | Inference-Time Scaling of Verification: Self-Evolving Deep Research Agents via Test-Time Rubric-Guided Verification | 2026-01-22 (v2 04-29) | Rubrics derived from an automatically constructed failure taxonomy drive a plug-and-play outcome verifier at test time; 8–11% gains on GAIA / XBench-DeepSearch **without training**. | no | **low-medium** — rubric-based LLM verification is exactly what 2607.07436 warns about when a real verifier exists |
| **2606.17838** | Environment-Grounded Automated Prompt Optimization for LLM Game Agents | 2026-06-16 | Decomposes observation→action into descriptor and action-selection modules, refines each module's prompt through an LLM evolutionary loop guided by **environment returns**, with a behaviour analyzer attributing outcomes to prompt components. PutNext 0% → 72.5%. | no | **low-medium** — per-component credit attribution from environment return is the right idea; the domain and rollout cost are not ours |
| **2605.09018** | Evolving Ensemble of Agents (EvE) | 2026-05-09 (v4 08-17) | Fixes the base agent substrate and evolves only **cumulative guidance and skills**, with two co-evolving populations scored by synchronous races and Elo on marginal gains; ablations show stage-dependent adaptation is necessary to break static ceilings. | no | **low** — right philosophy, wrong economics (races and Elo need many head-to-heads) |
| **2608.13560** | AutoDesign: Meta-Harness Optimization for Long-Horizon Agentic Design | 2026-08-13 | Meta-harness optimizer guides a code agent to recursively improve a harness from rollout feedback; the learned DesignHarness lifts seven code-agent configurations 54.99 → 67.39 average. Poster generation. | yes (`Yaxin9Luo/AutoDesign`) | **low** — subjective quality objective, rollout-hungry, no verifier |
| **2608.13951** | HELIX: Model-Harness Co-evolution for Recursive Self-Improvement | 2026-08-14 | Source-traceable substrate decomposing agents into typed ports, atoms, recipes, product shells and runtime policies; a 65-candidate portfolio improves coverage 4.0% and yields 438 verified SFT/critic/filter/preference records **for a subsequent model update**. | yes (`HKUDS/HELIX`) | **low (method) / medium (substrate)** — the loop requires model updates; the typed-port decomposition is worth reading for our manifest |
| **2608.11350** | Self-Evolving Embodied Agents via Skill-Harness Evolution (SHAPER) | 2026-08-11 | Train-free embodied adaptation keeping parameters **frozen** while evolving reusable skills and a **context-code harness** through target-environment rollouts; the same frozen model serves as planner and optimizer. Compared against SFT and test-time-scaling baselines. | no | **medium** — good "frozen model, evolve skills+harness, compare against TTS" template; fixed-interface framing matches ours |
| **2608.03137** | Verifiable Memory: Learning Unified Memory Management with Local and Global Verifiers (VerMem) | 2026-08-04 | Seven atomic memory operations under one policy, **initialized by SFT and trained with a three-stage RL curriculum**; local verifier scores memory transitions, global verifier assesses terminal consistency. Verifiers used only during training. | yes (`Sun-SYSU-24/VerMem`) | **low** — requires policy training; violates the frozen-model constraint |
| **2608.05446** | EvoHarness-RL: Learning Self-Evolving Runtime Harness for Long-Horizon LLM Agents | 2026-08-05 | Belief/Progress/Experience harness state learned via **supervised harness fine-tuning + cost-aware GRPO**; 96.9% on ALFWorld with Qwen3-8B; reports "harness annealing" as training internalizes harness-use patterns. | no | **low** — weight updates; out of scope, but "harness annealing" is a good name for the effect we would *not* see with a frozen model |
| **2607.01480** | Procedural Memory Distillation: Online Reflection for Self-Improving Language Models | 2026-07-01 | Converts cross-episode signals into procedural memory and **distils it into the policy's weights**, yielding a memory-free model at inference. | no | **low** — weight updates |
| **2608.02508** | RoMeRL: Balancing Feedback Coverage and the Memory-Reward Trap in Self-Evolving Agent Memory | 2026-08-03 (v3 08-10) | Replaces a growing trajectory-indexed utility space with a **fixed-dimensional per-task memory state**; cuts maintained memory size 84.4%, raises feedback density ~6×, cuts LLM calls 21.1%. RL is over memory utilities, not model weights. | yes (`YOUNG-fnxm/RoMeRL`) | **low-medium** — model stays frozen and the bounded-support idea is right, but concentrating feedback still presumes a feedback stream we do not have |
| **2607.23809** | ACM: Agentic Context Management for Long Horizon Tasks | 2026-07-26 | Agent **autonomously decides when to compress** its context, offloads to external memory and **queries it on demand**; plus a post-training pipeline over context-management demonstrations. | yes (`lixiaochuan2020/agentic-context-management`) | **low** — agent-initiated retrieval is our verified local negative; post-training is out of scope |
| **2607.28692** | SciToolAgent-Evo: An Ontology-Aware Self-Evolving Agent for Open-World Scientific Tool Acquisition | 2026-07-30 | Evolving memory of skills, experiences and an ontologized tool graph; at inference a **LinUCB bandit gate** balances exploration/exploitation over active tool requests. 900-task OpenSciToolBench. | no | **low** — a bandit gate over agent-initiated requests is doubly wrong for us (retrieval-gated + needs many pulls) |
| **2608.15776** | ALKEMIE Agent: an autonomous platform for computational materials design | 2026-08-16 | RAG + materials knowledge base + registered skills + provenance + bounded task execution + error-diagnostic assistance in one traceable control loop; demonstrated on phonon calculations, MLIP training, **LAMMPS simulations**, AIMC sampling. | no | **medium (as prior art)** — hand-designed, not evolved, but it is a LAMMPS-touching agent platform we should cite |
| **2608.13228** | Capability Sheaves for Compositional Agent-Harness Repair | 2026-08-13 | Sheaf-theoretic model of harness component disagreement; on a real SWE-bench-Multilingual discovery split the cohomological selector resolves 118 vs 116 issues, **not supported across repositories (sign-flip p=0.75)** — the authors report the discovery gate as failed. | no | **low** — an honestly reported negative; do not build on it |
| **2608.02639** | Instruction Stacking Collapse: A Benchmark and the Capability-Dependent Value of Prompt Compilation | 2026-07-31 | Stacks 24 verifier-checked instructions one to twenty at a time: instruction-following degrades **non-linearly, from ~96% to as low as 20%**, driven by a reproducible set of pairwise conflicts (one "output JSON" constraint is jointly unsatisfiable with nine others). A training-free instruction compiler recovers up to +11 points **for weaker models only**, leaving strong models unchanged. | benchmark/verifiers released; no GitHub URL on abs page | **medium-high** — our primer plus cheatsheet plus negative constraints *is* a stacked-instruction prompt; this quantifies the cost of adding one more line and predicts the benefit is capability-graded across our cross-model panel |
| **2607.25032** | Authoring Agent Skills: A Software-Engineering Approach | 2026-07-27 | Position note treating an Agent Skill as a software artefact: single responsibility, interface/implementation separation, low coupling, **economy in a shared token budget**, behavioural evaluation in place of deterministic testing; gives a rule for choosing between skills, memory files, hooks, subagents and tools **based on who decides that a mechanism runs**. | no | **medium** — "who decides that a mechanism runs" is exactly the axis on which our MCP-memory experiment failed; useful framing for the paper |

---

## 2. Area 1 — harness / scaffold self-evolution for frozen models

**What changed after TTHE (2607.08124, Jul 9) and EvolveNet (2608.04968, Aug 5).** August 2026 produced a
dense burst. Ordered by relevance to us:

- **DarwinX (2608.07545, Jul 31)** is the most important conceptual advance. Two of its three
  contributions are things we already want and one is a thing we cannot afford. The **preserve-and-extend
  contract** — admit only variants that extend coverage *without regressing* — is our per-task cliff gate
  stated as a selection operator. **Fitness from the benchmark's own verifier, "no gold solutions, no
  hand-picked winners"** is the formal version of what our validator makes possible. The population +
  recombination archive is what we should not copy.
- **HarnessCompass (2608.01918, Aug 3)** is the direct successor to AHE and beats it on both effectiveness
  and evolution efficiency. Its three ideas map cleanly: global constraints restricting edits to
  **task-agnostic** changes (an anti-contamination gate we independently need), **proactive first-person
  feedback** from the agent about harness usage (a cheap evidence channel we do not currently collect —
  ask the agent, in-trajectory, what the primer/cheatsheet failed to tell it), and **component-wise
  optimization then consolidation** (our per-component manifest, with an explicit warning that joint
  optimization causes interference).
- **Evo-Harness (2608.15071, Aug 15)** formalizes **online harness learning under a one-shot-per-task
  opportunity**. That is our budget written down as a problem statement, and it is the newest framing
  available. Code is public.
- **HSI (2608.08466, Aug 9)** runs on **DeepSeek-V4-Flash-Preview**, our cross-model panel member, and
  states two bounds we should quote and test: a **feedback-fidelity bound** (evolution needs informative
  reward, which our TreeSim-at-ceiling barely supplies and our validator does) and a **backbone capability
  bound** (on NLE, harness evolution gave nothing). Its thinking-on/off design — reasoning disabled during
  task execution, enabled during self-modification — is a clean isolation trick.
- **StateM (2608.15089, Aug 15)** is the practical outlier: harness scaling that raises DeepSeek-V4 Flash
  82.7 → 88.1 for **under $38**, and whose central artifact is a *versioned procedural practice* /
  *runbook* turned into **executable preconditions**. That is our constraints-as-checks proposal, shipped.
- **OEO (2608.09629, Aug 10)** is the anti-thesis: with a frontier optimizer, no prescribed pipeline is
  needed at all. Read it as a bound on how much of our machinery is essential — and note its own finding
  that **SkillOpt beats OEO with a medium optimizer**, which is the regime a cheap proposer puts us in.
- Out of scope but worth naming so nobody proposes them: **HELIX 2608.13951** and **EvoHarness-RL
  2608.05446** both require model updates.

**Assessment.** Nothing published supersedes the GEPA-as-outer-loop / Self-Harness-as-gate decision.
What *has* moved is (a) the acceptance criterion — DarwinX's preserve-and-extend and VaG's pre-commit
gating are strictly better statements of the same intent than "regression test", and (b) the evidence
channel — HarnessCompass's proactive first-person feedback and HarnessFix's trace IR are both cheaper
and more targeted than AHE's layered corpus alone.

---

## 3. Area 2 — memory and context evolution (the post-ACE line)

The field has split into three tracks, and only one of them is ours.

1. **Long-horizon context management** (ACM 2607.23809, CrystalMem 2608.00303, RoMeRL 2608.02508,
   VerMem 2608.03137). Concerned with a context that *grows during a task*. Mostly agent-initiated or
   RL-trained. **Not our problem** — our artifact is authored offline and delivered always-on.
2. **Skill/procedural-memory optimization** (SkillOpt 2605.23904, SkillProx 2608.07449,
   SkillRevise 2606.01139, SkillZip 2608.11079, AFTER 2606.23127). This *is* our problem, and it is
   where the strongest recent work is.
3. **Diagnosis of why memory artifacts fail** (Catastrophic Remembering 2608.11095, Demystifying Agent
   Skills 2608.14036, Blind Curator 2607.07436, Rethinking Skills 2608.02636, Fragility 2608.18066).
   These are the papers that should shape our design, and every one of them is Jun–Aug 2026.

**Answer to the brief's specific question — what the field currently considers the strongest method for
evolving an always-on procedural-memory artifact under a hard token budget:** there is no single named
winner, but the *de facto* reference is **SkillOpt (2605.23904)**, on three independent grounds:

- It is the method that explicitly frames the artifact as "the external state of a frozen agent" and
  imports optimizer discipline (bounded edits, a textual learning-rate budget, a rejected-edit buffer,
  strict-improvement acceptance on held-out validation, epoch-wise slow/meta updates).
- **OEO (2608.09629) picks SkillOpt and GEPA as the two prescribed pipelines worth beating** — that is the
  field naming its own state of the art — and finds SkillOpt wins when the optimizer is only medium-strength.
- It is one of very few methods evaluated **inside Claude Code** as an execution harness (alongside direct
  chat and Codex), with transfer across harnesses demonstrated.

But SkillOpt alone does not enforce a token budget; its budget is on *edit size*, not artifact size. The
budget mechanism the field has converged on is **SkillZip (2608.11079)**: an MDL objective over a typed
skill contract with a hard coverage constraint per extracted trigger/workflow-edge/tool-requirement/
obligation/output-field, and — crucially for us — it is **evaluation-free**, costing one structured
extraction call rather than rollouts. Its "explain once, reference many" factoring is also the right shape
for a cheatsheet full of near-duplicate GEOS block templates.

And the missing third piece is **why deletion never happens**, answered by **Catastrophic Remembering
(2608.11095)**: appending is cheap, but once an instruction's rationale is lost, deleting it safely costs
O(2^|D|). Their fix — prompt comments encoding the latent rationale — removed 99.3% of excess instructions
in verifiable worlds. Our v1 grew 12× monotonically; this is the mechanism, and the fix is one column in
`constraints.yaml`.

---

## 4. Area 3 — sparse / near-ceiling reward and sample-efficient search

This is where the sweep paid off most, because two Aug-2026 papers address our exact pathology.

- **RLMOpt (2608.10471, Aug 11)** contributes two things. First, a **no-regression floor**: it returns the
  seed prompt rather than accept a noisy candidate with a lower score, and across 11 runs it *never*
  produced a prompt below its seed while GEPA did twice. Second, and more important, its headline
  conclusion: **"optimization gains are determined primarily by the headroom available in the seed prompt,
  rather than by the search budget."** Our in-distribution scores sit at 0.86–0.92 against a hand-designed
  seed adapter. That sentence is a prediction that our in-distribution search will find nothing, and that
  the only place headroom exists is the tail. It argues for making the *tail* the objective explicitly,
  not hoping the mean finds it.
- **MAGE (2607.11944, Jul 11)** names the **Prompt Optimization Coupling Effect** — stacking stochastic
  optimization signals inside a closed reflective loop raises the mean *and* amplifies variance (3.7× when
  going from 3 to 5 candidates). Two of its findings are direct threats: **POCE is headroom-dependent and
  disappears when base accuracy is already high** (so we may see the variance without the gain), and
  **at N_train=30 a well-designed fixed prompt beat every reflective optimizer, "scaffold choice dominates
  optimizer choice."** Our N is 17. This is the strongest published reason to expect our search to lose to
  its own seed, and it should be pre-registered as a kill criterion.
- **SEA (2607.00871, Jul 1)** is the constructive answer: confine self-modification to a **steering adapter
  and versioned harness around a frozen base**, and admit each modification only through an
  **anytime-valid gate emitting an auditable certificate against a fixed error budget**. Anytime-validity
  is exactly the property you want when you cannot afford a pre-committed sample size — you may peek after
  every seed and stop when the certificate clears. It also supplies **five verifier-in-the-loop mechanisms
  to generate the dense, grader-free signal the gates require**, computed from the task statement alone.
  Caveat, stated by the authors: results are single-run.
- **Rethinking Skills (2608.02636, Jul 31)** quantifies the sparsity: **55 of 388 candidates** produced a
  byte-distinct validation best, and validation-based selection picked an evolved skill in 11 of 14
  settings with 9 improving test. Also runs the test-time-scaling controls our §4.1 baselines demand, and
  finds oracle parallel sampling comes within 0.43 points on one benchmark but is 30.96 behind on another.
- **Fragility (2608.18066, Aug 18)** is the newest and closest to our measurement problem: multiple runs
  plus **shuffled task order** show evaluation noise is amplified by the self-improving loop and that
  default task orderings impose a hidden curriculum. Our v1 fed each round a *different* task slice; this
  paper says that alone could produce the entire observed trajectory.
- **Pure-exploration bandits (2605.14553, May 14)** supplies the formal object for "maximize score subject
  to an efficiency constraint": **best feasible arm identification**. Worth reading for the acceptance
  rule's shape even though we cannot afford the pull counts.

**Assessment.** Nothing here is free. The honest reading of RLMOpt + MAGE + 2608.02636 together is that a
sample-starved search against a near-ceiling in-distribution metric is expected to return its seed. The
design response is to (a) make the objective the tail (zero-rate, per-task min) rather than the mean,
(b) move the cheap signal to the validator so that most acceptance decisions cost no TreeSim rollouts, and
(c) use an acceptance rule with an explicit error budget (SEA) rather than an unqualified "did it improve".

---

## 5. Area 4 — verifier-grounded / execution-grounded evolution

Our biggest untapped asset, and the fastest-moving area.

- **DarwinX (2608.07545)**: "Fitness comes from each benchmark's own verifier: no gold solutions, no
  hand-picked winners." The cleanest statement of the principle, with four benchmarks behind it.
- **VaG (2608.05810)**: the strongest *result* in this area. Skill accumulation is non-monotonic; the
  contamination is **structurally irreversible** because a defective artifact becomes reference material
  for later ones, so **post-hoc rollback recovers only a fraction**; therefore admission must be
  **pre-commit**. Three heterogeneous critics — structural validity, behavioural harmlessness, semantic
  consistency — are shown to be complementary and non-substitutable, and a marginal-gain subset selection
  removes combinatorial contamination. Result: 72% pass@1 with a ~5× smaller pool, transferring frozen to
  four other backbones. **`geosx --validate-input` is a ready-made structural-validity critic**, and our
  contamination gate is a ready-made second critic.
- **SkillRevise (2606.01139)**: "retain the **first verifier-passing** candidate within the revision
  budget, fall back to empirical utility only when none passes." This is the cheapest acceptance rule in
  the literature and it is exactly implementable against our validator. It is also explicitly designed for
  **cold start from an imperfect initial skill**, which is our situation with the hand-designed adapter.
- **Self-Modifying Lean Proof Agents (2607.17352)**: a small trusted runtime around a fully mutable
  workspace, where **a success counts only when the behaviour yields verifier-checked output under a
  trusted snapshot**, plus a coevolving mastery-throttled curriculum with single-anchor recalibration to
  keep scores comparable as difficulty rises. The recalibration trick is directly transferable to our
  fixed-anchor-slice design.
- **Blind Curator (2607.07436)** is the constraint that makes all of the above matter: a **false-pass**
  biased judge past a threshold **silently disables** contribution-based retirement, and the paper finds
  only "near-zero-false-pass, **verifier-like graders**" are spared. If we ever consider an LLM judge for
  the retirement signal, this is the reason not to.
- **RIZZ (2606.20638)** contributes **verifier-gated writes** — only verified interactions may update
  memory, promote rules, demote harmful rules, or create **anti-patterns** — which is a memory-side
  formulation of the same principle and gives a name (anti-pattern) to our negative-constraint class.
- **PACE-Bench (2608.14441)** supplies the external evidence: across ten self-evolving methods over 144
  simulator-grounded adaptation pairs, **simulator-grounded reflection is more reliable than unverified
  self-revision**, while memory anchors agents to early designs.

**Assessment.** The field has converged on "the environment's own checker is the reward" within the last
three months, and every paper that says so is newer than our current shortlist. We have a *stronger*
verifier than any of them: `geosx --validate-input` does not just return pass/fail, it prints the valid
attribute table and the ~50 valid solver types inline. Nobody is exploiting a **repair-directive**
verifier. See §9.

---

## 6. Area 5 — demonstration-bootstrapped adaptation

The thinnest area, and the one where our assets are most unusual.

- **DemoEvolve (2605.24539)** remains the only method whose stated purpose is using demonstrations to
  overcome sparse feedback in harness evolution. Nothing published since supersedes it.
- **DarwinX (2608.07545)** adds the useful architectural point that **failure-, teacher-, and self-derived
  evidence share one edit interface** — i.e. demonstrations should enter the search as just another
  evidence source over the same action space, not as a separate pipeline.
- **AFTER (2606.23127)** contributes the most actionable empirical result: skills evolved from **diverse
  multi-model execution traces** reach 73.1% cross-model test accuracy, **outperforming all single-model
  trace sources**, and **a single refinement round already delivers 3.7–6.7 points**. For a
  sample-starved loop, "one round from diverse traces" is the highest-value configuration reported.
- **SkillRevise (2606.01139)** contains the sharpest observation about human demonstrations:
  expert-authored skills are "costly and may not align with how LLM agents actually execute tasks", while
  one-shot LLM-authored skills are "syntactically well formed yet behaviorally weak". This is an argument
  for using expert traces as *evidence about what to know*, not as *the artifact*.
- **Evo-Harness (2608.15071)** notes that one-shot executions yield "rich but highly noisy contexts,
  entangling broadly useful lessons with task-specific artifacts" — which is the contamination hazard of
  mining our expert traces, stated by someone else.

**Assessment.** Nobody has published on using **human expert demonstrations with information-seeking
traces** (browser histories) to bootstrap harness or prompt search. We have that. See §9, gap 3.

---

## 7. Area 6 — evaluation discipline

Everything below is newer than SEAGym 2606.17546 and Rethinking-Eval 2607.12227, and all of it tightens
rather than loosens the protocol.

- **Fragility (2608.18066, Aug 18)** — report **multiple runs** and stress-test under **shuffled task
  order**; the self-improving loop amplifies evaluation noise; default orderings are a hidden curriculum.
  Code released. This is the single most important addition to our evaluation tier.
- **Rethinking Skills (2608.02636, Jul 31)** — the model protocol: hold executor, optimizer,
  revision procedure, validation rule and round budget fixed and vary exactly one thing; count how many
  candidates produce a **byte-distinct validation best**; run **test-time-scaling controls** (parallel
  sampling and sequential refinement) at matched budget. This is §4.1 of the adoption plan, executed.
- **PHREEQC-MCQ-200 (2607.00436, Jul 1)** — from the scientific-agent side: report **item-level retention**
  (which items you *lost*), output-access sensitivity, trajectory failures, and where the computation chain
  breaks — not aggregate accuracy. Non-monotonic tool gains are exactly our two-rescues-and-noise pattern.
- **Evo-Bench (2608.09096, Aug 10)** — construct evaluation so that harness improvement is isolated from
  base model strength (auxiliary-task evolution to find framework-sensitive tasks; sensitivity-aware
  stratified splitting). Names **early saturation** as a temporal anomaly to look for.
- **EvoAgentBench (2607.05202, Jul 6)** — the benchmark to cite for "curated content transfers reliably,
  **but no current automatic method sustains positive gain in all settings**."
- **AgentStream (2608.00155, Jul 31)** — benefit is **gated by model capability and non-monotonic in model
  strength**; no single method dominates. Confirms 2605.30621 and justifies the cross-model panel.
- **Don't Blame the LLM (2607.03691, Jul 4)** — the controlled longitudinal design (fix the model, vary
  35 sequential harness releases) is the cleanest existing demonstration that harness deltas are
  attributable, and a good citation for why the harness is the right object of study.
- **Phantom Guardrails (2607.13083, Jul 13)** — add a **counterfactual-fabrication audit**: plant a
  condition where the correct edit is *do nothing* and measure how often the proposer invents a violation.
  15/60 on rule-shaped legal input. Our proposer's brief is literally "add negative constraints".

---

## 8. What supersedes what

### 8.1 The headline: ACE (2510.04618) should be replaced

**Recommendation: replace ACE with SkillOpt (2605.23904) as the optimizer, SkillZip (2608.11079) as the
budget-enforcement operator, and the rationale-comment representation from Catastrophic Remembering
(2608.11095) as the item schema. Keep exactly one thing from ACE: the itemized add/update/delete/keep
delta vocabulary.**

**Why ACE has to go, evidenced.** RIZZ (2606.20638), which calls ACE "one of the strongest published
online-learning baselines and an architectural inspiration", documents in its Appendix C — text I fetched
and read directly — that in the released ACE implementation:

> "The token budget is advisory rather than enforced. ACE inserts the playbook budget into the prompt as a
> textual instruction instead of truncating memory after updates. In practice, the model ignores the
> constraint. Under the published 80K setting, the playbook exceeds 130K tokens by step 290 on StreamBench.
> On TRACE, prompts eventually overflow Haiku's context window entirely, producing hard failures rather
> than incorrect answers."

RIZZ names two further issues: "Per-record pruning dominates runtime" and "The released implementation does
not support conversational memory benchmarks", and had to add **hard truncation** as a fairness workaround
rather than a faithful reproduction.

That is disqualifying for us specifically. Our M is **775 tokens, always-on, on every turn of every run**,
under an efficiency **gate** — an adapter that wins on score while inflating tokens is defined as a failure.
ACE's grow-and-refine has no enforcement mechanism, and we already reproduced the failure locally: v0→v3
grew the primer 270 B → 3,159 B and the cheatsheet 0 → ~4.5 KB, monotonically, exactly as
2608.11095 predicts for an append-cheap/delete-expensive artifact.

**Why SkillOpt is the replacement.**

1. **It optimizes our object.** A single skill document treated as the external state of a **frozen** agent
   — not a growing playbook, not a retrieved memory store.
2. **Its acceptance rule is ours.** An edit is accepted only when it **strictly improves** a held-out
   validation score; there is a rejected-edit buffer so failed edits are not silently re-proposed. That is
   Self-Harness's regression gate at the item level.
3. **Its budget is structural, not advisory.** Bounded add/delete/replace edits plus a textual
   learning-rate budget cap how much can change per step, which is what stopped ACE-style drift.
4. **It satisfies the efficiency gate by construction**: "zero inference-time model calls at deployment."
5. **It was evaluated in our harness.** Three execution harnesses including **Claude Code**, with transfer
   between Codex and Claude Code demonstrated, and it beats GEPA, TextGrad, Trace2Skill, EvoSkill,
   one-shot LLM, and human skills on all 52 (model, benchmark, harness) cells.
6. **The field treats it as the reference.** OEO (2608.09629) benchmarks against SkillOpt and GEPA as *the*
   two prescribed pipelines, and finds SkillOpt wins when the optimizer is medium-strength — our regime,
   given 2605.30621's cheap-proposer economics.
7. **Public code** at `microsoft.github.io/SkillOpt` (redirect from `aka.ms/skillopt`, verified).

**Where SkillOpt is weak for us, and what patches it.** Its acceptance needs a held-out validation score
per edit, i.e. rollouts, and we have ~17 tasks × 2–3 seeds. Three patches, all from papers verified above:

- Move most acceptance decisions onto the **validator**, per SkillRevise's "retain the first
  verifier-passing candidate" (2606.01139) and DarwinX's verifier-only fitness (2608.07545). TreeSim is
  then spent only on the round-level gate, not per edit.
- Enforce artifact size with **SkillZip** (2608.11079), which is **evaluation-free** — one structured
  extraction call and deterministic MDL optimization, with a hard coverage constraint that provably
  preserves rare rules (our "exactly *k* Constitutive children" negative constraints) and a Zip-on-Write
  mode that integrates each patch without replaying tasks.
- Make deletion decidable by attaching each item's **rationale as a comment** (2608.11095): which failure
  it was written for, which check enforces it, which task family it was observed on. This also makes AHE's
  decision observability a property of the artifact rather than of a side log.

**Alternatives considered and rejected as the ACE replacement:**

| Candidate | Why not |
|---|---|
| ACM 2607.23809 | Agent-*initiated* context editing tools; our `memory_lookup` MCP tool was called zero times. Also ships a post-training pipeline. |
| RIZZ 2606.20638 | Verifier-gated writes are right, but the delivery path is router + branch retrieval. Take the anti-pattern idea, not the architecture. |
| CrystalMem 2608.00303 | Solves *elastic* byte budgets; ours is fixed. Its hysteresis proof is a good argument for keeping rationales, which 2608.11095 already gives us more cheaply. |
| SkillProx 2608.07449 | The frozen leave-one-out utility audit is the ideal way to find dead cheatsheet lines, but it costs \|units\| × rollouts. Revisit once the audit can run against the validator. |
| Living-Harness 2607.26598 | Bounded updates are good; the evolved state is **retrieved** at inference. |
| AutoMem / MemSkill / EvolveMem / Janus (already known) | None enforces a hard artifact budget, which is the specific thing ACE gets wrong. |

### 8.2 Other supersessions

| Currently on the shortlist | Superseded / strengthened by | Nature of the change |
|---|---|---|
| **AHE 2604.25850** (observability pillars) | **HarnessCompass 2608.01918** | Directly outperforms AHE in effectiveness *and* evolution efficiency; adds task-agnostic edit constraints, first-person agent feedback, and component-wise-then-consolidate optimization to fix AHE's overfitting. Keep AHE's three-pillar vocabulary; adopt HarnessCompass's three fixes. |
| **AHE pillar 2** (evidence corpus) | **HarnessFix 2606.06324** | Gives the corpus a schema (Harness-aware Trace IR with step-level data/control flow aligned to harness artifacts) plus failure attribution to *responsible artifacts*, which is what our proposer actually needs. |
| **Self-Harness 2606.09498** (regression gate) | **DarwinX 2608.07545** preserve-and-extend + **VaG 2608.05810** pre-commit gating + **SEA 2607.00871** anytime-valid certificate | Three strictly sharper statements of the same intent: extend-without-regressing as a *contract*; admission must be *pre-commit* because contamination is irreversible; and acceptance should carry an *error budget*, not just a comparison. |
| **GEPA 2507.19457** (outer loop) | **RLMOpt 2608.10471** — *complement, not replacement* | Keep GEPA as the library (Pareto archive, budget accounting, module selector). Add RLMOpt's **no-regression floor** (return the seed rather than accept a noisy lower-scoring candidate) — GEPA fell below its seed twice in 11 matched runs; we cannot afford that at n=2–3. |
| **TTHE 2607.08124** (execution-derived proxies at test time) | **DarwinX / SkillRevise / 2607.17352** | Not superseded, but generalized: the same "no gold, use the checker" principle now has train-time formulations with acceptance rules attached. |
| **Retrieval-gated memory** (our local negative) | **Demystifying Agent Skills 2608.14036** | External confirmation: retrieval actual-use precision falls 29.6% → 3.3% as the pool grows 5 → 100, and skills work as *procedural anchors* (65.7%) rather than knowledge injection (4.5%). Our zero-call result is now a published phenomenon, not an anecdote. |
| **§5.3 negative constraints as checkable artifacts** | **StateM 2608.15089** + **RIZZ anti-patterns 2606.20638** | Partially anticipated: StateM turns postmortem findings into "persistent, executable preconditions"; RIZZ creates "anti-patterns" from verified failures. Our novelty narrows to the **dual prose/check compilation from one source entry** and the demonstration that it moves `extra_block`. Adjust the claim accordingly. |
| **§5.4 attribute-level oracles** | **JutulGPT 2603.00214** | Confirms the plan's own conclusion: this is engineering. JutulGPT adds a threat we should adopt — **choices resolved tacitly through simulator defaults are invisible to any assumption log**, which is a named blind spot for validator-only scoring. |

---

## 9. You should NOT adopt this, and here's why

| Method | Looks attractive because | Fails on |
|---|---|---|
| **EvoHarness-RL 2608.05446** | 96.9% on ALFWorld; "harness annealing" is a beautiful result | **SFT + GRPO on the policy.** Violates the frozen-model constraint outright. |
| **HELIX 2608.13951** | Typed-port substrate is the best-engineered manifest in the literature | The loop's *point* is producing SFT/critic/preference data for a model update. Read the substrate; do not run the loop. |
| **VerMem 2608.03137** | Local + global verifiers over memory operations is our exact framing | Initialized by SFT, trained with a three-stage RL curriculum. Verifiers are training-time only. |
| **PMD 2607.01480** | "Procedural memory" in the title | Distils the memory **into the weights**. |
| **ACM 2607.23809** | Lossless context management with a real code release | **Agent-initiated** compression and on-demand querying — our `memory_lookup` tool was called zero times while functional. Also has a post-training pipeline. |
| **SciToolAgent-Evo 2607.28692** | A self-evolving *scientific* agent, superficially our domain | A **LinUCB bandit gate over agent-initiated tool requests**: retrieval-gated (fails our local negative) *and* bandit-gated (needs pulls we do not have). |
| **Living-Harness 2607.26598** | Bounded updates, frozen tools and base context, code coming | The evolved episodic memory and state graph are **retrieved** to guide future interactions. |
| **DarwinX 2608.07545** *as a loop* | Best contract and best fitness definition in the sweep | A **population with recombination across lineages** needs many evaluations per generation. Take the preserve-and-extend contract and verifier-only fitness; leave the population. |
| **EvE 2605.09018** | Fixes the substrate, evolves only guidance — philosophically identical to us | Synchronous **races** and **Elo** ratings require many head-to-head rollouts per candidate. |
| **AutoDesign 2608.13560** | Meta-harness optimizer with public code and a real long-horizon loop | Subjective quality objective with no verifier, 253 tool calls per rollout. Nothing about it survives contact with a $0.07/task-run budget. |
| **OEO 2608.09629** | 12–1–1 against SkillOpt and GEPA using a third of the token budget | Explicit **capability boundary**: SkillOpt wins with a medium optimizer, and a weak optimizer cannot use the interface at all. 2605.30621 says our proposer should be cheap. Also spends its budget on unconstrained agentic interaction, which is exactly the efficiency risk our gate exists to catch. |
| **MAGE 2607.11944** *as a method* | Beats GEPA by 12.4 points on GSM8K-Hard | The authors say plainly it is "not proposed as a superior optimizer". Adopt the **POCE warning**, not the optimizer — and note their own finding that at N_train=30 a fixed prompt beat every reflective optimizer. |
| **Capability Sheaves 2608.13228** | Elegant formalism for component interference, our exact problem | The authors report their own discovery gate as **failed** (sign-flip p=0.75; the confirmatory split stays sealed). Honest negative result; do not build on it. |
| **DeepVerifier 2601.15808** | Plug-and-play test-time verification, no training, 8–11% gains | Rubric-based **LLM** verification. 2607.07436 shows a false-pass-biased judge silently disables retirement past a threshold and spares only verifier-like graders. We have a real verifier; using an LLM judge instead would be a self-inflicted wound. |
| **Retrieval-augmented simulator agents generally** (IteraSim RAG 2607.20346, ALKEMIE 2608.15776) | Strong engineering, our exact simulators | These are hand-designed retrieval systems, not evolved adapters. Cite as baselines and prior art; do not treat their architecture as the method. |
| **CrystalMem 2608.00303 / RoMeRL 2608.02508** | Serious memory-efficiency results | Solve budget *elasticity* and *feedback density* problems we do not have; both presume a task stream long enough to accumulate utility statistics. |

---

## 10. Explicit gaps — what nobody has done that we are unusually well-positioned to do

1. **A repair-directive verifier as the evolution signal.** Every verifier-grounded method found
   (DarwinX 2608.07545, VaG 2608.05810, SkillRevise 2606.01139, 2607.17352, TTHE 2607.08124) consumes a
   **pass/fail or scalar** verifier. `geosx --validate-input` emits the *valid attribute table* and the
   ~50 valid solver types **inline** when it rejects a deck. That is a gold-free channel that names the
   correct action space, not just the fact of failure — which means the negative-constraint artifact class
   can be **derived automatically from verifier output** rather than proposed by an LLM. Nobody has an
   evolution loop whose evidence channel is machine-generated repair directives.
2. **Selection on the tail rather than the mean, at a near-ceiling metric.** RLMOpt (2608.10471) states
   that gains are set by seed headroom; 2608.02636 shows evolution is sparse; MAGE (2607.11944) shows
   variance amplification vanishes at high base accuracy. Nobody has run harness search where the
   **objective itself is the zero-rate / per-task minimum** and in-distribution mean is explicitly
   conceded as saturated. Our archive is already Pareto-over-per-task-scores; making the tail the declared
   objective and reporting the zero-rate as the primary metric is a genuinely unclaimed position.
3. **Paired human-expert and agent traces on the same tasks, including information-seeking behaviour.**
   DemoEvolve (2605.24539) uses demonstrations; DarwinX (2608.07545) admits "teacher-derived evidence"
   into the edit interface; SkillRevise (2606.01139) observes that expert-authored skills "may not align
   with how LLM agents actually execute tasks". Nobody has the object we have: two domain experts authoring
   decks under observation **with browser histories**, plus agent trajectories on the same tasks. The
   derived quantity — *what the expert looked up that the agent never did* — is a principled, contamination-
   auditable generator for an always-on primer, and it does not exist in the literature.
4. **Efficiency as an acceptance gate, not a reported metric.** 2608.11224 shows evolved memory can *halve*
   token burden and cut tool calls >2× in a scientific-simulation setting; RLMOpt reports prompt sizes;
   HarnessCompass reports evolution efficiency. But no harness-evolution paper makes **non-inflation of
   tool calls and wall-clock a hard rejection criterion**. Pairing that gate with SkillZip's evaluation-free
   compression gives a defensible "reliability at constant cost" claim that nobody currently makes.
5. **Binding-constraint discovery across simulator interfaces.** HSI (2608.08466) gets closest with its
   feedback-fidelity and backbone-capability bounds, and HarnessCompass (2608.01918) decouples components
   to avoid interference — but neither *infers which component binds* from an unseen interface's failure
   signature and reallocates budget accordingly. With GEOS (structure-bound) and LAMMPS (value-bound)
   answers already known from the SIGA factorial, we have a retrospective validation set for exactly this.
6. **A counterfactual-fabrication audit on a real scientific harness.** Phantom Guardrails (2607.13083)
   demonstrates fabricated guardrails in a synthetic micro-lab with a byte-exact oracle. We have a
   **real** byte-exact oracle (the validator) and a proposer whose brief is literally "add negative
   constraints". Running their audit on our loop, and reporting the fabrication rate, would be the first
   deployment of that audit outside its own paper.
7. **Tacit simulator defaults as an unmeasured failure class.** JutulGPT (2603.00214) reports that
   "choices resolved tacitly through simulator defaults are invisible to the assumption log and to any
   downstream representation". That is a live threat to validator-as-reward: a deck can validate *because*
   defaults filled the gap. Nobody has quantified how much of a validator-grounded score is default-filled.
   Our `treesim_detail` per-section scores plus the validator give us the two views needed to measure it.

