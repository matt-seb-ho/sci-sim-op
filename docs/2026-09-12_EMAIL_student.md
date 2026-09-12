# Draft email to the prospective collaborator

Fill in the bracketed parts. Two versions: a short one, and a longer one if you
want to set more context up front. The repo's `TASK.md` carries all the detail,
so the email only needs to cover what is not in it: the time you expect, the
dates, and the money.

---

## Short version

> **Subject:** GEOS agent project — a task to try before we go further
>
> Hi [name],
>
> Thanks for the survey — [one specific sentence about it, e.g. "the section on
> verifier-grounded methods was the part I found most useful"].
>
> The next step is a task that gets you into the actual problem. Pick one of the
> self-improving harness techniques from your survey, argue that it applies to
> our setting, implement it, and run it. We have put everything except the loop
> itself into a repository:
>
> https://github.com/matt-seb-ho/geos-harness-qual
>
> Read `TASK.md` first, then `README.md`. The short version: a coding agent has
> to write a GEOS simulation input file from a written description; the model is
> fixed and everything around it — prompt, tools, hooks, retries — is what your
> loop changes.
>
> Practical points:
>
> - **Time.** Aim for roughly [N] hours of work, by [date]. It is open-ended, so
>   that number is a real limit rather than an estimate. Doing less and saying
>   clearly what you left out is better than going over.
> - **Check in with me after the one-page write-up in step 2, before you start
>   implementing.** That is the cheapest point to correct a wrong plan and I do
>   not want you spending the whole budget on one.
> - **API costs.** You will need your own OpenRouter key — I cannot issue keys
>   to people outside the group yet. A rollout costs about $0.12 and the whole
>   task can be done for a couple of dollars; please keep it small, and set a
>   spend limit on the key. [If you can reimburse: "Keep the receipts and I will
>   reimburse you."] If cost is a problem, tell me before you start rather than
>   quietly cutting the work.
> - **Use `z-ai/glm-5.3-flash` and do not change models.** The whole premise is
>   improving the harness around a fixed model.
>
> One thing worth saying up front: our own result on this problem is a null, and
> the literature predicts a search with this few samples returns its starting
> point. You are not expected to beat it. What I care about is how you think
> about the problem and how you work things out — whether you read the
> transcripts and the data, and whether your decisions come from something you
> observed. `TASK.md` says this in more detail.
>
> Happy to answer questions at any point; being stuck for two days on something
> I can answer in five minutes is worse than asking.
>
> [sign-off]

---

## Longer version, if you want more context in the email itself

Same as above, with this inserted after the repository link:

> **What the project is.** We are trying to work out whether an agent can be
> made better at configuring scientific simulators by optimising the harness
> around it rather than by training the model. GEOS is the first simulator;
> OpenFOAM and LAMMPS are on the list. The measurement problem is most of the
> difficulty: rollouts are slow and expensive, the task pool is small, and it is
> easy to produce a number that looks like an improvement and is not. A lot of
> the kit exists to stop that happening.
>
> **Why this task.** It is a real slice of what we would want you working on,
> and it is self-contained — the tasks, the container, the scorer and the
> statistics are all provided, so you write the loop and nothing else.

---

## Notes for you, not for the email

- **Decide the hours and the deadline** before sending. The repo deliberately
  contains no time estimates so you can set them here.
- **Decide on reimbursement.** $2–6 is small but not nothing to an
  undergraduate, and offering to cover it removes a reason for someone good to
  say no.
- **The repo is public.** If you would rather it were not, say so before sending
  the link — the tasks pair descriptions with reference decks, and the only new
  exposure is that pairing.
- **Set a calendar reminder for the step-2 check-in.** If it does not arrive,
  that is itself information.
