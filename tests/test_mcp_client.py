"""End-to-end tests through `mcp.Client` against the real server (fake auth, mocked HTTP)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import Tool

from snapchat_ads_mcp import __version__, server, tools
from snapchat_ads_mcp.auth import register_secret
from snapchat_ads_mcp.client import SnapchatAdsClient
from snapchat_ads_mcp.config import Config, load_config
from snapchat_ads_mcp.tool_catalog import ALWAYS_REGISTERED, TOOL_SPECS

from .conftest import AD_ACCOUNT, BASE, ORG, FakeAuth, call

META_TOOLS = [
    "snapchat_ads_describe_server",
    "snapchat_ads_health_check",
    "snapchat_ads_audit_lookup",
    "snapchat_ads_audit_tail",
    "snapchat_ads_set_dry_run",
]
EXPECTED_TOOL_COUNT = 58


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


def _build(config: Config, **changes: Any) -> MCPServer:
    return server.build_server(dataclasses.replace(config, **changes))


async def _tools(mcp: MCPServer) -> list[Tool]:
    async with Client(mcp) as c:
        return (await c.list_tools()).tools


def _group_tool_names(client: SnapchatAdsClient) -> dict[str, list[str]]:
    """Tool names per group, by registering each module on its own server."""
    out: dict[str, list[str]] = {}
    for group in tools.TOOL_GROUPS:
        mcp = MCPServer("probe")
        getattr(tools, group).register(mcp, client)
        out[group] = list(mcp._tool_manager._tools)
    return out


# ---------------------------------------------------------------- metadata


async def test_server_reports_version_and_instructions(config: Config) -> None:
    async with Client(_build(config)) as c:
        assert c.server_info is not None
        assert c.server_info.name == "snapchat-ads-mcp"
        assert c.server_info.version == __version__
        assert c.instructions
        assert "snapchat_ads_describe_server" in c.instructions
        assert "dry-run" in c.instructions
        assert "micro-currency" in c.instructions
        assert "SNAPCHAT_ADS_TOOL_GROUPS" in c.instructions
        assert "other ad platforms" in c.instructions
        assert "train models" in c.instructions
        assert 4 <= len(c.instructions.splitlines()) <= 8


async def test_every_tool_has_a_catalog_entry(config: Config) -> None:
    listed = await _tools(_build(config))
    assert len(listed) == EXPECTED_TOOL_COUNT
    for tool in listed:
        assert tool.name.startswith("snapchat_ads_"), tool.name
        assert tool.name in TOOL_SPECS, f"{tool.name} has no tool_catalog entry"
        assert tool.title and tool.title[0].isupper(), tool.name
        assert tool.description, tool.name
        a = tool.annotations
        assert a is not None, tool.name
        assert a.read_only_hint is not None, tool.name
        assert a.destructive_hint is not None, tool.name
        assert a.idempotent_hint is not None, tool.name
        assert a.open_world_hint is not None, tool.name
    # The catalog has no stale entries either.
    assert {t.name for t in listed} == set(TOOL_SPECS)


async def test_annotations_are_plausible(config: Config) -> None:
    by_name = {t.name: t.annotations for t in await _tools(_build(config))}
    read_only = {n for n, a in by_name.items() if a and a.read_only_hint}
    destructive = {n for n, a in by_name.items() if a and a.destructive_hint}
    assert not read_only & destructive
    for name in by_name:
        verb = name.removeprefix("snapchat_ads_").split("_")[0]
        if verb in {"list", "get", "search", "estimate", "check", "download"}:
            assert name in read_only, name
        if verb == "delete":
            assert name in destructive, name
        if verb in {"create", "update", "set", "upload"} and name not in {
            "snapchat_ads_create_async_report",
            "snapchat_ads_set_dry_run",
        }:
            assert name not in read_only, name
    assert "snapchat_ads_request" in destructive
    assert {"snapchat_ads_run_report", "snapchat_ads_read_request"} <= read_only
    closed = {n for n, a in by_name.items() if a and a.open_world_hint is False}
    assert closed == set(META_TOOLS) - {"snapchat_ads_health_check"}


async def test_tools_list_order_is_deterministic(config: Config, client: SnapchatAdsClient) -> None:
    first = [t.name for t in await _tools(_build(config))]
    second = [t.name for t in await _tools(_build(config))]
    assert first == second
    per_group = _group_tool_names(client)
    assert first == META_TOOLS + [n for g in tools.TOOL_GROUPS for n in per_group[g]]


# ---------------------------------------------------------------- filtering


async def test_tool_groups_limit_registration(config: Config, client: SnapchatAdsClient) -> None:
    names = [t.name for t in await _tools(_build(config, tool_groups=["reporting", "accounts"]))]
    per_group = _group_tool_names(client)
    assert names == META_TOOLS + per_group["accounts"] + per_group["reporting"]


async def test_read_only_registers_only_read_tools(config: Config) -> None:
    listed = await _tools(_build(config, read_only=True))
    names = {t.name for t in listed}
    for tool in listed:
        if tool.name not in ALWAYS_REGISTERED:
            assert tool.annotations and tool.annotations.read_only_hint, tool.name
    assert "snapchat_ads_update_campaigns" not in names
    assert "snapchat_ads_upload_media" not in names
    assert "snapchat_ads_request" not in names
    assert {"snapchat_ads_list_campaigns", "snapchat_ads_run_report"} <= names
    expected = {n for n, s in TOOL_SPECS.items() if s.annotations.read_only_hint}
    assert names == expected | set(META_TOOLS)


async def test_read_only_combines_with_groups(config: Config) -> None:
    names = {t.name for t in await _tools(_build(config, tool_groups=["bulk"], read_only=True))}
    assert names == set(META_TOOLS)


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **values: str) -> Path:
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_ID", "client-id-for-tests")
    monkeypatch.setenv("SNAPCHAT_ADS_CLIENT_SECRET", "secret-for-tests")
    monkeypatch.setenv("SNAPCHAT_ADS_REFRESH_TOKEN", "refresh-for-tests")
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    return tmp_path / "missing.env"


async def test_env_vars_filter_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = _env(
        monkeypatch,
        tmp_path,
        SNAPCHAT_ADS_TOOL_GROUPS="accounts,pixels",
        SNAPCHAT_ADS_READ_ONLY="1",
    )
    names = {t.name for t in await _tools(server.build_server(env_file=env_file))}
    assert names == set(META_TOOLS) | {
        "snapchat_ads_get_me",
        "snapchat_ads_list_organizations",
        "snapchat_ads_list_ad_accounts",
        "snapchat_ads_get_ad_account",
        "snapchat_ads_list_funding_sources",
        "snapchat_ads_list_pixels",
        "snapchat_ads_get_pixel_domains",
        "snapchat_ads_get_pixel_stats",
        "snapchat_ads_list_snap_apps",
    }


def test_unknown_group_fails_at_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = _env(monkeypatch, tmp_path, SNAPCHAT_ADS_TOOL_GROUPS="campaigns,nope")
    with pytest.raises(RuntimeError) as exc_info:
        server.build_server(env_file=env_file)
    message = str(exc_info.value)
    assert "nope" in message
    for group in tools.TOOL_GROUPS:
        assert group in message


def test_load_config_normalises_group_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = _env(monkeypatch, tmp_path, SNAPCHAT_ADS_TOOL_GROUPS="Reporting, ad-squads")
    assert load_config(env_file=env_file).tool_groups == ["ad_squads", "reporting"]


# ---------------------------------------------------------------- calls


@respx.mock
async def test_api_error_reaches_the_client_redacted(config: Config) -> None:
    register_secret("leaky-secret-value-123")
    respx.get(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        return_value=httpx.Response(
            403,
            json={
                "request_status": "ERROR",
                "error_code": "E3002",
                "display_message": "No permission (leaky-secret-value-123)",
            },
        )
    )
    async with Client(_build(config)) as c:
        result = await c.call_tool("snapchat_ads_list_campaigns", {})
    assert result.is_error
    text = " ".join(getattr(block, "text", "") for block in result.content)
    assert "Snap Marketing API error 403" in text
    assert "E3002" in text
    assert "leaky-secret-value-123" not in text


async def test_describe_server_reports_settings(config: Config) -> None:
    payload = await call(
        _build(config, tool_groups=["reporting"], read_only=True), "snapchat_ads_describe_server"
    )
    assert payload["tool_groups"] == ["reporting"]
    assert payload["read_only"] is True
    assert payload["api_host"] == BASE
    assert payload["default_ad_account_id"] == AD_ACCOUNT
    assert payload["version"] == __version__
    assert "secret" not in json.dumps(payload).lower()


@respx.mock
async def test_health_check(config: Config) -> None:
    respx.get(f"{BASE}/v1/me/organizations").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_status": "SUCCESS",
                "organizations": [
                    {
                        "sub_request_status": "SUCCESS",
                        "organization": {
                            "id": ORG,
                            "name": "Example Org",
                            "ad_accounts": [
                                {
                                    "id": AD_ACCOUNT,
                                    "name": "Example",
                                    "currency": "GBP",
                                    "timezone": "Europe/London",
                                }
                            ],
                        },
                    }
                ],
            },
        )
    )
    payload = await call(_build(config), "snapchat_ads_health_check")
    assert payload["ok"] is True
    assert [c["check"] for c in payload["checks"]] == [
        "token_refresh",
        "list_organizations",
        "default_ad_account_visible",
    ]
    assert payload["organizations"][0]["ad_accounts"][0]["currency"] == "GBP"


async def test_set_dry_run_and_audit_tail(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
            return_value=httpx.Response(200, json={})
        )
        async with Client(_build(config)) as c:
            await c.call_tool("snapchat_ads_set_dry_run", {"enabled": True})
            created = await c.call_tool(
                "snapchat_ads_create_campaigns",
                {"items": [{"name": "x", "start_time": "2026-12-01T00:00:00Z"}]},
            )
            tail = await c.call_tool("snapchat_ads_audit_tail", {"limit": 5})
            created_payload = created.structured_content or {}
            lookup_id = created_payload["audit_ids"][0]
            found = await c.call_tool("snapchat_ads_audit_lookup", {"audit_id": lookup_id})
    assert route.call_count == 0
    assert created_payload["_dry_run"] is True
    assert created_payload["would_send"]["campaigns"][0]["status"] == "PAUSED"
    assert (tail.structured_content or {})["count"] == 1
    assert (found.structured_content or {})["found"] is True


def test_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parent.parent
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'\nversion = "{__version__}"\n' in pyproject


def test_docs_list_every_tool() -> None:
    root = Path(__file__).resolve().parent.parent
    docs = (root / "docs" / "tools.md").read_text(encoding="utf-8")
    missing = [name for name in TOOL_SPECS if f"`{name}`" not in docs]
    assert not missing, f"docs/tools.md is missing {missing}"
    assert f"**{len(TOOL_SPECS)} tools" in docs
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert f"{len(TOOL_SPECS)} tools" in readme
