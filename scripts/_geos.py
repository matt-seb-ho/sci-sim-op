"""The one place that knows how this box runs GEOS.

Everything environment-shaped for a real rollout lives here so the search
scripts stay about searching. Values are the ones verified on serv6 on
2026-08-26; anything that is a guess is marked as one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness_evolve.integration import find_repo3  # noqa: E402
from harness_evolve.runners.subprocess import (  # noqa: E402
    SubprocessRunner, SubprocessRunnerConfig,
)
from harness_evolve.simulators.base import SimulatorRegistry  # noqa: E402

REPO3 = find_repo3() or Path.home() / "src" / "repo3"
DATA = REPO3 / "data" / "eval"

#: The rollout model. Overridable so a closing free window costs one env var
#: rather than an edit.
#:
#: `stealth/ox-alpha` was the workhorse until 2026-08-26 ~16:27, when its free
#: period ended mid-session -- OpenRouter: "Thank you for participating in the
#: Stealth Ox Alpha testing period"; Nous: "This model free period has ended".
#: Both 404. It was ZAI's GLM-5.3 behind the stealth badge.
#:
#: `z-ai/glm-5.2:free` is the replacement: Artificial Analysis intelligence index
#: 51 (the highest of anything screened, and above the deepseek-v4-flash-0420 bar
#: of 42), 256k context, verified `usage.cost == 0`, and ~14 s latency versus
#: ox-alpha's ~50 s.
MODEL = os.environ.get("HARNESS_EVOLVE_MODEL", "z-ai/glm-5.2:free")

#: repo3's default (`runner/constants.py:TEMP_GEOS_PARENT`) is owned by another
#: user and is not writable by us: the harness fails every task with
#: `[Errno 13] Permission denied` and still exits 0. Must live on the same
#: filesystem as --geos-lib-dir (/data) so the filtered-GEOS copies can be
#: hardlink farms rather than 20 GB of real copies.
TMP_GEOS_PARENT = Path("/data/matt/tmp_geos")


def load_env(path: Path = REPO / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def geos_env() -> None:
    """Environment the repo3 harness child needs. Idempotent."""
    load_env()
    # Containers on serv6 are enroot: docker access was withdrawn.
    os.environ.setdefault("REPO3_CONTAINER_BACKEND", "enroot")
    # The harness authenticates to a gateway via ANTHROPIC_AUTH_TOKEN, never a
    # real Anthropic key -- see docker_cmd.build_claude_native_env.
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = os.environ.get("OPENROUTER_API_KEY", "")
    os.environ.setdefault("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
    os.environ["ANTHROPIC_API_KEY"] = ""

    # Host-side validator. SubprocessRunner runs `geosx --validate-input`
    # directly (outside the container) to capture the simulator's own error text
    # -- the valid-attribute tables constraint derivation consumes. Without
    # these the corpus gets verdicts only, which is the starvation
    # runners/subprocess.py:390 documents. Paths per repo3 runner/constants.py.
    runtime = Path("/home/brian/.geosx_docker_runtime")
    geosx = runtime / "install" / "bin" / "geosx"
    if geosx.is_file():
        os.environ.setdefault("GEOSX_EXECUTABLE", str(geosx))
        libs = [str(runtime / "install" / "lib")]
        libs += [str(runtime / "tpl" / sub / "lib")
                 for sub in ("hdf5", "suitesparse", "superlu_dist", "vtk")]
        libs.append("/home/brian/miniconda3/envs/geos-build/lib")
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ":".join(libs + ([existing] if existing else []))


def runner(
    results_root: Path,
    *,
    model: str = MODEL,
    timeout_s: float = 1800.0,
    workers: int = 1,
    extra_args: tuple[str, ...] = (),
    run_prefix: str = "evolve",
) -> SubprocessRunner:
    geos_env()
    # Absolute, always: the launcher is invoked with cwd=repo3, so a relative
    # results root resolves against the wrong repo and the harness exits with
    # "plugin dir not found" -- which SubprocessRunner reports as an empty
    # workspace, i.e. a score of 0 that looks like a model failure.
    results_root = Path(results_root).resolve()
    return SubprocessRunner(
        SimulatorRegistry.get("geos"),
        SubprocessRunnerConfig(
            harness_root=REPO3,
            experiments_dir=DATA / "experiments",
            ground_truth_dir=DATA / "experiments_gt",
            results_root=results_root,
            # Resolved live, never snapshotted: v1's snapshot froze before the
            # geosx --validate-input swap and drifted 274 lines.
            scaffolding_dir=REPO3 / "plugin",
            adapter_root=results_root / "adapters",
            run_prefix=run_prefix,
            timeout_s=timeout_s,
            # This box has no docker daemon at all; the container backend is
            # enroot and the probe would fail on a binary it never calls.
            probe_docker=False,
            # NB: SubprocessRunner.argv() already passes --workers 1; adding
            # another here made the launcher see the flag twice.
            extra_args=("--claude-model", model,
                        "--tmp-geos-parent", str(TMP_GEOS_PARENT)) + extra_args,
        )
    )
