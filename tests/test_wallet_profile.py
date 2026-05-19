from __future__ import annotations

from typing import Any

from polymarket_copy_trading import engine as engine_rules
from polymarket_copy_trading.wallet_profile import (
    apply_wallet_profile_overrides,
    event_book_planner_default_overrides,
    wallet_profile_float,
    wallet_profile_json_from_legacy_wallet,
    wallet_profile_list,
)


RN1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
SWISSTONY = "0x204f72f35326db932158cba6adff0b9a1da95e14"


def _tiers_allow_price(tiers: list[dict[str, Any]], price: float) -> bool:
    return any(float(tier["min_price"]) <= price < float(tier["max_price"]) for tier in tiers)


def _legacy_wallet(**overrides: Any) -> dict[str, Any]:
    wallet = {
        "address": "0x1111111111111111111111111111111111111111",
        "name": "test",
        "enabled": True,
        "strategy_label": "Standard",
        "allowed_market_types": ["crypto", "weather", "sports", "other"],
        "bracket_strategy_enabled": False,
        "bracket_buy_size_usdc": 10.0,
        "bracket_stop_loss_pct": 0.0,
        "bracket_max_open_events": 0,
        "bracket_allowed_patterns": ["exact_or_binary", "range", "above_or_higher", "below_or_lower"],
        "repeat_buy_strategy_enabled": False,
        "repeat_buy_size_usdc": 5.0,
        "repeat_buy_stop_loss_pct": 0.0,
        "repeat_buy_min_source_notional_usdc": 0.0,
        "repeat_buy_min_buy_count": 2,
        "repeat_buy_min_avg_price": 0.01,
        "repeat_buy_max_avg_price": 1.0,
        "repeat_buy_max_total_exposure_usdc": 0.0,
        "repeat_buy_blocked_title_patterns": [],
        "repeat_buy_allowed_sports": [],
        "repeat_buy_allowed_bet_types": [],
        "event_follow_strategy_enabled": False,
        "event_follow_buy_size_usdc": 2.0,
        "event_follow_max_event_exposure_usdc": 4.0,
        "event_follow_max_total_exposure_usdc": 50.0,
        "event_follow_min_source_trade_usdc": 20.0,
        "event_follow_min_event_source_notional_usdc": 250.0,
        "event_follow_min_event_buy_count": 3,
        "event_follow_min_avg_price": 0.20,
        "event_follow_max_avg_price": 0.80,
        "sports_trailing_stop_enabled": False,
        "sports_trailing_activation_pct": 35.0,
        "sports_trailing_stop_pct": 25.0,
        "sports_trailing_floor_delta": 0.03,
        "reserved_cash_usdc": 0.0,
    }
    wallet.update(overrides)
    return wallet


def test_event_book_planner_default_overrides_are_wallet_specific() -> None:
    rn1_defaults = event_book_planner_default_overrides(RN1)
    swisstony_defaults = event_book_planner_default_overrides(SWISSTONY)
    combined_defaults = event_book_planner_default_overrides()

    assert rn1_defaults["planner_enabled"] is True
    assert rn1_defaults["planner_total_bankroll_usdc"] == 100.0
    assert rn1_defaults["planner_rn1_max_rebalance_order_usdc"] == 3.0
    assert rn1_defaults["planner_rn1_tennis_esports_base_event_budget_usdc"] == 5.0
    assert rn1_defaults["planner_rn1_tennis_esports_max_event_budget_usdc"] == 10.0
    assert rn1_defaults["rn1_fresh_max_source_legs"] == 3
    assert "planner_swisstony_max_event_budget_usdc" not in rn1_defaults
    assert swisstony_defaults["planner_swisstony_max_event_budget_usdc"] == 5.0
    assert "planner_rn1_max_rebalance_order_usdc" not in swisstony_defaults
    assert set(rn1_defaults).issubset(combined_defaults)
    assert set(swisstony_defaults).issubset(combined_defaults)


def test_rn1_legacy_profile_backfill_preserves_current_event_book_strategy() -> None:
    profile = wallet_profile_json_from_legacy_wallet(
        _legacy_wallet(
            address=RN1,
            name="RN1",
            allowed_market_types=["sports", "other"],
            repeat_buy_strategy_enabled=True,
            repeat_buy_min_source_notional_usdc=1000.0,
            repeat_buy_min_avg_price=0.05,
            repeat_buy_max_avg_price=0.80,
            repeat_buy_max_total_exposure_usdc=180.0,
            reserved_cash_usdc=140.0,
        )
    )

    assert profile["source_follow"]["enabled"] is True
    assert profile["source_follow"]["copy_scale"] == 0.0005
    assert profile["binary_hedge"]["enabled"] is True
    assert profile["risk"]["reserved_cash_usdc"] == 20.0
    assert profile["filter_copy"]["daily_deployed_cap_usdc"] == 100.0
    assert profile["filter_copy"]["max_source_price"] == 0.60
    assert profile["filter_copy"]["min_single_fill_usdc"] == 0.0
    assert _tiers_allow_price(profile["filter_copy"]["tiers"], 0.60)
    assert profile["filter_copy"]["allowed_sports"] == [
        "nba",
        "nhl",
        "mlb",
        "soccer",
        "esports",
    ]
    assert profile["filter_copy"]["allowed_bet_types"] == ["moneyline_winlose"]
    assert profile["filter_copy"]["paused_sports"] == ["atp", "wta", "tennis"]
    assert profile["filter_copy"]["same_event_hedge_max_fraction"] == 0.15
    assert profile["filter_copy"]["event_book_min_asset_source_notional_usdc"] == 1000.0
    assert profile["filter_copy"]["rebalance"]["enabled"] is True
    assert profile["filter_copy"]["rebalance"]["max_source_price"] == 0.82
    assert profile["filter_copy"]["rebalance"]["max_repair_buy_usdc"] == 3.0
    assert profile["filter_copy"]["rebalance"]["normal_event_cap_usdc"] == 10.0
    assert profile["filter_copy"]["rebalance"]["extra_repair_event_cap_usdc"] == 5.0
    assert profile["filter_copy"]["rebalance"]["allowed_sports"] == ["soccer", "mlb", "nba", "nhl"]
    assert profile["event_book"]["planner_rn1_max_rebalance_order_usdc"] == 3.0
    assert profile["event_book"]["planner_rn1_tennis_esports_base_event_budget_usdc"] == 5.0
    assert profile["event_book"]["planner_rn1_tennis_esports_max_event_budget_usdc"] == 10.0
    assert profile["event_book"]["planner_enabled"] is True
    assert profile["event_book"]["planner_rebalance_min_worst_case_improvement_fraction"] == 0.15
    assert profile["event_book"]["tennis_fresh_min_dominance_share"] == 0.80
    assert profile["event_book"]["tennis_fresh_min_dominance_ratio"] == 3.0
    assert profile["event_book"]["esports_fresh_min_dominance_share"] == 0.95
    assert profile["event_book"]["esports_fresh_min_dominance_ratio"] == 8.0
    assert profile["event_book"]["rn1_fresh_max_source_legs"] == 3
    assert profile["event_book"]["min_source_notional_usdc"] == 3000.0
    assert profile["event_book"]["min_avg_price"] == 0.05
    assert profile["event_book"]["max_avg_price"] == 0.80
    assert wallet_profile_list({"profile_json": profile}, "event_follow", "allowed_sports", [], lower=True) == [
        "soccer",
        "mlb",
        "nba",
        "nhl",
        "esports",
    ]


def test_rn1_event_book_uses_sport_specific_source_floors() -> None:
    profile = wallet_profile_json_from_legacy_wallet(_legacy_wallet(address=RN1, name="RN1"))
    wallet = {"profile_json": profile}

    assert profile["event_book"]["planner_rn1_soccer_min_event_source_usdc"] == 10000.0
    assert profile["event_book"]["planner_rn1_mlb_min_event_source_usdc"] == 5000.0
    assert engine_rules._filter_copy_min_cumulative_source_usdc(RN1, wallet, {"sport_key": "soccer"}) == 10000.0
    assert engine_rules._filter_copy_min_cumulative_source_usdc(RN1, wallet, {"sport_key": "mlb"}) == 5000.0
    assert engine_rules._filter_copy_min_cumulative_source_usdc(RN1, wallet, {"sport_key": "nba"}) == 3000.0


def test_swisstony_legacy_profile_backfill_enables_event_book_markets() -> None:
    profile = wallet_profile_json_from_legacy_wallet(
        _legacy_wallet(
            address=SWISSTONY,
            name="swisstony",
            strategy_label="Custom",
            allowed_market_types=["sports", "other"],
            event_follow_strategy_enabled=True,
            event_follow_buy_size_usdc=2.0,
            event_follow_max_event_exposure_usdc=75.0,
            event_follow_max_total_exposure_usdc=350.0,
            event_follow_min_source_trade_usdc=0.0,
            event_follow_min_event_source_notional_usdc=1000.0,
            event_follow_min_event_buy_count=2,
            event_follow_min_avg_price=0.05,
            event_follow_max_avg_price=0.90,
            reserved_cash_usdc=80.0,
        )
    )

    assert profile["source_follow"]["enabled"] is True
    assert profile["source_follow"]["copy_scale"] == 0.001
    assert profile["binary_hedge"]["enabled"] is True
    assert profile["strategy"]["copy_buys_enabled"] is True
    assert profile["filter_copy"]["scale_up_enabled"] is True
    assert profile["risk"]["reserved_cash_usdc"] == 20.0
    assert profile["filter_copy"]["daily_deployed_cap_usdc"] == 100.0
    assert profile["filter_copy"]["min_single_fill_usdc"] == 0.0
    assert profile["filter_copy"]["max_source_price"] == 0.60
    assert _tiers_allow_price(profile["filter_copy"]["tiers"], 0.60)
    assert profile["filter_copy"]["allowed_sports"] == ["soccer"]
    assert profile["filter_copy"]["allowed_bet_types"] == ["moneyline_winlose"]
    assert not {"mlb", "nba", "nhl", "nfl", "esports", "atp", "wta", "tennis", "other"} & set(
        profile["filter_copy"]["allowed_sports"]
    )
    assert profile["filter_copy"]["sport_rules"] == {}
    assert "wta" not in profile["filter_copy"]["sport_rules"]
    assert "atp" not in profile["filter_copy"]["sport_rules"]
    assert profile["filter_copy"]["rebalance"]["enabled"] is True
    assert profile["filter_copy"]["rebalance"]["max_source_price"] == 0.82
    assert profile["filter_copy"]["rebalance"]["min_event_share"] == 0.55
    assert profile["filter_copy"]["rebalance"]["max_repair_buy_usdc"] == 5.0
    assert profile["filter_copy"]["rebalance"]["allowed_sports"] == ["soccer"]
    assert profile["source_follow"]["max_asset_exposure_usdc"] == 5.0
    assert profile["event_follow"]["max_event_exposure_usdc"] == 5.0
    assert profile["filter_copy"]["scale_up_max_position_usdc"] == 5.0
    assert profile["event_book"]["max_avg_price"] == 0.8
    assert profile["event_book"]["planner_swisstony_max_event_budget_usdc"] == 5.0
    assert profile["risk"]["local_stop_loss_enabled"] is False
    assert profile["event_follow"]["allowed_sports"] == ["soccer"]
    assert profile["event_follow"]["allowed_bet_types"] == ["moneyline_winlose"]


def test_profile_overrides_project_to_legacy_wallet_payload() -> None:
    wallet = _legacy_wallet(address=SWISSTONY, name="swisstony")
    profile = wallet_profile_json_from_legacy_wallet(
        wallet,
        {
            "market_filters": {"allowed_market_types": ["sports"]},
            "event_follow": {
                "enabled": True,
                "buy_size_usdc": 3,
                "max_event_exposure_usdc": 12,
                "max_total_exposure_usdc": 34,
                "min_source_trade_usdc": 0,
                "min_event_source_notional_usdc": 100,
                "min_event_buy_count": 2,
                "min_avg_price": 0.2,
                "max_avg_price": 0.7,
            },
            "risk": {"reserved_cash_usdc": 80},
        },
    )

    apply_wallet_profile_overrides(wallet, profile)

    assert wallet["allowed_market_types"] == ["sports"]
    assert wallet["event_follow_strategy_enabled"] is True
    assert wallet["event_follow_buy_size_usdc"] == 3.0
    assert wallet["event_follow_max_event_exposure_usdc"] == 12.0
    assert wallet["event_follow_max_total_exposure_usdc"] == 34.0
    assert wallet["event_follow_min_source_trade_usdc"] == 0.0
    assert wallet["event_follow_min_event_source_notional_usdc"] == 100.0
    assert wallet["event_follow_min_event_buy_count"] == 2
    assert wallet["event_follow_min_avg_price"] == 0.2
    assert wallet["event_follow_max_avg_price"] == 0.7
    assert wallet["reserved_cash_usdc"] == 80.0
    assert wallet_profile_float({"profile_json": profile}, "source_follow", "copy_scale", 0.0) == 0.001
