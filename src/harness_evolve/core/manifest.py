"""The adapter manifest: an explicit, typed description of what is searchable.

In v1 a candidate was "whatever files happen to be in ``plugin_evolving/vN/``",
and the writable set was hardcoded in ``reflect.py:240-243`` as
``{PRIMER.md, memory/, skills/, agents/}``. Everything else -- crucially the
stop hook, the validators, and the MCP servers -- was copied verbatim by
``copy_scaffolding()`` and could never be searched. The paper's own ablation
says S is the dominant component on GEOS and OpenFOAM, so v1's search space
excluded the thing that mattered.

Here the adapter is a manifest of typed components. Prose components carry a
token budget (v1's primer grew 270B -> 3159B over three unmonitored rounds).
The stop policy is a *config* component, so retry budget, feedback shape, and
which checks run are all searchable without letting the proposer rewrite hook
code. Code components are check plugins behind a fixed interface with a
mandatory test (arXiv:2603.05578: one-shot tool creation fails, interface
errors compound).

Scaffolding is deliberately absent from the manifest: it is resolved from
``plugin/`` at materialization time rather than snapshotted, because v1's
snapshot froze at the pre-``geosx --validate-input`` implementation and the
lineage silently diverged 274 lines from the plugin it was supposed to extend.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ComponentKind = Literal["prose", "itemized", "checked", "config", "code"]

#: Component kinds a proposer may emit as free text.
TEXT_KINDS: frozenset[str] = frozenset({"prose", "itemized", "checked"})

#: Feedback shapes the stop hook may return. ``errors_plus_tables`` forwards
#: geosx's inline valid-attribute table, which is the richest signal the
#: validator produces and the natural target for an EFC-style objective.
FEEDBACK_SHAPES: frozenset[str] = frozenset(
    {"minimal", "structured_errors", "errors_plus_tables"}
)

#: Last-resort check names, used only when the check registry cannot be
#: imported. Never treat this as the universe of checks: hardcoding that list
#: here silently truncates the search space to whatever was known when this
#: module was written, and a stop policy naming a perfectly good check would be
#: rejected as invalid. Resolution goes through :func:`resolve_known_checks`.
_FALLBACK_CHECKS: frozenset[str] = frozenset(
    {"parse", "geosx_validate", "required_sections", "constraints"}
)


def resolve_known_checks(
    explicit: frozenset[str] | None = None, plugins: Any = None
) -> frozenset[str]:
    """The set of check names a stop policy may name.

    Resolved from the live check registry rather than a constant, so adding a
    built-in or vetting a candidate-authored plugin widens the search space
    automatically. The alternative -- a hardcoded list -- fails in the worst
    available way: the manifest rejects a stop policy naming a real check, so
    the loop looks like it is searching over checks while quietly refusing most
    of them.

    The import is lazy and tolerated to fail so ``core`` stays usable on its own.
    """
    if explicit is not None:
        return explicit
    try:
        from harness_evolve.checks.api import known_check_names
    except Exception:
        return _FALLBACK_CHECKS
    try:
        return frozenset(known_check_names(plugins))
    except Exception:
        return _FALLBACK_CHECKS

DEFAULT_MANIFEST_NAME = "manifest.toml"

#: Deprecated alias. Prefer :func:`resolve_known_checks`, which reflects the
#: live registry instead of a snapshot of it.
KNOWN_CHECKS = _FALLBACK_CHECKS


class ManifestError(ValueError):
    """Raised when a manifest is structurally invalid.

    Always raised *before* any rollout is spent -- a malformed manifest is a
    free rejection, and free rejections are where most bad proposals should die.
    """


@dataclass(frozen=True)
class ComponentSpec:
    """One searchable component of the adapter."""

    name: str
    kind: ComponentKind
    path: str | None = None
    dir: str | None = None
    budget_tokens: int | None = None

    @property
    def is_text(self) -> bool:
        return self.kind in TEXT_KINDS

    def validate(self) -> None:
        if self.kind not in ("prose", "itemized", "checked", "config", "code"):
            raise ManifestError(f"component {self.name!r}: unknown kind {self.kind!r}")
        if self.kind == "code":
            if not self.dir:
                raise ManifestError(f"component {self.name!r}: kind=code requires 'dir'")
        elif self.kind == "config":
            pass  # config lives inline in the manifest, no path
        else:
            if not self.path:
                raise ManifestError(
                    f"component {self.name!r}: kind={self.kind} requires 'path'"
                )
        if self.budget_tokens is not None and self.budget_tokens <= 0:
            raise ManifestError(
                f"component {self.name!r}: budget_tokens must be positive"
            )


@dataclass(frozen=True)
class StopPolicy:
    """The ``stop_0 -> stop_S`` interface, made searchable.

    v1 could not touch this: ``GEOS_HOOK_MAX_RETRIES`` was fixed at 2 and the
    feedback shape was whatever ``verify_outputs.py`` happened to emit. The
    paper's recommendation (vi) -- "static hooks only raise the floor;
    closed-loop retries driven by validator output are needed to raise the
    ceiling" -- is a claim about exactly these three fields.
    """

    retries: int = 2
    feedback_shape: str = "structured_errors"
    checks: tuple[str, ...] = ("parse", "geosx_validate")

    def validate(self, known_checks: frozenset[str] | None = None) -> None:
        known_checks = resolve_known_checks(known_checks)
        if not 0 <= self.retries <= 6:
            raise ManifestError(f"stop_policy.retries out of range [0,6]: {self.retries}")
        if self.feedback_shape not in FEEDBACK_SHAPES:
            raise ManifestError(
                f"stop_policy.feedback_shape {self.feedback_shape!r} not in "
                f"{sorted(FEEDBACK_SHAPES)}"
            )
        if not self.checks:
            raise ManifestError("stop_policy.checks must not be empty")
        unknown = sorted(set(self.checks) - set(known_checks))
        if unknown:
            raise ManifestError(f"stop_policy.checks: unknown checks {unknown}")

    def to_env(self) -> dict[str, str]:
        """Environment the runner exports so the hook honours this policy.

        Keeps the historical ``GEOS_HOOK_*`` names -- every ``launch_*.sh``
        already exports ``GEOS_HOOK_XMLLINT`` and the hook kept that flag name
        through the geosx swap for exactly this reason.
        """
        return {
            "GEOS_HOOK_MAX_RETRIES": str(self.retries),
            "GEOS_HOOK_XMLLINT": "1" if "geosx_validate" in self.checks else "0",
            "GEOS_EVOLVE_FEEDBACK_SHAPE": self.feedback_shape,
            "GEOS_EVOLVE_CHECKS": ",".join(self.checks),
        }


@dataclass
class Manifest:
    """A parsed ``manifest.toml``."""

    components: dict[str, ComponentSpec] = field(default_factory=dict)
    stop_policy: StopPolicy = field(default_factory=StopPolicy)
    parent: str | None = None
    generation: int = 0

    # -- construction ----------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        meta = data.get("meta") or {}
        raw_components = data.get("components") or {}
        if not isinstance(raw_components, dict):
            raise ManifestError("[components] must be a table")

        components: dict[str, ComponentSpec] = {}
        stop_policy = StopPolicy()
        for name, body in raw_components.items():
            if not isinstance(body, dict):
                raise ManifestError(f"component {name!r} must be a table")
            kind = body.get("kind")
            if kind is None:
                raise ManifestError(f"component {name!r}: missing 'kind'")
            if kind == "config":
                # The only config component we recognise today is the stop policy.
                if name != "stop_policy":
                    raise ManifestError(
                        f"component {name!r}: kind=config is only supported for "
                        "'stop_policy'"
                    )
                stop_policy = StopPolicy(
                    retries=int(body.get("retries", 2)),
                    feedback_shape=str(body.get("feedback_shape", "structured_errors")),
                    checks=tuple(body.get("checks", ("parse", "geosx_validate"))),
                )
            spec = ComponentSpec(
                name=name,
                kind=kind,
                path=body.get("path"),
                dir=body.get("dir"),
                budget_tokens=body.get("budget_tokens"),
            )
            components[name] = spec

        m = cls(
            components=components,
            stop_policy=stop_policy,
            parent=meta.get("parent"),
            generation=int(meta.get("generation", 0)),
        )
        m.validate()
        return m

    @classmethod
    def from_toml(cls, text: str) -> "Manifest":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManifestError(f"manifest is not valid TOML: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        return cls.from_toml(Path(path).read_text())

    # -- validation ------------------------------------------------------
    def validate(self, known_checks: frozenset[str] | None = None) -> None:
        if not self.components:
            raise ManifestError("manifest declares no components")
        seen_paths: dict[str, str] = {}
        for spec in self.components.values():
            spec.validate()
            target = spec.path or spec.dir
            if target:
                if target.startswith("/") or ".." in Path(target).parts:
                    raise ManifestError(
                        f"component {spec.name!r}: path escapes the adapter: {target!r}"
                    )
                if target in seen_paths:
                    raise ManifestError(
                        f"components {seen_paths[target]!r} and {spec.name!r} "
                        f"both claim {target!r}"
                    )
                seen_paths[target] = spec.name
        self.stop_policy.validate(known_checks)

    # -- accessors -------------------------------------------------------
    def text_components(self) -> dict[str, ComponentSpec]:
        """Components a proposer may emit as free text, keyed by name."""
        return {n: s for n, s in self.components.items() if s.is_text}

    def path_for(self, name: str) -> str:
        spec = self.components[name]
        if not spec.path:
            raise ManifestError(f"component {name!r} has no file path")
        return spec.path

    def component_for_path(self, rel_path: str) -> ComponentSpec | None:
        """Reverse lookup: which component owns ``rel_path``?

        This is the writable-path allowlist, derived from the manifest rather
        than hardcoded as in ``reflect.py:240-243``.
        """
        for spec in self.components.values():
            if spec.path and spec.path == rel_path:
                return spec
            if spec.dir and (rel_path.startswith(spec.dir.rstrip("/") + "/")):
                return spec
        return None

    def is_writable(self, rel_path: str) -> bool:
        if rel_path.startswith("/") or ".." in Path(rel_path).parts:
            return False
        if rel_path == DEFAULT_MANIFEST_NAME:
            return True
        return self.component_for_path(rel_path) is not None

    # -- serialization ---------------------------------------------------
    def content_toml(self) -> str:
        """Everything that defines behaviour, and nothing that records history.

        Used for content addressing. Two adapters that would behave identically
        must serialize identically here, however each was arrived at.
        """
        return self._render(include_meta=False)

    def to_toml(self) -> str:
        return self._render(include_meta=True)

    def _render(self, *, include_meta: bool) -> str:
        if not include_meta:
            return "\n".join(self._component_lines())
        lines = ["[meta]"]
        if self.parent:
            lines.append(f'parent = "{self.parent}"')
        lines.append(f"generation = {self.generation}")
        lines.append("")
        lines += self._component_lines()
        return "\n".join(lines)

    def _component_lines(self) -> list[str]:
        lines: list[str] = []
        for name, spec in self.components.items():
            lines.append(f"[components.{name}]")
            lines.append(f'kind   = "{spec.kind}"')
            if spec.path:
                lines.append(f'path   = "{spec.path}"')
            if spec.dir:
                lines.append(f'dir    = "{spec.dir}"')
            if spec.budget_tokens is not None:
                lines.append(f"budget_tokens = {spec.budget_tokens}")
            if spec.kind == "config" and name == "stop_policy":
                sp = self.stop_policy
                lines.append(f"retries = {sp.retries}")
                lines.append(f'feedback_shape = "{sp.feedback_shape}"')
                checks = ", ".join(f'"{c}"' for c in sp.checks)
                lines.append(f"checks = [{checks}]")
            lines.append("")
        return lines
