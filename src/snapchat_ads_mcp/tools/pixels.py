"""Snap Pixels and Snap App IDs: the conversion sources ad squads optimise for (read-only)."""

from __future__ import annotations

from typing import Any, Literal

from ..client import SnapchatAdsClient, check_id


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    def snapchat_ads_list_pixels(
        ad_account_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        """List Snap Pixels for an ad account (default) or a whole organisation.

        Pixels are created in Ads Manager; use a pixel's id as an ad squad's
        pixel_id for PIXEL_* optimisation goals.
        """
        if organization_id:
            path = f"/v1/organizations/{check_id(organization_id, 'organization_id')}/pixels"
        else:
            path = f"/v1/adaccounts/{client.resolve_ad_account(ad_account_id)}/pixels"
        items, truncated = client.paginate(path, None, key="pixels", max_results=1000)
        return {"pixels": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    def snapchat_ads_get_pixel_domains(pixel_id: str) -> dict[str, Any]:
        """List the website domains that fired a pixel in the last 7 days, with event counts."""
        pid = check_id(pixel_id, "pixel_id")
        return client.request("GET", f"/v1/pixels/{pid}/domains/stats")

    @mcp.tool()
    def snapchat_ads_get_pixel_stats(
        pixel_id: str,
        domain: str,
        start_time: str,
        end_time: str,
        granularity: Literal["DAY", "HOUR"] = "DAY",
        fields: str = "EVENT_TYPE",
    ) -> dict[str, Any]:
        """Get pixel event counts for one domain (up to 28 days back) to check the pixel works.

        fields: comma-separated EVENT_TYPE, OS_TYPE, BROWSER_TYPE. Times are ISO
        8601, e.g. 2026-11-01T00:00:00Z.
        """
        pid = check_id(pixel_id, "pixel_id")
        params = {
            "start_time": start_time,
            "end_time": end_time,
            "granularity": granularity,
            "domain": domain.strip(),
            "fields": fields,
        }
        return client.request("GET", f"/v1/pixels/{pid}/stats", params=params)

    @mcp.tool()
    def snapchat_ads_list_snap_apps(
        ad_account_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        """List Snap App IDs (mobile apps) for an ad account (default) or organisation.

        Use a Snap App ID in ad squad event_sources for APP_* goals, and with
        snapchat_ads_check_optimization_eligibility.
        """
        if organization_id:
            path = f"/v1/organizations/{check_id(organization_id, 'organization_id')}/mobile_apps"
        else:
            path = f"/v1/adaccounts/{client.resolve_ad_account(ad_account_id)}/mobile_apps"
        items, truncated = client.paginate(path, None, max_results=1000)
        return {"snap_apps": items, "count": len(items), "truncated": truncated}
