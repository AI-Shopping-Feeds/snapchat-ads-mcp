"""The signed-in user, organisations, ad accounts and funding sources (read-only)."""

from __future__ import annotations

from typing import Any

from ..client import SnapchatAdsClient, check_id, unwrap
from ._common import add_amounts
from ._progress import run_blocking


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    def snapchat_ads_get_me() -> dict[str, Any]:
        """Show the Snapchat user the server is signed in as (display name, organisation)."""
        me = client.request("GET", "/v1/me").get("me") or {}
        # Email and Bitmoji details are left out: this server keeps personal data to a minimum.
        keep = ("id", "display_name", "organization_id", "member_status")
        return {k: me.get(k) for k in keep if k in me}

    @mcp.tool()
    def snapchat_ads_list_organizations(with_ad_accounts: bool = True) -> dict[str, Any]:
        """List the organisations this user belongs to, with their ad accounts by default.

        Each ad account shows its currency and timezone: money fields are
        micro-currency in that currency, and DAY reports follow that timezone.
        """
        params = {"with_ad_accounts": "true"} if with_ad_accounts else None
        orgs = client.get_entities("/v1/me/organizations", "organizations", params)
        out = []
        for org in orgs:
            accounts = [add_amounts(a) for a in (org.get("ad_accounts") or [])]
            out.append({**org, "ad_accounts": accounts} if with_ad_accounts else org)
        return {"organizations": out, "count": len(out)}

    @mcp.tool()
    async def snapchat_ads_list_ad_accounts(
        organization_id: str | None = None, max_results: int = 500
    ) -> dict[str, Any]:
        """List the ad accounts in an organisation (currency, timezone, status, spend cap)."""
        oid = client.resolve_organization(organization_id)
        items, truncated = await run_blocking(
            client.paginate,
            f"/v1/organizations/{oid}/adaccounts",
            None,
            key="adaccounts",
            max_results=max_results,
        )
        return {
            "ad_accounts": [add_amounts(a) for a in items],
            "count": len(items),
            "truncated": truncated,
        }

    @mcp.tool()
    def snapchat_ads_get_ad_account(ad_account_id: str | None = None) -> dict[str, Any]:
        """Get one ad account: currency, timezone, status, funding sources and lifetime spend cap."""
        aid = client.resolve_ad_account(ad_account_id)
        found = unwrap(client.request("GET", f"/v1/adaccounts/{aid}"), "adaccounts")
        if not found:
            raise ValueError(f"Ad account {aid} not found or not visible to this user.")
        return add_amounts(found[0])

    @mcp.tool()
    def snapchat_ads_list_funding_sources(organization_id: str | None = None) -> dict[str, Any]:
        """List an organisation's funding sources (credit lines, cards, coupons) and their balances."""
        oid = client.resolve_organization(organization_id)
        items = client.get_entities(f"/v1/organizations/{check_id(oid)}/fundingsources")
        return {"funding_sources": [add_amounts(f) for f in items], "count": len(items)}
