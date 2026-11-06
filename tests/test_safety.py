"""Confirm-word guards and micro-currency helpers."""

from __future__ import annotations

import dataclasses

from snapchat_ads_mcp import safety
from snapchat_ads_mcp.config import Config


def test_micro_conversion() -> None:
    assert safety.to_micro(1) == 1_000_000
    assert safety.to_micro(123.45) == 123_450_000
    assert safety.to_micro(0.5) == 500_000
    assert safety.from_micro(50_000_000_000) == 50_000.0
    assert safety.from_micro(None) is None
    assert safety.from_micro("x") is None


def test_small_change_needs_nothing(config: Config) -> None:
    changes = safety.money_changes(
        [{"id": "a", "daily_budget_micro": 55_000_000}],
        [{"id": "a", "daily_budget_micro": 50_000_000}],
        fields=safety.CAMPAIGN_MONEY,
    )
    d = safety.assess(config, count=1, changes=changes)
    assert d.required is None
    assert d.changes[0]["change_pct"] == 10.0
    assert d.changes[0]["old"] == "50" and d.changes[0]["new"] == "55"


def test_big_rise_unknown_old_cap_and_removal(config: Config) -> None:
    cfg = dataclasses.replace(config, max_budget=100.0, max_bid=5.0)
    changes = safety.money_changes(
        [
            {"id": "a", "daily_budget_micro": 70_000_000},
            {"id": "b", "bid_micro": 2_000_000},
            {"id": "c", "daily_budget_micro": 200_000_000},
            {"id": "d", "lifetime_spend_cap_micro": None},
        ],
        [
            {"id": "a", "daily_budget_micro": 50_000_000},
            {"id": "c", "daily_budget_micro": 190_000_000},
            {"id": "d", "lifetime_spend_cap_micro": 1_000_000_000},
        ],
        fields=safety.CAMPAIGN_MONEY + safety.AD_SQUAD_MONEY,
    )
    d = safety.assess(cfg, count=4, changes=changes)
    text = " ".join(d.reasons)
    assert d.required == safety.APPLY
    assert "rises from 50 to 70" in text
    assert "current bid_micro for b is unknown" in text
    assert "above the cap of 100" in text
    assert "removing lifetime_spend_cap_micro for d lifts a spending limit" in text


def test_bulk_and_destructive(config: Config) -> None:
    d = safety.assess(config, count=11)
    assert d.required == safety.APPLY
    d = safety.assess(config, count=2, destructive=safety.DELETE)
    assert d.required == safety.DELETE
    assert safety.refusal(config, d, "DELETE") is None
    refused = safety.refusal(config, d, "delete", preview={"ids": ["x"]})
    assert refused is not None and refused["refused"] is True
    assert refused["would_send"] == {"ids": ["x"]}
    assert "confirm='DELETE'" in refused["error"]


def test_creating_checks_only_caps(config: Config) -> None:
    cfg = dataclasses.replace(config, max_bid=1.0)
    values = safety.new_values(
        [{"bid_micro": 2_000_000}, {"bid_micro": 500_000}], safety.AD_SQUAD_MONEY
    )
    d = safety.assess(cfg, count=2, changes=values, creating=True)
    assert d.required == safety.APPLY
    assert len(d.reasons) == 1


def test_dry_run_never_refuses(config: Config) -> None:
    cfg = dataclasses.replace(config, dry_run=True)
    d = safety.assess(cfg, count=50)
    assert safety.refusal(cfg, d, "") is None
    assert safety.annotate({"a": 1}, d)["safety"]["required_confirm"] == "APPLY"
    assert safety.annotate([1], d)["result"] == [1]
    assert safety.annotate({"a": 1}, safety.Decision()) == {"a": 1}
