"""Sibling test for ``lazy_resolved_refs``. Mandatory: no test, no plugin.

Written as plain asserts with no test framework so the sandbox can run it in a
bare subprocess -- a plugin whose test needs pytest installed inside the vetting
child is a plugin that cannot be vetted on a bare box.

The deck below is the exact case ``docs/GEOSX_VALIDATE.md`` confirmed
``--validate-input`` exits 0 on.
"""

from __future__ import annotations

from pathlib import Path

from harness_evolve.checks.api import CheckContext
from harness_evolve.simulators.base import Artifact

from lazy_resolved_refs import check

_GOOD = """<Problem>
  <Solvers>
    <SinglePhaseFVM name="flow" discretization="tpfa" targetRegions="{ region }"/>
  </Solvers>
  <NumericalMethods>
    <FiniteVolume>
      <TwoPointFluxApproximation name="tpfa"/>
    </FiniteVolume>
  </NumericalMethods>
</Problem>
"""

_DANGLING_DISCRETIZATION = _GOOD.replace('"tpfa" targetRegions', '"TPFA_DOES_NOT_EXIST" targetRegions')

_DANGLING_SOLVER_REF = """<Problem>
  <Solvers>
    <SinglePhaseFVM name="flow" discretization="tpfa"/>
    <SinglePhasePoromechanics name="coupled" flowSolverName="flowSolverTypo"/>
  </Solvers>
  <NumericalMethods>
    <FiniteVolume><TwoPointFluxApproximation name="tpfa"/></FiniteVolume>
  </NumericalMethods>
</Problem>
"""


def _findings(xml: str):
    artifact = Artifact(files={"deck.xml": xml})
    return check(artifact, CheckContext(workspace=Path(".")))


def test_clean_deck_is_silent() -> None:
    assert _findings(_GOOD) == []


def test_dangling_discretization_is_reported() -> None:
    findings = _findings(_DANGLING_DISCRETIZATION)
    assert len(findings) == 1, findings
    assert findings[0].severity == "error"
    assert "TPFA_DOES_NOT_EXIST" in findings[0].message
    # The message must enumerate what *is* defined; a finding the agent cannot
    # act on is worse than no finding.
    assert "tpfa" in findings[0].message


def test_unknown_solver_reference_is_reported() -> None:
    findings = _findings(_DANGLING_SOLVER_REF)
    assert [f.source for f in findings] == ["lazy_resolved_refs"]
    assert "flowSolverTypo" in findings[0].message


def test_missing_section_defers_to_required_sections() -> None:
    # No <NumericalMethods> at all: that is the completeness check's finding,
    # not this one's.
    xml = "<Problem><Solvers><SinglePhaseFVM name='f' discretization='tpfa'/></Solvers></Problem>"
    assert _findings(xml) == []


def test_empty_artifact_is_silent() -> None:
    assert check(Artifact(), CheckContext(workspace=Path("."))) == []


def main() -> None:
    test_clean_deck_is_silent()
    test_dangling_discretization_is_reported()
    test_unknown_solver_reference_is_reported()
    test_missing_section_defers_to_required_sections()
    test_empty_artifact_is_silent()


if __name__ == "__main__":
    main()
    print("lazy_resolved_refs: ok")
