"""Model backends for the proposer, and the routing layer that keeps them alive.

The proposer takes an injected caller, so a backend is just a callable from
prompt to text. Keeping them here rather than inside ``LLMProposer`` means the
proposer's prompt design and its transport are independently testable, and
adding a provider never touches the part that decides what to say.

Several exist because the choice is not free. The proposer should not be the same
model that runs the rollouts -- that is a self-distillation confound, cheap to
avoid -- and which providers are reachable depends on whose keys are configured.
Neither is a default worth hardcoding.

``anthropic`` is an optional dependency. The package is otherwise stdlib-only,
and a search that can run offline against a mock is worth more than one that
cannot start without a network client installed.

What the free window forced in here
-----------------------------------
This module used to be forty lines of raw HTTP with no ``User-Agent``, no retry,
and no reading of the ``usage`` block. All three were fatal for a campaign whose
whole premise is running for hours against models that are free *for now*, and
each corresponds to a fact measured on 2026-08-26 rather than to a guess:

* **User-Agent.** Nous' edge returns 403 for the *default* urllib UA string,
  ``Python-urllib/3.12``, and 200 for literally any other value. Without one the
  failure is indistinguishable from a bad key. Every request this module makes
  sets one.
* **429 with jitter, and adaptive concurrency.** ``stealth/ox-alpha`` has exactly
  one upstream pool (``Stealth``), reached identically through OpenRouter, Nous
  and Venice. Goodput peaks near 12.3 completions/min at concurrency 16 and
  everything past that converts directly into 429s. So the limit is discovered by
  AIMD rather than configured, and retries are jittered so a throttled fleet does
  not resynchronise into a thundering herd.
* **Cost from ``usage``.** A catalogue price of ``0`` is evidence about the
  listing, not about what the next call costs: OpenRouter reclassified
  ``tencent/hy3:free`` to paid, and Nous' ``:free`` slug bills ~$5e-5/call while
  still answering. The only reliable signal is what the response reports it
  charged, so every call reads it and a non-zero reading permanently disables the
  route. That is the entire budget policy.

Failover across the roster buys *availability*, not throughput: pointing three
provider accounts at ox-alpha adds nothing, because they resolve to the same
upstream pool. It is in here so that one provider's edge going down costs a
retry rather than the run.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from harness_evolve.proposers.base import ProposerError

#: Never the urllib default. See the module docstring: Nous 403s that exact
#: string, and the resulting failure looks like an auth error.
USER_AGENT = "sci-sim-op/0.1 (harness-evolve)"

#: Reached identically through every provider that lists it; see module docstring.
OX_ALPHA = "stealth/ox-alpha"


class Backend(Protocol):
    """Prompt in, completion text out."""

    name: str

    def __call__(self, prompt: str, *, system: str = "") -> str: ...


class BilledCallError(ProposerError):
    """A route that was supposed to be free reported a non-zero cost.

    Raised once, on the first billing response. The route is disabled at the same
    moment, so this is a stop signal rather than something to retry through.
    """


class RouteExhausted(ProposerError):
    """Every route in the roster is disabled or refused the call."""


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpError(Exception):
    """An HTTP failure that retry policy can reason about."""

    code: int
    body: str = ""
    retry_after: float | None = None

    @property
    def throttled(self) -> bool:
        return self.code == 429

    @property
    def transient(self) -> bool:
        # 5xx and 408 are the provider's problem and usually pass; 502/503 in
        # particular is what Venice returns for "the model is overloaded", which
        # is a capacity statement, not a price one.
        return self.code in (408, 409, 500, 502, 503, 504)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"HTTP {self.code}: {self.body[:200]}"


Transport = Callable[[str, dict, dict, float], dict]


def urllib_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    """POST JSON, return the decoded body. Raises :class:`HttpError` on failure.

    The key is only ever an ``Authorization`` header -- never a query parameter,
    because URLs land in logs and proxy access records.
    """
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()[:500].decode("utf8", "replace")
        retry_after = None
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if raw:
            try:
                retry_after = float(raw)
            except ValueError:
                retry_after = None
        raise HttpError(exc.code, body, retry_after) from exc
    except urllib.error.URLError as exc:
        # DNS/connection/timeout: no status code, but retryable in the same way
        # a 503 is. 599 is a convention, not a real code.
        raise HttpError(599, str(exc.reason)) from exc


def backoff_delay(attempt: int, *, base: float = 2.0, cap: float = 60.0,
                  retry_after: float | None = None,
                  rng: random.Random | None = None) -> float:
    """Full-jitter exponential backoff, honouring ``Retry-After`` when given.

    Full jitter rather than exponential-plus-jitter because the failure mode here
    is a fleet of workers all throttled by the *same* upstream pool at the same
    instant. Equal-and-decorrelated waits are what stop them retrying in lockstep.
    """
    rng = rng or random
    ceiling = min(cap, base * (2 ** attempt))
    if retry_after is not None:
        # Never retry sooner than asked; still jitter above it.
        return retry_after + rng.uniform(0.0, min(cap, base * (2 ** attempt)) / 2)
    return rng.uniform(0.0, ceiling)


# --------------------------------------------------------------------------
# adaptive concurrency
# --------------------------------------------------------------------------


@dataclass
class AdaptiveLimiter:
    """AIMD concurrency control for one route.

    The measured ceiling is a property of an upstream pool we do not own and
    cannot query, and it moves: 12.3/min at concurrency 16 today says nothing
    about tomorrow, or about what happens when someone else's job starts. So the
    limit is *discovered* -- additive increase on sustained success, multiplicative
    decrease on a 429 -- rather than configured. Configuring it would mean either
    leaving goodput on the table or manufacturing 429s all night.

    Additive increase is deliberately slow (one slot per ``limit`` consecutive
    successes) and the decrease is immediate. Overshooting costs real requests.
    """

    start: int = 8
    minimum: int = 1
    maximum: int = 16
    _limit: float = field(init=False, default=0.0)
    _in_flight: int = field(init=False, default=0)
    _streak: int = field(init=False, default=0)
    _cv: threading.Condition = field(init=False, repr=False,
                                     default_factory=threading.Condition)

    def __post_init__(self) -> None:
        self._limit = float(max(self.minimum, min(self.start, self.maximum)))

    @property
    def limit(self) -> int:
        return int(self._limit)

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def acquire(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while self._in_flight >= max(self.minimum, int(self._limit)):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cv.wait(remaining if remaining is not None else 1.0)
            self._in_flight += 1
            return True

    def release(self) -> None:
        with self._cv:
            self._in_flight = max(0, self._in_flight - 1)
            self._cv.notify()

    def on_success(self) -> None:
        with self._cv:
            self._streak += 1
            if self._streak >= max(1, int(self._limit)) and self._limit < self.maximum:
                self._limit = min(float(self.maximum), self._limit + 1.0)
                self._streak = 0
                self._cv.notify()

    def on_throttle(self) -> None:
        with self._cv:
            self._streak = 0
            self._limit = max(float(self.minimum), self._limit * 0.5)

    def __enter__(self) -> "AdaptiveLimiter":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# --------------------------------------------------------------------------
# cost accounting
# --------------------------------------------------------------------------


@dataclass
class CostLedger:
    """What the provider says it charged, per call, with a hard stop at non-zero.

    The campaign's budget policy is one rule: never call a model whose
    ``usage.cost`` comes back non-zero. This enforces it rather than reporting it.

    ``None`` is not zero. Venice returns no cost field at all, and absence is
    evidence about the response schema, not about the price -- so unknown-cost
    calls are counted separately and left to the roster's ``require_zero_cost``
    setting rather than being quietly treated as free.
    """

    path: Path | None = None
    calls: int = field(default=0, init=False)
    unknown_cost_calls: int = field(default=0, init=False)
    total_cost: float = field(default=0.0, init=False)
    billed: dict[str, float] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, route: str, model: str, usage: dict | None) -> float | None:
        cost = (usage or {}).get("cost")
        with self._lock:
            self.calls += 1
            if cost is None:
                self.unknown_cost_calls += 1
            else:
                self.total_cost += float(cost)
                if float(cost) != 0.0:
                    self.billed[route] = float(cost)
            if self.path is not None:
                entry = {
                    "ts": int(time.time()), "route": route, "model": model,
                    "cost": cost, "tokens": (usage or {}).get("total_tokens"),
                }
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(entry) + "\n")
                except OSError:
                    pass
        return None if cost is None else float(cost)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


@dataclass
class Route:
    """One (provider, model) pair, with its own limiter and health.

    A route rather than a provider because the thing that throttles, bills, or
    disappears is the pair. ``stealth/ox-alpha`` on OpenRouter and on Nous are two
    routes over one upstream pool: independently reachable, not independently
    fast.
    """

    name: str
    model: str
    api_url: str
    api_key_env: str
    require_zero_cost: bool = True
    limiter: AdaptiveLimiter = field(default_factory=AdaptiveLimiter)
    disabled_reason: str = ""
    successes: int = 0
    throttles: int = 0
    failures: int = 0

    @property
    def enabled(self) -> bool:
        return not self.disabled_reason

    def key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProposerError(f"{self.api_key_env} is not set")
        return key

    def disable(self, reason: str) -> None:
        self.disabled_reason = reason

    def stats(self) -> dict:
        return {
            "route": self.name, "model": self.model, "limit": self.limiter.limit,
            "successes": self.successes, "throttles": self.throttles,
            "failures": self.failures, "disabled": self.disabled_reason or None,
        }


def free_roster(models: Sequence[str] = (OX_ALPHA,)) -> list[Route]:
    """The routes the free-window campaign may use, in preference order.

    OpenRouter first: it load-balances across upstreams by itself and is the
    account with headroom. Nous second, as a different door onto the same room --
    worth having when OpenRouter's edge is the thing that is unwell, worth nothing
    as extra capacity. Venice is deliberately absent: it returns no cost field
    (so ``require_zero_cost`` can never be satisfied) and answers "the model is
    currently overloaded" under exactly the load this campaign generates.
    """
    routes: list[Route] = []
    for model in models:
        if os.environ.get("OPENROUTER_API_KEY"):
            routes.append(Route(
                name=f"openrouter/{model}", model=model,
                api_url="https://openrouter.ai/api/v1/chat/completions",
                api_key_env="OPENROUTER_API_KEY",
            ))
        if os.environ.get("NOUS_API_KEY"):
            routes.append(Route(
                name=f"nous/{model}", model=model,
                api_url="https://inference-api.nousresearch.com/v1/chat/completions",
                api_key_env="NOUS_API_KEY",
            ))
    return routes


def content_or_error(name: str, data: dict) -> str:
    """Pull the completion text out, or say precisely why there is none.

    ``stealth/ox-alpha`` is a reasoning model, and OpenRouter returns its chain of
    thought in ``message.reasoning`` while ``message.content`` stays ``None``
    until the model finishes thinking. Measured 2026-08-26: at ``max_tokens=300``
    every call came back ``finish_reason="length"`` with ``content: null`` and
    ~300 tokens of reasoning; at 1500 the same prompt answered normally.

    Two consequences, both encoded here.

    Returning ``None`` would violate this module's own Protocol and surface
    downstream as ``TypeError: object of type 'NoneType' has no len()`` -- which
    is what it did, in the first live smoke run. So an empty completion is an
    error that names ``finish_reason``.

    And the reasoning text is *not* substituted for the answer. The proposer
    parses ``<edit>`` and ``<prediction>`` blocks; handing it a chain of thought
    would give the parser two things that look like answers, which is the exact
    confound ``AnthropicBackend`` filters thinking blocks to avoid.
    """
    if data.get("error"):
        raise ProposerError(
            f"{name} returned an error: {json.dumps(data['error'])[:200]}"
        )
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError) as exc:
        raise ProposerError(f"unexpected {name} response: {exc}") from exc

    text = message.get("content")
    if text and text.strip():
        return text

    finish = choice.get("finish_reason") or choice.get("native_finish_reason") or "?"
    reasoning = (message.get("reasoning") or "")
    if finish == "length":
        raise ProposerError(
            f"{name} returned no content (finish_reason=length, "
            f"{len(reasoning)} chars of reasoning): the token budget was spent "
            "thinking. Raise max_tokens -- this model needs room to reason "
            "*and* answer."
        )
    raise ProposerError(
        f"{name} returned no content (finish_reason={finish}, "
        f"{len(reasoning)} chars of reasoning)"
    )


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------


@dataclass
class AnthropicBackend:
    """Claude via the official SDK.

    Adaptive thinking is on because proposing a harness edit is a reasoning
    task: the model has to read a layered evidence corpus, locate a failure it
    can act on, and choose one bounded change. Thinking blocks are filtered out
    of the returned text -- the caller wants the ``<edit>`` and ``<prediction>``
    blocks, and letting reasoning text through would give the response parser
    two things that look like answers.
    """

    model: str = "claude-opus-5"
    max_tokens: int = 8000
    effort: str = "high"
    timeout_s: float = 300.0
    name: str = "anthropic"
    _client: Any = field(default=None, repr=False)

    def client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ProposerError(
                    "the anthropic package is not installed; "
                    "pip install 'harness-evolve[anthropic]'"
                ) from exc
            # Zero-arg: resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or a
            # configured profile, in that order. Never take a key as an argument.
            self._client = anthropic.Anthropic(timeout=self.timeout_s)
        return self._client

    def __call__(self, prompt: str, *, system: str = "") -> str:
        try:
            response = self.client().messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system or None,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise ProposerError(f"{self.name} call failed: {exc}") from exc

        # A refusal is a successful HTTP response with no usable content; reading
        # .content without checking would surface it as an unparseable proposal
        # and burn a retry on the wrong diagnosis.
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            raise ProposerError(
                f"{self.name} declined the request "
                f"({getattr(details, 'category', 'unspecified')})"
            )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        if not text.strip():
            raise ProposerError(
                f"{self.name} returned no text "
                f"(stop_reason={getattr(response, 'stop_reason', '?')})"
            )
        return text


@dataclass
class OpenRouterBackend:
    """Any OpenAI-compatible endpoint, over raw HTTP.

    Deliberately dependency-free: this is the escape hatch for running the
    proposer on a model whose own SDK we do not want to depend on, which is the
    usual case when the point is *not* to use the same family as the rollouts.

    Nous is this class with a different base URL and key env -- see :meth:`nous`.
    """

    model: str = "gemini-3-flash-preview"
    api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    api_key_env: str = "OPENROUTER_API_KEY"
    max_tokens: int = 4000
    temperature: float = 0.8
    timeout_s: float = 300.0
    name: str = "openrouter"
    user_agent: str = USER_AGENT
    max_attempts: int = 5
    require_zero_cost: bool = False
    ledger: CostLedger | None = None
    transport: Transport = urllib_transport
    rng: random.Random | None = None
    #: Usage block from the most recent successful call. Convenience for
    #: single-threaded use; concurrent callers should read the ledger instead.
    last_usage: dict = field(default_factory=dict, repr=False)

    @classmethod
    def nous(cls, model: str = OX_ALPHA, **kw: Any) -> "OpenRouterBackend":
        return cls(
            model=model,
            api_url="https://inference-api.nousresearch.com/v1/chat/completions",
            api_key_env="NOUS_API_KEY", name="nous", **kw,
        )

    def _payload(self, prompt: str, system: str) -> dict:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }

    def _headers(self, key: str) -> dict:
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }

    def __call__(self, prompt: str, *, system: str = "") -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProposerError(f"{self.api_key_env} is not set")
        payload = self._payload(prompt, system)
        headers = self._headers(key)
        rng = self.rng or random

        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                data = self.transport(self.api_url, headers, payload, self.timeout_s)
            except HttpError as exc:
                last = exc
                if not (exc.throttled or exc.transient) or attempt == self.max_attempts - 1:
                    raise ProposerError(f"{self.name} call failed: {exc}") from exc
                time.sleep(backoff_delay(attempt, retry_after=exc.retry_after, rng=rng))
                continue
            except Exception as exc:  # noqa: BLE001 - transport may be injected
                raise ProposerError(f"{self.name} call failed: {exc}") from exc

            return self._extract(data)
        raise ProposerError(f"{self.name} call failed: {last}")

    def _extract(self, data: dict) -> str:
        usage = data.get("usage") or {}
        self.last_usage = usage
        if self.ledger is not None:
            self.ledger.record(self.name, self.model, usage)
        cost = usage.get("cost")
        # Cost is checked before content: a call that billed has already billed,
        # whether or not it produced anything usable.
        if self.require_zero_cost and cost is not None and float(cost) != 0.0:
            raise BilledCallError(
                f"{self.name}/{self.model} reported usage.cost={cost} -- this "
                "campaign is free-models-only, so the route is dropped"
            )
        return content_or_error(self.name, data)


@dataclass
class RoutedBackend:
    """A free-roster backend: adaptive concurrency, jittered retry, failover.

    One call may traverse several routes. Within a route, 429s are retried with
    full-jitter backoff and the route's concurrency limit is halved; across
    routes, a route that is throttled *out* (or that bills, or that 4xxs
    structurally) hands the call to the next one. A route that reports a non-zero
    cost is disabled permanently and never retried -- billing is not a transient
    failure.

    Thread-safe: intended to be shared by a pool of workers, which is the only
    configuration where the concurrency control means anything.
    """

    routes: list[Route] = field(default_factory=free_roster)
    #: Generous because the roster is reasoning models: measured 2026-08-26,
    #: ox-alpha spends the whole budget thinking and returns no content at 300,
    #: and answers normally at 1500. A proposal is longer than that prompt was.
    max_tokens: int = 8000
    temperature: float = 0.8
    timeout_s: float = 300.0
    attempts_per_route: int = 4
    name: str = "free-roster"
    user_agent: str = USER_AGENT
    ledger: CostLedger = field(default_factory=CostLedger)
    transport: Transport = urllib_transport
    rng: random.Random | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def available(self) -> list[Route]:
        with self._lock:
            return [r for r in self.routes if r.enabled]

    def stats(self) -> dict:
        return {
            "routes": [r.stats() for r in self.routes],
            "calls": self.ledger.calls,
            "total_cost": self.ledger.total_cost,
            "unknown_cost_calls": self.ledger.unknown_cost_calls,
        }

    def __call__(self, prompt: str, *, system: str = "") -> str:
        rng = self.rng or random
        errors: list[str] = []
        for route in self.available():
            try:
                return self._call_route(route, prompt, system, rng)
            except BilledCallError as exc:
                route.disable(f"billed: {exc}")
                errors.append(str(exc))
            except ProposerError as exc:
                route.failures += 1
                errors.append(f"{route.name}: {exc}")
        raise RouteExhausted(
            "every free route failed or is disabled; tried "
            f"{len(self.routes)}: " + " | ".join(errors[:4])
        )

    def _call_route(self, route: Route, prompt: str, system: str,
                    rng: random.Random) -> str:
        key = route.key()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        payload = {
            "model": route.model, "max_tokens": self.max_tokens,
            "temperature": self.temperature, "messages": messages,
        }

        last: Exception | None = None
        for attempt in range(self.attempts_per_route):
            route.limiter.acquire()
            try:
                data = self.transport(route.api_url, headers, payload, self.timeout_s)
            except HttpError as exc:
                last = exc
                if exc.throttled:
                    route.throttles += 1
                    route.limiter.on_throttle()
                elif not exc.transient:
                    raise ProposerError(f"{route.name}: {exc}") from exc
                if attempt == self.attempts_per_route - 1:
                    break
                time.sleep(backoff_delay(attempt, retry_after=exc.retry_after, rng=rng))
                continue
            except Exception as exc:  # noqa: BLE001 - injected transports vary
                raise ProposerError(f"{route.name}: {exc}") from exc
            finally:
                route.limiter.release()

            text = self._extract(route, data)
            route.successes += 1
            route.limiter.on_success()
            return text

        raise ProposerError(f"{route.name}: exhausted retries ({last})")

    def _extract(self, route: Route, data: dict) -> str:
        usage = data.get("usage") or {}
        cost = self.ledger.record(route.name, route.model, usage)
        if route.require_zero_cost and cost is not None and cost != 0.0:
            raise BilledCallError(
                f"{route.name} reported usage.cost={cost} -- free-models-only"
            )
        return content_or_error(route.name, data)


def default_backend() -> Backend:
    """Whichever backend the environment can actually reach.

    Resolution order is by what is configured, not by preference: a proposer
    that cannot make a call is useless regardless of which model it would have
    preferred. If nothing is configured the error names both options rather than
    failing on whichever happened to be checked first.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return OpenRouterBackend()
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return AnthropicBackend()
    raise ProposerError(
        "no proposer backend is configured: set OPENROUTER_API_KEY or "
        "ANTHROPIC_API_KEY, or pass an explicit backend"
    )


def free_window_backend(
    models: Sequence[str] = (OX_ALPHA,),
    *,
    ledger_path: Path | None = None,
    **kw: Any,
) -> RoutedBackend:
    """The campaign backend: the free roster, with billing as a hard stop."""
    routes = free_roster(models)
    if not routes:
        raise ProposerError(
            "no free-window route is configured: set OPENROUTER_API_KEY "
            "and/or NOUS_API_KEY"
        )
    return RoutedBackend(routes=routes, ledger=CostLedger(path=ledger_path), **kw)
