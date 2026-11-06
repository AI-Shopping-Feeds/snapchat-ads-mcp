"""Configuration: required values, per-user paths, .env lookup and validation."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from snapchat_ads_mcp import config as cfg
from snapchat_ads_mcp.auth import save_token_file


def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_ID", "client-id-123456")
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_SECRET", "client-secret")


def test_missing_client_credentials() -> None:
    with pytest.raises(RuntimeError, match="SNAPCHAT_ADS_CLIENT_ID"):
        cfg.load_config()


def test_missing_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _creds(monkeypatch)
    with pytest.raises(RuntimeError, match="snapchat-ads-mcp auth"):
        cfg.load_config()
    assert cfg.load_config(require_refresh_token=False).refresh_token is None


def test_defaults_live_in_the_user_folder(
    monkeypatch: pytest.MonkeyPatch, _isolated_env: Path
) -> None:
    _creds(monkeypatch)
    monkeypatch.setenv("SNAPCHAT_ADS_REFRESH_TOKEN", "rt")
    c = cfg.load_config()
    assert c.token_file == _isolated_env / "secrets" / "snapchat-ads-token.json"
    assert c.audit_log == _isolated_env / "logs" / "audit.jsonl"
    assert c.max_increase_pct == 20.0
    assert c.audit_retention_days == 30
    assert c.bulk_threshold == 10
    assert c.transport == "stdio" and c.host == "127.0.0.1"
    assert c.allow_remote is False


def test_home_defaults_to_dot_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAPCHAT_ADS_HOME")
    assert cfg.home_dir() == Path.home() / ".snapchat-ads-mcp"


def test_token_file_is_read(monkeypatch: pytest.MonkeyPatch, _isolated_env: Path) -> None:
    _creds(monkeypatch)
    save_token_file(
        _isolated_env / "secrets" / "snapchat-ads-token.json", {"refresh_token": "from-file"}
    )
    assert cfg.load_config().refresh_token == "from-file"


def test_env_files_order(monkeypatch: pytest.MonkeyPatch, _isolated_env: Path) -> None:
    Path(".env").write_text(
        "SNAPCHAT_ADS_CLIENT_ID=from-cwd\nSNAPCHAT_ADS_CLIENT_SECRET=cwd-secret\n"
        "SNAPCHAT_ADS_REFRESH_TOKEN=rt\n"
    )
    _isolated_env.mkdir(parents=True)
    (_isolated_env / ".env").write_text(
        "SNAPCHAT_ADS_CLIENT_ID=from-home\nSNAPCHAT_ADS_AD_ACCOUNT_ID=acct-from-home\n"
    )
    c = cfg.load_config()
    assert c.client_id == "from-cwd"
    assert c.ad_account_id == "acct-from-home"


def test_explicit_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = tmp_path / "custom.env"
    env.write_text(
        "SNAPCHAT_ADS_CLIENT_ID=from-file\nSNAPCHAT_ADS_CLIENT_SECRET=s\nSNAPCHAT_ADS_REFRESH_TOKEN=r\n"
        "SNAPCHAT_ADS_MAX_BUDGET=250\nSNAPCHAT_ADS_TOOL_GROUPS=Reporting, ad-squads\n"
    )
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_ID", "from-process")
    c = cfg.load_config(env_file=env)
    assert c.client_id == "from-process"
    assert c.max_budget == 250.0
    assert c.tool_groups == ["ad_squads", "reporting"]


@pytest.mark.parametrize(
    ("var", "value", "message"),
    [
        ("SNAPCHAT_ADS_TRANSPORT", "websocket", "SNAPCHAT_ADS_TRANSPORT"),
        ("SNAPCHAT_ADS_PAGE_SIZE", "10", "between 50 and 1000"),
        ("SNAPCHAT_ADS_PORT", "eighty", "integer"),
        ("SNAPCHAT_ADS_MAX_BID", "lots", "number"),
        ("SNAPCHAT_ADS_TOOL_GROUPS", "campaigns,nope", "nope"),
        ("SNAPCHAT_ADS_UPLOAD_DIR", "/definitely/not/a/folder", "not a folder"),
    ],
)
def test_validation(monkeypatch: pytest.MonkeyPatch, var: str, value: str, message: str) -> None:
    _creds(monkeypatch)
    monkeypatch.setenv("SNAPCHAT_ADS_REFRESH_TOKEN", "rt")
    monkeypatch.setenv(var, value)
    with pytest.raises(RuntimeError, match=message):
        cfg.load_config()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_private_dir(tmp_path: Path) -> None:
    path = cfg.ensure_private_dir(tmp_path / "a" / "b")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
