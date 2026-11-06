"""Audit log: redaction, retention pruning, purge and file permissions."""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import pytest

from snapchat_ads_mcp.audit import DAY, AuditLog
from snapchat_ads_mcp.auth import register_secret


def test_record_find_tail_and_redaction(tmp_path: Path) -> None:
    register_secret("audit-secret-token-xyz")
    log = AuditLog(tmp_path / "logs" / "audit.jsonl")
    first = log.record(
        op="update_campaigns",
        resource="/v1/x",
        method="PATCH",
        url="https://adsapi.snapchat.com/v1/x",
        request_body={"note": "audit-secret-token-xyz", "access_token": "abc"},
    )
    log.record(op="b", resource="/v1/y", method="POST", url="u", dry_run=True)
    entry = log.find(first)
    assert entry is not None
    assert entry["request_body"] == {"note": "***", "access_token": "***"}
    assert [e["op"] for e in log.tail(5)] == ["update_campaigns", "b"]
    assert log.tail(0) == []
    assert log.find("missing") is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_files_are_owner_only(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "logs" / "audit.jsonl")
    log.record(op="a", resource="r", method="POST", url="u")
    assert stat.S_IMODE(os.stat(log.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(log.path.parent).st_mode) == 0o700


def test_prune_and_purge(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", retention_days=30)
    log.record(op="old", resource="r", method="POST", url="u")
    log.record(op="new", resource="r", method="POST", url="u")
    later = time.time() + 31 * DAY
    # Make the second entry recent relative to `later`.
    lines = log.path.read_text().splitlines()
    import json

    entries = [json.loads(line) for line in lines]
    entries[1]["ts"] = later - DAY
    log.path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    assert log.prune(now=later) == 1
    assert [e["op"] for e in log.entries()] == ["new"]
    assert AuditLog(log.path, retention_days=0).prune(now=later * 2) == 0
    assert log.purge() is True
    assert log.purge() is False
    assert log.entries() == []
