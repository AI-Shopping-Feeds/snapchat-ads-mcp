"""Shared building blocks for the entity tool modules.

Campaigns, ad squads, ads and creatives follow one pattern in the Snap
Marketing API v1:

* list: GET under a parent (ad account, campaign or ad squad), cursor-paged;
  or POST /v1/adaccounts/{id}/get_<collection>_by_ids for up to 2,000 IDs;
* create: POST under the parent, a few entities per request;
* update: PATCH one entity with a JSON Patch document (RFC 6902). This server
  never uses PUT for these entities, because PUT resets omitted fields to
  their defaults;
* delete: DELETE /v1/<collection>/{id}, which is permanent.

`create_entities()` and `register_update_delete()` give every entity the same
guards, before-snapshots and audit trail; the list tools live in each module.
`patch_entities()` is also used by the bulk status, budget and bid tools.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from mcp.server.mcpserver import Context

from .. import safety
from ..client import SnapchatAdsClient, check_id, unwrap
from ._progress import report, run_blocking

MAX_ITEMS = 200
# Fields that can't be changed through PATCH.
READ_ONLY_FIELDS = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "delivery_status",
        "effective_status",
        "review_status",
        "review_status_reasons",
        "deleted",
        "skadnetwork_properties",
        "separated_types",
        "auto_bid_max_bid_micro",
        "amounts",
        "_warnings",
    }
)
STATUSES = ("ACTIVE", "PAUSED")


def ids_to_strings(ids: Sequence[Any] | None, what: str = "id") -> list[str]:
    return [check_id(i, what) for i in (ids or []) if str(i).strip()]


def check_items(items: list[dict[str, Any]], what: str, max_items: int = MAX_ITEMS) -> None:
    if not items:
        raise ValueError(f"Pass at least one {what}.")
    if len(items) > max_items:
        raise ValueError(f"At most {max_items} {what} per call; got {len(items)}.")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{what}[{i}] must be an object.")


def add_amounts(entity: Any) -> Any:
    """Return the entity with an `amounts` map: each *_micro field in whole currency units.

    Snap money fields are micro-currency (1.00 = 1,000,000). The raw fields stay
    as they are; `amounts` is only a reading aid, e.g. {"daily_budget": 50.0}.
    """
    if not isinstance(entity, dict):
        return entity
    amounts: dict[str, float] = {}
    for key, value in entity.items():
        if key.endswith("_micro"):
            converted = safety.from_micro(value)
            if converted is not None:
                amounts[key.removesuffix("_micro")] = converted
        elif isinstance(value, dict):
            for sub, sub_value in value.items():
                if sub.endswith("_micro"):
                    converted = safety.from_micro(sub_value)
                    if converted is not None:
                        amounts[f"{key}.{sub.removesuffix('_micro')}"] = converted
    return {**entity, "amounts": amounts} if amounts else entity


def _pointer(name: str) -> str:
    return "/" + name.replace("~", "~0").replace("/", "~1")


def build_patch(changes: dict[str, Any], current: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Turn {"field": value} into JSON Patch operations for Snap's PATCH endpoints.

    A field set to None is removed. Fields the entity already has are replaced;
    missing or null ones are added. Without a before-snapshot every change is a
    'replace'. Nested objects and arrays are replaced whole (Snap doesn't accept
    array-index paths).
    """
    ops: list[dict[str, Any]] = []
    for name, value in changes.items():
        if name in READ_ONLY_FIELDS:
            raise ValueError(f"{name} can't be changed.")
        has_value = current is not None and current.get(name) is not None
        if value is None:
            if current is None or has_value:
                ops.append({"op": "remove", "path": _pointer(name)})
            continue
        op = "replace" if (current is None or has_value) else "add"
        ops.append({"op": op, "path": _pointer(name), "value": value})
    return ops


@dataclass(frozen=True)
class EntitySpec:
    """One Snap entity with list/create/update/delete endpoints."""

    noun: str  # plural used in tool names, e.g. "ad_squads"
    label: str  # human label, e.g. "ad squads"
    collection: str  # API collection key, e.g. "adsquads"
    singular: str  # API singular key, e.g. "adsquad"
    parent_field: str  # field naming the parent on create, e.g. "campaign_id"
    create_path: Callable[[str], str]
    patch_path: Callable[[dict[str, Any]], str]
    delete: bool = True
    create_batch: int = 30
    money: tuple[tuple[str, tuple[str, ...]], ...] = ()
    default_paused: bool = True
    create_example: str = ""
    update_example: str = ""
    extra_create_notes: str = ""
    patch_parents: tuple[str, ...] = field(default_factory=tuple)


def fetch_by_ids(
    client: SnapchatAdsClient, spec: EntitySpec, ad_account_id: str, ids: list[str]
) -> list[dict[str, Any]]:
    return client.get_by_ids(ad_account_id, spec.collection, ids)


def filter_entities(
    items: list[dict[str, Any]], statuses: list[str] | None, name_contains: str | None
) -> list[dict[str, Any]]:
    out = items
    if statuses:
        wanted = {s.upper() for s in statuses}
        out = [e for e in out if str(e.get("status", "")).upper() in wanted]
    if name_contains:
        needle = name_contains.lower()
        out = [e for e in out if needle in str(e.get("name", "")).lower()]
    return out


async def patch_entities(
    client: SnapchatAdsClient,
    spec: EntitySpec,
    ad_account_id: str,
    items: list[dict[str, Any]],
    *,
    confirm: str,
    op: str,
    ctx: Context | None = None,
    current: list[dict[str, Any]] | None = None,
    extra_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """PATCH each item ({"id": ..., field: value}) with guards, snapshot, audit and progress."""
    check_items(items, "items")
    ids = [check_id(it.get("id"), f"{spec.label} id") for it in items]
    if current is None:
        current = await run_blocking(
            client.snapshot, fetch_by_ids, client, spec, ad_account_id, ids
        )
    by_id = {str(e.get("id")): e for e in (current or [])}
    decision = safety.assess(
        client.config,
        count=len(items),
        changes=safety.money_changes(items, list(by_id.values()) or None, fields=spec.money),
    )
    if extra_reasons:
        decision.reasons.extend(extra_reasons)
        decision.required = decision.required or safety.APPLY
    plans: list[tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]] = []
    for eid, item in zip(ids, items, strict=True):
        before = by_id.get(eid)
        changes = {k: v for k, v in item.items() if k != "id" and k not in spec.patch_parents}
        if not changes:
            raise ValueError(f"Item {eid} has no fields to change.")
        ops = build_patch(changes, before)
        context = {**(before or {}), **{k: item[k] for k in spec.patch_parents if k in item}}
        context["id"] = eid
        missing = [p for p in spec.patch_parents if not context.get(p)]
        if missing:
            raise ValueError(
                f"Couldn't read {spec.label} {eid} to find its {', '.join(missing)}; "
                f"pass {', '.join(missing)} in the item."
            )
        plans.append((eid, spec.patch_path(context), ops, before))
    preview = [{"id": eid, "path": path, "patch": ops} for eid, path, ops, _ in plans]
    refused = safety.refusal(client.config, decision, confirm, preview=preview)
    if refused:
        return refused

    results: list[Any] = []
    failed: list[dict[str, Any]] = []
    total = len(plans)
    for done, (eid, path, ops, before) in enumerate(plans, start=1):
        try:
            out = await run_blocking(
                client.request,
                "PATCH",
                path,
                json_body=ops,
                content_type="application/json-patch+json",
                op=op,
                before=before,
                ad_account_id=ad_account_id,
            )
            if out.get("sub_request_errors"):
                failed.append({"id": eid, "reason": out["sub_request_errors"]})
            else:
                updated = unwrap(out, spec.collection)
                results.append(
                    {
                        "id": eid,
                        "audit_id": out.get("audit_id"),
                        "dry_run": bool(out.get("_dry_run")),
                        "entity": add_amounts(updated[0]) if updated else None,
                        "patch": ops,
                    }
                )
            await report(ctx, done, total, f"Updated {eid} ({done} of {total})")
        except Exception as e:
            failed.append({"id": eid, "reason": str(e)[:500]})
            await report(ctx, done, total, f"Failed {eid} ({done} of {total})")
    return safety.annotate(
        {
            "updated_count": len(results),
            "failed_count": len(failed),
            "results": results,
            "failed": failed[:50],
        },
        decision,
    )


async def create_entities(
    client: SnapchatAdsClient,
    spec: EntitySpec,
    parent: str,
    items: list[dict[str, Any]],
    *,
    confirm: str,
    ad_account_id: str | None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """POST new entities under one parent in batches, with guards and audit."""
    check_items(items, "items")
    prepared: list[dict[str, Any]] = []
    for item in items:
        body = {**item, spec.parent_field: parent}
        if spec.default_paused and "status" not in body:
            body["status"] = "PAUSED"
        prepared.append(body)
    decision = safety.assess(
        client.config,
        count=len(prepared),
        changes=safety.new_values(prepared, spec.money),
        creating=True,
    )
    refused = safety.refusal(client.config, decision, confirm, preview={spec.collection: prepared})
    if refused:
        return refused
    created: list[Any] = []
    errors: list[Any] = []
    audit_ids: list[str] = []
    dry_run = False
    batches = [
        prepared[i : i + spec.create_batch] for i in range(0, len(prepared), spec.create_batch)
    ]
    for done, batch in enumerate(batches, start=1):
        out = await run_blocking(
            client.request,
            "POST",
            spec.create_path(parent),
            json_body={spec.collection: batch},
            op=f"create_{spec.noun}",
            ad_account_id=ad_account_id,
        )
        dry_run = dry_run or bool(out.get("_dry_run"))
        if out.get("audit_id"):
            audit_ids.append(out["audit_id"])
        created.extend(add_amounts(e) for e in unwrap(out, spec.collection))
        errors.extend(out.get("sub_request_errors") or [])
        await report(ctx, done, len(batches), f"Sent batch {done} of {len(batches)}")
    result: dict[str, Any] = {
        "created_count": len(created),
        spec.collection: created,
        "errors": errors,
        "audit_ids": audit_ids,
    }
    if dry_run:
        result["_dry_run"] = True
        result["would_send"] = {spec.collection: prepared}
    return safety.annotate(result, decision)


def create_description(spec: EntitySpec, parent_help: str) -> str:
    paused = (
        " New entities are created PAUSED unless an item sets status."
        if spec.default_paused
        else ""
    )
    return (
        f"Create {spec.label} under one {parent_help} (up to {MAX_ITEMS} per call, sent "
        f"{spec.create_batch} per request). Changes the live account.{paused}\n\n"
        f"items: one object per entity in Snap's {spec.singular} format; {spec.parent_field} "
        "is filled in for you. Money fields are micro-currency (1.00 = 1000000). "
        f"{spec.create_example}{spec.extra_create_notes}\n"
        "Large batches and values over SNAPCHAT_ADS_MAX_BUDGET / SNAPCHAT_ADS_MAX_BID need "
        "confirm='APPLY'. Rehearse with dry-run first."
    )


def register_update_delete(mcp, client: SnapchatAdsClient, spec: EntitySpec) -> None:
    """Register update and (where the API allows) delete tools for `spec`."""
    base = f"snapchat_ads_{{}}_{spec.noun}"

    @mcp.tool(
        name=base.format("update"),
        description=(
            f"Update {spec.label} (up to {MAX_ITEMS} per call). Changes the live account.\n\n"
            "items: objects with id plus only the fields to change, e.g. "
            f"{spec.update_example}. Set a field to null to remove it. Each item is sent "
            "as a JSON Patch (PATCH), so fields you don't name stay as they are; nested "
            "objects such as targeting are replaced whole. Money fields are micro-currency.\n"
            "Current values are read first and kept in the audit log. Bid or budget rises "
            "above SNAPCHAT_ADS_MAX_INCREASE_PCT, removing a spend cap, and large batches need "
            "confirm='APPLY'."
        ),
    )
    async def update_tool(
        items: list[dict[str, Any]],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        aid = client.resolve_ad_account(ad_account_id)
        return await patch_entities(
            client, spec, aid, items, confirm=confirm, op=f"update_{spec.noun}", ctx=ctx
        )

    if not spec.delete:
        return

    @mcp.tool(
        name=base.format("delete"),
        description=(
            f"Delete {spec.label} by ID, one request per ID, with progress. Snap deletes are "
            "permanent and can't be undone, so this needs confirm='DELETE' after the user "
            "agrees. To stop delivery temporarily, set status PAUSED instead "
            "(snapchat_ads_set_status)."
        ),
    )
    async def delete_tool(
        ids: list[str],
        ad_account_id: str | None = None,
        confirm: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        id_list = ids_to_strings(ids, f"{spec.label} id")
        if not id_list:
            raise ValueError("Pass at least one ID.")
        if len(id_list) > MAX_ITEMS:
            raise ValueError(f"At most {MAX_ITEMS} IDs per call.")
        decision = safety.assess(client.config, count=len(id_list), destructive=safety.DELETE)
        refused = safety.refusal(client.config, decision, confirm, preview={"ids": id_list})
        if refused:
            return refused
        aid = (ad_account_id or client.config.ad_account_id or "").strip() or None
        before = (
            await run_blocking(client.snapshot, fetch_by_ids, client, spec, aid, id_list)
            if aid
            else None
        )
        by_id = {str(e.get("id")): e for e in (before or [])}
        deleted: list[Any] = []
        failed: list[dict[str, Any]] = []
        total = len(id_list)
        for done, eid in enumerate(id_list, start=1):
            try:
                out = await run_blocking(
                    client.request,
                    "DELETE",
                    f"/v1/{spec.collection}/{eid}",
                    op=f"delete_{spec.noun}",
                    before=by_id.get(eid),
                    ad_account_id=aid,
                )
                deleted.append(
                    {
                        "id": eid,
                        "audit_id": out.get("audit_id"),
                        "dry_run": bool(out.get("_dry_run")),
                    }
                )
                await report(ctx, done, total, f"Deleted {eid} ({done} of {total})")
            except Exception as e:
                failed.append({"id": eid, "reason": str(e)[:500]})
                await report(ctx, done, total, f"Failed {eid} ({done} of {total})")
        return safety.annotate(
            {
                "deleted_count": len(deleted),
                "failed_count": len(failed),
                "deleted": deleted,
                "failed": failed[:50],
            },
            decision,
        )
