#!/usr/bin/env python3
"""One real proposer call, to check that the prompt design actually works.

Everything else about the proposer is tested against injected responses, which
verifies the parsing and the guards but says nothing about whether a real model,
given this prompt, produces a compliant edit. That is the part most likely to be
wrong, and it cannot be tested for free.

**This spends API credits.** One call. It is limited to one deliberately: the
question is whether the contract is followable, not how often it is followed,
and the second question is only worth asking once the first is settled.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_evolve.core.candidate import Candidate  # noqa: E402
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy  # noqa: E402
from harness_evolve.evidence.corpus import RoundEvidence, TaskEvidence  # noqa: E402
from harness_evolve.evidence.directives import (  # noqa: E402
    derive_constraints, parse_validator_output,
)
from harness_evolve.proposers.backends import AnthropicBackend  # noqa: E402
from harness_evolve.proposers.base import Demonstration  # noqa: E402
from harness_evolve.proposers.llm import LLMProposer  # noqa: E402

VALIDATOR_OUTPUT = """
Error: XML Node Solvers/SinglePhasePoromechanics contains unused attribute 'gravityVector'. Valid attributes are:
  cflFactor, discretization, flowSolverName, initialDt, logLevel, name, solidSolverName, targetRegions

Error: XML Node Solvers/SinglePhasePoromechanics contains unused attribute 'gravityVector'. Valid attributes are:
  cflFactor, discretization, flowSolverName, initialDt, logLevel, name, solidSolverName, targetRegions
"""


def load_env() -> None:
    """Read ~/.env if the key is not already exported."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env = Path.home() / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()


def build_candidate() -> Candidate:
    return Candidate(
        manifest=Manifest(
            components={
                "primer": ComponentSpec("primer", "prose", path="PRIMER.md",
                                        budget_tokens=200),
                "memory": ComponentSpec("memory", "itemized",
                                        path="memory/cheatsheet.md",
                                        budget_tokens=300),
                "stop_policy": ComponentSpec("stop_policy", "config"),
            },
            stop_policy=StopPolicy(retries=2, feedback_shape="structured_errors",
                                   checks=("parse", "geosx_validate")),
        ),
        files={
            "PRIMER.md": "Author a valid multiphysics simulator input deck in "
                         "the workspace inputs directory.",
            "memory/cheatsheet.md": (
                "- Poroelastic problems need a coupled solver plus a matching "
                "constitutive block.\n"
                "- Name every region referenced by a solver.\n"
                "- Prefer an analogous published case as a structural template.\n"
                "- Include an events block; runs without one produce no output."
            ),
        },
    )


def build_evidence() -> RoundEvidence:
    """A round where surplus content is the visible failure mode."""
    from harness_evolve.simulators.base import Diagnosis
    from harness_evolve.types import Cost, Rollout, Score

    def rollout(task: str, value: float, seed: int) -> Rollout:
        return Rollout(task=task, candidate_id="cand_demo", seed=seed,
                       score=Score(task, value), cost=Cost(tool_calls=80.0))

    return RoundEvidence.from_rollouts(
        [
            rollout("wellbore_thermo", 0.61, 1),
            rollout("wellbore_thermo", 0.59, 2),
            rollout("proppant_transport", 0.44, 1),
            rollout("proppant_transport", 0.46, 2),
        ],
        candidate_id="cand_demo",
        parent_scores={"wellbore_thermo": 0.63, "proppant_transport": 0.41},
        diagnoses={
            "wellbore_thermo": Diagnosis(
                section_scores={"Constitutive": 0.34, "Solvers": 0.88,
                                "Events": 0.91, "ElementRegions": 0.55},
                extra_elements=["ElasticIsotropic", "BiotPorosity"],
                n_extra=2, category="extra_block",
            ),
            "proppant_transport": Diagnosis(
                section_scores={"Constitutive": 0.29, "Solvers": 0.71},
                extra_elements=["ElasticIsotropic"],
                n_extra=1, category="hallucinated_extras",
            ),
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--effort", default="high")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not available; nothing to smoke test.")
        return 2

    candidate = build_candidate()
    constraints = derive_constraints(parse_validator_output(VALIDATOR_OUTPUT))
    print(f"derived {len(constraints)} constraint(s) from validator output:")
    for c in constraints:
        print(f"  {c.prose}")

    proposer = LLMProposer(
        backend=AnthropicBackend(model=args.model, effort=args.effort),
        derived_constraints=constraints,
    )
    prompt = proposer.build_prompt(
        candidate, build_evidence(), [],
        [Demonstration(
            task="wellbore_thermo",
            summary="The expert worked from the narrative documentation for "
                    "events and outputs rather than from example files.",
            notes="reported the events and outputs setup as the hardest part",
        )],
    )
    print(f"\nprompt: {len(prompt)} chars. Calling {args.model} (effort={args.effort})...\n")

    child = proposer.propose(
        candidate, build_evidence(), [],
        [Demonstration(task="wellbore_thermo",
                       summary="worked from narrative documentation")],
    )

    pred = child.predictions[0]
    print("=" * 66)
    print("PROPOSAL ACCEPTED BY THE PARSER AND THE BUDGET GATE")
    print("=" * 66)
    print(f"component      {pred.component}")
    print(f"targets        {pred.targets_category}")
    print(f"beneficiaries  {list(pred.predicted_beneficiaries)}")
    print(f"predicted Δ    {pred.predicted_delta:+.3f}")
    print(f"rationale      {pred.rationale}")
    spec = child.manifest.components[pred.component]
    print(f"\n--- {spec.path} after the edit ---")
    print(child.files[spec.path])

    before = candidate.files.get(spec.path, "").splitlines()
    after = child.files[spec.path].splitlines()
    print(f"\nlines {len(before)} -> {len(after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
