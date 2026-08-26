"""Locate the predecessor repo (repo3) without hardcoding one machine's layout.

The hygiene and TreeSim-parity tests check this project against repo3's real
artifacts. Those are integration tests, so they skip when repo3 is absent -- but
a *hardcoded* path means they also skip silently on any machine that merely
lays the checkout out differently, which is exactly the machine that has the
data and where the contamination tests matter most.

Resolution order: $REPO3_PATH, then a list of conventional locations.
"""
from __future__ import annotations

import os
from pathlib import Path

_MARKER = "plugin_evolving"


def _candidates():
    env = os.environ.get("REPO3_PATH")
    if env:
        yield Path(env).expanduser()
    home = Path.home()
    yield home / "repo3"
    yield home / "src" / "repo3"
    yield Path(__file__).resolve().parents[2] / "repo3"       # sibling checkout
    yield Path("/home/agent/repo3")                            # legacy default


def find_repo3() -> Path | None:
    """Return the repo3 checkout root, or None if it cannot be found."""
    for c in _candidates():
        try:
            if (c / _MARKER).is_dir():
                return c
        except OSError:
            continue
    return None


REPO3 = find_repo3() or Path("/nonexistent/repo3")
