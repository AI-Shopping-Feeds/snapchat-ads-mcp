"""Targeting options, audience size, bid estimates and optimisation-goal eligibility (read-only)."""

from __future__ import annotations

from typing import Any, Literal

from ..client import SnapchatAdsClient, check_id, unwrap
from ._common import add_amounts

# Targeting option lists: kind -> (path template, needs country_code in the path).
# Oracle (DLX) interest options were retired by Snap in September 2024 and are left out.
TARGETING_KINDS: dict[str, tuple[str, bool]] = {
    "supported_options": ("/v1/targeting/v1/options", False),
    "countries": ("/v1/targeting/geo/country", False),
    "regions": ("/v1/targeting/geo/{cc}/region", True),
    "metros": ("/v1/targeting/geo/{cc}/metro", True),
    "postal_codes": ("/v1/targeting/geo/{cc}/postal_code", True),
    "age_groups": ("/v1/targeting/demographics/age_group", False),
    "genders": ("/v1/targeting/demographics/gender", False),
    "languages": ("/v1/targeting/demographics/languages", False),
    "advanced_demographics": ("/v1/targeting/demographics/advanced_demographics", False),
    "lifestyle_categories": ("/v1/targeting/v1/interests/scls", False),
    "shopper_interests": ("/v1/targeting/v1/interests/shp", False),
    "visitation_categories": ("/v1/targeting/v1/interests/vac", False),
    "nielsen_interests": ("/v1/targeting/interests/nln", False),
    "location_categories": ("/v1/targeting/location/categories_loi", False),
    "os_types": ("/v1/targeting/device/os_type", False),
    "os_versions": ("/v1/targeting/device/{os}/os_version", False),
    "carriers": ("/v1/targeting/device/carrier", False),
    "connection_types": ("/v1/targeting/device/connection_type", False),
    "device_makes": ("/v1/targeting/device/marketing_name", False),
}
TargetingKind = Literal[
    "supported_options",
    "countries",
    "regions",
    "metros",
    "postal_codes",
    "age_groups",
    "genders",
    "languages",
    "advanced_demographics",
    "lifestyle_categories",
    "shopper_interests",
    "visitation_categories",
    "nielsen_interests",
    "location_categories",
    "os_types",
    "os_versions",
    "carriers",
    "connection_types",
    "device_makes",
]


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    def snapchat_ads_get_targeting_options(
        kind: TargetingKind,
        country_code: str | None = None,
        os_type: Literal["iOS", "ANDROID"] | None = None,
        search: str | None = None,
        hec_safe: bool = False,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """Look up targeting values (IDs and names) to use in an ad squad's targeting spec.

        kind: supported_options (what a country supports), countries, regions,
        metros, postal_codes (these three need country_code), age_groups, genders,
        languages, advanced_demographics, lifestyle_categories (SLC interests),
        shopper_interests, visitation_categories, nielsen_interests,
        location_categories, os_types, os_versions (needs os_type), carriers,
        connection_types, device_makes. country_code is ISO alpha-2, lower case
        (e.g. 'gb'). search filters by name; hec_safe=true returns only options
        allowed for Housing, Credit and Employment ads where Snap supports it.
        """
        path_template, needs_cc = TARGETING_KINDS[kind]
        cc = (country_code or "").strip().lower()
        if cc and (len(cc) != 2 or not cc.isalpha()):
            raise ValueError("country_code must be a two-letter ISO code, e.g. 'gb'.")
        if needs_cc and not cc:
            raise ValueError(f"{kind} needs country_code.")
        if kind == "supported_options" and not cc:
            raise ValueError("supported_options needs country_code.")
        if kind == "os_versions" and not os_type:
            raise ValueError("os_versions needs os_type (iOS or ANDROID).")
        path = path_template.format(cc=cc, os=os_type or "")
        params: dict[str, Any] = {}
        if cc and not needs_cc:
            params["country_code"] = cc
        if hec_safe:
            params["is_hec"] = "true"
        if kind == "supported_options":
            out = client.request("GET", path, params=params)
            return {"kind": kind, "country_code": cc, "options": out.get("targeting_option", out)}
        items, truncated = client.paginate(path, params, max_results=max(max_results, 1))
        if search:
            needle = search.lower()
            items = [i for i in items if needle in str(i.get("name", "")).lower()]
        return {"kind": kind, "options": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    def snapchat_ads_estimate_audience_size(
        ad_squad_id: str | None = None,
        targeting: dict[str, Any] | None = None,
        ad_squad_spec: dict[str, Any] | None = None,
        ad_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Estimate the reach of an existing ad squad, or of a targeting spec before you create one.

        Pass ad_squad_id, or targeting (e.g. {"geos": [{"country_code": "gb"}],
        "demographics": [{"min_age": 18, "max_age": 34}]}) with optional
        ad_squad_spec fields such as optimization_goal and placement_v2.
        Returns audience_size_minimum and audience_size_maximum.
        """
        if ad_squad_id:
            sid = check_id(ad_squad_id, "ad_squad_id")
            out = client.request("GET", f"/v1/adsquads/{sid}/audience_size_v2")
        else:
            if not targeting:
                raise ValueError("Pass ad_squad_id or targeting.")
            aid = client.resolve_ad_account(ad_account_id)
            body = {**(ad_squad_spec or {}), "targeting": targeting}
            body.setdefault("type", "SNAP_ADS")
            out = client.request(
                "POST", f"/v1/adaccounts/{aid}/audience_size_v2", json_body=body, read_only=True
            )
        return out.get("audience_size", out)

    @mcp.tool()
    def snapchat_ads_get_bid_estimate(
        ad_squad_id: str | None = None,
        optimization_goal: str | None = None,
        targeting: dict[str, Any] | None = None,
        ad_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Get Snap's suggested bid range for an ad squad, or for an optimisation goal and targeting.

        Values are micro-currency; `amounts` shows them in whole currency units.
        """
        if ad_squad_id:
            sid = check_id(ad_squad_id, "ad_squad_id")
            out = client.request("GET", f"/v1/adsquads/{sid}/bid_estimate")
        else:
            if not (optimization_goal and targeting):
                raise ValueError("Pass ad_squad_id, or optimization_goal and targeting.")
            aid = client.resolve_ad_account(ad_account_id)
            out = client.request(
                "POST",
                f"/v1/adaccounts/{aid}/bid_estimate",
                json_body={"optimization_goal": optimization_goal.upper(), "targeting": targeting},
                read_only=True,
            )
        estimate = out.get("bid_estimate", out)
        if isinstance(estimate, dict):
            amounts = {
                k.removesuffix("_micro").removeprefix("bid_estimate_"): v / 1_000_000
                for k, v in estimate.items()
                if k.startswith("bid_estimate_") and isinstance(v, int | float)
            }
            return {**estimate, "amounts": amounts}
        return out

    @mcp.tool()
    def snapchat_ads_get_bid_recommendation(
        pixel_id: str,
        optimization_goal: str,
        conversion_window: Literal["SWIPE_28DAY_VIEW_1DAY", "SWIPE_7DAY"] | None = None,
        ad_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Get Snap's recommended TARGET_COST bid and daily budget for a pixel and goal.

        optimization_goal: PIXEL_PURCHASE, PIXEL_ADD_TO_CART, PIXEL_PAGE_VIEW,
        PIXEL_SIGNUP, LANDING_PAGE_VIEW, SWIPES or STORY_OPENS. Values ending in
        _micros are micro-currency.
        """
        aid = client.resolve_ad_account(ad_account_id)
        params: dict[str, Any] = {
            "signal_type": "PIXEL",
            "signal_id": check_id(pixel_id, "pixel_id"),
            "optimization_goal": optimization_goal.upper(),
        }
        if conversion_window:
            params["conversion_window"] = conversion_window
        out = client.request("GET", f"/v1/adaccounts/{aid}/spend_guidance/", params=params)
        items = unwrap(out, "spend_guidance")
        for item in items:
            guidance = item.get("guidance")
            if isinstance(guidance, dict):
                item["amounts"] = {
                    k.removesuffix("_micros"): v / 1_000_000
                    for k, v in guidance.items()
                    if k.endswith("_micros") and isinstance(v, int | float)
                }
        return {"recommendations": items, "count": len(items)}

    @mcp.tool()
    def snapchat_ads_check_optimization_eligibility(
        pixel_id: str | None = None,
        snap_app_id: str | None = None,
        optimization_goal: str | None = None,
        conversion_window: Literal["SWIPE_28DAY_VIEW_1DAY", "SWIPE_7DAY"] | None = None,
        ad_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Check which optimisation goals and conversion windows a pixel or Snap App ID can use.

        Snap rejects ad squads whose goal or window the pixel/app isn't eligible
        for, so check before creating pixel- or app-optimised ad squads. The app
        response also says whether Unified Attribution is available.
        """
        if bool(pixel_id) == bool(snap_app_id):
            raise ValueError("Pass exactly one of pixel_id or snap_app_id.")
        params: dict[str, Any] = {}
        if optimization_goal:
            params["optimization_goal"] = optimization_goal.upper()
        if conversion_window:
            params["conversion_window"] = conversion_window
        aid = (ad_account_id or client.config.ad_account_id or "").strip()
        if aid:
            params["ad_account_id"] = check_id(aid, "ad_account_id")
        if pixel_id:
            path = f"/v1/pixels/{check_id(pixel_id, 'pixel_id')}/campaign_eligibilities"
        else:
            path = f"/v1/mobile_apps/{check_id(snap_app_id, 'snap_app_id')}/campaign_eligibilities"
        out = client.request("GET", path, params=params)
        items = unwrap(out)
        return {"eligibilities": [add_amounts(i) for i in items], "count": len(items)}
