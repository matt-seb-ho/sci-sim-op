# W7 — verified literature sweep, August 2026

**Date:** 2026-08-19 · **Output:** `docs/LITERATURE_2026-08.md`
**Brief:** find what is current as of Aug 2026 across seven areas, emphasis Jun–Aug 2026; verify every
arXiv ID against its abs page; do not report anything not fetched.

---

## 1. Method

### 1.1 Context read first
- `repo4/docs/ARCHITECTURE.md` (whole file).
- `repo3/docs/2026-08-19_method-adoption-plan.md` §0, §1 (all subsections, for the failure evidence),
  §2 (ranked shortlist + declined table), §4 (evaluation protocol), §5 (novel-method opportunities), §6.
  Read via section-index grep then targeted `sed -n` ranges rather than the whole 913-line file.

### 1.2 Discovery
Two channels, used in that order:

1. **WebSearch** for orientation — 8 queries covering harness self-evolution, post-ACE context
   evolution, verifier-grounded evolution, sample-efficient / near-ceiling prompt search,
   demonstration-bootstrapped adaptation, evaluation discipline, and scientific-simulator agents.
   Useful for finding named methods, unreliable for recency ranking.
2. **arXiv Atom API**, which turned out to be far better and is what most of the sweep ran on:
   `http://export.arxiv.org/api/query?search_query=<q>&sortBy=submittedDate&sortOrder=descending`.
   Script at `<scratch>/apiq.py`. Queries run (each returning 12–60 results, newest first):
   - `all:"harness evolution"` — the single highest-yield query; returns the complete
     Apr 2026 → Aug 2026 harness-evolution line in date order.
   - `all:"self-evolving agent"`
   - `all:"procedural memory" AND all:agent`
   - `all:"context engineering" AND all:evolving`
   - `abs:"prompt optimization" AND abs:"sample efficient"`
   - `abs:verifier AND abs:"self-evolving"`
   - `abs:"input deck" OR abs:OpenFOAM OR abs:LAMMPS`
   - `abs:"demonstrations" AND abs:"agent" AND abs:"harness"`
   - `abs:"expert trajectories" AND abs:"prompt"`
   - `abs:"headroom" AND abs:"prompt"`
   - `abs:"always-on" AND abs:agent`
   - `abs:"token budget" AND abs:"memory" AND abs:agent`
   - `abs:"sparse reward" AND abs:"prompt optimization"`
   - `abs:"human demonstrations" AND abs:"LLM agent"`
   - `abs:"cold start" AND abs:"self-evolving"`
   - `abs:"validator" AND abs:"agent" AND abs:"self-improve"`
   - `abs:"seeds" AND abs:"variance" AND abs:"agent" AND abs:"benchmark" AND abs:"evaluation"`
   - `abs:"few-shot" AND abs:"harness" AND abs:"evolution"` *(no useful hits)*
   - `abs:"execution feedback" AND abs:"evolution" AND abs:"frozen model"` *(zero hits)*
   - `abs:"seed" AND abs:"demonstrations" AND abs:"context optimization"` *(zero hits)*
   - `abs:"trace" AND abs:"expert" AND abs:"skill" AND abs:"agent" AND abs:2026` *(zero hits)*

### 1.3 Verification
Script at `<scratch>/fetch.py`: fetches `https://arxiv.org/abs/<id>` and extracts
`citation_title`, `citation_date`, the `dateline` div (submission + revision history),
the subject line, the full `blockquote.abstract` text, and every `github.com` URL on the page.
I read each abstract before writing anything about the paper.

**61 IDs fetched and confirmed.** Every ID in `docs/LITERATURE_2026-08.md` is from this set.
No ID failed to resolve. No abstract contradicted what the search snippet had suggested, with one
partial exception noted in §4.

Additional verification steps beyond the abs page:
- **RIZZ 2606.20638** — fetched `https://arxiv.org/html/2606.20638v1` and grepped the rendered text,
  because the ACE critique is in Appendix C and not in the abstract. Confirmed verbatim: *"The token
  budget is advisory rather than enforced. ACE inserts the playbook budget into the prompt as a textual
  instruction instead of truncating memory after updates. In practice, the model ignores the constraint.
  Under the published 80K setting, the playbook exceeds 130K tokens by step 290 on StreamBench. On TRACE,
  prompts eventually overflow Haiku's context window entirely, producing hard failures rather than
  incorrect answers."* The two other issues RIZZ names are *"Per-record pruning dominates runtime"* and
  *"The released implementation does not support conversational memory benchmarks"*, with workarounds
  labelled "ACE-tuned" and "ACE hard-capped". This is the load-bearing evidence for the ACE replacement
  recommendation, so it was worth the extra fetch.
- **SkillOpt 2605.23904 code link** — the abs page has no `github.com` URL; the abstract's link is
  `https://aka.ms/skillopt`. Resolved the redirect with `curl -sIL`: `301 →
  https://microsoft.github.io/SkillOpt/`. Public code confirmed, Microsoft-hosted.
- **EvoAgentBench 2607.05202** — abstract link resolves to a HuggingFace dataset
  (`huggingface.co/datasets/EverMind-AI/EvoAgentBench`), not a code repo. Reported as such.
- **JutulGPT 2603.00214 / RLMOpt 2608.10471 / SEA 2607.00871** — checked for in-abstract hyperlinks;
  none present. JutulGPT's abstract asserts code/prompts/logs are public but gives no URL on the abs page.

---

## 2. What was verified (61 IDs, grouped by area)

**Harness / scaffold self-evolution:** 2608.07545 (DarwinX), 2608.01918 (HarnessCompass),
2608.15071 (Evo-Harness), 2608.08466 (HSI), 2608.09629 (OEO), 2608.15089 (StateM),
2608.11350 (SHAPER), 2605.22166 (Life-Harness), 2607.26598 (Living-Harness), 2606.06324 (HarnessFix),
2607.13285 (Harness Handbook), 2607.03691 (Don't Blame the LLM), 2607.02882 (FlowFixer),
2608.13951 (HELIX), 2608.05446 (EvoHarness-RL), 2608.13560 (AutoDesign), 2605.09018 (EvE),
2604.15034 (Autogenesis), 2608.13228 (Capability Sheaves), 2608.03392 (survey),
2605.18747 (Code as Agent Harness survey).

**Memory / context evolution:** 2605.23904 (SkillOpt), 2608.11079 (SkillZip), 2608.07449 (SkillProx),
2606.01139 (SkillRevise), 2606.23127 (AFTER), 2608.11095 (Catastrophic Remembering),
2608.14036 (Demystifying Agent Skills), 2607.07436 (Blind Curator), 2606.20638 (RIZZ),
2607.23809 (ACM), 2608.00303 (CrystalMem), 2608.02508 (RoMeRL), 2608.03137 (VerMem),
2607.01480 (PMD), 2607.25032 (Authoring Agent Skills).

**Sparse / near-ceiling / sample-efficient:** 2608.10471 (RLMOpt), 2607.11944 (MAGE),
2607.00871 (SEA), 2605.14553 (pure-exploration bandits), 2608.02636 (Rethinking Skills),
2608.18066 (Fragility), 2608.02639 (Instruction Stacking Collapse).

**Verifier-grounded evolution:** 2608.05810 (VaG), 2607.17352 (Lean coevolution),
2601.15808 (DeepVerifier), 2606.17838 (env-grounded APO).

**Evaluation discipline:** 2608.09096 (Evo-Bench), 2607.05202 (EvoAgentBench),
2608.00155 (AgentStream), 2607.13083 (Phantom Guardrails), 2607.00436 (PHREEQC-MCQ-200).

**AI-for-science / simulator agents:** 2603.00214 (JutulGPT), 2608.14441 (PACE-Bench),
2608.15881 (MOOSEnger), 2607.20346 (IteraSim RAG), 2608.15776 (ALKEMIE),
2608.11224 (materials lifelong memory), 2606.31763 (ProtoPilot), 2607.28692 (SciToolAgent-Evo).

**Smoke test:** 2507.19457 (GEPA) — re-fetched once to confirm the extraction script worked against a
known-good target before trusting it. Title, ICLR-2026 status implied by v2 revision date (14 Feb 2026),
and `github.com/gepa-ai/gepa` all matched the prior record.

---

## 3. Seen in arXiv API listings but NOT abstract-verified

Title and submission date come from the arXiv API (so those two fields are reliable), but I did **not**
fetch and read the abstracts, so nothing about their content is asserted anywhere in the deliverable.
Listed here as a backlog for a future sweep. Anyone using these must verify first.

- 2608.17684 (2026-08-18) Auditing Self-Evolution in Financial Agents
- 2608.15763 (2026-08-16) TaoLive Digital Avatar Agent Technical Report: Training Agents to Evolve with Their Harness — *name suggests training; likely out of scope*
- 2608.12629 (2026-08-12) CAKE: Compiler-Agent Co-Design for Frontier Kernel Evolution
- 2608.12720 (2026-08-13) ERSkill: Evolving for Skill-Guided Adaptive Memory Retrieval — *retrieval-gated; likely out of scope*
- 2608.10504 (2026-08-11) MEGA: Self-Evolving Agent Optimization Infrastructure via Wisdom Graph
- 2608.10494 (2026-08-11) GeoForge: Non-Parametric Self-Evolving Agents for Earth-Observation Reasoning
- 2608.09885 (2026-08-10) SHE: Trajectory-driven Safety Harness Evolution for LLM Agents
- 2608.09044 (2026-08-10) Tree-of-Experience: Hierarchical Experience Management for Self-Evolving Agents
- 2608.02113 (2026-08-03) MemArbiter: Decision-Time Memory Arbitration for Long-Horizon LLM Agents
- 2608.01759 / 2608.05563 / 2608.03509 / 2608.08303 — trajectory-poisoning and skill-backdoor papers; security angle, not method
- 2607.29468 (2026-07-31) Self-Play Meets Skill Evolution
- 2607.29104 (2026-07-31) Reproducing LightMem: Naive RAG Is Just as Good for Memory Management — *possibly relevant to the retrieval negative*
- 2607.15758 / 2606.20047 / 2606.05894 / 2606.06337 — context-budget / submodular-selection papers
- 2606.29824 (2026-06-29) Neural Procedural Memory: activation steering — *steering, not text; likely out of scope*
- 2608.17504 (2026-08-18) Agentic Porting … Multi-Phase Advanced Reactor simulation Kit — *nuclear multiphysics; possibly close prior art*
- 2607.07663 (2026-07-08) Recursive Self-Improvement in AI (survey)
- 2606.20683 (2026-06-14) From Question Answering to Task Completion: A Survey on Agent System and Harness Design
- 2606.13174, 2606.08702, 2606.09316, 2606.08049, 2605.18693, 2603.17399 — skill/context items surfaced by
  WebSearch that I deprioritized after the arXiv listings showed stronger, newer alternatives.

---

## 4. Dead ends, and things I could not confirm

- **`abs:"execution feedback" AND abs:"evolution" AND abs:"frozen model"` returned zero results**, as did
  three other conjunctive queries aimed at demonstration-bootstrapped adaptation. The arXiv API's `abs:`
  field matching is strict; multi-term conjunctions over five terms almost always return nothing. Broad
  two-term queries plus manual triage of the date-sorted list was strictly more productive.
- **Demonstration-bootstrapped adaptation (area 5) is genuinely thin, not under-searched.** I ran four
  distinct query formulations across both WebSearch and the arXiv API. Nothing supersedes DemoEvolve
  (2605.24539). The only new material is architectural (DarwinX admitting teacher-derived evidence into a
  shared edit interface) or empirical (AFTER's multi-model-trace result). I am reporting this as a gap
  rather than as a failure to find, and I am moderately confident that is correct — but a Semantic Scholar
  citation-graph walk forward from DemoEvolve would be the right way to raise that confidence, and I did
  not do it.
- **No single paper names "the strongest method for evolving an always-on procedural-memory artifact
  under a hard token budget."** The brief asked what the field currently considers strongest; the honest
  answer is that no such consensus statement exists. My SkillOpt recommendation is inferred from three
  pieces of evidence (its scope matches the artifact; OEO 2608.09629 selects it as one of the two
  prescribed pipelines to beat; it is one of the few methods evaluated inside Claude Code) plus the
  separate observation that its budget mechanism is on edit size rather than artifact size, which is why
  I pair it with SkillZip. That inference is stated as an inference in §8.1 of the deliverable, not as a
  reported fact.
- **ACE's ICLR 2026 status** appears in search snippets and in the PDF header. I did not independently
  verify the acceptance; `docs/LITERATURE_2026-08.md` does not assert it.
- **Claims about method quality inside papers I only read the abstract of.** All numeric claims in the
  deliverable are quoted from abstracts I read, except the RIZZ Appendix C passage, which I fetched from
  the paper's HTML and quoted verbatim. I did not read any full PDFs.
- **Code availability is reported as "a URL exists on the abs page or in the abstract."** I did not clone
  or run any repository. The only link I resolved was `aka.ms/skillopt`.
- **`2605.23904` (SkillOpt) v1 vs v2.** The abs page shows v2 (25 May 2026). I read v2's abstract. If the
  method details cited (learning-rate budget, rejected-edit buffer, epoch-wise slow/meta update) matter to
  implementation, read the paper — I have only the abstract's description of them.
- **`2608.14441` (PACE-Bench)** — I quote its finding that "memory anchors agents to early designs". That
  is a paraphrase of the abstract's own sentence, not a result I traced to a table.
- I did **not** re-verify any of the 30 IDs the brief listed as already confirmed, per instructions.

---

## 5. Things that surprised me, worth flagging to the reader

1. **Three independent Jun–Aug 2026 papers describe our two local negative results.**
   2608.14036 (retrieval precision collapse 29.6% → 3.3%) reproduces the `memory_lookup`-called-zero-times
   finding as a measured phenomenon. 2608.11095 (catastrophic remembering, +226% growth over an
   instruction file's lifetime) reproduces the v0→v3 12× monotone growth. Both were previously "our
   anecdote"; both are now citable.
2. **The evidence against ACE is stronger and more specific than expected**, and it is in an appendix of a
   paper that describes ACE as an architectural inspiration — i.e. a friendly source, which makes it more
   credible, not less.
3. **RLMOpt's and MAGE's findings jointly predict our search will return its seed.** Gains are set by seed
   headroom, not budget (RLMOpt); at N_train=30 a fixed prompt beat every reflective optimizer, and
   variance amplification disappears at high base accuracy (MAGE). We are at N=17 with a hand-designed seed
   at 0.86–0.92. This should be a pre-registered kill criterion, and it is the most important thing this
   sweep found that is *bad news*.
4. **`aka.ms/skillopt` is a Microsoft repo.** Given the WAYPOINT internship context, worth knowing who the
   authors are before building on it.
