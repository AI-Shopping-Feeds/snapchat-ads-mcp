"""Campaigns: the top of the ad hierarchy, holding budget caps and the objective."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from ..client import SnapchatAdsClient
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
from ._specs import CAMPAIGN


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    async def snapchat_ads_list_campaigns(
        ad_account_id: str | None = None,
        ids: list[str] | None = None,
        statuses: list[str] | None = None,
        name_contains: str | None = None,
        include_deleted: bool = False,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List campaigns in an ad account, newest first by Snap's paging order.

        ids fetches those campaigns directly (up to 2,000). statuses (ACTIVE,
        PAUSED) and name_contains filter the result. Each campaign has an
        `amounts` map with its *_micro money fields in whole currency units, and
        delivery_status explains why it is or isn't serving.
        """
        aid = client.resolve_ad_account(ad_account_id)
        id_list = ids_to_strings(ids, "campaign id")
        if id_list:
            items = await run_blocking(fetch_by_ids, client, CAMPAIGN, aid, id_list)
            truncated = False
        else:
            params = {"read_deleted_entities": "true"} if include_deleted else None
            items, truncated = await run_blocking(
                client.paginate,
                f"/v1/adaccounts/{aid}/campaigns",
                params,
                key="campaigns",
                max_results=max_results,
            )
        items = filter_entities(items, statuses, name_contains)
        return {
            "campaigns": [add_amounts(c) for c in items],
            "count": len(items),
            "truncated": truncated,
        }

    @mcp.tool(description=create_description(CAMPAIGN, "ad account"))
    async def snapchat_ads_create_campaigns(
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        aid = client.resolve_ad_account(ad_account_id)
        return await create_entities(
            client, CAMPAIGN, aid, items, confirm=confirm, ad_account_id=aid, ctx=ctx
        )

    register_update_delete(mcp, client, CAMPAIGN)
