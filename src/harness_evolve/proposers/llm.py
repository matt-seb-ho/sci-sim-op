"""The model-driven proposer.

What it is shown, and why each part is there:

* **The reward.** The predecessor's proposer was shown ``mean treesim 0.0000``
  and ``treesim N/A`` per task, every round, because the round was never scored
  before reflection. Everything else here is downstream of not repeating that.
* **A layered evidence corpus** rather than a list of tool names, with drill-down
  available for one named task instead of everything dumped at once.
* **Constraints the validator already stated.** This is the unusual part. Rather
  than asking the model to guess a negative constraint and then spending a full
  evaluation round finding out whether it is true, the constraints the simulator
  has *already asserted* are handed over as settled fact, and the model is told
  not to re-derive them. It costs nothing and it is correct by construction.
* **Expert demonstrations**, when available, because reward-only search is
  reported to break down in exactly this regime (arXiv:2605.24539).
* **Its own recent record** -- which of its predictions came true. A proposer
  that cannot see its own calibration cannot improve it.

What it is required to produce: exactly one bounded edit, and a prediction that
can be falsified next round.

The proposer model defaults to something other than the inference model. Not
because self-distillation is why the predecessor failed -- harness-updating
capability is reported roughly flat across model tiers (arXiv:2605.30621), so
this is likely second-order -- but because it is free and removes a confound.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from harness_evolve.core.candidate import Candidate
from harness_evolve.core.decision import Prediction
from harness_evolve.proposers.base import Demonstration, Proposer, ProposerError
from harness_evolve.proposers.demonstrations import render_all
from harness_evolve.proposers.edits import Edit, EditError, apply_edit, parse_edits

PREDICTION_RE = re.compile(r"<prediction>\s*(\{.*?\})\s*</prediction>", re.DOTALL)

SYSTEM_PROMPT = """\
You are improving a *grounding adapter*: a small set of always-visible artifacts
wrapped around a frozen coding agent so it can author a valid input deck for a
scientific simulator. You are not writing the agent and you cannot change it.
You edit only the artifacts.

Every rule below is enforced mechanically after you answer. Violating one costs
the proposal, not the run.

1. EXACTLY ONE EDIT. One <edit> block, on one component.
2. BOUNDED OPERATIONS ONLY: add one line, delete one line, or replace one line.
   For delete and replace, `anchor` must quote the existing line.
3. DELETION IS A REAL MOVE. Components have hard token budgets and the adapter
   is read on every single rollout. If a line has not earned its place, remove
   it. An artifact that only grows is a cost with no evidence behind it.
4. NEVER NAME A FILE, A TASK, OR A GROUND-TRUTH VALUE. Not a filename of any
   extension, not a benchmark task identifier, not a number you saw in a deck.
   Describe physics classes, element shapes, and simulator conventions instead.
   A proposal that leaks any of these is discarded before it is ever run.
5. THE VALIDATOR'S CONSTRAINTS ARE ALREADY KNOWN. Anything listed under
   "constraints the validator has already stated" is settled. Do not restate it,
   do not weaken it, do not spend your edit rediscovering it.
6. NEGATIVE CONSTRAINTS BEAT POSITIVE ONES HERE. Telling the agent what to
   include reliably makes it include that *and more*. If the evidence shows
   surplus or hallucinated content, the fix is a bound, not another suggestion.
7. YOU MAY EDIT THE STOP POLICY. Retry budget, feedback shape, and which checks
   run are components too.

Answer with exactly one <edit> block and one <prediction> block:

<edit component="COMPONENT" op="add|delete|replace" anchor="EXISTING LINE IF ANY">
the new line, or empty for delete
</edit>
<prediction>
{"targets_category": "missing_block",
 "predicted_beneficiaries": ["TaskA"],
 "predicted_delta": 0.03,
 "rationale": "one or two sentences tied to the evidence above"}
</prediction>

The prediction is a contract. It is checked against next round's outcomes and
recorded. An edit whose named beneficiaries do not move is reverted.
"""

USER_TEMPLATE = """\
## Current adapter

{components}

## Evidence from the last evaluation

{evidence}

## Constraints the validator has already stated

{derived}

## Expert demonstrations

{demos}

## Your recent record

{history}

## Components you may edit

{editable}

Propose exactly one bounded edit.
"""


@dataclass
class LLMProposerConfig:
    model: str = "gemini-3-flash-preview"
    api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    api_key_env: str = "OPENROUTER_API_KEY"
    max_tokens: int = 2000
    temperature: float = 0.8
    timeout_s: int = 300
    evidence_level: int = 2
    max_demo_chars: int = 3000
    history_window: int = 6


def _api_key(cfg: LLMProposerConfig) -> str:
    key = os.environ.get(cfg.api_key_env)
    if key:
        return key
    raise ProposerError(
        f"{cfg.api_key_env} is not set; the proposer cannot run without it"
    )


def call_openrouter(prompt: str, cfg: LLMProposerConfig) -> str:
    body = json.dumps(
        {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        cfg.api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {_api_key(cfg)}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise ProposerError(f"proposer call failed: {exc}") from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ProposerError(f"unexpected proposer response shape: {exc}") from exc


@dataclass
class LLMProposer(Proposer):
    """Proposes one bounded edit per call, with a falsifiable prediction."""

    config: LLMProposerConfig = field(default_factory=LLMProposerConfig)
    #: Transport. Left unset, resolved from whichever provider is configured.
    backend: Any = None
    #: Constraints already entailed by validator output. Supplying these is the
    #: difference between a model guessing a bound and being handed one.
    derived_constraints: Sequence[Any] = ()
    call: Callable[[str], str] | None = None

    def _backend_caller(self):
        from harness_evolve.proposers.backends import default_backend

        backend = self.backend or default_backend()
        return lambda prompt: backend(prompt, system=SYSTEM_PROMPT)

    # -- prompt assembly --------------------------------------------------
    def render_components(self, candidate: Candidate) -> str:
        from harness_evolve.core.candidate import estimate_tokens

        parts = []
        for name, spec in candidate.manifest.components.items():
            if spec.kind == "config":
                sp = candidate.manifest.stop_policy
                parts.append(
                    f"### {name} (config)\n"
                    f"retries={sp.retries} feedback_shape={sp.feedback_shape} "
                    f"checks={list(sp.checks)}"
                )
                continue
            if not spec.path:
                continue
            text = candidate.files.get(spec.path, "")
            used = estimate_tokens(text)
            budget = (
                f" — {used}/{spec.budget_tokens} tokens used"
                if spec.budget_tokens
                else f" — ~{used} tokens"
            )
            parts.append(f"### {name} ({spec.kind}{budget})\n{text or '(empty)'}")
        return "\n\n".join(parts)

    def render_editable(self, candidate: Candidate) -> str:
        rows = []
        for name, spec in candidate.manifest.components.items():
            headroom = ""
            if spec.budget_tokens and spec.path:
                from harness_evolve.core.candidate import estimate_tokens

                left = spec.budget_tokens - estimate_tokens(
                    candidate.files.get(spec.path, "")
                )
                headroom = (
                    f", {left} tokens of headroom"
                    if left > 0
                    else ", AT BUDGET — you must delete before you can add"
                )
            rows.append(f"- {name} ({spec.kind}{headroom})")
        return "\n".join(rows)

    def render_derived(self) -> str:
        if not self.derived_constraints:
            return "(none yet — the validator has not repeated itself)"
        from harness_evolve.evidence.directives import render_constraints

        return render_constraints(list(self.derived_constraints))

    def render_history(self, history: Sequence[dict[str, Any]]) -> str:
        rows = []
        for h in list(history)[-self.config.history_window:]:
            verdict = "accepted" if h.get("accepted") else "REJECTED"
            hit = h.get("prediction_hit_rate")
            hit_s = "no prediction" if hit is None else f"prediction hit rate {hit:.0%}"
            reasons = "; ".join(h.get("reasons") or []) or "—"
            rows.append(
                f"- {h.get('component')} [{h.get('edit_type')}]: {verdict} "
                f"({reasons}); {hit_s}"
            )
        return "\n".join(rows) or "(this is the first proposal)"

    def build_prompt(
        self,
        parent: Candidate,
        evidence: Any,
        history: Sequence[dict[str, Any]],
        demonstrations: Sequence[Demonstration],
    ) -> str:
        try:
            ev_text = evidence.render(level=self.config.evidence_level)
        except AttributeError:
            ev_text = str(evidence) if evidence is not None else "(no evidence)"
        return USER_TEMPLATE.format(
            components=self.render_components(parent),
            evidence=ev_text,
            derived=self.render_derived(),
            demos=render_all(list(demonstrations), max_chars=self.config.max_demo_chars),
            history=self.render_history(history),
            editable=self.render_editable(parent),
        )

    # -- response handling -------------------------------------------------
    def parse(self, response: str, parent: Candidate) -> tuple[Edit, Prediction]:
        edits = parse_edits(response)
        if not edits:
            raise ProposerError("no <edit> block in response")
        if len(edits) > 1:
            raise ProposerError(
                f"{len(edits)} edits proposed; exactly one is allowed so the "
                "verdict can be attributed to it"
            )
        edit = edits[0]
        if edit.component not in parent.manifest.components:
            raise ProposerError(
                f"unknown component {edit.component!r}; available: "
                f"{sorted(parent.manifest.components)}"
            )

        m = PREDICTION_RE.search(response)
        if not m:
            raise ProposerError("no <prediction> block; every edit must be falsifiable")
        try:
            raw = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise ProposerError(f"prediction is not valid JSON: {exc}") from exc
        raw.setdefault("component", edit.component)
        return edit, Prediction.from_dict(raw)

    # -- the interface -----------------------------------------------------
    def propose(
        self,
        parent: Candidate,
        evidence: Any = None,
        history: Sequence[dict[str, Any]] = (),
        demonstrations: Sequence[Demonstration] = (),
    ) -> Candidate:
        prompt = self.build_prompt(parent, evidence, history, demonstrations)
        caller = self.call or self._backend_caller()
        edit, prediction = self.parse(caller(prompt), parent)

        spec = parent.manifest.components[edit.component]
        if spec.kind == "config":
            raise ProposerError(
                "config components are edited through the manifest, not an "
                "<edit> block"
            )
        if not spec.path:
            raise ProposerError(f"component {edit.component!r} has no file path")

        try:
            new_text = apply_edit(parent.files.get(spec.path, ""), edit)
        except EditError as exc:
            raise ProposerError(str(exc)) from exc

        child = parent.with_edits(
            {spec.path: new_text},
            predictions=[Prediction.from_dict(prediction.to_dict())],
        )
        # Budgets and writability are re-checked here so a proposal that cannot
        # be accepted is rejected before it reaches the paid gates.
        child.validate()
        return child
