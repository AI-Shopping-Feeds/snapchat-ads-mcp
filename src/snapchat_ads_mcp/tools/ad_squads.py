"""Ad squads: targeting, placement, optimisation goal, budget and bid for a group of ads."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from ..client import SnapchatAdsClient, check_id
from ._common import (
    add_amounts,
    create_description,
    create_entities,
    fetch_by_ids,
    filter_entities,
    ids_to_strings,
    register_update_delete,
)
from ._progress import run_blocking
from ._specs import AD_SQUAD


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    async def snapchat_ads_list_ad_squads(
        ad_account_id: str | None = None,
        campaign_id: str | None = None,
        ids: list[str] | None = None,
        statuses: list[str] | None = None,
        name_contains: str | None = None,
        include_deleted: bool = False,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List ad squads in a campaign (campaign_id) or a whole ad account.

        ids fetches those ad squads directly (up to 2,000; needs the ad account).
        statuses and name_contains filter the result. bid_micro and the budgets
        are micro-currency; `amounts` shows them in whole currency units.
        """
        id_list = ids_to_strings(ids, "ad squad id")
        if id_list:
            aid = client.resolve_ad_account(ad_account_id)
            items = await run_blocking(fetch_by_ids, client, AD_SQUAD, aid, id_list)
            truncated = False
        else:
            path = (
                f"/v1/campaigns/{check_id(campaign_id, 'campaign_id')}/adsquads"
                if campaign_id
                else f"/v1/adaccounts/{client.resolve_ad_account(ad_account_id)}/adsquads"
            )
            params = {"read_deleted_entities": "true"} if include_deleted else None
            items, truncated = await run_blocking(
                client.paginate, path, params, key="adsquads", max_results=max_results
            )
        items = filter_entities(items, statuses, name_contains)
        return {
            "ad_squads": [add_amounts(a) for a in items],
            "count": len(items),
            "truncated": truncated,
        }

    @mcp.tool(description=create_description(AD_SQUAD, "campaign"))
    async def snapchat_ads_create_ad_squads(
        campaign_id: str,
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        cid = check_id(campaign_id, "campaign_id")
        account = (ad_account_id or client.config.ad_account_id or "").strip() or None
        return await create_entities(
            client, AD_SQUAD, cid, items, confirm=confirm, ad_account_id=account, ctx=ctx
        )

    register_update_delete(mcp, client, AD_SQUAD)
