"""The R1 receipt: a green check that cannot outlive the code it checked.

R1 is an *observation* -- the hook event log was seen to differ between two
feedback shapes -- and observations go stale the moment the hook is edited. A
checkbox that survives that is worse than no checkbox, because it gets trusted.
"""

from __future__ import annotations

import json

from harness_evolve.integration import check_r1, digest, find_repo3, hook_path


def write_receipt(path, hook, *, ok=True, checks=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "ok": ok,
        "verified_at": "2026-08-26T08:54:35+0000",
        "hook": str(hook),
        "hook_sha256": digest(hook),
        "checks": checks or [{"label": "feedback text differs", "ok": True}],
        "headline": "minimal=86ch / errors_plus_tables=3038ch",
    }))


def fake_repo3(tmp_path, body="# hook\n"):
    root = tmp_path / "repo3"
    (root / "plugin_evolving").mkdir(parents=True)
    hook = root / "plugin" / "hooks" / "verify_outputs.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(body)
    return root, hook


def test_a_passing_receipt_that_matches_the_hook_verifies(tmp_path):
    root, hook = fake_repo3(tmp_path)
    receipt = tmp_path / "receipt.json"
    write_receipt(receipt, hook)
    status = check_r1(receipt, repo3=root)
    assert status.verified
    assert "3038ch" in status.reason


def test_editing_the_hook_invalidates_the_receipt(tmp_path):
    """The whole point. A stale green check is the failure mode being prevented."""
    root, hook = fake_repo3(tmp_path)
    receipt = tmp_path / "receipt.json"
    write_receipt(receipt, hook)
    hook.write_text("# hook, edited since verification\n")

    status = check_r1(receipt, repo3=root)
    assert not status.verified
    assert "different verify_outputs.py" in status.reason
    assert "Re-run the verification" in status.reason


def test_a_missing_receipt_says_what_to_run(tmp_path):
    root, _ = fake_repo3(tmp_path)
    status = check_r1(tmp_path / "absent.json", repo3=root)
    assert not status.verified
    assert "verify_r1_feedback_channel.py" in status.reason


def test_a_failing_receipt_names_the_failed_checks(tmp_path):
    root, hook = fake_repo3(tmp_path)
    receipt = tmp_path / "receipt.json"
    write_receipt(receipt, hook, ok=False, checks=[
        {"label": "feedback text differs across shapes", "ok": False},
        {"label": "both arms blocked", "ok": True},
    ])
    status = check_r1(receipt, repo3=root)
    assert not status.verified
    assert "feedback text differs across shapes" in status.reason
    assert "both arms blocked" not in status.reason


def test_a_corrupt_receipt_is_not_verified(tmp_path):
    root, _ = fake_repo3(tmp_path)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{not json")
    assert not check_r1(receipt, repo3=root).verified


def test_repo3_is_found_by_marker_not_by_one_machines_path(tmp_path, monkeypatch):
    root, _ = fake_repo3(tmp_path)
    monkeypatch.setenv("REPO3_PATH", str(root))
    assert find_repo3() == root
    assert hook_path(root) is not None
