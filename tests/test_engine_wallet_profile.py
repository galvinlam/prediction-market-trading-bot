from __future__ import annotations

from types import SimpleNamespace

import polymarket_copy_trading.engine as engine_module
from polymarket_copy_trading.engine import CopyTradingEngine


SHARP = "0x8a091656e5f4c6bc4fdf37b2585be0235f68e317"
RN1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"


def test_strategy_flag_helpers_prefer_profile_json_over_stale_legacy_flags() -> None:
    wallet = {
        "bracket_strategy_enabled": False,
        "repeat_buy_strategy_enabled": True,
        "event_follow_strategy_enabled": True,
        "profile_json": {
            "weather_bracket": {"enabled": True},
            "repeat_buy": {"enabled": False},
            "event_follow": {"enabled": False},
        },
    }

    assert engine_module._weather_bracket_strategy_enabled(wallet) is True
    assert engine_module._repeat_buy_strategy_enabled(wallet) is False
    assert engine_module._event_follow_strategy_enabled(wallet) is False


def test_wallet_numeric_helpers_prefer_profile_json_over_stale_legacy_fields() -> None:
    wallet = {
        "event_follow_min_avg_price": 0.2,
        "event_follow_min_event_buy_count": 3,
        "profile_json": {
            "event_follow": {
                "min_avg_price": 0.35,
                "min_event_buy_count": 5,
            },
        },
    }

    assert engine_module._wallet_float(wallet, "event_follow_min_avg_price", 0.2) == 0.35
    assert engine_module._wallet_int(wallet, "event_follow_min_event_buy_count", 3) == 5


def test_sharp_fixed_buy_uses_profile_strategy_toggles() -> None:
    wallet = {
        "name": "Sharp_0x8a091",
        "bracket_strategy_enabled": False,
        "repeat_buy_strategy_enabled": True,
        "event_follow_strategy_enabled": True,
        "profile_json": {
            "fixed_buy": {"enabled": True, "market_types": ["crypto"]},
            "weather_bracket": {"enabled": False},
            "repeat_buy": {"enabled": False},
            "event_follow": {"enabled": False},
        },
    }

    assert engine_module._sharp_simple_crypto_copy_enabled(SHARP, wallet, "crypto") is True


def test_swisstony_source_follow_cap_fallback_reads_profile_event_caps() -> None:
    wallet = {
        "event_follow_max_event_exposure_usdc": 4.0,
        "event_follow_max_total_exposure_usdc": 50.0,
        "profile_json": {
            "event_follow": {
                "max_event_exposure_usdc": 75.0,
                "max_total_exposure_usdc": 350.0,
            },
        },
    }

    assert engine_module._swisstony_source_follow_enabled(wallet) is True


def test_filter_copy_uses_profile_toggle_and_limits_over_known_wallet_defaults() -> None:
    disabled_wallet = {"profile_json": {"filter_copy": {"enabled": False}}}
    custom_limits_wallet = {
        "profile_json": {
            "filter_copy": {
                "enabled": True,
                "max_source_price": 1.0,
                "min_single_fill_usdc": 0.0,
                "min_cumulative_source_usdc": 0.0,
                "accumulation_window_seconds": 0,
                "daily_deployed_cap_usdc": 0.0,
            }
        }
    }

    assert engine_module._filter_copy_enabled(RN1, disabled_wallet) is False
    assert engine_module._filter_copy_enabled(RN1, custom_limits_wallet) is True
    assert engine_module._filter_copy_max_source_price(RN1, custom_limits_wallet) == 1.0
    assert engine_module._filter_copy_min_single_fill_usdc(RN1, custom_limits_wallet) == 0.0
    assert engine_module._filter_copy_min_cumulative_source_usdc(RN1, custom_limits_wallet) == 0.0
    assert engine_module._filter_copy_window_seconds(RN1, custom_limits_wallet) == 0
    assert engine_module._filter_copy_daily_deployed_cap_usdc(custom_limits_wallet) == 0.0


def test_available_cash_reserves_profile_risk_cash_for_other_wallets() -> None:
    engine = object.__new__(CopyTradingEngine)
    engine.broker = SimpleNamespace(cash_usdc=100.0)
    engine.store = SimpleNamespace(
        list_wallets=lambda: [
            {
                "enabled": True,
                "address": "0xcurrent",
                "reserved_cash_usdc": 90.0,
                "profile_json": {"risk": {"reserved_cash_usdc": 90.0}},
            },
            {
                "enabled": True,
                "address": "0xother",
                "reserved_cash_usdc": 0.0,
                "profile_json": {"risk": {"reserved_cash_usdc": 30.0}},
            },
        ]
    )

    assert engine._available_cash_for_wallet("0xcurrent") == 70.0
