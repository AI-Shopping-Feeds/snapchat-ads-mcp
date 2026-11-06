"""Status, budget and bid changes across many campaigns, ad squads or ads.

Amounts here are in whole units of the ad account's currency (12.50), and are
converted to Snap's micro-currency (12500000) before sending.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context

from .. import safety
from ..client import SnapchatAdsClient, check_id
from ._common import STATUSES, EntitySpec, check_items, fetch_by_ids, ids_to_strings, patch_entities
from ._progress import run_blocking
from ._specs import AD, AD_SQUAD, CAMPAIGN

_SPECS: dict[str, EntitySpec] = {"campaign": CAMPAIGN, "ad_squad": AD_SQUAD, "ad": AD}
_BUDGET_FIELDS = {
    "campaign": {
        "daily_budget": "daily_budget_micro",
        "lifetime_budget": "lifetime_spend_cap_micro",
    },
    "ad_squad": {"daily_budget": "daily_budget_micro", "lifetime_budget": "lifetime_budget_micro"},
}


def _micro_or_none(value: Any, what: str) -> int | None:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{what} must be a number in the account currency, got {value!r}.") from e
    if amount < 0:
        raise ValueError(f"{what} can't be negative.")
    return safety.to_micro(amount)


def register(mcp, client: SnapchatAdsClient) -> None:
    @mcp.tool()
    async def snapchat_ads_set_status(
        entity_type: Literal["campaign", "ad_squad", "ad"],
        ids: list[str],
        status: Literal["ACTIVE", "PAUSED"],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Pause or activate many campaigns, ad squads or ads (one PATCH each, with progress).

        ACTIVE starts spending again once parents are active too. More than
        SNAPCHAT_ADS_BULK_THRESHOLD IDs needs confirm='APPLY'.
        """
        spec = _SPECS[entity_type]
        status = status.upper()  # type: ignore[assignment]
        if status not in STATUSES:
            raise ValueError("status must be ACTIVE or PAUSED.")
        id_list = ids_to_strings(ids, f"{entity_type} id")
        if not id_list:
            raise ValueError("Pass at least one ID.")
        aid = client.resolve_ad_account(ad_account_id)
        items = [{"id": i, "status": status} for i in id_list]
        return await patch_entities(
            client, spec, aid, items, confirm=confirm, op=f"set_status_{spec.noun}", ctx=ctx
        )

    @mcp.tool()
    async def snapchat_ads_set_budgets(
        entity_type: Literal["campaign", "ad_squad"],
        changes: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Set campaign or ad squad budgets in whole currency units (not micro).

        changes: [{"id": "...", "daily_budget": 50}] or {"id", "lifetime_budget": 1000},
        or {"id", "change_pct": 10} to move the budget the entity already uses
        (daily if set, else lifetime) by a percentage. For campaigns
        lifetime_budget is the lifetime spend cap; null removes it. Current values
        are read first. Rises above SNAPCHAT_ADS_MAX_INCREASE_PCT, removing a
        cap, values over SNAPCHAT_ADS_MAX_BUDGET and big batches need
        confirm='APPLY'. Snap's minimums: campaign daily 20.00, ad squad daily 5.00.
        """
        spec = _SPECS[entity_type]
        fields = _BUDGET_FIELDS[entity_type]
        check_items(changes, "changes")
        aid = client.resolve_ad_account(ad_account_id)
        ids = [check_id(c.get("id"), f"{entity_type} id") for c in changes]
        current = await run_blocking(client.snapshot, fetch_by_ids, client, spec, aid, ids)
        by_id = {str(e.get("id")): e for e in (current or [])}
        items: list[dict[str, Any]] = []
        for eid, change in zip(ids, changes, strict=True):
            item: dict[str, Any] = {"id": eid}
            for name, api_field in fields.items():
                if name in change:
                    item[api_field] = _micro_or_none(change[name], name)
            if "change_pct" in change:
                entity = by_id.get(eid)
                if entity is None:
                    raise ValueError(f"Couldn't read the current budget of {eid}; pass an amount.")
                in_use = next((f for f in fields.values() if entity.get(f) is not None), None)
                if in_use is None:
                    raise ValueError(f"{eid} has no budget set; pass an amount instead.")
                pct = float(change["change_pct"])
                item[in_use] = round(int(entity[in_use]) * (1 + pct / 100))
            if len(item) == 1:
                raise ValueError(
                    f"Change for {eid} needs daily_budget, lifetime_budget or change_pct."
                )
            items.append(item)
        return await patch_entities(
            client,
            spec,
            aid,
            items,
            confirm=confirm,
            op=f"set_budgets_{spec.noun}",
            ctx=ctx,
            current=current,
        )

    @mcp.tool()
    async def snapchat_ads_set_bids(
        changes: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Set ad squad bids in whole currency units (not micro), or move them by a percentage.

        changes: [{"id": "<ad squad id>", "bid": 2.5}] or {"id", "change_pct": -10}.
        bid_micro is the max bid (LOWEST_COST_WITH_MAX_BID) or target cost
        (TARGET_COST); ad squads on AUTO_BID ignore it. Current bids are read
        first. Rises above SNAPCHAT_ADS_MAX_INCREASE_PCT, values over
        SNAPCHAT_ADS_MAX_BID and big batches need confirm='APPLY'.
        """
        check_items(changes, "changes")
        aid = client.resolve_ad_account(ad_account_id)
        ids = [check_id(c.get("id"), "ad squad id") for c in changes]
        current = await run_blocking(client.snapshot, fetch_by_ids, client, AD_SQUAD, aid, ids)
        by_id = {str(e.get("id")): e for e in (current or [])}
        items: list[dict[str, Any]] = []
        notes: list[str] = []
        for eid, change in zip(ids, changes, strict=True):
            entity = by_id.get(eid)
            if "bid" in change:
                new = _micro_or_none(change["bid"], "bid")
            elif "change_pct" in change:
                if not entity or entity.get("bid_micro") is None:
                    raise ValueError(f"Couldn't read the current bid of {eid}; pass bid instead.")
                new = round(int(entity["bid_micro"]) * (1 + float(change["change_pct"]) / 100))
            else:
                raise ValueError(f"Change for {eid} needs bid or change_pct.")
            if new is None:
                raise ValueError("bid can't be null.")
            if entity and str(entity.get("bid_strategy", "")).upper() == "AUTO_BID":
                notes.append(f"{eid} uses AUTO_BID, so bid_micro has no effect on delivery.")
            items.append({"id": eid, "bid_micro": new})
        out = await patch_entities(
            client,
            AD_SQUAD,
            aid,
            items,
            confirm=confirm,
            op="set_bids_ad_squads",
            ctx=ctx,
            current=current,
        )
        if notes and isinstance(out, dict):
            out = {**out, "notes": notes}
        return out
