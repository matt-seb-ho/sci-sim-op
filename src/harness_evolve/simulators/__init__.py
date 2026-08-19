"""Simulator plugins. Importing this package registers every built-in spec.

Registration happens on import rather than lazily, so
``SimulatorRegistry.names()`` is complete for any caller that has imported the
package -- a config referring to a simulator by string must not depend on
whether some other module happened to import it first.
"""

from harness_evolve.simulators.base import (
    Artifact,
    ContaminationPolicy,
    Diagnosis,
    SimulatorRegistry,
    SimulatorSpec,
)
from harness_evolve.simulators.geos import GeosSimulator
from harness_evolve.simulators.lammps import LammpsSimulator
from harness_evolve.simulators.mock import MockConfig, MockSimulator, MockTask
from harness_evolve.simulators.openfoam import OpenFoamSimulator

__all__ = [
    "Artifact",
    "ContaminationPolicy",
    "Diagnosis",
    "GeosSimulator",
    "LammpsSimulator",
    "MockConfig",
    "MockSimulator",
    "MockTask",
    "OpenFoamSimulator",
    "SimulatorRegistry",
    "SimulatorSpec",
]
