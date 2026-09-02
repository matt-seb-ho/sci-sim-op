"""The provider layer, which the free window makes load-bearing.

Every test here corresponds to a way the campaign could quietly lose hours or
money rather than to a way the code could be inelegant:

* a missing ``User-Agent`` makes Nous return 403, which reads as a bad key;
* an unhandled 429 kills a multi-hour search on its first throttle, and the
  measured ceiling guarantees throttling;
* a discarded ``usage`` block means we find out a model started billing from the
  invoice rather than from the run.
"""

from __future__ import annotations

import random
import threading

import pytest

from harness_evolve.proposers.backends import (
    USER_AGENT,
    AdaptiveLimiter,
    BilledCallError,
    CostLedger,
    HttpError,
    OpenRouterBackend,
    Route,
    RouteExhausted,
    RoutedBackend,
    backoff_delay,
    free_roster,
    free_window_backend,
)
from harness_evolve.proposers.base import ProposerError


def completion(text: str = "ok", cost: float | None = 0.0) -> dict:
    usage = {"total_tokens": 12}
    if cost is not None:
        usage["cost"] = cost
    return {"choices": [{"message": {"content": text}}], "usage": usage}


class FakeTransport:
    """Records every request and replays a scripted sequence of responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, payload, timeout):
        self.requests.append((url, headers, payload))
        item = self.responses.pop(0) if self.responses else completion()
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Backoff is real time; the tests only care that it was asked for."""
    slept: list[float] = []
    monkeypatch.setattr(
        "harness_evolve.proposers.backends.time.sleep", slept.append
    )
    return slept


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")


# --- the User-Agent, which is not decoration --------------------------------


def test_every_request_sets_an_explicit_user_agent(keys):
    """Nous 403s the default urllib UA. Without this the campaign cannot start."""
    transport = FakeTransport(completion())
    OpenRouterBackend(transport=transport)("hello")
    _, headers, _ = transport.requests[0]
    assert headers["User-Agent"] == USER_AGENT
    assert "urllib" not in headers["User-Agent"].lower()


def test_the_routed_backend_sets_it_too(keys):
    transport = FakeTransport(completion())
    RoutedBackend(transport=transport)("hello")
    _, headers, _ = transport.requests[0]
    assert headers["User-Agent"] == USER_AGENT


def test_the_key_travels_in_a_header_and_never_in_the_url(keys):
    transport = FakeTransport(completion())
    RoutedBackend(transport=transport)("hello")
    url, headers, _ = transport.requests[0]
    assert "or-key" not in url
    assert headers["Authorization"] == "Bearer or-key"


# --- 429 ---------------------------------------------------------------------


def test_a_throttle_is_retried_rather_than_fatal(keys, no_real_sleeping):
    transport = FakeTransport(HttpError(429, "slow down"), completion("second try"))
    assert OpenRouterBackend(transport=transport)("x") == "second try"
    assert len(no_real_sleeping) == 1


def test_a_throttle_halves_the_route_concurrency_limit(keys, no_real_sleeping):
    route = Route(name="r", model="m", api_url="u", api_key_env="OPENROUTER_API_KEY",
                  limiter=AdaptiveLimiter(start=8))
    backend = RoutedBackend(routes=[route],
                            transport=FakeTransport(HttpError(429), completion()))
    backend("x")
    assert route.limiter.limit == 4
    assert route.throttles == 1


def test_a_structural_4xx_is_not_retried(keys, no_real_sleeping):
    """A 400 will fail identically forever; retrying it just wastes the window."""
    transport = FakeTransport(HttpError(400, "bad request"), completion())
    with pytest.raises(ProposerError, match="400"):
        OpenRouterBackend(transport=transport)("x")
    assert len(transport.requests) == 1
    assert no_real_sleeping == []


def test_retry_after_is_honoured(monkeypatch):
    rng = random.Random(0)
    assert backoff_delay(0, retry_after=30.0, rng=rng) >= 30.0


def test_backoff_is_bounded_and_jittered():
    rng = random.Random(1)
    delays = [backoff_delay(6, cap=60.0, rng=rng) for _ in range(20)]
    assert all(0.0 <= d <= 60.0 for d in delays)
    # Full jitter: a fleet throttled by one upstream pool at one instant must not
    # come back in lockstep.
    assert len(set(delays)) > 15


# --- cost --------------------------------------------------------------------


def test_a_billing_response_stops_the_route_immediately(keys):
    """The entire budget policy: usage.cost != 0 means drop the model."""
    route = Route(name="paid", model="m", api_url="u", api_key_env="OPENROUTER_API_KEY")
    good = Route(name="free", model="m", api_url="u", api_key_env="NOUS_API_KEY")
    transport = FakeTransport(completion(cost=5e-05), completion("from the free one"))
    backend = RoutedBackend(routes=[route, good], transport=transport)

    assert backend("x") == "from the free one"
    assert not route.enabled
    assert "billed" in route.disabled_reason
    assert good.enabled


def test_a_billed_route_is_never_retried(keys):
    route = Route(name="paid", model="m", api_url="u", api_key_env="OPENROUTER_API_KEY")
    backend = RoutedBackend(routes=[route],
                            transport=FakeTransport(completion(cost=1e-06)))
    with pytest.raises(RouteExhausted):
        backend("x")
    with pytest.raises(RouteExhausted, match="disabled"):
        backend("x")


def test_the_single_backend_raises_on_billing_when_asked(keys):
    backend = OpenRouterBackend(transport=FakeTransport(completion(cost=0.01)),
                                require_zero_cost=True)
    with pytest.raises(BilledCallError, match="free-models-only"):
        backend("x")


def test_a_free_call_is_recorded_with_its_zero(keys):
    ledger = CostLedger()
    backend = RoutedBackend(transport=FakeTransport(completion()), ledger=ledger)
    backend("x")
    assert ledger.calls == 1
    assert ledger.total_cost == 0.0
    assert ledger.unknown_cost_calls == 0


def test_a_missing_cost_field_is_unknown_not_zero(keys):
    """Venice reports no cost at all; absence is not evidence of free."""
    ledger = CostLedger()
    backend = RoutedBackend(transport=FakeTransport(completion(cost=None)),
                            ledger=ledger)
    backend("x")
    assert ledger.unknown_cost_calls == 1
    assert ledger.calls == 1


def test_the_ledger_persists_when_given_a_path(keys, tmp_path):
    path = tmp_path / "nested" / "ledger.jsonl"
    backend = RoutedBackend(transport=FakeTransport(completion()),
                            ledger=CostLedger(path=path))
    backend("x")
    assert path.read_text().count("\n") == 1
    assert '"cost": 0.0' in path.read_text()


# --- failover ----------------------------------------------------------------


def test_a_dead_provider_costs_a_retry_rather_than_the_run(keys, no_real_sleeping):
    a = Route(name="a", model="m", api_url="u", api_key_env="OPENROUTER_API_KEY")
    b = Route(name="b", model="m", api_url="v", api_key_env="NOUS_API_KEY")
    transport = FakeTransport(*([HttpError(503, "overloaded")] * 4), completion("b"))
    assert RoutedBackend(routes=[a, b], transport=transport)("x") == "b"
    assert a.failures == 1 and b.successes == 1


def test_exhausting_every_route_names_what_was_tried(keys, no_real_sleeping):
    a = Route(name="a", model="m", api_url="u", api_key_env="OPENROUTER_API_KEY")
    transport = FakeTransport(*([HttpError(503)] * 8))
    with pytest.raises(RouteExhausted, match="a:"):
        RoutedBackend(routes=[a], transport=transport)("x")


def test_an_error_inside_a_200_body_is_diagnosed_as_an_error(keys):
    """OpenRouter delivers "unavailable for free" exactly this way."""
    body = {"error": {"message": "This model is unavailable for free."}}
    # Both roster routes, so the failover path cannot mask it.
    with pytest.raises(RouteExhausted, match="unavailable for free"):
        RoutedBackend(transport=FakeTransport(body, body))("x")


# --- roster ------------------------------------------------------------------


def test_the_roster_is_built_from_the_keys_that_exist(monkeypatch):
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert [r.name for r in free_roster()] == ["openrouter/stealth/ox-alpha"]

    monkeypatch.setenv("NOUS_API_KEY", "k2")
    assert [r.name for r in free_roster()] == [
        "openrouter/stealth/ox-alpha", "nous/stealth/ox-alpha",
    ]


def test_venice_is_not_in_the_roster(keys, monkeypatch):
    """It advertises $0, reports no cost, and 503s under this campaign's load."""
    monkeypatch.setenv("VENICE_API_KEY", "v")
    assert all("venice" not in r.name for r in free_roster())


def test_every_roster_route_demands_a_zero_cost(keys):
    assert all(r.require_zero_cost for r in free_roster())


def test_a_roster_with_no_keys_says_so(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    with pytest.raises(ProposerError, match="no free-window route"):
        free_window_backend()


def test_a_second_model_gets_its_own_routes(keys):
    routes = free_roster(("stealth/ox-alpha", "z-ai/glm-5.2:free"))
    assert len(routes) == 4
    assert routes[2].model == "z-ai/glm-5.2:free"


# --- adaptive concurrency ----------------------------------------------------


def test_the_limit_falls_immediately_and_rises_slowly():
    """Overshoot costs real requests; undershoot costs a little goodput."""
    lim = AdaptiveLimiter(start=8, minimum=1, maximum=16)
    lim.on_throttle()
    assert lim.limit == 4

    for _ in range(4):
        lim.on_success()
    assert lim.limit == 5          # one slot back after `limit` successes
    for _ in range(5):
        lim.on_success()
    assert lim.limit == 6


def test_the_limit_never_leaves_its_bounds():
    lim = AdaptiveLimiter(start=2, minimum=1, maximum=3)
    for _ in range(20):
        lim.on_throttle()
    assert lim.limit == 1
    for _ in range(200):
        lim.on_success()
    assert lim.limit == 3


def test_the_limiter_actually_blocks_past_its_limit():
    lim = AdaptiveLimiter(start=2, minimum=1, maximum=8)
    assert lim.acquire() and lim.acquire()
    assert lim.acquire(timeout=0.05) is False
    lim.release()
    assert lim.acquire(timeout=0.5) is True


def test_the_limiter_is_safe_under_threads():
    lim = AdaptiveLimiter(start=4, minimum=1, maximum=4)
    peak = 0
    seen = threading.Lock()

    def worker():
        nonlocal peak
        with lim:
            with seen:
                peak = max(peak, lim.in_flight)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak <= 4
    assert lim.in_flight == 0


def test_stats_report_what_the_run_actually_did(keys):
    backend = RoutedBackend(transport=FakeTransport(completion(), completion()))
    backend("x")
    stats = backend.stats()
    assert stats["calls"] == 1
    assert stats["total_cost"] == 0.0
    assert stats["routes"][0]["successes"] == 1


# --- the reasoning-model failure mode ---------------------------------------


def reasoning_only(finish: str = "length") -> dict:
    """What ox-alpha returns when the token budget runs out mid-thought."""
    return {
        "choices": [{
            "finish_reason": finish,
            "message": {"content": None, "reasoning": "Let me think about this..."},
        }],
        "usage": {"cost": 0, "total_tokens": 300},
    }


def test_an_empty_completion_is_an_error_not_a_none(keys):
    """It surfaced live as `TypeError: object of type 'NoneType' has no len()`."""
    with pytest.raises(RouteExhausted, match="finish_reason=length"):
        RoutedBackend(transport=FakeTransport(reasoning_only(), reasoning_only()))("x")


def test_the_diagnosis_names_the_actual_cause(keys):
    backend = OpenRouterBackend(transport=FakeTransport(reasoning_only()))
    with pytest.raises(ProposerError, match="Raise max_tokens"):
        backend("x")


def test_reasoning_text_is_never_passed_off_as_the_answer(keys):
    """The proposer parses <edit> blocks; a chain of thought would confuse it."""
    backend = OpenRouterBackend(transport=FakeTransport(reasoning_only("stop")))
    with pytest.raises(ProposerError) as caught:
        backend("x")
    assert "Let me think about this" not in str(caught.value)


def test_a_truncated_call_still_counts_against_the_budget(keys):
    """It billed (or did not) regardless of whether it produced anything."""
    ledger = CostLedger()
    backend = RoutedBackend(transport=FakeTransport(reasoning_only(), reasoning_only()),
                            ledger=ledger)
    with pytest.raises(RouteExhausted):
        backend("x")
    assert ledger.calls == 2
