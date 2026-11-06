"""Tool behaviour through the MCP server: guards, PATCH documents, money and uploads."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer

from snapchat_ads_mcp import server
from snapchat_ads_mcp.config import Config
from snapchat_ads_mcp.tools import creatives

from .conftest import (
    AD_ACCOUNT,
    AD_ID,
    BASE,
    CAMPAIGN_ID,
    SQUAD_ID,
    FakeAuth,
    audit_entries,
    call,
    call_error,
    wrap,
)


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


def _build(config: Config, **changes: Any) -> MCPServer:
    return server.build_server(dataclasses.replace(config, **changes))


def _by_ids(router: respx.Router, collection: str, singular: str, *entities: dict[str, Any]):
    return router.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/get_{collection}_by_ids").mock(
        return_value=httpx.Response(200, json=wrap(collection, singular, *entities))
    )


# ---------------------------------------------------------------- lists


@respx.mock
async def test_list_campaigns_adds_amounts_and_filters(config: Config) -> None:
    respx.get(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        return_value=httpx.Response(
            200,
            json=wrap(
                "campaigns",
                "campaign",
                {
                    "id": "a",
                    "name": "Spring sale",
                    "status": "ACTIVE",
                    "daily_budget_micro": 50_000_000,
                },
                {"id": "b", "name": "Brand", "status": "PAUSED"},
            ),
        )
    )
    out = await call(_build(config), "snapchat_ads_list_campaigns", {"statuses": ["ACTIVE"]})
    assert out["count"] == 1
    assert out["campaigns"][0]["amounts"] == {"daily_budget": 50.0}


@respx.mock
async def test_list_ads_by_squad_and_review_status(config: Config) -> None:
    respx.get(f"{BASE}/v1/adsquads/{SQUAD_ID}/ads").mock(
        return_value=httpx.Response(
            200,
            json=wrap(
                "ads",
                "ad",
                {"id": "1", "review_status": "REJECTED", "review_status_reasons": ["x"]},
                {"id": "2", "review_status": "APPROVED"},
            ),
        )
    )
    out = await call(
        _build(config),
        "snapchat_ads_list_ads",
        {"ad_squad_id": SQUAD_ID, "review_status": "rejected"},
    )
    assert [a["id"] for a in out["ads"]] == ["1"]


@respx.mock
async def test_list_by_ids_uses_post(config: Config) -> None:
    route = _by_ids(respx.mock, "adsquads", "adsquad", {"id": SQUAD_ID, "bid_micro": 1_500_000})
    out = await call(_build(config), "snapchat_ads_list_ad_squads", {"ids": [SQUAD_ID]})
    assert out["ad_squads"][0]["amounts"] == {"bid": 1.5}
    assert json.loads(route.calls[0].request.content) == {"entity_ids": [{"id": SQUAD_ID}]}


async def test_missing_ad_account_is_explained(config: Config) -> None:
    text = await call_error(_build(config, ad_account_id=None), "snapchat_ads_list_campaigns")
    assert "SNAPCHAT_ADS_AD_ACCOUNT_ID" in text


# ---------------------------------------------------------------- create


@respx.mock
async def test_create_campaigns_paused_by_default(config: Config, tmp_audit_log: Path) -> None:
    route = respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns").mock(
        return_value=httpx.Response(
            200, json=wrap("campaigns", "campaign", {"id": "new", "status": "PAUSED"})
        )
    )
    out = await call(
        _build(config),
        "snapchat_ads_create_campaigns",
        {
            "items": [
                {"name": "A", "start_time": "2026-12-01T00:00:00Z"},
                {"name": "B", "status": "ACTIVE"},
            ]
        },
    )
    sent = json.loads(route.calls[0].request.content)["campaigns"]
    assert sent[0]["status"] == "PAUSED" and sent[0]["ad_account_id"] == AD_ACCOUNT
    assert sent[1]["status"] == "ACTIVE"
    assert out["created_count"] == 1
    assert audit_entries(tmp_audit_log)[0]["op"] == "create_campaigns"


async def test_create_over_cap_needs_apply(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__startswith=BASE).mock(return_value=httpx.Response(200, json={}))
        out = await call(
            _build(config, max_budget=100.0),
            "snapchat_ads_create_ad_squads",
            {
                "campaign_id": CAMPAIGN_ID,
                "items": [{"name": "s", "daily_budget_micro": 500_000_000}],
            },
        )
    assert out["refused"] is True
    assert out["required_confirm"] == "APPLY"
    assert out["would_send"]["adsquads"][0]["campaign_id"] == CAMPAIGN_ID
    assert route.call_count == 0


@respx.mock
async def test_create_batches_large_requests(config: Config) -> None:
    route = respx.post(f"{BASE}/v1/adsquads/{SQUAD_ID}/ads").mock(
        return_value=httpx.Response(200, json=wrap("ads", "ad", {"id": "x"}))
    )
    items = [{"name": f"ad {i}", "creative_id": "c", "type": "SNAP_AD"} for i in range(31)]
    out = await call(
        _build(config),
        "snapchat_ads_create_ads",
        {"ad_squad_id": SQUAD_ID, "items": items, "confirm": "APPLY"},
    )
    assert route.call_count == 2
    assert [len(json.loads(c.request.content)["ads"]) for c in route.calls] == [30, 1]
    assert out["safety"]["required_confirm"] == "APPLY"


# ---------------------------------------------------------------- update (PATCH)


@respx.mock
async def test_update_sends_json_patch_with_snapshot(config: Config, tmp_audit_log: Path) -> None:
    current = {
        "id": CAMPAIGN_ID,
        "ad_account_id": AD_ACCOUNT,
        "name": "Old",
        "daily_budget_micro": 50_000_000,
        "end_time": "2026-12-31T00:00:00Z",
    }
    _by_ids(respx.mock, "campaigns", "campaign", current)
    patch = respx.patch(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns/{CAMPAIGN_ID}").mock(
        return_value=httpx.Response(
            200, json=wrap("campaigns", "campaign", {**current, "name": "New"})
        )
    )
    out = await call(
        _build(config),
        "snapchat_ads_update_campaigns",
        {
            "items": [
                {
                    "id": CAMPAIGN_ID,
                    "name": "New",
                    "daily_budget_micro": 55_000_000,
                    "lifetime_spend_cap_micro": 900_000_000,
                    "end_time": None,
                }
            ],
            "confirm": "APPLY",
        },
    )
    req = patch.calls[0].request
    assert req.headers["Content-Type"] == "application/json-patch+json"
    assert json.loads(req.content) == [
        {"op": "replace", "path": "/name", "value": "New"},
        {"op": "replace", "path": "/daily_budget_micro", "value": 55_000_000},
        {"op": "add", "path": "/lifetime_spend_cap_micro", "value": 900_000_000},
        {"op": "remove", "path": "/end_time"},
    ]
    assert out["updated_count"] == 1
    assert audit_entries(tmp_audit_log)[0]["before"]["name"] == "Old"


async def test_budget_rise_needs_apply(config: Config) -> None:
    current = {"id": SQUAD_ID, "campaign_id": CAMPAIGN_ID, "daily_budget_micro": 20_000_000}
    with respx.mock(assert_all_called=False) as router:
        _by_ids(router, "adsquads", "adsquad", current)
        patch = router.patch(url__startswith=BASE).mock(return_value=httpx.Response(200, json={}))
        out = await call(
            _build(config),
            "snapchat_ads_update_ad_squads",
            {"items": [{"id": SQUAD_ID, "daily_budget_micro": 40_000_000}]},
        )
    assert out["refused"] is True
    assert "rises from 20 to 40" in " ".join(out["reasons"])
    assert out["would_send"][0]["path"] == f"/v1/campaigns/{CAMPAIGN_ID}/adsquads/{SQUAD_ID}"
    assert patch.call_count == 0


async def test_update_without_snapshot_needs_parent(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(url__startswith=f"{BASE}/v1/adaccounts").mock(return_value=httpx.Response(500))
        text = await call_error(
            _build(config), "snapchat_ads_update_ads", {"items": [{"id": AD_ID, "name": "x"}]}
        )
    assert "ad_squad_id" in text


async def test_read_only_fields_are_refused(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        _by_ids(router, "ads", "ad", {"id": AD_ID, "ad_squad_id": SQUAD_ID})
        text = await call_error(
            _build(config),
            "snapchat_ads_update_ads",
            {"items": [{"id": AD_ID, "review_status": "APPROVED"}]},
        )
    assert "review_status can't be changed" in text


# ---------------------------------------------------------------- bulk


@respx.mock
async def test_set_status_patches_each(config: Config) -> None:
    _by_ids(
        respx.mock,
        "ads",
        "ad",
        {"id": "a1", "ad_squad_id": SQUAD_ID, "status": "ACTIVE"},
        {"id": "a2", "ad_squad_id": SQUAD_ID, "status": "ACTIVE"},
    )
    p1 = respx.patch(f"{BASE}/v1/adsquads/{SQUAD_ID}/ads/a1").mock(
        return_value=httpx.Response(200, json={})
    )
    p2 = respx.patch(f"{BASE}/v1/adsquads/{SQUAD_ID}/ads/a2").mock(
        return_value=httpx.Response(200, json={})
    )
    out = await call(
        _build(config),
        "snapchat_ads_set_status",
        {"entity_type": "ad", "ids": ["a1", "a2"], "status": "PAUSED"},
    )
    assert out["updated_count"] == 2
    assert json.loads(p1.calls[0].request.content) == [
        {"op": "replace", "path": "/status", "value": "PAUSED"}
    ]
    assert p2.called


@respx.mock
async def test_set_budgets_converts_to_micro(config: Config) -> None:
    _by_ids(
        respx.mock,
        "campaigns",
        "campaign",
        {"id": CAMPAIGN_ID, "ad_account_id": AD_ACCOUNT, "daily_budget_micro": 100_000_000},
    )
    patch = respx.patch(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/campaigns/{CAMPAIGN_ID}").mock(
        return_value=httpx.Response(200, json={})
    )
    await call(
        _build(config),
        "snapchat_ads_set_budgets",
        {"entity_type": "campaign", "changes": [{"id": CAMPAIGN_ID, "daily_budget": 90.5}]},
    )
    assert json.loads(patch.calls[0].request.content) == [
        {"op": "replace", "path": "/daily_budget_micro", "value": 90_500_000}
    ]


async def test_set_budgets_pct_rise_needs_apply(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        _by_ids(
            router,
            "adsquads",
            "adsquad",
            {"id": SQUAD_ID, "campaign_id": CAMPAIGN_ID, "lifetime_budget_micro": 1_000_000_000},
        )
        out = await call(
            _build(config),
            "snapchat_ads_set_budgets",
            {"entity_type": "ad_squad", "changes": [{"id": SQUAD_ID, "change_pct": 50}]},
        )
    assert out["refused"] is True
    assert out["money_changes"][0]["new_micro"] == 1_500_000_000


@respx.mock
async def test_set_bids_pct_and_auto_bid_note(config: Config) -> None:
    _by_ids(
        respx.mock,
        "adsquads",
        "adsquad",
        {
            "id": SQUAD_ID,
            "campaign_id": CAMPAIGN_ID,
            "bid_micro": 2_000_000,
            "bid_strategy": "AUTO_BID",
        },
    )
    patch = respx.patch(f"{BASE}/v1/campaigns/{CAMPAIGN_ID}/adsquads/{SQUAD_ID}").mock(
        return_value=httpx.Response(200, json={})
    )
    out = await call(
        _build(config), "snapchat_ads_set_bids", {"changes": [{"id": SQUAD_ID, "change_pct": -10}]}
    )
    assert json.loads(patch.calls[0].request.content)[0]["value"] == 1_800_000
    assert "AUTO_BID" in out["notes"][0]


# ---------------------------------------------------------------- delete


async def test_delete_needs_confirm_then_deletes(config: Config, tmp_audit_log: Path) -> None:
    mcp = _build(config)
    with respx.mock(assert_all_called=False) as router:
        _by_ids(router, "campaigns", "campaign", {"id": CAMPAIGN_ID, "name": "Old"})
        delete = router.delete(f"{BASE}/v1/campaigns/{CAMPAIGN_ID}").mock(
            return_value=httpx.Response(200, json={"request_status": "SUCCESS"})
        )
        refused = await call(mcp, "snapchat_ads_delete_campaigns", {"ids": [CAMPAIGN_ID]})
        assert refused["required_confirm"] == "DELETE"
        assert delete.call_count == 0
        out = await call(
            mcp, "snapchat_ads_delete_campaigns", {"ids": [CAMPAIGN_ID], "confirm": "DELETE"}
        )
    assert out["deleted_count"] == 1
    assert audit_entries(tmp_audit_log)[0]["before"] == {"id": CAMPAIGN_ID, "name": "Old"}


# ---------------------------------------------------------------- audiences


async def test_segments_never_upload_identifiers(config: Config) -> None:
    text = await call_error(
        _build(config),
        "snapchat_ads_create_segments",
        {
            "items": [
                {"name": "x", "source_type": "FIRST_PARTY", "retention_in_days": 30, "users": []}
            ]
        },
    )
    assert "customer identifiers" in text


@respx.mock
async def test_update_segment_merges_current(config: Config) -> None:
    respx.get(f"{BASE}/v1/segments/123").mock(
        return_value=httpx.Response(
            200,
            json=wrap(
                "segments",
                "segment",
                {"id": "123", "name": "Old", "description": "d", "retention_in_days": 180},
            ),
        )
    )
    put = respx.put(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/segments").mock(
        return_value=httpx.Response(
            200, json=wrap("segments", "segment", {"id": "123", "name": "New"})
        )
    )
    await call(
        _build(config), "snapchat_ads_update_segments", {"items": [{"id": "123", "name": "New"}]}
    )
    assert json.loads(put.calls[0].request.content) == {
        "segments": [
            {
                "id": "123",
                "name": "New",
                "ad_account_id": AD_ACCOUNT,
                "description": "d",
                "retention_in_days": 180,
            }
        ]
    }


# ---------------------------------------------------------------- media upload


def _upload_config(config: Config, tmp_path: Path) -> tuple[Config, Path]:
    folder = tmp_path / "uploads"
    folder.mkdir()
    return dataclasses.replace(config, upload_dir=folder), folder


async def test_upload_needs_upload_dir_and_stays_inside(config: Config, tmp_path: Path) -> None:
    text = await call_error(_build(config), "snapchat_ads_upload_media", {"source": "a.png"})
    assert "SNAPCHAT_ADS_UPLOAD_DIR" in text
    cfg, _ = _upload_config(config, tmp_path)
    (tmp_path / "secret.png").write_bytes(b"x")
    text = await call_error(_build(cfg), "snapchat_ads_upload_media", {"source": "../secret.png"})
    assert "outside SNAPCHAT_ADS_UPLOAD_DIR" in text
    text = await call_error(
        _build(cfg), "snapchat_ads_upload_media", {"source": "https://cdn.example/a.png"}
    )
    assert "doesn't upload media from a URL" in text


@respx.mock
async def test_upload_single(config: Config, tmp_path: Path) -> None:
    cfg, folder = _upload_config(config, tmp_path)
    (folder / "hero.png").write_bytes(b"\x89PNG fake image")
    create = respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/media").mock(
        return_value=httpx.Response(
            200, json=wrap("media", "media", {"id": "m1", "media_status": "PENDING_UPLOAD"})
        )
    )
    upload = respx.post(f"{BASE}/v1/media/m1/upload").mock(
        return_value=httpx.Response(200, json={"result": {"id": "m1", "media_status": "READY"}})
    )
    out = await call(
        _build(cfg), "snapchat_ads_upload_media", {"source": "hero.png", "ai_generated": True}
    )
    assert out["media_id"] == "m1" and out["upload"] == "single"
    media = json.loads(create.calls[0].request.content)["media"][0]
    assert media == {
        "name": "hero",
        "type": "IMAGE",
        "ad_account_id": AD_ACCOUNT,
        "ai_content_source": "USER_AI_GEN",
    }
    body = upload.calls[0].request.content
    assert b"multipart" not in body[:0] and b'filename="hero.png"' in body
    assert upload.calls[0].request.headers["Content-Type"].startswith("multipart/form-data")


@respx.mock
async def test_upload_chunked(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(creatives, "SINGLE_UPLOAD_MAX", 10)
    monkeypatch.setattr(creatives, "PART_SIZE", 10)
    cfg, folder = _upload_config(config, tmp_path)
    (folder / "clip.mp4").write_bytes(b"0123456789abcdefghijXYZ")  # 23 bytes -> 3 parts
    respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/media").mock(
        return_value=httpx.Response(200, json=wrap("media", "media", {"id": "m2"}))
    )
    init = respx.post(f"{BASE}/v1/media/m2/multipart-upload-v2", params={"action": "INIT"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "upload_id": "up-1",
                "add_path": "/us/v1/media/m2/multipart-upload-v2?action=ADD",
                "finalize_path": "/v1/media/m2/multipart-upload-v2?action=FINALIZE",
            },
        )
    )
    add = respx.post(f"{BASE}/us/v1/media/m2/multipart-upload-v2", params={"action": "ADD"}).mock(
        return_value=httpx.Response(200, json={"request_status": "SUCCESS"})
    )
    final = respx.post(
        f"{BASE}/v1/media/m2/multipart-upload-v2", params={"action": "FINALIZE"}
    ).mock(return_value=httpx.Response(200, json={"result": {"id": "m2", "media_status": "READY"}}))
    out = await call(_build(cfg), "snapchat_ads_upload_media", {"source": "clip.mp4"})
    assert out["upload"] == "chunked" and out["parts"] == 3
    assert b'name="number_of_parts"\r\n\r\n3' in init.calls[0].request.content
    assert add.call_count == 3
    assert b"XYZ" in add.calls[2].request.content
    assert b'name="upload_id"\r\n\r\nup-1' in final.calls[0].request.content


async def test_upload_dry_run_creates_nothing(config: Config, tmp_path: Path) -> None:
    cfg, folder = _upload_config(config, tmp_path)
    (folder / "a.jpg").write_bytes(b"jpg")
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__startswith=BASE).mock(return_value=httpx.Response(200, json={}))
        out = await call(
            _build(cfg, dry_run=True), "snapchat_ads_upload_media", {"source": "a.jpg"}
        )
    assert out["_dry_run"] is True and out["upload"] == "single"
    assert route.call_count == 0


# ---------------------------------------------------------------- targeting and catalogs


@respx.mock
async def test_targeting_options(config: Config) -> None:
    route = respx.get(f"{BASE}/v1/targeting/geo/gb/region").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_status": "SUCCESS",
                "targeting_dimensions": [
                    {"sub_request_status": "SUCCESS", "region": {"id": "1", "name": "Scotland"}},
                    {"sub_request_status": "SUCCESS", "region": {"id": "2", "name": "Wales"}},
                ],
            },
        )
    )
    out = await call(
        _build(config),
        "snapchat_ads_get_targeting_options",
        {"kind": "regions", "country_code": "GB", "search": "wal"},
    )
    assert out["options"] == [{"id": "2", "name": "Wales"}]
    assert route.called
    text = await call_error(
        _build(config), "snapchat_ads_get_targeting_options", {"kind": "regions"}
    )
    assert "country_code" in text


@respx.mock
async def test_audience_size_is_a_read(config: Config, tmp_audit_log: Path) -> None:
    route = respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/audience_size_v2").mock(
        return_value=httpx.Response(
            200, json={"audience_size": {"audience_size_minimum": 1, "audience_size_maximum": 2}}
        )
    )
    out = await call(
        _build(config, dry_run=True),
        "snapchat_ads_estimate_audience_size",
        {"targeting": {"geos": [{"country_code": "gb"}]}},
    )
    assert out == {"audience_size_minimum": 1, "audience_size_maximum": 2}
    assert route.called  # read-only POSTs run even in dry-run
    assert audit_entries(tmp_audit_log) == []


@respx.mock
async def test_search_products(config: Config) -> None:
    respx.post(f"{BASE}/v1/catalogs/cat-1/products/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_status": "SUCCESS",
                "summary": {"total_products": {"count": "209"}},
                "paging": {"next_link": f"{BASE}/v1/catalogs/cat-1/products/search?cursor=x"},
                "products": [{"sub_request_status": "SUCCESS", "product": {"id": "p1"}}],
            },
        )
    )
    out = await call(
        _build(config),
        "snapchat_ads_search_products",
        {"catalog_id": "cat-1", "filter": {"AVAILABILITY": {"EQ": "IN_STOCK"}}},
    )
    assert out["products"] == [{"id": "p1"}] and out["more"] is True


# ---------------------------------------------------------------- escape hatches


async def test_read_request_refuses_writes(config: Config) -> None:
    text = await call_error(
        _build(config),
        "snapchat_ads_read_request",
        {"method": "DELETE", "path": f"/v1/campaigns/{CAMPAIGN_ID}"},
    )
    assert "snapchat_ads_request" in text


@pytest.mark.parametrize(
    "path",
    ["/v2/x", "https://evil.example/v1/me", "/v1/../x", "/v1//x", "/v1/me?x=1", "v1/me"],
)
async def test_escape_hatch_paths(config: Config, path: str) -> None:
    text = await call_error(
        _build(config), "snapchat_ads_read_request", {"method": "GET", "path": path}
    )
    assert "path" in text.lower() or "query" in text.lower()


async def test_raw_write_needs_apply(config: Config, tmp_audit_log: Path) -> None:
    mcp = _build(config)
    with respx.mock(assert_all_called=False) as router:
        route = router.put(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/pixels").mock(
            return_value=httpx.Response(200, json={"request_status": "SUCCESS"})
        )
        refused = await call(
            mcp,
            "snapchat_ads_request",
            {"method": "PUT", "path": f"/v1/adaccounts/{AD_ACCOUNT}/pixels", "body": {}},
        )
        assert refused["refused"] is True and route.call_count == 0
        out = await call(
            mcp,
            "snapchat_ads_request",
            {
                "method": "PUT",
                "path": f"/v1/adaccounts/{AD_ACCOUNT}/pixels",
                "body": {},
                "confirm": "APPLY",
            },
        )
    assert out["audit_id"]
    assert audit_entries(tmp_audit_log)[0]["op"].startswith("request PUT")


@respx.mock
async def test_read_request_post_by_ids(config: Config) -> None:
    route = respx.post(f"{BASE}/v1/adaccounts/{AD_ACCOUNT}/get_ads_by_ids").mock(
        return_value=httpx.Response(200, json={"request_status": "SUCCESS"})
    )
    await call(
        _build(config, dry_run=True),
        "snapchat_ads_read_request",
        {
            "method": "POST",
            "path": f"/v1/adaccounts/{AD_ACCOUNT}/get_ads_by_ids",
            "body": {"entity_ids": []},
        },
    )
    assert route.called


# ---------------------------------------------------------------- accounts


@respx.mock
async def test_get_me_drops_email(config: Config) -> None:
    respx.get(f"{BASE}/v1/me").mock(
        return_value=httpx.Response(
            200,
            json={"me": {"id": "u1", "display_name": "Example User", "email": "user@example.com"}},
        )
    )
    out = await call(_build(config), "snapchat_ads_get_me")
    assert out == {"id": "u1", "display_name": "Example User"}
