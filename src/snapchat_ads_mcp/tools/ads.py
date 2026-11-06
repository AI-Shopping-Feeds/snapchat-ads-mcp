"""Ads: link a creative to an ad squad. New ads go through Snap's review."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from ..client import SnapchatAdsClient, check_id
from ._common import (
    create_description,
    create_entities,
    fetch_by_ids,
    filter_entities,
    ids_to_strings,
    register_update_delete,
)
from ._progress import run_blocking
from ._specs import AD


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    async def snapchat_ads_list_ads(
        ad_account_id: str | None = None,
        campaign_id: str | None = None,
        ad_squad_id: str | None = None,
        ids: list[str] | None = None,
        statuses: list[str] | None = None,
        review_status: str | None = None,
        name_contains: str | None = None,
        include_deleted: bool = False,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List ads in an ad squad, a campaign or a whole ad account.

        ids fetches those ads directly (up to 2,000; needs the ad account).
        review_status (PENDING, APPROVED, REJECTED) finds rejected ads;
        review_status_reasons says why.
        """
        id_list = ids_to_strings(ids, "ad id")
        if id_list:
            aid = client.resolve_ad_account(ad_account_id)
            items = await run_blocking(fetch_by_ids, client, AD, aid, id_list)
            truncated = False
        else:
            if ad_squad_id:
                path = f"/v1/adsquads/{check_id(ad_squad_id, 'ad_squad_id')}/ads"
            elif campaign_id:
                path = f"/v1/campaigns/{check_id(campaign_id, 'campaign_id')}/ads"
            else:
                path = f"/v1/adaccounts/{client.resolve_ad_account(ad_account_id)}/ads"
            params = {"read_deleted_entities": "true"} if include_deleted else None
            items, truncated = await run_blocking(
                client.paginate, path, params, key="ads", max_results=max_results
            )
        items = filter_entities(items, statuses, name_contains)
        if review_status:
            items = [
                a for a in items if str(a.get("review_status", "")).upper() == review_status.upper()
            ]
        return {"ads": items, "count": len(items), "truncated": truncated}

    @mcp.tool(description=create_description(AD, "ad squad"))
    async def snapchat_ads_create_ads(
        ad_squad_id: str,
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        sid = check_id(ad_squad_id, "ad_squad_id")
        account = (ad_account_id or client.config.ad_account_id or "").strip() or None
        return await create_entities(
            client, AD, sid, items, confirm=confirm, ad_account_id=account, ctx=ctx
        )

    register_update_delete(mcp, client, AD)
