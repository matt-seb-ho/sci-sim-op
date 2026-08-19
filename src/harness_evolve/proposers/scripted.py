"""Proposers that do not call a model.

Two uses, both about being able to trust the loop:

* **Testing.** A scripted proposer makes the search loop deterministic
  end-to-end, so its selection, gating, and accounting can be tested without an
  API key. The predecessor loop was never exercised end-to-end and consequently
  ran three rounds with a silently broken reward channel.
* **A floor to beat.** A proposer making blind, cheap edits is the control that
  says whether an LLM proposer is contributing judgement or just churn. Given
  that harness-*updating* capability is reported to be roughly flat across model
  tiers (arXiv:2605.30621), a trivial baseline is not a straw man.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from harness_evolve.core.candidate import Candidate, Prediction
from harness_evolve.proposers.base import Demonstration, Proposer, ProposerError


@dataclass
class ScriptedProposer(Proposer):
    """Replays a fixed list of edits, in order.

    Each script entry is ``(component, new_text, prediction_dict)``. Raises when
    exhausted rather than looping, so a test cannot accidentally pass by
    re-proposing the same thing forever.
    """

    script: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    _i: int = 0

    def propose(
        self,
        parent: Candidate,
        evidence: Any = None,
        history: Sequence[dict[str, Any]] = (),
        demonstrations: Sequence[Demonstration] = (),
    ) -> Candidate:
        if self._i >= len(self.script):
            raise ProposerError("script exhausted")
        component, text, pred = self.script[self._i]
        self._i += 1
        spec = parent.manifest.components.get(component)
        if spec is None or not spec.path:
            raise ProposerError(f"unknown or pathless component {component!r}")
        pred = {**pred, "component": component}
        child = parent.with_edits(
            {spec.path: text}, predictions=[Prediction.from_dict(pred)]
        )
        child.validate()
        return child


@dataclass
class RandomEditProposer(Proposer):
    """Appends or deletes a line from a random text component.

    The control condition: it respects the interface exactly -- one component,
    a prediction, budgets -- and brings no judgement whatsoever. If the search
    does no better with a real proposer than with this, the loop is measuring
    search pressure rather than reasoning.
    """

    lines: Sequence[str] = ("- prefer a coupled solver for poroelastic problems",)
    rng: random.Random = field(default_factory=lambda: random.Random(0))
    delete_prob: float = 0.3

    def propose(
        self,
        parent: Candidate,
        evidence: Any = None,
        history: Sequence[dict[str, Any]] = (),
        demonstrations: Sequence[Demonstration] = (),
    ) -> Candidate:
        text_components = [
            (n, s) for n, s in parent.manifest.components.items()
            if s.is_text and s.path
        ]
        if not text_components:
            raise ProposerError("candidate has no editable text component")
        name, spec = self.rng.choice(text_components)
        current = parent.files.get(spec.path, "")
        current_lines = [l for l in current.splitlines() if l.strip()]

        if current_lines and self.rng.random() < self.delete_prob:
            drop = self.rng.randrange(len(current_lines))
            new_lines = current_lines[:drop] + current_lines[drop + 1:]
            category = "extra_block"
        else:
            new_lines = current_lines + [self.rng.choice(list(self.lines))]
            category = "missing_block"

        child = parent.with_edits(
            {spec.path: "\n".join(new_lines)},
            predictions=[
                Prediction(
                    component=name,
                    targets_category=category,
                    rationale="random control edit; no diagnosis",
                )
            ],
        )
        child.validate()
        return child
