"""Where this package meets repo3, and how it proves the meeting happened.

Two things live here, and they are the same thing viewed twice.

**Finding repo3.** The evaluation harness, the container runner and the stop hook
are all in the predecessor repo. Hardcoding one machine's layout means the
integration checks skip silently on the machine that actually has the data --
which is the machine where they matter.

**The R1 receipt.** ``INTEGRATION_REQUIREMENTS`` R1 is satisfied only when the
stop policy demonstrably reaches the hook, proven by *diffing the hook's own
event log* across two feedback shapes. That is not a property of the source; it
is an observation, and observations go stale. So the verification script writes a
receipt naming the SHA-256 of the hook it verified, and everything downstream
checks the receipt against the hook on disk. Edit the hook and the receipt stops
matching -- which is the point. A green checkbox that survives the code changing
underneath it is worth less than no checkbox, because it is trusted.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

_MARKER = "plugin_evolving"
HOOK_RELPATH = Path("plugin") / "hooks" / "verify_outputs.py"
DEFAULT_RECEIPT = Path(".evolve") / "r1_verification" / "receipt.json"


def _candidates():
    env = os.environ.get("REPO3_PATH")
    if env:
        yield Path(env).expanduser()
    home = Path.home()
    yield home / "repo3"
    yield home / "src" / "repo3"
    yield Path(__file__).resolve().parents[3] / "repo3"       # sibling checkout
    yield Path("/home/agent/repo3")                            # legacy default


def find_repo3() -> Path | None:
    """Return the repo3 checkout root, or None if it cannot be found."""
    for candidate in _candidates():
        try:
            if (candidate / _MARKER).is_dir():
                return candidate
        except OSError:
            continue
    return None


def hook_path(repo3: Path | None = None) -> Path | None:
    root = repo3 or find_repo3()
    if root is None:
        return None
    path = root / HOOK_RELPATH
    return path if path.is_file() else None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class R1Status:
    """Whether the stop policy is known to reach the hook, and how we know."""

    verified: bool
    reason: str
    receipt: dict | None = None

    @property
    def hook_sha(self) -> str:
        return (self.receipt or {}).get("hook_sha256", "")


def check_r1(receipt_path: Path, repo3: Path | None = None) -> R1Status:
    """Validate an R1 receipt against the hook that is actually on disk."""
    if not receipt_path.is_file():
        return R1Status(False, (
            f"no R1 receipt at {receipt_path}. Run repo3's "
            "scripts/verify_r1_feedback_channel.py -- until the hook event log "
            "is shown to differ between two feedback shapes, any result that "
            "varies the stop policy is measuring nothing."
        ))
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return R1Status(False, f"R1 receipt at {receipt_path} is unreadable: {exc}")

    if not receipt.get("ok"):
        failed = [c["label"] for c in receipt.get("checks", []) if not c.get("ok")]
        return R1Status(False, (
            "the R1 verification did not pass: "
            + (", ".join(failed) or "no checks recorded")
        ), receipt)

    live = hook_path(repo3)
    if live is None:
        return R1Status(False, (
            "cannot find repo3's plugin/hooks/verify_outputs.py to compare the "
            "receipt against; set REPO3_PATH"
        ), receipt)
    live_sha = digest(live)
    if live_sha != receipt.get("hook_sha256"):
        return R1Status(False, (
            f"the R1 receipt was written for a different {live.name} "
            f"(receipt {str(receipt.get('hook_sha256'))[:12]}, "
            f"on disk {live_sha[:12]}). Re-run the verification."
        ), receipt)

    return R1Status(True, (
        f"verified {receipt.get('verified_at', '?')} against hook {live_sha[:12]}: "
        + receipt.get("headline", "")
    ), receipt)
