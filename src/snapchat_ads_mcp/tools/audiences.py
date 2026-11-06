"""Audience segments: customer lists, pixel/app/engagement audiences and lookalikes.

This server reads segments and creates, renames or deletes them. It does not
upload customer identifiers (hashed emails, phone numbers or device IDs): that
data is governed by Snap's Audience Match terms and shouldn't pass through an
AI client. Use Snap Ads Manager or your own pipeline for that step.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from .. import safety
from ..client import SnapchatAdsClient, check_id, unwrap
from ._common import check_items, ids_to_strings
from ._progress import report, run_blocking

SEGMENT_BATCH = 15
CREATE_SOURCES = {"FIRST_PARTY", "LOOKALIKE", "PIXEL", "MOBILE"}
EDITABLE = {"name", "description", "retention_in_days"}


def register(mcp, client: SnapchatAdsClient) -> None:
    def _get(segment_id: str) -> dict[str, Any] | None:
        found = unwrap(client.request("GET", f"/v1/segments/{segment_id}"), "segments")
        return found[0] if found else None

    @mcp.tool()
    async def snapchat_ads_list_segments(
        ad_account_id: str | None = None,
        ids: list[str] | None = None,
        name_contains: str | None = None,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List audience segments in an ad account, or fetch some by ids.

        Shows source_type (FIRST_PARTY customer list, PIXEL, MOBILE, ENGAGEMENT,
        LOOKALIKE), approximate_number_users, upload_status and targetable_status
        (READY, TOO_FEW_USERS, NOT_READY). Use segment IDs in an ad squad's
        targeting.segments.
        """
        id_list = ids_to_strings(ids, "segment id")
        if id_list:
            items: list[dict[str, Any]] = []
            for sid in id_list[:100]:
                seg = await run_blocking(_get, sid)
                if seg:
                    items.append(seg)
            truncated = len(id_list) > 100
        else:
            aid = client.resolve_ad_account(ad_account_id)
            items, truncated = await run_blocking(
                client.paginate,
                f"/v1/adaccounts/{aid}/segments",
                None,
                key="segments",
                max_results=max_results,
            )
        if name_contains:
            needle = name_contains.lower()
            items = [s for s in items if needle in str(s.get("name", "")).lower()]
        return {"segments": items, "count": len(items), "truncated": truncated}

    @mcp.tool()
    def snapchat_ads_create_segments(
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create audience segments (up to 15 per call). Changes the live account.

        items, e.g. an empty customer list to fill in Ads Manager:
        {"name": "Past buyers", "source_type": "FIRST_PARTY", "retention_in_days": 180},
        or a lookalike of an existing customer list:
        {"name": "Lookalike UK", "source_type": "LOOKALIKE", "retention_in_days": 180,
        "creation_spec": {"seed_segment_id": "...", "countries": ["GB"], "type": "BALANCE"}}.
        retention_in_days 9999 means lifetime (lookalikes max 180). This tool never
        uploads customer identifiers.
        """
        check_items(items, "items", max_items=SEGMENT_BATCH)
        aid = client.resolve_ad_account(ad_account_id)
        for i, item in enumerate(items):
            source = str(item.get("source_type", "")).upper()
            if source not in CREATE_SOURCES:
                raise ValueError(
                    f"items[{i}].source_type must be one of {', '.join(sorted(CREATE_SOURCES))}."
                )
            if "users" in item or "identifiers" in item:
                raise ValueError("This server doesn't upload customer identifiers.")
        prepared = [{**item, "ad_account_id": aid} for item in items]
        decision = safety.assess(client.config, count=len(prepared))
        refused = safety.refusal(client.config, decision, confirm, preview={"segments": prepared})
        if refused:
            return refused
        out = client.request(
            "POST",
            f"/v1/adaccounts/{aid}/segments",
            json_body={"segments": prepared},
            op="create_segments",
            ad_account_id=aid,
        )
        return safety.annotate(
            {
                "segments": unwrap(out, "segments"),
                "errors": out.get("sub_request_errors") or [],
                "audit_id": out.get("audit_id"),
                **(
                    {"_dry_run": True, "would_send": {"segments": prepared}}
                    if out.get("_dry_run")
                    else {}
                ),
            },
            decision,
        )

    @mcp.tool()
    async def snapchat_ads_update_segments(
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Rename segments or change their description or retention_in_days.

        items: [{"id": "...", "name": "New name"}]. Snap's segment update takes the
        whole object, so each segment is read first, merged with your changes and
        sent back (the read is kept in the audit log).
        """
        check_items(items, "items", max_items=SEGMENT_BATCH)
        aid = client.resolve_ad_account(ad_account_id)
        merged: list[dict[str, Any]] = []
        befores: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            sid = check_id(item.get("id"), "segment id")
            unknown = set(item) - EDITABLE - {"id"}
            if unknown:
                raise ValueError(
                    f"items[{i}] can only change {', '.join(sorted(EDITABLE))}; got {sorted(unknown)}."
                )
            current = await run_blocking(_get, sid)
            if current is None:
                raise ValueError(f"Segment {sid} not found.")
            befores.append(current)
            body = {
                "id": sid,
                "name": current.get("name"),
                "ad_account_id": aid,
                "description": current.get("description"),
                "retention_in_days": current.get("retention_in_days"),
            }
            if current.get("organization_id"):
                body["organization_id"] = current["organization_id"]
            body.update({k: v for k, v in item.items() if k != "id"})
            merged.append({k: v for k, v in body.items() if v is not None})
            await report(ctx, i + 1, len(items) + 1, f"Read segment {sid}")
        decision = safety.assess(client.config, count=len(merged))
        refused = safety.refusal(client.config, decision, confirm, preview={"segments": merged})
        if refused:
            return refused
        out = await run_blocking(
            client.request,
            "PUT",
            f"/v1/adaccounts/{aid}/segments",
            json_body={"segments": merged},
            op="update_segments",
            before=befores,
            ad_account_id=aid,
        )
        await report(ctx, len(items) + 1, len(items) + 1, "Sent update")
        return safety.annotate(
            {
                "segments": unwrap(out, "segments"),
                "errors": out.get("sub_request_errors") or [],
                "audit_id": out.get("audit_id"),
                **({"_dry_run": True} if out.get("_dry_run") else {}),
            },
            decision,
        )

    @mcp.tool()
    async def snapchat_ads_delete_segments(
        ids: list[str],
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Delete audience segments by ID. Deleted segments can't be recovered, so this needs
        confirm='DELETE' after the user agrees. Ad squads targeting them lose that targeting."""
        id_list = ids_to_strings(ids, "segment id")
        if not id_list:
            raise ValueError("Pass at least one ID.")
        if len(id_list) > 100:
            raise ValueError("At most 100 IDs per call.")
        decision = safety.assess(client.config, count=len(id_list), destructive=safety.DELETE)
        refused = safety.refusal(client.config, decision, confirm, preview={"ids": id_list})
        if refused:
            return refused
        deleted: list[Any] = []
        failed: list[dict[str, Any]] = []
        for done, sid in enumerate(id_list, start=1):
            try:
                before = await run_blocking(client.snapshot, _get, sid)
                out = await run_blocking(
                    client.request,
                    "DELETE",
                    f"/v1/segments/{sid}",
                    op="delete_segments",
                    before=before,
                )
                deleted.append({"id": sid, "audit_id": out.get("audit_id")})
                await report(ctx, done, len(id_list), f"Deleted {sid}")
            except Exception as e:
                failed.append({"id": sid, "reason": str(e)[:500]})
                await report(ctx, done, len(id_list), f"Failed {sid}")
        return safety.annotate(
            {
                "deleted_count": len(deleted),
                "failed_count": len(failed),
                "deleted": deleted,
                "failed": failed[:50],
            },
            decision,
        )
