"""Title and MCP annotations for every snapchat_ads_* tool.

`SnapchatAdsMCPServer.tool()` looks each tool up here by name, so the tool
modules stay free of metadata. Every tool must have an entry:
tests/test_mcp_client.py fails if a registered tool is missing or an entry has
no tool.

Annotation kinds (all API tools are open-world: they call the Snap API):

* READ: changes nothing in the ad account (includes read-only POSTs such as
  fetch-by-IDs, estimates and product searches).
* REPORT: starts an async report. Changes nothing in the account, but each
  call starts a new report job, so it isn't idempotent.
* WRITE: creates something; repeating it creates it again.
* UPSERT: an update or status change; repeating it changes nothing more.
* DESTRUCTIVE: deletes; Snap deletes are permanent.
* DESTRUCTIVE_ONCE: the raw request tool, which may do anything.
* LOCAL_*: touches only this server (audit log, session settings).
"""

from __future__ import annotations

from typing import NamedTuple

from mcp.types import ToolAnnotations


def _ann(*, read_only: bool, destructive: bool, idempotent: bool, open_world: bool = True):
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


READ = _ann(read_only=True, destructive=False, idempotent=True)
REPORT = _ann(read_only=True, destructive=False, idempotent=False)
WRITE = _ann(read_only=False, destructive=False, idempotent=False)
UPSERT = _ann(read_only=False, destructive=False, idempotent=True)
DESTRUCTIVE = _ann(read_only=False, destructive=True, idempotent=True)
DESTRUCTIVE_ONCE = _ann(read_only=False, destructive=True, idempotent=False)
LOCAL_READ = _ann(read_only=True, destructive=False, idempotent=True, open_world=False)
LOCAL_SETTING = _ann(read_only=False, destructive=False, idempotent=True, open_world=False)


class ToolSpec(NamedTuple):
    title: str
    annotations: ToolAnnotations


# Registered regardless of SNAPCHAT_ADS_TOOL_GROUPS and SNAPCHAT_ADS_READ_ONLY.
ALWAYS_REGISTERED = frozenset(
    {
        "snapchat_ads_describe_server",
        "snapchat_ads_health_check",
        "snapchat_ads_audit_lookup",
        "snapchat_ads_audit_tail",
        "snapchat_ads_set_dry_run",
    }
)

_CATALOG: dict[str, tuple[str, ToolAnnotations]] = {
    # server (meta)
    "snapchat_ads_describe_server": ("Describe the server configuration", LOCAL_READ),
    "snapchat_ads_health_check": ("Check the token and list organisations", READ),
    "snapchat_ads_audit_lookup": ("Look up an audit log entry", LOCAL_READ),
    "snapchat_ads_audit_tail": ("Show recent audit log entries", LOCAL_READ),
    "snapchat_ads_set_dry_run": ("Turn dry-run mode on or off", LOCAL_SETTING),
    # accounts
    "snapchat_ads_get_me": ("Show the signed-in Snapchat user", READ),
    "snapchat_ads_list_organizations": ("List organisations and ad accounts", READ),
    "snapchat_ads_list_ad_accounts": ("List ad accounts in an organisation", READ),
    "snapchat_ads_get_ad_account": ("Get an ad account", READ),
    "snapchat_ads_list_funding_sources": ("List funding sources", READ),
    # campaigns
    "snapchat_ads_list_campaigns": ("List campaigns", READ),
    "snapchat_ads_create_campaigns": ("Create campaigns", WRITE),
    "snapchat_ads_update_campaigns": ("Update campaigns", UPSERT),
    "snapchat_ads_delete_campaigns": ("Delete campaigns", DESTRUCTIVE),
    # ad_squads
    "snapchat_ads_list_ad_squads": ("List ad squads", READ),
    "snapchat_ads_create_ad_squads": ("Create ad squads", WRITE),
    "snapchat_ads_update_ad_squads": ("Update ad squads", UPSERT),
    "snapchat_ads_delete_ad_squads": ("Delete ad squads", DESTRUCTIVE),
    # ads
    "snapchat_ads_list_ads": ("List ads", READ),
    "snapchat_ads_create_ads": ("Create ads", WRITE),
    "snapchat_ads_update_ads": ("Update ads", UPSERT),
    "snapchat_ads_delete_ads": ("Delete ads", DESTRUCTIVE),
    # bulk
    "snapchat_ads_set_status": ("Pause or activate many entities", UPSERT),
    "snapchat_ads_set_budgets": ("Set campaign or ad squad budgets", UPSERT),
    "snapchat_ads_set_bids": ("Set ad squad bids", UPSERT),
    # creatives
    "snapchat_ads_list_creatives": ("List creatives", READ),
    "snapchat_ads_create_creatives": ("Create creatives", WRITE),
    "snapchat_ads_update_creatives": ("Update creatives", UPSERT),
    "snapchat_ads_get_creative_preview": ("Preview a creative", READ),
    "snapchat_ads_list_media": ("List uploaded media", READ),
    "snapchat_ads_upload_media": ("Upload an image, video or playable", WRITE),
    # audiences
    "snapchat_ads_list_segments": ("List audience segments", READ),
    "snapchat_ads_create_segments": ("Create audience segments", WRITE),
    "snapchat_ads_update_segments": ("Update audience segments", UPSERT),
    "snapchat_ads_delete_segments": ("Delete audience segments", DESTRUCTIVE),
    # targeting
    "snapchat_ads_get_targeting_options": ("Look up targeting options", READ),
    "snapchat_ads_estimate_audience_size": ("Estimate audience size", READ),
    "snapchat_ads_get_bid_estimate": ("Get a bid estimate", READ),
    "snapchat_ads_get_bid_recommendation": ("Get a recommended bid and budget", READ),
    "snapchat_ads_check_optimization_eligibility": (
        "Check optimisation goal eligibility",
        READ,
    ),
    # pixels
    "snapchat_ads_list_pixels": ("List Snap Pixels", READ),
    "snapchat_ads_get_pixel_domains": ("List domains firing a pixel", READ),
    "snapchat_ads_get_pixel_stats": ("Get pixel event stats", READ),
    "snapchat_ads_list_snap_apps": ("List Snap App IDs", READ),
    # catalogs
    "snapchat_ads_list_catalogs": ("List product catalogs", READ),
    "snapchat_ads_list_product_feeds": ("List product feeds", READ),
    "snapchat_ads_list_feed_uploads": ("List product feed uploads", READ),
    "snapchat_ads_list_product_sets": ("List product sets", READ),
    "snapchat_ads_search_products": ("Search catalog products", READ),
    "snapchat_ads_create_product_sets": ("Create product sets", WRITE),
    # reporting
    "snapchat_ads_get_stats": ("Get performance stats", READ),
    "snapchat_ads_create_async_report": ("Start an async report", REPORT),
    "snapchat_ads_get_async_report": ("Check an async report", READ),
    "snapchat_ads_download_async_report": ("Download an async report", READ),
    "snapchat_ads_run_report": ("Run a report and return its rows", REPORT),
    "snapchat_ads_get_change_log": ("Show an entity's change history", READ),
    # request
    "snapchat_ads_read_request": ("Read from any Snap Marketing API endpoint", READ),
    "snapchat_ads_request": ("Call any Snap Marketing API endpoint", DESTRUCTIVE_ONCE),
}

TOOL_SPECS: dict[str, ToolSpec] = {
    name: ToolSpec(title, annotations) for name, (title, annotations) in _CATALOG.items()
}
