"""Spend enforcement against the provider account, not against local accounting.

Named ``spend`` rather than ``budget`` because ``harness_evolve.evaluation.budget``
already exists and means something else entirely: *compute* matching, the
planner that decides how many best-of-k draws make a baseline arm comparable to
a search. That one is about rollout counts; this one is about money. Two modules
called ``budget`` in one package is an invitation to import the wrong one.

Four facts make this module necessary, and each one on its own would be enough.

**The old policy is the wrong policy.** ``CostLedger`` hard-stopped on any
non-zero ``usage.cost``. That was correct for the free-window campaign it was
written for; against a paid model it aborts on the first call. The policy this
replaces it with is a *cap*: cumulative spend must stay under a ceiling.

**Local accounting cannot see the money.** A rollout's cost is spent by the
coding agent running inside the container, through its own credentials, in calls
this process never makes and never observes. The proposer calls that
``CostLedger`` does see are a rounding error beside them. A cap enforced on the
ledger would therefore report a few cents while the account drained -- which is
worse than no cap, because it reads as a working safeguard.

**Two different numbers look like one.** The account balance and the API key's
spending cap are separate quantities on separate endpoints, and conflating them
is what produced the first draft of tonight's brief. Measured 2026-09-02 10:21:

===============  ======================  ======================================
scope            endpoint                reading
===============  ======================  ======================================
account balance  ``/api/v1/credits``     ``210 - 168.323`` -> **$41.68 available**
this API key     ``/api/v1/key``         ``limit 10``, ``usage 1.271``,
                                         ``limit_remaining 8.729``
===============  ======================  ======================================

The ``$10`` is a **per-key spending cap**, not the balance. So the authorized
$20 is affordable; only the key cap is in the way, and the owner can raise it
from the dashboard *while a run is in progress*.

**Therefore the ceiling is polled, not hardcoded.** If the cap is raised
mid-run, ``limit`` jumps and the run should simply continue up to the full
authorization without a restart.

Ground truth is ``GET /api/v1/key``, polled between batches of real work and
logged every time. The guard's job is to stop *starting* new rollouts once the
ceiling is reached.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import Rollout, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate

#: Nous' edge 403s the default Python UA outright, and OpenRouter is happier
#: with an identifiable one. Same string the rest of the campaign sends.
USER_AGENT = "sci-sim-op/0.1 (harness-evolve budget guard)"

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"

#: Account spend on this key when the 2026-09-02 campaign started. Every
#: "additional spend" figure is measured from here.
BASELINE_USAGE = 1.271071093

#: What the owner authorized, in additional spend. The ceiling is the smaller of
#: this and what the key's own cap allows.
AUTHORIZED_USD = 20.00

#: Never spend the key's last few cents. The key cap is a hard provider-side
#: wall: crossing it does not warn, it starts refusing calls mid-rollout, which
#: converts paid-for work into `harness_error`s. Held back from the ceiling.
KEY_RESERVE_USD = 0.25


class BudgetExhausted(RuntimeError):
    """The spend ceiling has been reached. Stop starting work.

    Not a transient failure and never retried: the next call would cost money
    that is not authorized. Callers should let in-flight work finish, write up
    what they have, and escalate.
    """


@dataclass(frozen=True)
class AccountUsage:
    """One reading of the provider's own counters for this key."""

    usage: float
    limit: float | None
    limit_remaining: float | None
    ts: float

    def ceiling(self, *, baseline: float = BASELINE_USAGE,
                authorized: float = AUTHORIZED_USD,
                reserve: float = KEY_RESERVE_USD) -> float:
        """Additional spend allowed, in dollars, given this reading.

        ``min(authorized, key cap headroom)``, where the key's headroom is
        computed from ``limit`` rather than from the live ``limit_remaining``.

        That distinction is the whole subtlety. ``limit_remaining`` shrinks as we
        spend, so testing ``usage - baseline >= min(20, limit_remaining)``
        against a live reading is self-defeating: the two sides converge on each
        other and the run halts at *half* its allowance ($4.36 of $8.73, in
        tonight's numbers). Since ``limit_remaining == limit - usage``, the
        intended quantity is the headroom *at the baseline*, which is
        ``limit - baseline`` -- a fixed number that does not move as we spend,
        and that rises immediately if the owner raises ``limit``. Both readings
        agree at t=0, which is why the two forms are easy to confuse.
        """
        if self.limit is None:
            return authorized
        return min(authorized, max(0.0, self.limit - baseline - reserve))

    def spent(self, *, baseline: float = BASELINE_USAGE) -> float:
        return self.usage - baseline

    @property
    def as_entry(self) -> dict:
        return {
            "ts": int(self.ts),
            "kind": "account_usage",
            "provider": "openrouter",
            "usage": self.usage,
            "limit": self.limit,
            "limit_remaining": self.limit_remaining,
        }


def _get(url: str, *, api_key_env: str, timeout_s: float) -> dict:
    key = os.environ.get(api_key_env)
    if not key:
        raise BudgetExhausted(
            f"{api_key_env} is not set, so account spend cannot be read and the "
            f"ceiling cannot be enforced"
        )
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8")).get("data") or {}


def read_openrouter_usage(
    *, api_key_env: str = "OPENROUTER_API_KEY", timeout_s: float = 30.0
) -> AccountUsage:
    """Read this key's counters. Raises rather than guessing.

    A failed read is deliberately *not* treated as "probably fine". An
    unreadable counter is the state in which a ceiling cannot be enforced, and
    proceeding through it is how a ceiling becomes decorative.
    """
    data = _get(KEY_URL, api_key_env=api_key_env, timeout_s=timeout_s)
    if "usage" not in data:
        raise BudgetExhausted(
            f"{KEY_URL} returned no 'usage' field; the ceiling cannot be "
            f"enforced against a counter that is not there (keys: {sorted(data)})"
        )
    return AccountUsage(
        usage=float(data["usage"]),
        limit=(float(data["limit"]) if data.get("limit") is not None else None),
        limit_remaining=(
            float(data["limit_remaining"])
            if data.get("limit_remaining") is not None
            else None
        ),
        ts=time.time(),
    )


def read_account_credits(
    *, api_key_env: str = "OPENROUTER_API_KEY", timeout_s: float = 30.0
) -> tuple[float, float]:
    """``(available, total_credits)`` for the *account*, not the key.

    Checked once at start to confirm the balance is not the binding limit. If it
    ever is, no amount of raising the key cap helps and the run should stop.
    """
    data = _get(CREDITS_URL, api_key_env=api_key_env, timeout_s=timeout_s)
    total = float(data.get("total_credits", 0.0))
    used = float(data.get("total_usage", 0.0))
    return total - used, total


@dataclass
class BudgetGuard:
    """Poll the key's counters, log every reading, trip at the ceiling.

    Parameters
    ----------
    baseline_usd:
        Key ``usage`` when this campaign started. Additional spend is measured
        from here.
    authorized_usd:
        What the owner authorized in additional spend.
    batch_cost_usd:
        Estimated cost of one more batch of work. The guard also stops when the
        key's live ``limit_remaining`` falls below this, because being refused
        *during* a batch wastes the rollouts already in flight.
    min_interval_s:
        Floor on polling rate. Rollouts land every few minutes and the endpoint
        is free, but a poll per rollout across a thread pool is pointless
        traffic. Batch boundaries poll with ``force=True`` regardless.
    """

    baseline_usd: float = BASELINE_USAGE
    authorized_usd: float = AUTHORIZED_USD
    reserve_usd: float = KEY_RESERVE_USD
    batch_cost_usd: float = 0.0
    ledger_path: Path | None = None
    min_interval_s: float = 45.0
    reader: Callable[[], AccountUsage] = read_openrouter_usage
    on_reading: Callable[[AccountUsage], None] | None = None
    on_limit_change: Callable[[float | None, float | None], None] | None = None

    tripped: bool = field(default=False, init=False)
    trip_reason: str = field(default="", init=False)
    last: AccountUsage | None = field(default=None, init=False)
    readings: int = field(default=0, init=False)
    seen_limit: float | None = field(default=None, init=False)
    _last_poll: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- reading ------------------------------------------------------------
    def ceiling(self) -> float:
        """Additional spend currently allowed. Rises if the key cap is raised."""
        if self.last is None:
            return 0.0
        return self.last.ceiling(
            baseline=self.baseline_usd,
            authorized=self.authorized_usd,
            reserve=self.reserve_usd,
        )

    def spent(self) -> float:
        return 0.0 if self.last is None else self.last.spent(baseline=self.baseline_usd)

    def poll(self) -> AccountUsage:
        """Read the key's counters and log them. Trips at the ceiling."""
        reading = self.reader()
        changed_from: float | None = None
        changed = False
        with self._lock:
            if self.seen_limit is not None and reading.limit != self.seen_limit:
                changed_from, changed = self.seen_limit, True
            self.seen_limit = reading.limit
            self.last = reading
            self.readings += 1
            self._last_poll = time.monotonic()

            spent = reading.spent(baseline=self.baseline_usd)
            ceiling = reading.ceiling(
                baseline=self.baseline_usd,
                authorized=self.authorized_usd,
                reserve=self.reserve_usd,
            )
            if spent >= ceiling:
                self.tripped = True
                self.trip_reason = (
                    f"additional spend ${spent:.4f} has reached the ceiling "
                    f"${ceiling:.4f} (key limit {reading.limit}, authorized "
                    f"${self.authorized_usd:.2f}, ${self.reserve_usd:.2f} reserved)"
                )
            elif (
                self.batch_cost_usd > 0
                and reading.limit_remaining is not None
                and reading.limit_remaining < self.batch_cost_usd
            ):
                self.tripped = True
                self.trip_reason = (
                    f"key limit_remaining ${reading.limit_remaining:.4f} is below "
                    f"the cost of one more batch (${self.batch_cost_usd:.4f}); "
                    f"being refused mid-batch would waste the rollouts already "
                    f"in flight"
                )
        self._log(reading)
        if changed and self.on_limit_change is not None:
            try:
                self.on_limit_change(changed_from, reading.limit)
            except Exception:  # noqa: BLE001 - reporting must not kill a run
                pass
        if self.on_reading is not None:
            try:
                self.on_reading(reading)
            except Exception:  # noqa: BLE001
                pass
        return reading

    def _log(self, reading: AccountUsage) -> None:
        if self.ledger_path is None:
            return
        entry = dict(reading.as_entry)
        entry.update(
            baseline_usd=self.baseline_usd,
            authorized_usd=self.authorized_usd,
            spent_this_campaign=round(reading.spent(baseline=self.baseline_usd), 6),
            ceiling_usd=round(
                reading.ceiling(
                    baseline=self.baseline_usd,
                    authorized=self.authorized_usd,
                    reserve=self.reserve_usd,
                ),
                6,
            ),
            tripped=self.tripped,
        )
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass

    # -- enforcement --------------------------------------------------------
    def check(self, *, force: bool = False) -> AccountUsage | None:
        """Poll if due, then raise if the ceiling is reached.

        Returns the reading when one was taken, ``None`` when the poll was
        skipped as too recent. Raises :class:`BudgetExhausted` either way once
        the guard has tripped -- a trip is permanent within a process, because
        spend does not go back down. (A *raised cap* is not a reason to
        un-trip in place: the run has stopped by then, and restarting it is one
        command and leaves a record.)
        """
        with self._lock:
            already = self.tripped
            due = force or (time.monotonic() - self._last_poll) >= self.min_interval_s
        if already:
            raise BudgetExhausted(self.reason())
        reading = self.poll() if due else None
        if self.tripped:
            raise BudgetExhausted(self.reason())
        return reading

    def reason(self) -> str:
        base = self.trip_reason or "budget guard tripped with no reading"
        return (
            f"{base}. Stop spending, write up what is in the corpus, and "
            f"escalate. Do NOT switch to a different model to keep going -- "
            f"that silently changes the independent variable."
        )

    def summary(self) -> dict:
        last = self.last
        return {
            "baseline_usd": self.baseline_usd,
            "authorized_usd": self.authorized_usd,
            "readings": self.readings,
            "tripped": self.tripped,
            "trip_reason": self.trip_reason,
            "usage": None if last is None else last.usage,
            "key_limit": None if last is None else last.limit,
            "limit_remaining": None if last is None else last.limit_remaining,
            "spent_this_campaign": None if last is None else round(self.spent(), 6),
            "ceiling_usd": None if last is None else round(self.ceiling(), 6),
            "headroom_usd": (
                None if last is None else round(self.ceiling() - self.spent(), 6)
            ),
        }

    def render(self) -> str:
        s = self.summary()
        if s["usage"] is None:
            return "budget: no reading yet"
        return (
            f"budget: spent ${s['spent_this_campaign']:.4f} of ${s['ceiling_usd']:.4f} "
            f"(key usage ${s['usage']:.4f}, limit {s['key_limit']}, "
            f"remaining ${s['limit_remaining']:.4f}) "
            f"-> ${s['headroom_usd']:.4f} headroom, "
            f"~{int(max(0.0, s['headroom_usd']) / 0.0381)} rollouts"
        )


@dataclass
class BudgetGuardedRunner(RolloutRunner):
    """Refuse to *start* a rollout once the ceiling is reached.

    Placed inside the recording runner rather than outside it, deliberately: a
    replayed rollout costs nothing, and a guard that also blocked replays would
    make the free part of the work -- re-analysis, resume -- fail in exactly the
    situation where it is the only thing left that can be done.
    """

    inner: RolloutRunner
    guard: BudgetGuard

    @property
    def capabilities(self) -> RunnerCapabilities:
        return self.inner.capabilities

    def preflight(self) -> list[str]:
        reasons = list(self.inner.preflight())
        try:
            self.guard.check(force=True)
        except BudgetExhausted as exc:
            reasons.append(str(exc))
        return reasons

    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        self.guard.check()
        return self.inner.run(candidate, task, seed)
