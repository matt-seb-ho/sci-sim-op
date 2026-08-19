"""harness-evolve: search over simulator-grounding adapters.

Rebuild of the SIGA self-evolution loop (`repo3/scripts/self_evolving/`) as an
actual search. See `docs/ARCHITECTURE.md` for the design and
`docs/WHY_V1_FAILED.md` for the evidence that motivated the rebuild.

Three contracts hold the system together and everything else plugs into them:

* :class:`~harness_evolve.simulators.base.SimulatorSpec` -- what it takes to
  ground an agent in *a* simulator. Making this a protocol rather than
  GEOS-specific code is the portability claim: adding OpenFOAM or LAMMPS is
  implementing one class, not forking the loop.
* :class:`~harness_evolve.runners.base.RolloutRunner` -- how a candidate
  adapter is actually executed on a task. Lets the search run against the real
  containerised harness, against a cached corpus, or against a deterministic
  mock, without the loop knowing which.
* :class:`~harness_evolve.proposers.base.Proposer` -- how a child candidate is
  produced from a parent plus evidence.
"""

__version__ = "0.1.0"
