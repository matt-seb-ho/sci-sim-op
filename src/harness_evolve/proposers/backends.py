"""Model backends for the proposer.

The proposer takes an injected caller, so a backend is just a callable from
prompt to text. Keeping them here rather than inside ``LLMProposer`` means the
proposer's prompt design and its transport are independently testable, and
adding a provider never touches the part that decides what to say.

Two exist because the choice is not free. The proposer should not be the same
model that runs the rollouts — that is a self-distillation confound, cheap to
avoid — and which providers are reachable depends on whose keys are configured.
Neither is a default worth hardcoding.

``anthropic`` is an optional dependency. The package is otherwise stdlib-only,
and a search that can run offline against a mock is worth more than one that
cannot start without a network client installed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from harness_evolve.proposers.base import ProposerError


class Backend(Protocol):
    """Prompt in, completion text out."""

    name: str

    def __call__(self, prompt: str, *, system: str = "") -> str: ...


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
    """Any model reachable through OpenRouter, over raw HTTP.

    Deliberately dependency-free: this is the escape hatch for running the
    proposer on a model whose own SDK we do not want to depend on, which is the
    usual case when the point is *not* to use the same family as the rollouts.
    """

    model: str = "gemini-3-flash-preview"
    api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    api_key_env: str = "OPENROUTER_API_KEY"
    max_tokens: int = 4000
    temperature: float = 0.8
    timeout_s: float = 300.0
    name: str = "openrouter"

    def __call__(self, prompt: str, *, system: str = "") -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProposerError(f"{self.api_key_env} is not set")
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": messages,
            }
        ).encode()
        req = urllib.request.Request(
            self.api_url, data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise ProposerError(f"{self.name} call failed: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProposerError(f"unexpected {self.name} response: {exc}") from exc


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
