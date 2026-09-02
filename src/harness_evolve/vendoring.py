"""Ship the check registry into the container the hook runs in.

The stop policy may legally name ``required_sections``, ``constraints`` or
``cross_section_refs``. The hook implements ``parse`` and ``geosx_validate``
only, and records the rest as ``checks_unsupported`` -- visibly, which is why
this was a known hole rather than a silent one (2026-08-26 worklog Â§2.6).

The hole exists because the hook executes *inside* the rollout container, where
``harness_evolve`` is not installed and cannot be: the container image is not
ours to rebuild per candidate. The adapter directory, however, is mounted into
every rollout at ``/plugins/repo3``. So the fix is to copy the parts of this
package the checks need into that directory at materialization time, and have
the hook put them on ``sys.path``.

**What is copied is deliberately a subtree, not the package.** A check that could
import the search loop, the proposers or the provider backends would be able to
reach the ground-truth corpus and the network from inside a rollout, which is
exactly the boundary the hygiene work exists to defend. The closure below is
computed and then *asserted* by a test that imports it in a subprocess with
nothing else on the path -- so an import added later fails the test rather than
failing a rollout four hours into a run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

#: Modules and packages copied into the adapter. The closure of what
#: ``harness_evolve.checks`` needs, and nothing else: ``checks`` itself,
#: ``simulators`` (for ``Artifact`` and the per-simulator specs a check reads),
#: ``types`` (``Finding``, ``Score``), and the package ``__init__``.
VENDORED: tuple[str, ...] = (
    "__init__.py",
    "types.py",
    "checks",
    "simulators",
)

#: Where the vendored tree lands inside the adapter, and therefore inside the
#: container at ``/plugins/repo3/<this>``.
VENDOR_DIRNAME = "vendor"

_EXCLUDE = shutil.ignore_patterns("__pycache__", "*.pyc", "*_test.py")


def package_root() -> Path:
    return Path(__file__).resolve().parent


def vendor_checks(dest: Path, *, package: Path | None = None) -> Path:
    """Copy the check subtree into ``dest/vendor/harness_evolve``.

    Returns the directory that should go on ``sys.path`` -- i.e. ``dest/vendor``,
    not the package inside it.
    """
    src = Path(package) if package is not None else package_root()
    root = Path(dest) / VENDOR_DIRNAME
    pkg = root / "harness_evolve"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    for name in VENDORED:
        s = src / name
        if not s.exists():
            raise FileNotFoundError(f"cannot vendor {name}: {s} does not exist")
        if s.is_dir():
            shutil.copytree(s, pkg / name, ignore=_EXCLUDE)
        else:
            shutil.copy2(s, pkg / name)
    return root
