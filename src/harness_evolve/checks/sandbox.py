"""The fence around candidate-authored check code.

Checks are the one place the search loop is allowed to author *code*, so this
is the one place a bad proposal can do more than waste a rollout. arXiv:
2603.05578 (Tool-Genesis) is the direct evidence: one-shot autonomous tool
creation fails, and interface errors compound rather than stay local. So a
plugin must clear every one of these before it is ever loaded into a run:

1. a sibling test file exists (``<name>.py`` -> ``<name>_test.py``);
2. the plugin imports without error;
3. it exports ``check`` with the fixed two-argument signature;
4. its test passes;
5. its test actually *calls* ``check`` at least once -- otherwise "write a
   test" is satisfiable by ``assert True``, and a proposer optimising against
   a gate will find that;
6. import and test together finish inside :data:`CHECK_TIMEOUT_S`.

All of it runs *before any rollout is spent*: free rejections are where bad
proposals should die, and this whole category is free to reject.

Two things are done in a subprocess that the predecessor did in-process. The
test, obviously -- a hang or ``sys.exit`` must not take the search down. But
also the *import*, because a module with a hang or an ``os._exit`` at import
time is exactly as fatal, and "import it to see whether it is safe to import"
is not a fence. Only a plugin that has already been vetted in a child process
is imported into the parent.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.checks.api import CheckFn

#: Per-plugin wall-clock budget covering import *and* test. A check that cannot
#: answer in five seconds is not a check, it is a second agent -- and it would
#: be paid on every turn of every rollout.
CHECK_TIMEOUT_S = 5.0

#: Marker the vetting child prints its verdict behind, so a chatty plugin's own
#: stdout cannot be mistaken for the verdict.
_VERDICT_MARKER = "@@HARNESS_EVOLVE_VET@@"

#: Rejection reasons. Strings rather than an enum so they survive the JSON hop
#: out of the child process and land readably in the decision log.
STATUS_OK = "ok"
STATUS_NO_TEST = "no_test"
STATUS_IMPORT_ERROR = "import_error"
STATUS_BAD_INTERFACE = "bad_interface"
STATUS_TEST_FAILED = "test_failed"
STATUS_VACUOUS_TEST = "vacuous_test"
STATUS_TIMEOUT = "timeout"
STATUS_EXITED_EARLY = "exited_early"


@dataclass(frozen=True)
class PluginReport:
    """Verdict on one plugin. Recorded whether or not it passed.

    A rejected plugin is evidence about the proposer, not just a discarded
    file, so the reason is kept in a form the decision log can read back.
    """

    name: str
    path: str
    status: str
    detail: str = ""
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "detail": self.detail,
            "duration_s": round(self.duration_s, 3),
        }

    def render(self) -> str:
        head = "accepted" if self.ok else f"REJECTED ({self.status})"
        tail = f": {self.detail}" if self.detail else ""
        return f"{self.name}: {head}{tail}"


def test_path_for(plugin_path: Path) -> Path:
    """The mandatory sibling test for ``plugin_path``."""
    plugin_path = Path(plugin_path)
    return plugin_path.with_name(f"{plugin_path.stem}_test.py")


def iter_plugin_paths(checks_dir: Path) -> list[Path]:
    """Plugin modules in ``checks_dir``: ``*.py``, excluding tests and privates."""
    checks_dir = Path(checks_dir)
    if not checks_dir.is_dir():
        return []
    return [
        p
        for p in sorted(checks_dir.glob("*.py"))
        if not p.name.startswith("_") and not p.name.endswith("_test.py")
    ]


def vet_plugin(plugin_path: Path, *, timeout: float = CHECK_TIMEOUT_S) -> PluginReport:
    """Run the full fence over one plugin. Never imports it into this process."""
    plugin_path = Path(plugin_path)
    test_path = test_path_for(plugin_path)
    started = time.monotonic()
    if not test_path.exists():
        return PluginReport(
            name=plugin_path.stem,
            path=str(plugin_path),
            status=STATUS_NO_TEST,
            detail=(
                f"no sibling test at {test_path.name}; every check plugin must "
                f"ship one that calls check() at least once"
            ),
        )

    env = dict(os.environ)
    # The child needs the same importable set as the parent so a plugin can
    # `import harness_evolve...` for Finding/Artifact. Derived from sys.path
    # rather than assumed installed: this package is normally run from src/.
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(plugin_path), str(test_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(plugin_path.parent.resolve()),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return PluginReport(
            name=plugin_path.stem,
            path=str(plugin_path),
            status=STATUS_TIMEOUT,
            detail=f"import plus test exceeded the {timeout}s budget",
            duration_s=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    verdict = _parse_verdict(proc.stdout)
    if verdict is None:
        # No verdict line: the child died or exited before reporting. A plugin
        # or test that calls sys.exit()/os._exit() lands here, and it must be a
        # rejection -- an exit code of 0 from a process that never ran the
        # assertions proves nothing.
        detail = (proc.stderr or proc.stdout or "").strip()[:800]
        return PluginReport(
            name=plugin_path.stem,
            path=str(plugin_path),
            status=STATUS_EXITED_EARLY,
            detail=detail or f"vetting child exited {proc.returncode} with no verdict",
            duration_s=duration,
        )
    return PluginReport(
        name=plugin_path.stem,
        path=str(plugin_path),
        status=str(verdict.get("status", STATUS_TEST_FAILED)),
        detail=str(verdict.get("detail", ""))[:800],
        duration_s=duration,
    )


def vet_plugins(
    checks_dir: Path, *, timeout: float = CHECK_TIMEOUT_S
) -> list[PluginReport]:
    """Vet every plugin in ``checks_dir``."""
    return [vet_plugin(p, timeout=timeout) for p in iter_plugin_paths(checks_dir)]


def load_vetted_plugins(
    checks_dir: Path, *, timeout: float = CHECK_TIMEOUT_S
) -> tuple[dict[str, "CheckFn"], list[PluginReport]]:
    """Vet, then import only what passed.

    Returns ``(name -> check, reports)``. The reports cover rejected plugins
    too; a caller that drops them loses the only record of what the proposer
    got wrong.
    """
    checks: dict[str, "CheckFn"] = {}
    reports: list[PluginReport] = []
    for path in iter_plugin_paths(checks_dir):
        report = vet_plugin(path, timeout=timeout)
        if report.ok:
            fn, err = _import_check(path)
            if fn is None:
                # Vetted in a child, then failed in the parent: an import with
                # process-local state. Rejecting is the only safe reading.
                report = PluginReport(
                    name=report.name, path=report.path,
                    status=STATUS_IMPORT_ERROR,
                    detail=f"passed vetting but failed to import here: {err}",
                    duration_s=report.duration_s,
                )
            else:
                checks[report.name] = fn
        reports.append(report)
    return checks, reports


def rejected(reports: Iterable[PluginReport]) -> list[PluginReport]:
    """Just the failures, for the decision log and the proposer's feedback."""
    return [r for r in reports if not r.ok]


# ---------------------------------------------------------------------------
# shared import path, used by both the parent (post-vetting) and the child
# ---------------------------------------------------------------------------


def _import_check(plugin_path: Path):  # -> tuple[CheckFn | None, str | None]
    """Import ``plugin_path`` and return its ``check``, or an error string."""
    plugin_path = Path(plugin_path)
    module_name = plugin_path.stem
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        return None, "could not create a module spec"
    module = importlib.util.module_from_spec(spec)
    # Registered before execution so the sibling test's `import <stem>` gets
    # *this* module object rather than a second, uninstrumented copy.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:  # noqa: BLE001 -- includes SystemExit
        sys.modules.pop(module_name, None)
        return None, f"{type(exc).__name__}: {exc}"
    fn = getattr(module, "check", None)
    if not callable(fn):
        return None, "module exports no callable named 'check'"
    return fn, None


def _signature_problem(fn) -> str | None:
    """Reject anything that is not ``check(artifact, ctx)``."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        return f"signature is not introspectable: {exc}"
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    required = [p for p in positional if p.default is p.empty]
    has_varargs = any(p.kind is p.VAR_POSITIONAL for p in sig.parameters.values())
    if has_varargs:
        return None
    if len(positional) < 2:
        return (
            f"check must accept (artifact, ctx); got ({', '.join(sig.parameters)})"
        )
    if len(required) > 2:
        return (
            f"check must be callable as check(artifact, ctx), but "
            f"{len(required)} arguments are required"
        )
    return None


# ---------------------------------------------------------------------------
# the vetting child
# ---------------------------------------------------------------------------


def _verdict(status: str, detail: str = "") -> None:
    sys.stdout.write(
        f"\n{_VERDICT_MARKER}{json.dumps({'status': status, 'detail': detail})}\n"
    )
    sys.stdout.flush()


def _parse_verdict(stdout: str) -> dict[str, object] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_VERDICT_MARKER):
            try:
                return json.loads(line[len(_VERDICT_MARKER):])
            except json.JSONDecodeError:
                return None
    return None


def _run_vetting_child(plugin_path: Path, test_path: Path) -> int:
    """Import, interface-check, instrument, run the test, confirm it exercised check."""
    # The plugin directory, not this file's, is what a sibling test imports from.
    sys.path.insert(0, str(Path(plugin_path).parent.resolve()))
    fn, err = _import_check(plugin_path)
    if fn is None:
        _verdict(STATUS_IMPORT_ERROR, err or "import failed")
        return 1
    problem = _signature_problem(fn)
    if problem:
        _verdict(STATUS_BAD_INTERFACE, problem)
        return 1

    calls = 0
    module = sys.modules[Path(plugin_path).stem]

    def counting_check(*args, **kwargs):
        nonlocal calls
        calls += 1
        return fn(*args, **kwargs)

    counting_check.__name__ = "check"
    counting_check.__doc__ = getattr(fn, "__doc__", None)
    module.check = counting_check  # type: ignore[attr-defined]

    test_name = Path(test_path).stem
    spec = importlib.util.spec_from_file_location(test_name, test_path)
    if spec is None or spec.loader is None:
        _verdict(STATUS_TEST_FAILED, "could not create a module spec for the test")
        return 1
    test_module = importlib.util.module_from_spec(spec)
    sys.modules[test_name] = test_module
    try:
        spec.loader.exec_module(test_module)
        # Both conventions work: top-level assertions, or a main() the file
        # would call under `if __name__ == "__main__"` (which does not fire
        # here, since the test is imported rather than run as a script).
        main = getattr(test_module, "main", None)
        if callable(main):
            main()
        for name in sorted(dir(test_module)):
            if name.startswith("test_") and callable(getattr(test_module, name)):
                getattr(test_module, name)()
    except BaseException as exc:  # noqa: BLE001 -- test may raise anything
        import traceback

        _verdict(
            STATUS_TEST_FAILED,
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}",
        )
        return 1

    if calls == 0:
        _verdict(
            STATUS_VACUOUS_TEST,
            "the sibling test never called check(); a test that does not "
            "exercise the plugin is not evidence the plugin works",
        )
        return 1
    _verdict(STATUS_OK, f"test passed, check() called {calls} time(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised via subprocess
    sys.exit(_run_vetting_child(Path(sys.argv[1]), Path(sys.argv[2])))
