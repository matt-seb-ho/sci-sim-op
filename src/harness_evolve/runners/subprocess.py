"""The executing runner: materialize the adapter, shell out, and score. Once.

This wraps the containerised harness in ``repo3`` (``scripts/run_experiment.py``
-> ``src/runner/cli.py`` -> ``docker run``). The frozen coding agent, the
container, and the eval harness are all unchanged; the only thing that varies
between rollouts is the adapter directory this runner writes and the stop-policy
environment it exports.

**Run and score are one call that cannot be half-performed.** In v1 they were
two separate steps in a shell script, and the scoring step was simply never
invoked -- so the reflection loop consumed ``treesim = None`` for every task and
reported a round mean of 0 across three rounds. Here scoring happens on the way
out of :meth:`SubprocessRunner.run`, on *every* path including a non-zero exit,
a timeout, and a missing workspace. A run with no usable output scores 0.0 with
a status saying why, because failures-as-zero is the convention and an absent
score is not representable.

**Not executed in this environment.** There is no Docker daemon and no ``/data``
volume here, so no rollout has ever been run through this class. That is why the
subprocess call is injected (:class:`CommandRunner`) rather than hardwired: every
branch -- argv construction, stop-policy export, non-zero exit, timeout, missing
workspace, cost parsing -- is unit-tested against a fake, and only the four-line
:func:`run_command` at the bottom is unexercised. :meth:`preflight` is what
turns "this box cannot run it" into a list of reasons at planning time instead
of a crash halfway through a search.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import Cost, Rollout, Score, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate
    from harness_evolve.simulators.base import SimulatorSpec

#: Written into the materialized adapter directory alongside the exported
#: environment. ``repo3/src/runner/docker_cmd.py`` forwards a fixed ``-e
#: GEOS_HOOK_*`` allowlist into the container and knows nothing about the newer
#: ``GEOS_EVOLVE_*`` names, so a policy that reached the *host* process could
#: still be dropped at the container boundary. The adapter directory is mounted
#: as the plugin dir, so a file inside it always arrives.
STOP_POLICY_ENV_FILE = "stop_policy.env"


@dataclass(frozen=True)
class CommandResult:
    """The part of a completed process this runner needs."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


#: Injected process launcher. Injected rather than called directly so every
#: branch of :meth:`SubprocessRunner.run` is testable on a box with no Docker.
CommandRunner = Callable[[Sequence[str], Mapping[str, str], float, Path], CommandResult]


def run_command(
    argv: Sequence[str], env: Mapping[str, str], timeout: float, cwd: Path
) -> CommandResult:
    """Default launcher. The only part of this module that is unexercised here."""
    try:
        proc = subprocess.run(
            list(argv),
            env=dict(env),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr),
            timed_out=True,
        )
    return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


@dataclass
class SubprocessRunnerConfig:
    """Everything environment-shaped, in one place.

    Kept out of the class body so a deployment can be described by a config
    record in the run log -- "which paths did this round actually use" is a
    question v1 could not answer, because they were spread across launcher
    shell scripts.
    """

    #: repo3 checkout; ``scripts/run_experiment.py`` lives under it.
    harness_root: Path
    #: Task directories (one per task, each with ``instructions.txt``).
    experiments_dir: Path
    #: Per-task ground truth, both for scoring and for the contamination gate.
    ground_truth_dir: Path
    #: Where the harness writes ``<agent>/<run>/<task>/``.
    results_root: Path
    #: Live plugin directory whose ``hooks/``, ``scripts/``, ``.claude-plugin/``
    #: are copied at materialization time. Resolved now, never snapshotted into
    #: a candidate -- v1's snapshot froze before the ``geosx --validate-input``
    #: swap and drifted 274 lines from the plugin it was meant to extend.
    scaffolding_dir: Path
    #: Where candidate adapters are materialized.
    adapter_root: Path
    #: Agent key in ``repo3/src/runner/agents.py``.
    agent: str = "claude_code_repo3_plugin_xmllint_all"
    run_prefix: str = "evolve"
    timeout_s: float = 1800.0
    #: Bind-mounted volume the harness needs for GEOS data. Checked in
    #: preflight because its absence is the single most common reason a box
    #: cannot run this.
    data_volume: Path = Path("/data")
    docker_binary: str = "docker"
    #: Probe the daemon in preflight. A readable ``docker`` binary is not the
    #: same as a reachable daemon; this host has neither, and a real host can
    #: have the first without the second.
    probe_docker: bool = True
    auth_token_env: str = "ANTHROPIC_AUTH_TOKEN"
    extra_args: tuple[str, ...] = ()
    extra_env: Mapping[str, str] = field(default_factory=dict)

    @property
    def launcher(self) -> Path:
        return Path(self.harness_root) / "scripts" / "run_experiment.py"


class SubprocessRunner(RolloutRunner):
    """Materialize the candidate, run the containerised harness, score the result."""

    def __init__(
        self,
        spec: "SimulatorSpec",
        config: SubprocessRunnerConfig,
        *,
        command_runner: CommandRunner | None = None,
        python_executable: str | None = None,
        capture_validator_output: bool = True,
    ) -> None:
        self.spec = spec
        self.config = config
        self._run_command: CommandRunner = command_runner or run_command
        self.python_executable = python_executable or sys.executable
        # Costs one validator subprocess per rollout (~2-3s against a run
        # measured in minutes) and is the only channel through which the
        # simulator's own error text -- the valid-attribute tables that
        # constraint derivation consumes -- reaches the corpus. Off only when a
        # caller has a reason.
        self.capture_validator_output = capture_validator_output

    @property
    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(
            can_execute=True,
            produces_trajectories=True,
            produces_validator_events=True,
            # A frozen agent is still a sampler: same candidate, same seed,
            # different trajectory. Claiming otherwise would let the evaluation
            # layer skip repeats it must not skip.
            deterministic=False,
            usd_per_task_run=1.0,
        )

    # -- readiness --------------------------------------------------------
    def preflight(self) -> list[str]:
        """Every reason this box cannot execute a rollout, collected not raised.

        Returning the full list matters: fixing them one crash at a time costs
        a round each, and the caller may reasonably decide to degrade to the
        cached or mock runner instead.
        """
        cfg = self.config
        reasons: list[str] = []
        if not cfg.launcher.is_file():
            reasons.append(f"harness launcher not found: {cfg.launcher}")
        if not Path(cfg.experiments_dir).is_dir():
            reasons.append(f"experiments dir not found: {cfg.experiments_dir}")
        if not Path(cfg.ground_truth_dir).is_dir():
            reasons.append(
                f"ground truth dir not found: {cfg.ground_truth_dir} "
                f"(without it nothing can be scored, and an unscored run is the "
                f"failure this runner exists to prevent)"
            )
        if not Path(cfg.scaffolding_dir).is_dir():
            reasons.append(f"plugin scaffolding dir not found: {cfg.scaffolding_dir}")
        if not Path(cfg.data_volume).is_dir():
            reasons.append(f"data volume not mounted: {cfg.data_volume}")
        if shutil.which(cfg.docker_binary) is None:
            reasons.append(f"docker binary not on PATH: {cfg.docker_binary!r}")
        elif cfg.probe_docker:
            probe = self._run_command(
                [cfg.docker_binary, "info"], dict(os.environ), 30.0, Path.cwd()
            )
            if not probe.ok:
                reasons.append(
                    "docker daemon not reachable: "
                    f"`{cfg.docker_binary} info` exited {probe.returncode}"
                    + (f" ({probe.stderr.strip()[:200]})" if probe.stderr.strip() else "")
                )
        if not os.environ.get(cfg.auth_token_env):
            reasons.append(f"{cfg.auth_token_env} is not set in the environment")
        reasons.extend(self.spec.preflight())
        return reasons

    # -- the runner contract ---------------------------------------------
    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        """Run and score. Scoring happens on every path, including failure."""
        cfg = self.config
        run_name = self.run_name(candidate, seed, task)
        adapter_dir = self.materialize(candidate, run_name)
        result_dir = self.result_dir(run_name, task)
        env = self.child_env(candidate, task, seed)
        argv = self.argv(adapter_dir, run_name, task)

        proc = self._run_command(argv, env, cfg.timeout_s, Path(cfg.harness_root))

        # Nothing between here and the Rollout may return early. The v1 defect
        # was structural, not a typo: scoring lived past a branch that was never
        # taken.
        score = self.score_result_dir(result_dir, task)
        # Checked before the returncode branch because the returncode is 0 here:
        # the launcher reports its own failures in stdout and exits successfully.
        infra = harness_failure(proc.stdout) if proc.ok else None
        # A launcher that exits non-zero without timing out never got as far as
        # running the agent -- a held run lock, an unreadable path, a missing
        # image. Attributing that to the candidate is the same confound as the
        # exit-0 case above. A *timeout* is different and stays a real outcome:
        # the adapter can genuinely make an agent slow.
        if (infra is None and not proc.ok and not proc.timed_out
                and score.status in ("no_workspace", "empty_workspace")):
            infra = self._error_summary(proc)
        if infra is not None:
            score = replace(
                score, status="harness_error",
                detail={**dict(score.detail), "harness_error": infra},
            )
        if not proc.ok:
            score = _annotate(
                score,
                {
                    "process_exit": proc.returncode,
                    "timed_out": proc.timed_out,
                    "stderr_tail": proc.stderr.strip()[-2000:],
                },
            )
        cost = self.collect_cost(result_dir)
        events_path = result_dir / "events.jsonl"
        return Rollout(
            task=task,
            candidate_id=candidate.cid,
            seed=seed,
            score=score,
            cost=cost,
            artifacts_dir=str(result_dir) if result_dir.exists() else None,
            events_path=str(events_path) if events_path.is_file() else None,
            validator_events=self.collect_validator_events(result_dir),
            error=(f"harness reported failure while exiting 0: {infra}"
                   if infra is not None
                   else None if proc.ok else self._error_summary(proc)),
        )

    # -- the pieces, each independently testable --------------------------
    def run_name(self, candidate: "Candidate", seed: int,
                 task: TaskId | None = None) -> str:
        """Result namespace. Seed is in the name so repeats never overwrite.

        The task is in it as well, and that is not cosmetic: repo3's launcher
        takes a **per-run-name PID lock**
        (``<results_root>/.run_locks/<run_name>.lock``, added after the run9
        incident where a second invocation SIGTERMed twelve in-flight tasks). So
        two rollouts of the same candidate and seed on *different tasks* would
        collide on the lock, and all but one would exit 2 having done nothing --
        which is exactly what happened the first time these were run
        concurrently. Measured 2026-08-26.
        """
        stem = f"{self.config.run_prefix}-{candidate.cid}-s{seed}"
        return f"{stem}-{task}" if task else stem

    def result_dir(self, run_name: str, task: TaskId) -> Path:
        """Where the harness lands results: ``<root>/<agent>/<run>/<task>/``."""
        return Path(self.config.results_root) / self.config.agent / run_name / task

    def materialize(self, candidate: "Candidate", run_name: str) -> Path:
        """Write the runnable adapter directory for this candidate."""
        dest = Path(self.config.adapter_root) / run_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        candidate.materialize(
            dest, scaffolding_from=Path(self.config.scaffolding_dir), overwrite=True
        )
        # Belt and braces on the stop policy: also inside the mounted adapter.
        policy = candidate.manifest.stop_policy.to_env()
        (dest / STOP_POLICY_ENV_FILE).write_text(
            "".join(f"{k}={v}\n" for k, v in sorted(policy.items()))
        )
        return dest

    def child_env(self, candidate: "Candidate", task: TaskId, seed: int) -> dict[str, str]:
        """The environment the harness child sees.

        ``StopPolicy.to_env()`` is the whole reason the stop interface is
        searchable: retry budget, whether the real validator runs, the feedback
        shape, and the enabled check list all reach the hook this way. v1 could
        not vary any of them -- ``GEOS_HOOK_MAX_RETRIES`` was pinned at 2.
        """
        env = dict(os.environ)
        env.update(candidate.manifest.stop_policy.to_env())
        env.update({str(k): str(v) for k, v in self.config.extra_env.items()})
        env["HARNESS_EVOLVE_CANDIDATE"] = candidate.cid
        env["HARNESS_EVOLVE_TASK"] = task
        env["HARNESS_EVOLVE_SEED"] = str(seed)
        return env

    def argv(self, adapter_dir: Path, run_name: str, task: TaskId) -> list[str]:
        """The ``run_experiment.py`` invocation for exactly one task."""
        cfg = self.config
        return [
            self.python_executable,
            str(cfg.launcher),
            "--run", run_name,
            "--agents", cfg.agent,
            "--include", task,
            "--experiments-dir", str(cfg.experiments_dir),
            "--ground-truth-dir", str(cfg.ground_truth_dir),
            "--results-root-dir", str(cfg.results_root),
            "--plugin-dir", str(adapter_dir),
            "--timeout", str(int(cfg.timeout_s)),
            "--workers", "1",
            *cfg.extra_args,
        ]

    # -- scoring ----------------------------------------------------------
    def score_result_dir(self, result_dir: Path, task: TaskId) -> Score:
        """Score the workspace the harness produced. Never returns ``None``.

        Every failure mode maps to a 0.0 with a status that names it, so the
        rate of unscorable runs -- the quantity the whole reliability claim is
        about -- stays visible in the same field as everything else.
        """
        inputs_dir = Path(result_dir) / "inputs"
        if not inputs_dir.is_dir():
            return Score(
                task=task, value=0.0, status="no_workspace",
                detail={"expected_inputs_dir": str(inputs_dir)},
            )
        if not any(p.is_file() for p in inputs_dir.rglob("*")):
            return Score(
                task=task, value=0.0, status="empty_workspace",
                detail={"inputs_dir": str(inputs_dir)},
            )
        gt = Path(self.config.ground_truth_dir) / task
        if not gt.is_dir():
            return Score(
                task=task, value=0.0, status="no_ground_truth",
                detail={"expected_ground_truth": str(gt)},
            )
        try:
            return self.spec.score(inputs_dir, gt, task)
        except Exception as exc:  # noqa: BLE001 -- a scorer may raise anything
            # A scorer crash is a zero with a reason, not a lost rollout. The
            # alternative -- letting it propagate -- discards a run that already
            # cost 25 minutes, and hides how often the scorer crashes.
            return Score(
                task=task, value=0.0, status="scorer_error",
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )

    # -- telemetry --------------------------------------------------------
    def collect_cost(self, result_dir: Path) -> Cost:
        """Read cost off ``events.jsonl``, falling back to ``status.json``.

        Tool calls are counted from ``tool_use`` blocks rather than trusted from
        a summary field: the efficiency constraint is a hard gate, and a gate
        reading a number nobody recomputes is a gate that drifts.
        """
        result_dir = Path(result_dir)
        cost = Cost()
        events = result_dir / "events.jsonl"
        if events.is_file():
            cost = _cost_from_events(events)
        if not cost.tool_calls:
            status = result_dir / "status.json"
            if status.is_file():
                try:
                    data = json.loads(status.read_text())
                except json.JSONDecodeError:
                    data = {}
                cost = Cost(
                    tool_calls=float(data.get("total_tool_calls", cost.tool_calls) or 0.0),
                    wall_seconds=float(data.get("elapsed_seconds", cost.wall_seconds) or 0.0),
                    input_tokens=cost.input_tokens,
                    output_tokens=cost.output_tokens,
                    usd=cost.usd,
                )
        return cost

    def collect_validator_events(self, result_dir: Path) -> list[dict[str, Any]]:
        """Everything the validator said about this workspace.

        Two sources, and both are needed.

        The stop hook logs its own *decisions* -- blocked or allowed, and why --
        which is what the stop-policy search reasons over. But a decision is a
        verdict: it records that a deck failed without recording the table of
        legal attributes the simulator printed alongside. That table is the
        input to constraint derivation, and reading only the hook log silently
        starves it.

        The failure was invisible because its symptom is indistinguishable from
        the honest one: an empty directive set renders as "0% naming an action
        space", which is exactly what a verdict-only validator should produce
        and exactly what the runbook says to trust. So the simulator's validator
        is run here directly, and the two sources are tagged so the difference
        is recoverable downstream.
        """
        result_dir = Path(result_dir)
        out: list[dict[str, Any]] = []

        path = result_dir / ".verify_hook_events.jsonl"
        if path.is_file():
            for line in path.read_text(errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event.setdefault("source", "stop_hook")
                out.append(event)

        out.extend(self.collect_validator_output(result_dir))
        return out

    def collect_validator_output(self, result_dir: Path) -> list[dict[str, Any]]:
        """Run the simulator's own validator and keep what it said, verbatim.

        Separated from the hook log so a caller can disable it (it costs a
        subprocess per rollout) without losing the hook decisions, and so its
        absence is attributable.
        """
        if not self.capture_validator_output:
            return []
        workspace = Path(result_dir) / "inputs"
        if not workspace.is_dir():
            return []
        try:
            artifact = self.spec.parse(workspace)
            findings = self.spec.validate(artifact, workspace)
        except NotImplementedError:
            # A simulator without a validator is a real configuration, not a
            # fault. Recorded as such so downstream can tell it from a channel
            # that broke.
            return [{"source": "simulator", "status": "no_validator"}]
        except Exception as exc:  # noqa: BLE001
            return [{
                "source": "simulator", "status": "validator_error",
                "message": f"{type(exc).__name__}: {exc}",
            }]
        return [{
            "source": "simulator",
            "severity": f.severity,
            "message": f.message,
            "location": f.location,
            "validator_output": f.message,
        } for f in findings]

    @staticmethod
    def _error_summary(proc: CommandResult) -> str:
        if proc.timed_out:
            return "harness timed out"
        return f"harness exited {proc.returncode}: {proc.stderr.strip()[-500:]}"


#: Strips the launcher's colour codes before its summary is parsed.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
#: repo3's launcher prints this and then **exits 0**, even when every task
#: failed. Measured 2026-08-26: an unwritable `--tmp-geos-parent` failed the
#: only task with `[Errno 13] Permission denied` and returned 0.
_HARNESS_SUMMARY_RE = re.compile(r"Done:\s*(\d+)\s+succeeded,\s*(\d+)\s+failed")
_HARNESS_FAILED_TASK_RE = re.compile(r"\[error\]\s*(.+)")


def harness_failure(stdout: str) -> str | None:
    """Did the launcher fail the task while still exiting 0?

    This matters more than it looks. A harness that cannot start the container
    produces an empty workspace, an empty workspace scores 0, and a 0 is
    indistinguishable from "the model wrote nothing" -- so an infrastructure
    outage is silently attributed to the candidate under evaluation. A search
    would then reject good candidates for a reason that has nothing to do with
    them, and the run would look entirely normal.

    Returning a reason here is what lets a rollout say "do not count me".
    """
    clean = _ANSI_RE.sub("", stdout or "")
    match = _HARNESS_SUMMARY_RE.search(clean)
    if not match or int(match.group(2)) == 0:
        return None
    detail = _HARNESS_FAILED_TASK_RE.search(clean)
    return (detail.group(1).strip() if detail
            else f"{match.group(2)} task(s) failed in the launcher")


def _annotate(score: Score, extra: Mapping[str, Any]) -> Score:
    """Attach process provenance without touching the value or the status."""
    return replace(score, detail={**dict(score.detail), **dict(extra)})


def _cost_from_events(events_path: Path) -> Cost:
    """Sum a Claude Code ``stream-json`` event log into a :class:`Cost`."""
    tool_calls = 0
    input_tokens = 0.0
    output_tokens = 0.0
    usd = 0.0
    wall_seconds = 0.0
    for line in events_path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        tool_calls += _count_tool_uses(record)
        if record.get("type") == "result":
            usd = float(record.get("total_cost_usd") or usd)
            wall_seconds = float(record.get("duration_ms") or 0.0) / 1000.0 or wall_seconds
            usage = record.get("usage") or {}
            input_tokens = float(usage.get("input_tokens") or input_tokens)
            output_tokens = float(usage.get("output_tokens") or output_tokens)
    return Cost(
        tool_calls=float(tool_calls),
        wall_seconds=wall_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=usd,
    )


def _count_tool_uses(node: Any) -> int:
    """Count ``tool_use`` blocks anywhere in a record.

    Recursive because the block's depth differs between agent adapters, and a
    depth-specific reader silently returns 0 on the one it was not written for.
    """
    if isinstance(node, dict):
        if str(node.get("type", "")).lower() == "tool_use":
            return 1
        return sum(_count_tool_uses(v) for v in node.values())
    if isinstance(node, list):
        return sum(_count_tool_uses(v) for v in node)
    return 0
