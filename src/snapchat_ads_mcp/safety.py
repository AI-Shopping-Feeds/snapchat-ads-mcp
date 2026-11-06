"""Confirmation guards for writes that change live ads or spend money.

A write tool asks `assess()` what its change needs, then `refusal()` whether to
stop. A guarded write is refused (with a summary of what it would do) unless the
caller passes the required `confirm` word:

* deletes need confirm='DELETE' (Snap deletes are permanent);
* writes touching more than SNAPCHAT_ADS_BULK_THRESHOLD entities, bid or
  budget increases above SNAPCHAT_ADS_MAX_INCREASE_PCT, increases whose current
  value couldn't be read, removing a spend cap, values above
  SNAPCHAT_ADS_MAX_BUDGET / SNAPCHAT_ADS_MAX_BID, and raw writes need
  confirm='APPLY'.

Money in the Snap Marketing API is in micro-currency: 1.00 in the ad account's
currency is 1,000,000 micro. Guards compare micro values; the caps are set in
whole currency units and converted here.

In dry-run mode nothing is sent, so guards don't block; the result says which
confirm a real run would need.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .config import Config

APPLY = "APPLY"
DELETE = "DELETE"
MICRO = 1_000_000

# Money fields per entity, as (kind, path) pairs. kind is "budget" or "bid".
CAMPAIGN_MONEY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget", ("daily_budget_micro",)),
    ("budget", ("lifetime_spend_cap_micro",)),
    ("bid", ("shared_properties", "target_cost_in_micro")),
)
AD_SQUAD_MONEY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget", ("daily_budget_micro",)),
    ("budget", ("lifetime_budget_micro",)),
    ("bid", ("bid_micro",)),
)
# Removing these caps lifts a spending limit, so it needs confirm='APPLY'.
SPEND_CAP_FIELDS = frozenset({"lifetime_spend_cap_micro", "daily_budget_micro"})


def to_micro(amount: float) -> int:
    """Whole currency units (e.g. 12.5) to micro-currency (12500000)."""
    return round(float(amount) * MICRO)


def from_micro(value: Any) -> float | None:
    """Micro-currency to whole currency units, or None if not a number."""
    try:
        return round(int(value) / MICRO, 6) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class MoneyChange:
    """A bid or budget value a write sets: `old` is None if it couldn't be read."""

    entity_id: str
    kind: str  # "bid" or "budget"
    field: str
    old: int | None
    new: int | None  # None: the field is being removed


@dataclass
class Decision:
    required: str | None = None
    reasons: list[str] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "required_confirm": self.required,
            "reasons": self.reasons,
            "money_changes": self.changes[:50],
        }


def _num(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def dig(obj: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _has(obj: Any, path: Sequence[str]) -> bool:
    for key in path[:-1]:
        if not isinstance(obj, dict):
            return False
        obj = obj.get(key)
    return isinstance(obj, dict) and path[-1] in obj


def money_changes(
    items: Iterable[dict[str, Any]],
    current: Iterable[dict[str, Any]] | None,
    *,
    fields: Sequence[tuple[str, Sequence[str]]],
    id_field: str = "id",
) -> list[MoneyChange]:
    """Pair each update's bid/budget fields with the entity's current values."""
    by_id = {str(c.get(id_field)): c for c in (current or []) if isinstance(c, dict)}
    out: list[MoneyChange] = []
    for item in items:
        eid = str(item.get(id_field))
        for kind, path in fields:
            if not _has(item, path):
                continue
            new = _num(dig(item, path))
            old = _num(dig(by_id[eid], path)) if eid in by_id else None
            out.append(MoneyChange(eid, kind, ".".join(path), old, new))
    return out


def new_values(
    items: Iterable[dict[str, Any]], fields: Sequence[tuple[str, Sequence[str]]]
) -> list[MoneyChange]:
    """Bid/budget values set by creates (no previous value to compare)."""
    out: list[MoneyChange] = []
    for i, item in enumerate(items):
        for kind, path in fields:
            new = _num(dig(item, path))
            if new is not None:
                out.append(MoneyChange(f"new[{i}]", kind, ".".join(path), None, new))
    return out


def _fmt(micro: int | None) -> str:
    return "none" if micro is None else f"{micro / MICRO:g}"


def assess(
    config: Config,
    *,
    count: int,
    destructive: str | None = None,
    changes: Sequence[MoneyChange] = (),
    creating: bool = False,
) -> Decision:
    """Work out which confirm word, if any, a write needs."""
    d = Decision()
    if destructive:
        d.required = destructive
        d.reasons.append(f"{destructive.lower()} of {count} item(s) can't be undone")
    if count > config.bulk_threshold:
        d.reasons.append(
            f"{count} items is more than SNAPCHAT_ADS_BULK_THRESHOLD ({config.bulk_threshold})"
        )
    limit = config.max_increase_pct
    for c in changes:
        info: dict[str, Any] = {
            "id": c.entity_id,
            "field": c.field,
            "old": _fmt(c.old),
            "new": _fmt(c.new),
            "old_micro": c.old,
            "new_micro": c.new,
        }
        if c.old and c.new is not None and c.old > 0:
            info["change_pct"] = round((c.new - c.old) / c.old * 100, 1)
        d.changes.append(info)
        if c.new is None:
            if not creating and c.field.split(".")[-1] in SPEND_CAP_FIELDS and c.old is not None:
                d.reasons.append(f"removing {c.field} for {c.entity_id} lifts a spending limit")
            continue
        cap = config.max_budget if c.kind == "budget" else config.max_bid
        if cap is not None and c.new > to_micro(cap):
            d.reasons.append(
                f"{c.field} {_fmt(c.new)} for {c.entity_id} is above the cap of {cap:g} "
                f"(SNAPCHAT_ADS_MAX_{c.kind.upper()})"
            )
        if creating:
            continue
        if c.old is None:
            d.reasons.append(
                f"current {c.field} for {c.entity_id} is unknown, so the change is unchecked"
            )
        elif c.old <= 0 < c.new or (c.old > 0 and (c.new - c.old) / c.old * 100 > limit):
            d.reasons.append(
                f"{c.field} for {c.entity_id} rises from {_fmt(c.old)} to {_fmt(c.new)} "
                f"(more than SNAPCHAT_ADS_MAX_INCREASE_PCT={limit:g}%)"
            )
    if d.reasons and d.required is None:
        d.required = APPLY
    return d


def refusal(
    config: Config, decision: Decision, confirm: str, *, preview: Any = None
) -> dict | None:
    """Return a refusal payload if the write must not go ahead, else None."""
    if decision.required is None or config.dry_run or confirm == decision.required:
        return None
    out: dict[str, Any] = {
        "refused": True,
        "error": (
            "Not sent. Show the user what will change, and once they agree call again "
            f"with confirm='{decision.required}' (case-sensitive)."
        ),
        **decision.as_dict(),
    }
    if preview is not None:
        out["would_send"] = preview
    return out


def annotate(result: Any, decision: Decision) -> Any:
    """Attach the guard summary to a result (useful in dry-run)."""
    if decision.required is None:
        return result
    if isinstance(result, dict):
        return {**result, "safety": decision.as_dict()}
    return {"result": result, "safety": decision.as_dict()}
