"""A candidate adapter: manifest + component texts + provenance.

v1 had no candidate object. ``reflect.py`` wrote ``v{N+1}/`` unconditionally
(``reflect.py:284-296``), so there was nothing to accept, reject, revert, or
compare -- and no archive to select a parent from. A candidate here is an
immutable, content-addressed value that can be scored, kept, or thrown away.

Materialization resolves scaffolding (``hooks/``, ``scripts/``,
``.claude-plugin/``) from a live plugin directory rather than snapshotting it
into the candidate. v1's ``copy_scaffolding()`` snapshotted at v0; by the time
the repo swapped ``xmllint --schema`` for ``geosx --validate-input``, every
``plugin_evolving/v*/`` still carried the retired implementation (274 lines of
drift, zero mentions of ``geosx``). A lineage that evolves against a validator
the project no longer ships is not evolving against anything real.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from harness_evolve.core.manifest import DEFAULT_MANIFEST_NAME, Manifest, ManifestError

#: Directories resolved from the live plugin at materialization time. Never
#: candidate-owned, never snapshotted into a candidate.
SCAFFOLDING_DIRS: tuple[str, ...] = ("hooks", "scripts", ".claude-plugin")

#: Rough chars-per-token used for budget checks. Deliberately conservative: an
#: over-estimate rejects a slightly-too-long component, which is the safe
#: direction given the whole point is preventing unmonitored context growth.
CHARS_PER_TOKEN = 3.6


class CandidateError(ValueError):
    """Raised when a candidate is structurally invalid."""


def estimate_tokens(text: str) -> int:
    """Cheap tokenizer-free estimate, deliberately biased high."""
    return int(len(text) / CHARS_PER_TOKEN + 0.5)


@dataclass(frozen=True)
class Prediction:
    """The falsifiable contract attached to an edit (AHE decision observability).

    Every proposal must say what it expects to fix and where, *before* it is
    evaluated. Verified against the next round's outcomes into
    ``.evolve/decision_log.jsonl``. Two payoffs: a calibration record for the
    proposer model, and a targeted reversion signal -- an accepted edit whose
    predicted beneficiaries did not move is over-specification in disguise.
    """

    component: str
    targets_category: str
    predicted_beneficiaries: tuple[str, ...] = ()
    predicted_delta: float = 0.0
    rationale: str = ""
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "targets_category": self.targets_category,
            "predicted_beneficiaries": list(self.predicted_beneficiaries),
            "predicted_delta": self.predicted_delta,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Prediction":
        return cls(
            component=str(d.get("component", "")),
            targets_category=str(d.get("targets_category", "")),
            predicted_beneficiaries=tuple(d.get("predicted_beneficiaries") or ()),
            predicted_delta=float(d.get("predicted_delta", 0.0) or 0.0),
            rationale=str(d.get("rationale", "")),
            evidence_refs=tuple(d.get("evidence_refs") or ()),
        )


@dataclass(frozen=True)
class Candidate:
    """An adapter candidate.

    ``files`` maps adapter-relative paths to their contents and must cover every
    file-backed component the manifest declares. ``cid`` is content-addressed,
    so identical candidates collapse in the archive and the evaluation cache.
    """

    manifest: Manifest
    files: dict[str, str]
    parent_id: str | None = None
    generation: int = 0
    predictions: tuple[Prediction, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # -- identity --------------------------------------------------------
    @property
    def cid(self) -> str:
        h = hashlib.sha256()
        h.update(self.manifest.to_toml().encode())
        for path in sorted(self.files):
            h.update(path.encode())
            h.update(b"\0")
            h.update(self.files[path].encode())
            h.update(b"\0")
        return "cand_" + h.hexdigest()[:12]

    # -- construction ----------------------------------------------------
    @classmethod
    def from_dir(cls, adapter_dir: Path, **kw: Any) -> "Candidate":
        adapter_dir = Path(adapter_dir)
        manifest = Manifest.load(adapter_dir / DEFAULT_MANIFEST_NAME)
        files: dict[str, str] = {}
        for spec in manifest.components.values():
            if spec.path:
                p = adapter_dir / spec.path
                if p.exists():
                    files[spec.path] = p.read_text()
            elif spec.dir:
                d = adapter_dir / spec.dir
                if d.is_dir():
                    for f in sorted(d.rglob("*")):
                        if f.is_file():
                            rel = f.relative_to(adapter_dir).as_posix()
                            files[rel] = f.read_text()
        return cls(manifest=manifest, files=files, **kw)

    def with_edits(
        self,
        edits: dict[str, str],
        *,
        manifest: Manifest | None = None,
        predictions: Iterable[Prediction] = (),
    ) -> "Candidate":
        """Return a child with ``edits`` applied.

        An edit whose value is the empty string empties the component -- deletion
        is a first-class operation because a curator that can only add is how a
        280-byte primer became 3159 bytes in three unmonitored rounds.

        A *declared* component keeps its file when emptied rather than losing it.
        "This cheatsheet currently has no lessons" is a legitimate state and the
        obvious way to reach it is to delete the last line; dropping the file
        instead makes the very next validation fail on a component whose
        manifest entry points at nothing. Only files no component claims are
        removed outright.
        """
        new_files = dict(self.files)
        manifest = manifest or self.manifest
        declared = {
            spec.path for spec in manifest.components.values() if spec.path
        }
        for path, text in edits.items():
            if text == "" and path not in declared:
                new_files.pop(path, None)
            else:
                new_files[path] = text
        return Candidate(
            manifest=replace(
                manifest,
                parent=self.cid,
                generation=self.generation + 1,
            ),
            files=new_files,
            parent_id=self.cid,
            generation=self.generation + 1,
            predictions=tuple(predictions),
        )

    # -- validation ------------------------------------------------------
    def validate(self) -> None:
        """Structural validation. Free -- runs before any rollout is spent."""
        self.manifest.validate()
        for path in self.files:
            if not self.manifest.is_writable(path):
                raise CandidateError(
                    f"file {path!r} is not owned by any manifest component"
                )
        for spec in self.manifest.components.values():
            if spec.path and spec.path not in self.files and spec.kind != "config":
                raise CandidateError(
                    f"component {spec.name!r} declares {spec.path!r} but it is missing"
                )
        self.check_budgets()

    def check_budgets(self) -> list[str]:
        """Return budget violations; raise if any.

        Enforcing the token budget as a *hard* gate is the structural fix for
        the over-specification failure mode the efficiency paragraph of the
        paper claims SIGA guards against -- and which the v1 lineage exhibits.
        """
        violations: list[str] = []
        for spec in self.manifest.components.values():
            if spec.budget_tokens is None or not spec.path:
                continue
            text = self.files.get(spec.path, "")
            est = estimate_tokens(text)
            if est > spec.budget_tokens:
                violations.append(
                    f"{spec.name} ({spec.path}): ~{est} tokens > budget "
                    f"{spec.budget_tokens}"
                )
        if violations:
            raise CandidateError("token budget exceeded: " + "; ".join(violations))
        return violations

    # -- materialization -------------------------------------------------
    def materialize(
        self,
        dest: Path,
        *,
        scaffolding_from: Path,
        overwrite: bool = False,
    ) -> Path:
        """Write a runnable plugin directory for this candidate.

        Scaffolding is copied from ``scaffolding_from`` (normally ``plugin/``)
        at call time, so a candidate always runs against the validator the
        project currently ships.
        """
        dest = Path(dest)
        scaffolding_from = Path(scaffolding_from)
        if not scaffolding_from.is_dir():
            raise CandidateError(f"scaffolding source missing: {scaffolding_from}")
        if dest.exists():
            if not overwrite:
                raise CandidateError(f"destination exists: {dest}")
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        for sub in SCAFFOLDING_DIRS:
            src = scaffolding_from / sub
            if src.is_dir():
                shutil.copytree(src, dest / sub, dirs_exist_ok=True)

        for rel, text in self.files.items():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text if text.endswith("\n") else text + "\n")

        (dest / DEFAULT_MANIFEST_NAME).write_text(self.manifest.to_toml())
        (dest / ".candidate.json").write_text(json.dumps(self.metadata(), indent=2))
        return dest

    def metadata(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "created_at": self.created_at,
            "files": {p: len(t) for p, t in sorted(self.files.items())},
            "estimated_tokens": {
                p: estimate_tokens(t) for p, t in sorted(self.files.items())
            },
            "stop_policy": {
                "retries": self.manifest.stop_policy.retries,
                "feedback_shape": self.manifest.stop_policy.feedback_shape,
                "checks": list(self.manifest.stop_policy.checks),
            },
            "predictions": [p.to_dict() for p in self.predictions],
        }

    # -- GEPA interop ----------------------------------------------------
    def to_component_dict(self) -> dict[str, str]:
        """GEPA's ``seed_candidate: dict[str, str]`` view.

        Keys are component names (not paths) so GEPA's ``module_selector`` can
        mutate one component per iteration -- Self-Harness's minimality by
        construction.
        """
        out: dict[str, str] = {}
        for name, spec in self.manifest.components.items():
            if spec.path:
                out[name] = self.files.get(spec.path, "")
        out[DEFAULT_MANIFEST_NAME] = self.manifest.to_toml()
        return out

    @classmethod
    def from_component_dict(
        cls, comps: dict[str, str], template: "Candidate"
    ) -> "Candidate":
        """Inverse of :meth:`to_component_dict`, using ``template`` for shape."""
        manifest_text = comps.get(DEFAULT_MANIFEST_NAME)
        try:
            manifest = (
                Manifest.from_toml(manifest_text) if manifest_text else template.manifest
            )
        except ManifestError:
            # A proposer that corrupts the manifest keeps the parent's -- the
            # edit is simply dropped rather than taking the candidate down.
            manifest = template.manifest
        files = dict(template.files)
        for name, text in comps.items():
            if name == DEFAULT_MANIFEST_NAME:
                continue
            spec = manifest.components.get(name)
            if spec and spec.path:
                if text == "":
                    files.pop(spec.path, None)
                else:
                    files[spec.path] = text
        return cls(
            manifest=manifest,
            files=files,
            parent_id=template.cid,
            generation=template.generation + 1,
        )
