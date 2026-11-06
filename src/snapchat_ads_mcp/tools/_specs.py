"""Endpoint specs for the entities that share the list/create/PATCH/delete pattern."""

from __future__ import annotations

from .. import safety
from ._common import EntitySpec

CAMPAIGN = EntitySpec(
    noun="campaigns",
    label="campaigns",
    collection="campaigns",
    singular="campaign",
    parent_field="ad_account_id",
    create_path=lambda parent: f"/v1/adaccounts/{parent}/campaigns",
    patch_path=lambda e: f"/v1/adaccounts/{e['ad_account_id']}/campaigns/{e['id']}",
    patch_parents=("ad_account_id",),
    create_batch=30,
    money=safety.CAMPAIGN_MONEY,
    create_example=(
        'e.g. {"name": "Spring sale", "start_time": "2026-12-01T00:00:00Z", '
        '"objective_v2_properties": {"objective_v2_type": "SALES"}, '
        '"daily_budget_micro": 50000000}. start_time is required. Use '
        "objective_v2_properties (AWARENESS_AND_ENGAGEMENT, SALES, TRAFFIC, APP_PROMOTION, "
        "LEADS), not the phased-out objective field."
    ),
    update_example='[{"id": "...", "name": "New name", "daily_budget_micro": 60000000}]',
)

AD_SQUAD = EntitySpec(
    noun="ad_squads",
    label="ad squads",
    collection="adsquads",
    singular="adsquad",
    parent_field="campaign_id",
    create_path=lambda parent: f"/v1/campaigns/{parent}/adsquads",
    patch_path=lambda e: f"/v1/campaigns/{e['campaign_id']}/adsquads/{e['id']}",
    patch_parents=("campaign_id",),
    create_batch=30,
    money=safety.AD_SQUAD_MONEY,
    create_example=(
        'e.g. {"name": "UK 18-34", "type": "SNAP_ADS", "billing_event": "IMPRESSION", '
        '"optimization_goal": "PIXEL_PURCHASE", "bid_strategy": "AUTO_BID", '
        '"daily_budget_micro": 20000000, "placement_v2": {"config": "AUTOMATIC"}, '
        '"targeting": {"geos": [{"country_code": "gb"}]}, "pixel_id": "..."}. '
        "Check goals with snapchat_ads_check_optimization_eligibility first."
    ),
    extra_create_notes=(
        " optimization_goal and billing_event can't be changed after creation. Responses may "
        "include _warnings (Snap's sub_request_warnings), e.g. dates outside the campaign."
    ),
    update_example='[{"id": "...", "bid_micro": 1500000}, {"id": "...", "status": "PAUSED"}]',
)

AD = EntitySpec(
    noun="ads",
    label="ads",
    collection="ads",
    singular="ad",
    parent_field="ad_squad_id",
    create_path=lambda parent: f"/v1/adsquads/{parent}/ads",
    patch_path=lambda e: f"/v1/adsquads/{e['ad_squad_id']}/ads/{e['id']}",
    patch_parents=("ad_squad_id",),
    create_batch=30,
    create_example=(
        'e.g. {"name": "Trainers - video 1", "creative_id": "...", "type": "REMOTE_WEBPAGE"}. '
        "The ad type must match the creative type (WEB_VIEW creative -> REMOTE_WEBPAGE ad, "
        "SNAP_AD -> SNAP_AD, APP_INSTALL -> APP_INSTALL, COMPOSITE -> STORY). New ads go "
        "into Snap's review before they serve."
    ),
    update_example='[{"id": "...", "name": "New name"}, {"id": "...", "status": "ACTIVE"}]',
)

CREATIVE = EntitySpec(
    noun="creatives",
    label="creatives",
    collection="creatives",
    singular="creative",
    parent_field="ad_account_id",
    create_path=lambda parent: f"/v1/adaccounts/{parent}/creatives",
    patch_path=lambda e: f"/v1/adaccounts/{e['ad_account_id']}/creatives/{e['id']}",
    patch_parents=("ad_account_id",),
    delete=False,
    default_paused=False,
    create_batch=10,
    create_example=(
        'e.g. {"name": "Trainers 9:16", "type": "WEB_VIEW", "headline": "New season", '
        '"top_snap_media_id": "...", "call_to_action": "SHOP_NOW", '
        '"profile_properties": {"profile_id": "..."}, '
        '"web_view_properties": {"url": "https://example.com/trainers"}}. '
        "Upload the media first with snapchat_ads_upload_media. headline max 34 characters."
    ),
    update_example='[{"id": "...", "headline": "New headline"}]',
)
