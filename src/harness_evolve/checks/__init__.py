"""Check plugins: the one place the search loop may author code.

A candidate may not rewrite the stop hook. It may only add a check behind one
fixed interface, with a mandatory sibling test::

    <name>.py         def check(artifact, ctx) -> list[Finding]
    <name>_test.py    REQUIRED -- the candidate is rejected without it

:mod:`harness_evolve.checks.sandbox` enforces that before any rollout is spent.
:mod:`harness_evolve.checks.constraints` holds the negative-constraint
declaration, which renders as cheatsheet prose and as an enforced check from
one source. See ``docs/ARCHITECTURE.md``.
"""

from harness_evolve.checks.api import (
    FEEDBACK_SHAPES,
    CheckContext,
    CheckFn,
    render_feedback,
    run_checks,
)
from harness_evolve.checks.builtins import BUILTIN_CHECKS
from harness_evolve.checks.constraints import (
    CONSTRAINT_KINDS,
    Constraint,
    ConstraintError,
    ConstraintSet,
    render_constraints_prose,
)
from harness_evolve.checks.sandbox import (
    CHECK_TIMEOUT_S,
    PluginReport,
    load_vetted_plugins,
    rejected,
    vet_plugin,
    vet_plugins,
)
from harness_evolve.checks.xmlview import ElementView

__all__ = [
    "BUILTIN_CHECKS",
    "CHECK_TIMEOUT_S",
    "CONSTRAINT_KINDS",
    "FEEDBACK_SHAPES",
    "CheckContext",
    "CheckFn",
    "Constraint",
    "ConstraintError",
    "ConstraintSet",
    "ElementView",
    "PluginReport",
    "load_vetted_plugins",
    "rejected",
    "render_constraints_prose",
    "render_feedback",
    "run_checks",
    "vet_plugin",
    "vet_plugins",
]
