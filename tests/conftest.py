"""Shared fixtures. All tests run offline: HTTP is mocked with respx and no real
Snap credentials are used."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from snapchat_ads_mcp.audit import AuditLog
from snapchat_ads_mcp.client import SnapchatAdsClient
from snapchat_ads_mcp.config import Config

BASE = "https://adsapi.snapchat.com"
AD_ACCOUNT = "8adc3db7-8148-4fbf-999c-8d2266369d74"
ORG = "40d6719b-da09-410b-9185-0cc9c0dfed1d"
CAMPAIGN_ID = "7c074b60-3ae7-4975-bc1d-5785cc0be2c8"
SQUAD_ID = "134aeb99-6552-4f1d-b7a6-82b9813fd079"
AD_ID = "8ade8ef7-0cde-4eaa-bde6-990133575229"
CLIENT_ID = "test-client-id-abcdef"

_ENV_VARS = (
    "SNAPCHAT_ADS_CLIENT_ID",
    "SNAPCHAT_ADS_CLIENT_SECRET",
    "SNAPCHAT_ADS_REFRESH_TOKEN",
    "SNAPCHAT_ADS_TOKEN_FILE",
    "SNAPCHAT_ADS_AUDIT_LOG",
    "SNAPCHAT_ADS_AD_ACCOUNT_ID",
    "SNAPCHAT_ADS_ORGANIZATION_ID",
    "SNAPCHAT_ADS_UPLOAD_DIR",
    "SNAPCHAT_ADS_TOOL_GROUPS",
    "SNAPCHAT_ADS_READ_ONLY",
    "SNAPCHAT_ADS_DRY_RUN",
    "SNAPCHAT_ADS_TRANSPORT",
    "SNAPCHAT_ADS_HOST",
    "SNAPCHAT_ADS_PORT",
    "SNAPCHAT_ADS_ALLOW_REMOTE",
    "SNAPCHAT_ADS_PAGE_SIZE",
    "SNAPCHAT_ADS_MAX_BUDGET",
    "SNAPCHAT_ADS_MAX_BID",
    "SNAPCHAT_ADS_MAX_INCREASE_PCT",
    "SNAPCHAT_ADS_BULK_THRESHOLD",
    "SNAPCHAT_ADS_REDIRECT_URI",
)


class FakeAuth:
    """Stand-in for SnapAuth in tests."""

    account_label = "fake:test"

    def __init__(self) -> None:
        self.invalidated = 0
        self.token = "0.fake-access-token-value"

    def access_token(self) -> str:
        return self.token

    def invalidate(self) -> None:
        self.invalidated += 1


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep tests away from the real ~/.snapchat-ads-mcp and any .env files."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("SNAPCHAT_ADS_HOME", str(home))
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    return home


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr("snapchat_ads_mcp.client.time.sleep", lambda s: slept.append(s))
    return slept


@pytest.fixture
def tmp_audit_log(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "audit.jsonl"


@pytest.fixture
def config(tmp_audit_log: Path, tmp_path: Path) -> Config:
    return Config(
        client_id=CLIENT_ID,
        client_secret="test-client-secret-value",
        refresh_token="test-refresh-token-value",
        audit_log=tmp_audit_log,
        token_file=tmp_path / "secrets" / "token.json",
        ad_account_id=AD_ACCOUNT,
        organization_id=ORG,
        page_size=50,
        timeout=5.0,
        max_rps=0,
    )


@pytest.fixture
def audit(tmp_audit_log: Path) -> AuditLog:
    return AuditLog(tmp_audit_log)


@pytest.fixture
def fake_auth() -> FakeAuth:
    return FakeAuth()


@pytest.fixture
def client(config: Config, audit: AuditLog, fake_auth: FakeAuth):
    c = SnapchatAdsClient(config, fake_auth, audit)
    yield c
    c.close()


def audit_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def wrap(collection: str, singular: str, *entities: dict[str, Any]) -> dict[str, Any]:
    """A Snap-style response: {"request_status": ..., collection: [{sub_request_status, singular}]}."""
    return {
        "request_status": "SUCCESS",
        "request_id": "req-1",
        collection: [{"sub_request_status": "SUCCESS", singular: e} for e in entities],
    }


async def call(mcp: MCPServer, name: str, args: dict[str, Any] | None = None) -> Any:
    """Call a tool through an in-memory MCP client and return the parsed result."""
    async with Client(mcp) as c:
        result = await c.call_tool(name, args or {})
    text = " ".join(getattr(block, "text", "") for block in result.content)
    if result.is_error:
        raise AssertionError(f"tool error: {text}")
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if set(sc) == {"result"} else sc
    return json.loads(text)


async def call_error(mcp: MCPServer, name: str, args: dict[str, Any] | None = None) -> str:
    async with Client(mcp) as c:
        result = await c.call_tool(name, args or {})
    assert result.is_error, "expected a tool error"
    return " ".join(getattr(block, "text", "") for block in result.content)
