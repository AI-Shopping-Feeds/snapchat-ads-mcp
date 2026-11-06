"""Stats flattening, async report flow with progress, and change logs."""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer

from snapchat_ads_mcp import server
from snapchat_ads_mcp.config import Config
from snapchat_ads_mcp.tools.reporting import flatten_stats

from .conftest import AD_ACCOUNT, BASE, CAMPAIGN_ID, FakeAuth, audit_entries, call, call_error

REPORT_URL = "https://data-transfer.snapads.com/async-report/snap_ads/run/file.csv"
RUN_ID = "ASYNC_STATS:acct:1727755200000:abc"


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


def _build(config: Config, **changes: Any) -> MCPServer:
    return server.build_server(dataclasses.replace(config, **changes))


def test_flatten_breakdown_timeseries_and_dimensions() -> None:
    payload = {
        "request_status": "SUCCESS",
        "timeseries_stats": [
            {
                "sub_request_status": "SUCCESS",
                "timeseries_stat": {
                    "id": CAMPAIGN_ID,
                    "type": "CAMPAIGN",
                    "finalized_data_end_time": "2026-11-04T00:00:00Z",
                    "breakdown_stats": {
                        "adsquad": [
                            {
                                "id": "sq1",
                                "type": "AD_SQUAD",
                                "granularity": "DAY",
                                "timeseries": [
                                    {
                                        "start_time": "2026-11-01",
                                        "end_time": "2026-11-02",
                                        "stats": {"impressions": 10, "spend": 1_250_000},
                                    },
                                    {
                                        "start_time": "2026-11-02",
                                        "end_time": "2026-11-03",
                                        "stats": {"impressions": 5, "spend": 0},
                                    },
                                ],
                            }
                        ]
                    },
                },
            }
        ],
    }
    rows, meta = flatten_stats(payload)
    assert meta == {"finalized_data_end_time": "2026-11-04T00:00:00Z"}
    assert rows[0] == {
        "id": "sq1",
        "type": "AD_SQUAD",
        "granularity": "DAY",
        "breakdown": "adsquad",
        "parent_id": CAMPAIGN_ID,
        "start_time": "2026-11-01",
        "end_time": "2026-11-02",
        "impressions": 10,
        "spend": 1_250_000,
        "spend_amount": 1.25,
    }
    assert len(rows) == 2

    insights = {
        "total_stats": [
            {
                "sub_request_status": "SUCCESS",
                "total_stat": {
                    "id": AD_ACCOUNT,
                    "type": "AD_ACCOUNT",
                    "granularity": "TOTAL",
                    "dimension_stats": [
                        {
                            "country": "gb",
                            "impressions": 3,
                            "conversion_purchases_value": 25_000_000,
                        },
                        {"country": "fr", "impressions": 4},
                    ],
                },
            }
        ]
    }
    rows, _ = flatten_stats(insights)
    assert [r["country"] for r in rows] == ["gb", "fr"]
    assert rows[0]["conversion_purchases_value_amount"] == 25.0


@respx.mock
async def test_get_stats_params_and_paging(config: Config) -> None:
    page1 = {
        "request_status": "SUCCESS",
        "paging": {"next_link": f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/stats?cursor=2&limit=200"},
        "total_stats": [
            {
                "sub_request_status": "SUCCESS",
                "total_stat": {
                    "id": AD_ACCOUNT,
                    "type": "AD_ACCOUNT",
                    "breakdown_stats": {"campaign": [{"id": "c1", "stats": {"spend": 2_000_000}}]},
                },
            }
        ],
    }
    page2 = {
        "request_status": "SUCCESS",
        "total_stats": [
            {
                "sub_request_status": "SUCCESS",
                "total_stat": {
                    "id": AD_ACCOUNT,
                    "breakdown_stats": {"campaign": [{"id": "c2", "stats": {"spend": 0}}]},
                },
            }
        ],
    }
    route = respx.get(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/stats").mock(
        side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
    )
    out = await call(
        _build(config),
        "snapchat_ads_get_stats",
        {
            "granularity": "TOTAL",
            "breakdown": "campaign",
            "start_time": "2026-11-01T00:00:00",
            "end_time": "2026-11-08T00:00:00",
            "fields": "spend",
            "swipe_up_attribution_window": "7_DAY",
        },
    )
    params = route.calls[0].request.url.params
    assert params["breakdown"] == "campaign"
    assert params["limit"] == "200"
    assert params["swipe_up_attribution_window"] == "7_DAY"
    assert [r["id"] for r in out["rows"]] == ["c1", "c2"]
    assert out["rows"][0]["spend_amount"] == 2.0
    assert route.calls[1].request.url.params["cursor"] == "2"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"granularity": "DAY"}, "needs start_time"),
        ({"granularity": "LIFETIME", "start_time": "2026-11-01"}, "takes no start_time"),
        (
            {"granularity": "HOUR", "start_time": "a", "end_time": "b", "report_dimension": "age"},
            "HOUR",
        ),
        (
            {"entity_type": "creative", "entity_id": "c1", "granularity": "TOTAL"},
            "DAY and LIFETIME",
        ),
        ({"entity_type": "campaign"}, "entity_id"),
        ({"extra_params": {"async": "true"}}, "async"),
    ],
)
async def test_get_stats_validation(config: Config, args: dict[str, Any], message: str) -> None:
    text = await call_error(_build(config), "snapchat_ads_get_stats", args)
    assert message in text


@respx.mock
async def test_run_report_polls_downloads_and_reports_progress(
    config: Config, tmp_audit_log
) -> None:
    stats = respx.get(f"{BASE}/v1/campaigns/{CAMPAIGN_ID}/stats").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_status": "SUCCESS",
                "async_stats_reports": [
                    {
                        "sub_request_status": "SUCCESS",
                        "async_stats_report": {"report_run_id": RUN_ID, "async_status": "STARTED"},
                    }
                ],
            },
        )
    )

    def status(state: str, result: str | None = None) -> httpx.Response:
        report: dict[str, Any] = {"report_run_id": RUN_ID, "async_status": state}
        if result:
            report["result"] = result
        return httpx.Response(
            200,
            json={
                "request_status": "SUCCESS",
                "async_stats_reports": [
                    {"sub_request_status": "SUCCESS", "async_stats_report": report}
                ],
            },
        )

    poll = respx.get(f"{BASE}/v1/campaigns/{CAMPAIGN_ID}/stats_report").mock(
        side_effect=[status("RUNNING"), status("COMPLETED", REPORT_URL)]
    )
    respx.get(REPORT_URL).mock(
        return_value=httpx.Response(200, content=b"date,impressions\n2026-11-01,5\n2026-11-02,7\n")
    )
    progress: list[tuple[float, str | None]] = []

    async def on_progress(p: float, total: float | None, message: str | None) -> None:
        progress.append((p, message))

    async with Client(_build(config)) as c:
        result = await c.call_tool(
            "snapchat_ads_run_report",
            {
                "entity_type": "campaign",
                "entity_id": CAMPAIGN_ID,
                "start_time": "2026-11-01T00:00:00",
                "end_time": "2026-11-03T00:00:00",
                "max_rows": 1,
                "poll_seconds": 0,
            },
            progress_callback=on_progress,
        )
    assert not result.is_error
    payload = result.structured_content
    assert payload is not None
    assert payload["row_count"] == 2 and payload["truncated"] is True
    assert payload["rows"] == [{"date": "2026-11-01", "impressions": "5"}]
    params = stats.calls[0].request.url.params
    assert params["async"] == "true" and params["async_format"] == "csv"
    assert poll.calls[0].request.url.params["report_run_id"] == RUN_ID
    assert [p for p, _ in progress] == sorted({p for p, _ in progress})
    assert any("downloading" in (m or "") for _, m in progress)
    assert audit_entries(tmp_audit_log) == []  # report rows are never stored


@respx.mock
async def test_download_not_ready(config: Config) -> None:
    respx.get(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/stats_report").mock(
        return_value=httpx.Response(
            200,
            json={
                "async_stats_reports": [
                    {
                        "sub_request_status": "SUCCESS",
                        "async_stats_report": {"report_run_id": RUN_ID, "async_status": "RUNNING"},
                    }
                ]
            },
        )
    )
    out = await call(
        _build(config), "snapchat_ads_download_async_report", {"report_run_id": RUN_ID}
    )
    assert out["status"] == "RUNNING" and "isn't ready" in out["message"]
    status = await call(_build(config), "snapchat_ads_get_async_report", {"report_run_id": RUN_ID})
    assert status["ready"] is False


@respx.mock
async def test_change_log_drops_emails(config: Config) -> None:
    respx.get(f"{BASE}/v1/campaigns/{CAMPAIGN_ID}/external_changelogs").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_status": "SUCCESS",
                "changelogs": [
                    {
                        "sub_request_status": "SUCCESS",
                        "changelog": {
                            "id": "x",
                            "action": "UPDATED",
                            "user_id": "u1",
                            "email": "someone@example.com",
                        },
                    }
                ],
            },
        )
    )
    out = await call(
        _build(config),
        "snapchat_ads_get_change_log",
        {"entity_type": "campaign", "entity_id": CAMPAIGN_ID},
    )
    assert out["changelogs"] == [{"id": "x", "action": "UPDATED", "user_id": "u1"}]
