"""HTTP client: headers, retries, dry-run, audit, errors, paging and report downloads."""

from __future__ import annotations

import dataclasses

import httpx
import pytest
import respx

from snapchat_ads_mcp import __version__
from snapchat_ads_mcp.audit import AuditLog
from snapchat_ads_mcp.client import (
    SnapchatAdsAPIError,
    SnapchatAdsClient,
    check_id,
    parse_csv,
    sub_request_errors,
    unwrap,
)
from snapchat_ads_mcp.config import Config

from .conftest import AD_ACCOUNT, BASE, CAMPAIGN_ID, FakeAuth, audit_entries, wrap


@respx.mock
def test_headers_and_user_agent(client: SnapchatAdsClient) -> None:
    route = respx.get(f"{BASE}/v1/me").mock(
        return_value=httpx.Response(200, json={"me": {"id": "u"}})
    )
    assert client.request("GET", "/v1/me") == {"me": {"id": "u"}}
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer 0.fake-access-token-value"
    assert req.headers["User-Agent"] == f"snapchat-ads-mcp/{__version__}"
    assert req.headers["Accept"] == "application/json"


@respx.mock
def test_401_refreshes_once(client: SnapchatAdsClient, fake_auth: FakeAuth) -> None:
    route = respx.get(f"{BASE}/v1/me").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
    )
    assert client.request("GET", "/v1/me") == {"ok": True}
    assert fake_auth.invalidated == 1
    assert route.call_count == 2


@respx.mock
def test_429_honours_retry_after(client: SnapchatAdsClient, _no_sleep: list[float]) -> None:
    respx.get(f"{BASE}/v1/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert client.request("GET", "/v1/me") == {"ok": True}
    assert _no_sleep and _no_sleep[0] >= 7


@respx.mock
def test_get_retries_5xx(client: SnapchatAdsClient) -> None:
    route = respx.get(f"{BASE}/v1/me").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    assert client.request("GET", "/v1/me")["ok"] is True
    assert route.call_count == 2


@respx.mock
def test_create_is_not_retried_on_5xx(client: SnapchatAdsClient, tmp_audit_log) -> None:
    route = respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        return_value=httpx.Response(500, json={"request_status": "ERROR"})
    )
    with pytest.raises(SnapchatAdsAPIError) as exc_info:
        client.request(
            "POST", f"/v1/adaccounts/{AD_ACCOUNT}/campaigns", json_body={"campaigns": []}
        )
    assert exc_info.value.status == 500
    assert route.call_count == 1
    assert audit_entries(tmp_audit_log)[0]["error"] == "HTTP 500"


@respx.mock
def test_write_is_audited(client: SnapchatAdsClient, tmp_audit_log) -> None:
    body = wrap("campaigns", "campaign", {"id": CAMPAIGN_ID, "name": "x"})
    respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        return_value=httpx.Response(200, json=body)
    )
    out = client.request(
        "POST",
        f"/v1/adaccounts/{AD_ACCOUNT}/campaigns",
        json_body={"campaigns": [{"name": "x"}]},
        op="create_campaigns",
        ad_account_id=AD_ACCOUNT,
    )
    entries = audit_entries(tmp_audit_log)
    assert out["audit_id"] == entries[0]["audit_id"]
    assert entries[0]["op"] == "create_campaigns"
    assert entries[0]["ad_account_id"] == AD_ACCOUNT
    assert entries[0]["request_body"] == {"campaigns": [{"name": "x"}]}


@respx.mock
def test_reads_are_not_audited(client: SnapchatAdsClient, tmp_audit_log) -> None:
    respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/get_campaigns_by_ids").mock(
        return_value=httpx.Response(200, json=wrap("campaigns", "campaign", {"id": "a"}))
    )
    assert client.get_by_ids(AD_ACCOUNT, "campaigns", ["a"]) == [{"id": "a"}]
    assert audit_entries(tmp_audit_log) == []


def test_dry_run_sends_nothing(
    config: Config, audit: AuditLog, fake_auth: FakeAuth, tmp_audit_log
) -> None:
    c = SnapchatAdsClient(dataclasses.replace(config, dry_run=True), fake_auth, audit)
    with respx.mock(assert_all_called=False) as router:
        route = router.patch(url__startswith=BASE).mock(return_value=httpx.Response(200))
        out = c.request(
            "PATCH",
            f"/v1/adaccounts/{AD_ACCOUNT}/campaigns/{CAMPAIGN_ID}",
            json_body=[{"op": "replace", "path": "/name", "value": "y"}],
        )
    assert out["_dry_run"] is True
    assert route.call_count == 0
    assert audit_entries(tmp_audit_log)[0]["dry_run"] is True


@respx.mock
def test_request_status_error_raises(client: SnapchatAdsClient) -> None:
    respx.get(f"{BASE}/v1/me").mock(
        return_value=httpx.Response(
            200, json={"request_status": "ERROR", "display_message": "nope", "error_code": "E3003"}
        )
    )
    with pytest.raises(SnapchatAdsAPIError, match="E3003"):
        client.request("GET", "/v1/me")


@respx.mock
def test_partial_errors_are_listed(client: SnapchatAdsClient) -> None:
    respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_status": "PARTIAL",
                "campaigns": [
                    {"sub_request_status": "ERROR", "sub_request_error_reason": "E1001 bad"},
                    {"sub_request_status": "SUCCESS", "campaign": {"id": "ok"}},
                ],
            },
        )
    )
    out = client.request("POST", f"/v1/adaccounts/{AD_ACCOUNT}/campaigns", json_body={})
    assert out["sub_request_errors"] == [
        {"collection": "campaigns", "index": 0, "reason": "E1001 bad"}
    ]
    assert unwrap(out, "campaigns") == [{"id": "ok"}]
    assert unwrap(out) == [{"id": "ok"}]


def test_unwrap_keeps_warnings() -> None:
    payload = {
        "adsquads": [
            {
                "sub_request_status": "SUCCESS",
                "sub_request_warnings": [{"code": "CONVERSION_WINDOW_NULL_AUTO_SET"}],
                "adsquad": {"id": "s"},
            }
        ]
    }
    assert unwrap(payload, "adsquads") == [
        {"id": "s", "_warnings": [{"code": "CONVERSION_WINDOW_NULL_AUTO_SET"}]}
    ]
    assert sub_request_errors({"x": 1}) == []


@pytest.mark.parametrize("path", ["v1/me", "https://evil.example/v1/me", "/v1/../oauth", "/v1\\me"])
def test_path_must_stay_on_the_api_host(client: SnapchatAdsClient, path: str) -> None:
    with pytest.raises(ValueError):
        client.request("GET", path)


@pytest.mark.parametrize("bad", ["", "a/b", "..", "x?y=1", "a b", "../etc"])
def test_check_id_rejects_path_tricks(bad: str) -> None:
    with pytest.raises(ValueError):
        check_id(bad)


def test_check_id_accepts_snap_ids() -> None:
    assert check_id(CAMPAIGN_ID) == CAMPAIGN_ID
    assert check_id(5677923948298240) == "5677923948298240"


@respx.mock
def test_paginate_follows_next_link_on_snap_only(client: SnapchatAdsClient) -> None:
    first = wrap("campaigns", "campaign", {"id": "a"}, {"id": "b"})
    first["paging"] = {
        "next_link": f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns?cursor=abc&limit=50"
    }
    second = wrap("campaigns", "campaign", {"id": "c"})
    second["paging"] = {"next_link": "https://evil.example/v1/steal?cursor=x"}
    route = respx.get(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
    )
    items, truncated = client.paginate(f"/v1/adaccounts/{AD_ACCOUNT}/campaigns", key="campaigns")
    assert [i["id"] for i in items] == ["a", "b", "c"]
    assert truncated is False
    assert route.calls[0].request.url.params["limit"] == "50"
    assert route.calls[1].request.url.params["cursor"] == "abc"


@respx.mock
def test_paginate_truncates(client: SnapchatAdsClient) -> None:
    page = wrap("ads", "ad", *[{"id": str(i)} for i in range(5)])
    page["paging"] = {"next_link": f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/ads?cursor=n"}
    respx.get(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/ads").mock(
        return_value=httpx.Response(200, json=page)
    )
    items, truncated = client.paginate(f"/v1/adaccounts/{AD_ACCOUNT}/ads", max_results=3)
    assert len(items) == 3 and truncated is True


@respx.mock
def test_throttle_spaces_requests(
    config: Config, audit: AuditLog, fake_auth: FakeAuth, _no_sleep
) -> None:
    c = SnapchatAdsClient(dataclasses.replace(config, max_rps=2), fake_auth, audit)
    respx.get(f"{BASE}/v1/me").mock(return_value=httpx.Response(200, json={}))
    for _ in range(3):
        c.request("GET", "/v1/me")
    assert len(_no_sleep) >= 1
    assert all(0 < s <= 1.0 for s in _no_sleep)


REPORT_URL = "https://data-transfer.snapads.com/async-report/snap_ads/run-1/file.csv"


@respx.mock
def test_download_report_parses_csv(client: SnapchatAdsClient) -> None:
    route = respx.get(REPORT_URL).mock(
        return_value=httpx.Response(200, content=b"\xef\xbb\xbfdate,spend\n2026-11-01,1000000\n")
    )
    assert client.download_report(REPORT_URL) == [{"date": "2026-11-01", "spend": "1000000"}]
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
def test_download_report_retries_with_auth_on_403(client: SnapchatAdsClient) -> None:
    route = respx.get(REPORT_URL).mock(
        side_effect=[httpx.Response(403), httpx.Response(200, content=b"a\n1\n")]
    )
    assert client.download_report(REPORT_URL) == [{"a": "1"}]
    assert route.calls[1].request.headers["Authorization"].startswith("Bearer ")


def test_download_report_refuses_other_hosts(client: SnapchatAdsClient) -> None:
    for url in ("https://example.com/r.csv", "http://data-transfer.snapads.com/r.csv"):
        with pytest.raises(ValueError, match="non-Snap host"):
            client.download_report(url)


@respx.mock
def test_download_report_size_cap(config: Config, audit: AuditLog, fake_auth: FakeAuth) -> None:
    c = SnapchatAdsClient(dataclasses.replace(config, max_download_mb=1), fake_auth, audit)
    respx.get(REPORT_URL).mock(return_value=httpx.Response(200, content=b"x" * (1024 * 1024 + 10)))
    with pytest.raises(ValueError, match="SNAPCHAT_ADS_MAX_DOWNLOAD_MB"):
        c.download_report(REPORT_URL)


def test_parse_csv_refuses_excel() -> None:
    with pytest.raises(ValueError, match="csv"):
        parse_csv(b"PK\x03\x04...")
    assert parse_csv(b"") == []
