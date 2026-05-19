from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from typing import Any


MARKET_TYPES = ("crypto", "weather", "sports", "other")
WEATHER_BRACKET_PATTERNS = ("exact_or_binary", "range", "above_or_higher", "below_or_lower")
RN1_PROFILE_ADDRESS = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
SWISSTONY_PROFILE_ADDRESS = "0x204f72f35326db932158cba6adff0b9a1da95e14"
SHARP_PROFILE_ADDRESS = "0x8a091656e5f4c6bc4fdf37b2585be0235f68e317"
RN1_EVENT_FOLLOW_SPORTS = ["soccer", "mlb", "nba", "nhl", "esports"]
RN1_EVENT_FOLLOW_BET_TYPES = ["moneyline_winlose"]
SWISSTONY_EVENT_FOLLOW_SPORTS = ["soccer"]
FILTER_COPY_EVENT_BOOK_BET_TYPES = [
    "moneyline_winlose",
    "total_or_over_under",
    "spread_handicap",
    "both_teams_score",
    "map_or_game_winner",
]
DEFAULT_WALLET_PROFILE_JSON: dict[str, Any] = {
    "version": 1,
    "market_filters": {"allowed_market_types": list(MARKET_TYPES)},
    "weather_bracket": {
        "enabled": False,
        "copy_source_leg_size": False,
        "buy_size_usdc": 10.0,
        "stop_loss_pct": 0.0,
        "max_open_events": 0,
        "allowed_patterns": list(WEATHER_BRACKET_PATTERNS),
    },
    "repeat_buy": {
        "enabled": False,
        "buy_size_usdc": 5.0,
        "stop_loss_pct": 0.0,
        "min_source_notional_usdc": 0.0,
        "min_buy_count": 2,
        "min_avg_price": 0.01,
        "max_avg_price": 1.0,
        "max_total_exposure_usdc": 0.0,
        "blocked_title_patterns": [],
        "allowed_sports": [],
        "allowed_bet_types": [],
    },
    "event_follow": {
        "enabled": False,
        "buy_size_usdc": 2.0,
        "max_event_exposure_usdc": 4.0,
        "max_total_exposure_usdc": 50.0,
        "min_source_trade_usdc": 20.0,
        "min_event_source_notional_usdc": 250.0,
        "min_event_buy_count": 3,
        "min_avg_price": 0.20,
        "max_avg_price": 0.80,
        "allowed_sports": [],
        "allowed_bet_types": [],
    },
    "sports_trailing": {
        "enabled": False,
        "activation_pct": 35.0,
        "stop_pct": 25.0,
        "floor_delta": 0.03,
    },
    "risk": {"reserved_cash_usdc": 0.0, "local_stop_loss_enabled": True},
    "source_follow": {
        "enabled": False,
        "copy_scale": 0.001,
        "max_asset_exposure_usdc": 25.0,
        "min_trade_usdc": 1.0,
    },
    "filter_copy": {
        "enabled": False,
        "max_source_price": 1.0,
        "min_source_price": 0.20,
        "min_single_fill_usdc": 0.0,
        "min_cumulative_source_usdc": 0.0,
        "accumulation_window_seconds": 0,
        "daily_deployed_cap_usdc": 0.0,
        "source_sell_exit_fraction": 0.0,
        "same_event_hedge_max_fraction": 0.25,
        "event_book_min_asset_source_notional_usdc": 1000.0,
        "scale_up_enabled": True,
        "scale_up_max_position_usdc": 60.0,
        "in_event_stop_loss_pct": 0.0,
        "allowed_sports": [],
        "paused_sports": [],
        "allowed_bet_types": list(FILTER_COPY_EVENT_BOOK_BET_TYPES),
        "sport_rules": {},
        "rebalance": {
            "enabled": False,
            "max_source_price": 0.82,
            "strong_max_source_price": 0.88,
            "min_source_notional_usdc": 3000.0,
            "strong_min_source_notional_usdc": 10000.0,
            "min_event_share": 0.45,
            "strong_min_event_share": 0.60,
            "min_repair_to_existing_source_ratio": 1.15,
            "max_repair_buy_usdc": 30.0,
            "normal_event_cap_usdc": 25.0,
            "extra_repair_event_cap_usdc": 20.0,
            "allowed_sports": [],
        },
        "blocked_title_patterns": [
            "map",
            "game",
            "o/u",
            "over/under",
            "total",
            "spread",
            "handicap",
            "both teams to score",
            "btts",
            "parlay",
            "draw",
        ],
        "tiers": [
            {"min_price": 0.20, "max_price": 0.35, "buy_size_usdc": 12.0},
            {"min_price": 0.35, "max_price": 0.45, "buy_size_usdc": 10.0},
            {"min_price": 0.45, "max_price": 0.55, "buy_size_usdc": 8.0},
        ],
    },
    "event_book": {
        "min_source_notional_usdc": 3000.0,
        "min_avg_price": 0.40,
        "max_avg_price": 0.70,
        "min_dominance_share": 0.60,
        "min_dominance_ratio": 1.75,
    },
    "fixed_buy": {"enabled": False, "buy_size_usdc": 5.0, "market_types": ["crypto"]},
    "binary_hedge": {"enabled": False},
    "limit_copy": {"limit_price_premium": 0.003, "limit_price_multiple": 1.20, "source_copy_scale": 0.25},
    "tier_sizing": {"tiers": []},
    "esports_repeat_buy": {
        "min_buy_count": 40,
        "min_source_notional_usdc": 3000.0,
        "min_avg_price": 0.40,
        "max_avg_price": 0.70,
        "allowed_bet_types": ["moneyline_winlose"],
    },
    "high_conviction": {
        "min_buy_count": 10,
        "min_source_notional_usdc": 3000.0,
        "min_avg_price": 0.40,
        "max_avg_price": 0.70,
    },
    "strategy": {"custom": False, "copy_buys_enabled": True},
}
EVENT_BOOK_PLANNER_COMMON_DEFAULTS: dict[str, Any] = {
    "planner_enabled": True,
    "planner_total_bankroll_usdc": 100.0,
    "planner_reserve_capital_usdc": 20.0,
    "planner_base_event_budget_usdc": 5.0,
    "planner_max_event_budget_usdc": 10.0,
    "planner_max_rebalance_reserve_usdc": 5.0,
    "planner_reserve_shape_improvement_fraction": 0.20,
    "planner_fresh_min_price": 0.01,
    "planner_fresh_max_price": 0.95,
    "planner_rebalance_min_price": 0.01,
    "planner_rebalance_max_price": 0.98,
}
RN1_EVENT_BOOK_PLANNER_DEFAULTS: dict[str, Any] = {
    "planner_rn1_max_rebalance_order_usdc": 3.0,
    "planner_rn1_tennis_esports_base_event_budget_usdc": 5.0,
    "planner_rn1_tennis_esports_max_event_budget_usdc": 10.0,
    "planner_rn1_soccer_min_event_source_usdc": 10000.0,
    "planner_rn1_mlb_min_event_source_usdc": 5000.0,
    "planner_rebalance_min_worst_case_improvement_fraction": 0.15,
    "rn1_fresh_max_source_legs": 3,
}
SWISSTONY_EVENT_BOOK_PLANNER_DEFAULTS: dict[str, Any] = {
    "planner_swisstony_base_event_budget_usdc": 3.0,
    "planner_swisstony_max_event_budget_usdc": 5.0,
    "planner_swisstony_max_rebalance_reserve_usdc": 2.0,
    "planner_swisstony_fresh_min_event_source_usdc": 40000.0,
    "planner_swisstony_fresh_min_top_leg_share": 0.55,
    "planner_swisstony_fresh_max_draw_share": 0.40,
}
WALLET_PROFILE_SECTIONS = frozenset(key for key in DEFAULT_WALLET_PROFILE_JSON if key != "version")


class WalletProfileError(ValueError):
    """Raised when a wallet profile JSON payload is invalid."""


def default_wallet_profile_json() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_WALLET_PROFILE_JSON))


def event_book_planner_default_overrides(source_wallet: str | None = None) -> dict[str, Any]:
    clean_source = str(source_wallet or "").strip().lower()
    defaults = dict(EVENT_BOOK_PLANNER_COMMON_DEFAULTS)
    if not clean_source:
        defaults.update(RN1_EVENT_BOOK_PLANNER_DEFAULTS)
        defaults.update(SWISSTONY_EVENT_BOOK_PLANNER_DEFAULTS)
    elif clean_source in {RN1_PROFILE_ADDRESS, "rn1"}:
        defaults.update(RN1_EVENT_BOOK_PLANNER_DEFAULTS)
    elif clean_source in {SWISSTONY_PROFILE_ADDRESS, "swisstony"}:
        defaults.update(SWISSTONY_EVENT_BOOK_PLANNER_DEFAULTS)
    return json.loads(json.dumps(defaults))


def wallet_profile_json_from_wallet_config(wallet: Any, profile_json: Any = None) -> dict[str, Any]:
    legacy_profile = parse_wallet_profile_json(
        {
            "market_filters": {"allowed_market_types": list(_wallet_value(wallet, "allowed_market_types", MARKET_TYPES))},
            "weather_bracket": {
                "enabled": _wallet_value(wallet, "bracket_strategy_enabled", False),
                "buy_size_usdc": _wallet_value(wallet, "bracket_buy_size_usdc", 10.0),
                "stop_loss_pct": _wallet_value(wallet, "bracket_stop_loss_pct", 0.0),
                "max_open_events": _wallet_value(wallet, "bracket_max_open_events", 0),
                "allowed_patterns": list(_wallet_value(wallet, "bracket_allowed_patterns", WEATHER_BRACKET_PATTERNS)),
            },
            "repeat_buy": {
                "enabled": _wallet_value(wallet, "repeat_buy_strategy_enabled", False),
                "buy_size_usdc": _wallet_value(wallet, "repeat_buy_size_usdc", 5.0),
                "stop_loss_pct": _wallet_value(wallet, "repeat_buy_stop_loss_pct", 0.0),
                "min_source_notional_usdc": _wallet_value(wallet, "repeat_buy_min_source_notional_usdc", 0.0),
                "min_buy_count": _wallet_value(wallet, "repeat_buy_min_buy_count", 2),
                "min_avg_price": _wallet_value(wallet, "repeat_buy_min_avg_price", 0.01),
                "max_avg_price": _wallet_value(wallet, "repeat_buy_max_avg_price", 1.0),
                "max_total_exposure_usdc": _wallet_value(wallet, "repeat_buy_max_total_exposure_usdc", 0.0),
                "blocked_title_patterns": list(_wallet_value(wallet, "repeat_buy_blocked_title_patterns", ())),
                "allowed_sports": list(_wallet_value(wallet, "repeat_buy_allowed_sports", ())),
                "allowed_bet_types": list(_wallet_value(wallet, "repeat_buy_allowed_bet_types", ())),
            },
            "event_follow": {
                "enabled": _wallet_value(wallet, "event_follow_strategy_enabled", False),
                "buy_size_usdc": _wallet_value(wallet, "event_follow_buy_size_usdc", 2.0),
                "max_event_exposure_usdc": _wallet_value(wallet, "event_follow_max_event_exposure_usdc", 4.0),
                "max_total_exposure_usdc": _wallet_value(wallet, "event_follow_max_total_exposure_usdc", 50.0),
                "min_source_trade_usdc": _wallet_value(wallet, "event_follow_min_source_trade_usdc", 20.0),
                "min_event_source_notional_usdc": _wallet_value(wallet, "event_follow_min_event_source_notional_usdc", 250.0),
                "min_event_buy_count": _wallet_value(wallet, "event_follow_min_event_buy_count", 3),
                "min_avg_price": _wallet_value(wallet, "event_follow_min_avg_price", 0.20),
                "max_avg_price": _wallet_value(wallet, "event_follow_max_avg_price", 0.80),
            },
            "sports_trailing": {
                "enabled": _wallet_value(wallet, "sports_trailing_stop_enabled", False),
                "activation_pct": _wallet_value(wallet, "sports_trailing_activation_pct", 35.0),
                "stop_pct": _wallet_value(wallet, "sports_trailing_stop_pct", 25.0),
                "floor_delta": _wallet_value(wallet, "sports_trailing_floor_delta", 0.03),
            },
            "risk": {"reserved_cash_usdc": _wallet_value(wallet, "reserved_cash_usdc", 0.0)},
            "source_follow": {},
            "event_book": {},
            "fixed_buy": {},
            "strategy": {"custom": str(_wallet_value(wallet, "strategy_label", "")).strip().lower() == "custom"},
        }
    )
    legacy_profile = apply_known_wallet_profile_defaults(legacy_profile, wallet)
    return merge_explicit_wallet_profile(legacy_profile, profile_json)


def wallet_profile_json_from_legacy_wallet(
    wallet: Mapping[str, Any],
    profile_json: Any = None,
    *,
    preserve_profile: Any = None,
) -> dict[str, Any]:
    legacy_profile = wallet_profile_json_from_wallet_config(wallet)
    legacy_profile = preserve_profile_only_settings(legacy_profile, preserve_profile)
    return merge_explicit_wallet_profile(legacy_profile, profile_json)


def apply_known_wallet_profile_defaults(profile: dict[str, Any], wallet: Any) -> dict[str, Any]:
    profile = parse_wallet_profile_json(profile)
    address = str(_wallet_value(wallet, "address", "") or "").strip().lower()
    name = str(_wallet_value(wallet, "name", "") or "").strip().lower()
    if address == RN1_PROFILE_ADDRESS:
        profile["filter_copy"].update(
            {
                "enabled": True,
                "max_source_price": 0.60,
                "min_source_price": 0.20,
                "min_single_fill_usdc": 0.0,
                "min_cumulative_source_usdc": 3000.0,
                "accumulation_window_seconds": 60,
                "daily_deployed_cap_usdc": 100.0,
                "same_event_hedge_max_fraction": 0.15,
                "allowed_sports": ["nba", "nhl", "mlb", "soccer", "esports"],
                "paused_sports": ["atp", "wta", "tennis"],
                "allowed_bet_types": ["moneyline_winlose"],
                "event_book_min_asset_source_notional_usdc": 1000.0,
                "rebalance": {
                    "enabled": True,
                    "max_source_price": 0.82,
                    "strong_max_source_price": 0.88,
                    "min_source_notional_usdc": 3000.0,
                    "strong_min_source_notional_usdc": 10000.0,
                    "min_event_share": 0.45,
                    "strong_min_event_share": 0.60,
                    "min_repair_to_existing_source_ratio": 1.15,
                    "max_repair_buy_usdc": 3.0,
                    "normal_event_cap_usdc": 10.0,
                    "extra_repair_event_cap_usdc": 5.0,
                    "allowed_sports": ["soccer", "mlb", "nba", "nhl"],
                },
                "tiers": [
                    {"min_price": 0.20, "max_price": 0.35, "buy_size_usdc": 12.0},
                    {"min_price": 0.35, "max_price": 0.45, "buy_size_usdc": 10.0},
                    {"min_price": 0.45, "max_price": 0.55, "buy_size_usdc": 8.0},
                    {"min_price": 0.55, "max_price": 0.600001, "buy_size_usdc": 5.0},
                ],
            }
        )
        profile["source_follow"].update(
            {
                "enabled": True,
                "copy_scale": 0.0005,
                "max_asset_exposure_usdc": 25.0,
                "min_trade_usdc": 1.0,
            }
        )
        profile["event_book"].update(
            {
                "min_source_notional_usdc": 3000.0,
                "min_avg_price": 0.05,
                "max_avg_price": 0.80,
                "min_dominance_share": 0.60,
                "min_dominance_ratio": 1.75,
                "tennis_fresh_min_dominance_share": 0.80,
                "tennis_fresh_min_dominance_ratio": 3.0,
                "esports_fresh_min_dominance_share": 0.95,
                "esports_fresh_min_dominance_ratio": 8.0,
                **event_book_planner_default_overrides(RN1_PROFILE_ADDRESS),
            }
        )
        profile["risk"]["reserved_cash_usdc"] = 20.0
    if address == RN1_PROFILE_ADDRESS or name == "rn1":
        profile["event_follow"].update(
            {
                "allowed_sports": list(RN1_EVENT_FOLLOW_SPORTS),
                "allowed_bet_types": list(RN1_EVENT_FOLLOW_BET_TYPES),
                "max_event_exposure_usdc": 50.0,
                "max_total_exposure_usdc": 180.0,
            }
        )
        profile["binary_hedge"]["enabled"] = True
    if _wallet_value(wallet, "event_follow_strategy_enabled", False) and "weather" in (
        _wallet_value(wallet, "allowed_market_types", ()) or ()
    ):
        profile["risk"]["local_stop_loss_enabled"] = False
    if address == SWISSTONY_PROFILE_ADDRESS:
        profile["strategy"]["copy_buys_enabled"] = True
        profile["filter_copy"].update(
            {
                "enabled": True,
                "max_source_price": 0.60,
                "min_source_price": 0.20,
                "min_single_fill_usdc": 0.0,
                "min_cumulative_source_usdc": 3000.0,
                "accumulation_window_seconds": 1800,
                "daily_deployed_cap_usdc": 100.0,
                "allowed_sports": ["soccer"],
                "allowed_bet_types": ["moneyline_winlose"],
                "event_book_min_asset_source_notional_usdc": 1000.0,
                "scale_up_max_position_usdc": 5.0,
                "sport_rules": {},
                "rebalance": {
                    "enabled": True,
                    "max_source_price": 0.82,
                    "strong_max_source_price": 0.88,
                    "min_source_notional_usdc": 3000.0,
                    "strong_min_source_notional_usdc": 10000.0,
                    "min_event_share": 0.55,
                    "strong_min_event_share": 0.60,
                    "min_repair_to_existing_source_ratio": 1.15,
                    "max_repair_buy_usdc": 5.0,
                    "normal_event_cap_usdc": 5.0,
                    "extra_repair_event_cap_usdc": 2.0,
                    "allowed_sports": ["soccer"],
                },
                "tiers": [
                    {"min_price": 0.20, "max_price": 0.35, "buy_size_usdc": 5.0},
                    {"min_price": 0.35, "max_price": 0.45, "buy_size_usdc": 5.0},
                    {"min_price": 0.45, "max_price": 0.55, "buy_size_usdc": 5.0},
                    {"min_price": 0.55, "max_price": 0.600001, "buy_size_usdc": 4.0},
                ],
                "scale_up_enabled": True,
            }
        )
        source_follow_enabled = (
            float(_wallet_value(wallet, "event_follow_max_event_exposure_usdc", 0) or 0) >= 50.0
            and float(_wallet_value(wallet, "event_follow_max_total_exposure_usdc", 0) or 0) >= 150.0
        )
        profile["source_follow"].update(
            {
                "enabled": source_follow_enabled,
                "copy_scale": 0.001,
                "max_asset_exposure_usdc": 5.0,
                "min_trade_usdc": 1.0,
            }
        )
        profile["event_follow"].update(
            {
                "allowed_sports": list(SWISSTONY_EVENT_FOLLOW_SPORTS),
                "allowed_bet_types": ["moneyline_winlose"],
                "buy_size_usdc": 2.0,
                "max_event_exposure_usdc": 5.0,
                "max_total_exposure_usdc": 350.0,
            }
        )
        profile["event_book"].update(
            {
                "min_source_notional_usdc": 3000.0,
                "min_avg_price": 0.05,
                "max_avg_price": 0.80,
                "min_dominance_share": 0.55,
                "min_dominance_ratio": 1.5,
                **event_book_planner_default_overrides(SWISSTONY_PROFILE_ADDRESS),
            }
        )
        profile["binary_hedge"]["enabled"] = True
        profile["risk"]["local_stop_loss_enabled"] = False
        profile["risk"]["reserved_cash_usdc"] = 20.0
    if address == SHARP_PROFILE_ADDRESS or name == "sharp_0x8a091":
        profile["fixed_buy"].update({"enabled": True, "buy_size_usdc": 5.0, "market_types": ["crypto"]})
        profile["risk"]["local_stop_loss_enabled"] = False
    if name == "vip68" and str(_wallet_value(wallet, "strategy_label", "") or "").strip().lower() == "custom":
        profile["weather_bracket"]["copy_source_leg_size"] = True
    return parse_wallet_profile_json(profile)


def preserve_profile_only_settings(base: dict[str, Any], raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return base
    existing = parse_wallet_profile_json(raw)
    merged = parse_wallet_profile_json(base)
    for section_name in (
        "event_book",
        "fixed_buy",
        "binary_hedge",
        "limit_copy",
        "tier_sizing",
        "esports_repeat_buy",
        "high_conviction",
    ):
        section = existing.get(section_name)
        if isinstance(section, dict) and section:
            merged[section_name] = section
    for section_name, keys in {
        "weather_bracket": ("copy_source_leg_size",),
        "event_follow": ("allowed_sports", "allowed_bet_types"),
        "source_follow": ("copy_scale", "max_asset_exposure_usdc", "min_trade_usdc"),
        "filter_copy": ("rebalance", "sport_rules"),
    }.items():
        existing_section = existing.get(section_name)
        merged_section = merged.setdefault(section_name, {})
        if not isinstance(existing_section, dict) or not isinstance(merged_section, dict):
            continue
        for key in keys:
            if key in existing_section:
                merged_section[key] = existing_section[key]
    return parse_wallet_profile_json(merged)


def parse_wallet_profile_json(raw: Any, name: str = "profile_json") -> dict[str, Any]:
    if raw is None or raw == "":
        return default_wallet_profile_json()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WalletProfileError(f"{name} must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise WalletProfileError(f"{name} must be a JSON object")

    profile = default_wallet_profile_json()
    for key, value in raw.items():
        clean_key = str(key)
        if clean_key == "version":
            try:
                profile["version"] = int(value)
            except (TypeError, ValueError) as exc:
                raise WalletProfileError(f"{name}.version must be an integer") from exc
            if profile["version"] < 1:
                raise WalletProfileError(f"{name}.version must be at least 1")
            continue
        if clean_key in WALLET_PROFILE_SECTIONS:
            section = profile.get(clean_key, {})
            if not isinstance(section, dict):
                section = {}
            profile[clean_key] = {
                **section,
                **_wallet_profile_section_payload(value, f"{name}.{clean_key}"),
            }
            continue
        profile[clean_key] = _json_compatible(value, f"{name}.{clean_key}")

    _validate_wallet_profile_numbers(profile, name)
    return profile


def merge_explicit_wallet_profile(base: dict[str, Any], raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return parse_wallet_profile_json(base)
    raw_object = raw_wallet_profile_object(raw)
    parsed = parse_wallet_profile_json(raw)
    merged = parse_wallet_profile_json(base)
    for key in raw_object:
        clean_key = str(key)
        if clean_key == "version":
            merged["version"] = parsed["version"]
        elif clean_key in WALLET_PROFILE_SECTIONS and isinstance(raw_object[clean_key], dict):
            section = dict(merged.get(clean_key) or {})
            parsed_section = parsed.get(clean_key) or {}
            for section_key in raw_object[clean_key]:
                section[str(section_key)] = parsed_section.get(str(section_key))
            merged[clean_key] = section
        else:
            merged[clean_key] = parsed.get(clean_key)
    return parse_wallet_profile_json(merged)


def raw_wallet_profile_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WalletProfileError("profile_json must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise WalletProfileError("profile_json must be a JSON object")
    return raw


def profile_json_to_text(value: Any) -> str:
    profile = parse_wallet_profile_json(value)
    return json.dumps(profile, sort_keys=True, separators=(",", ":"))


def profile_json_from_text(value: Any) -> dict[str, Any]:
    return parse_wallet_profile_json(value)


def apply_wallet_profile_overrides(
    wallet: dict[str, Any],
    profile: dict[str, Any],
    row: Mapping[str, Any] | None = None,
) -> None:
    parsed_profile = parse_wallet_profile_json(profile)
    market_filters = _profile_section_for_projection(parsed_profile, "market_filters")
    allowed_market_types = market_filters.get("allowed_market_types")
    if allowed_market_types is not None:
        try:
            wallet["allowed_market_types"] = clean_market_types(allowed_market_types)
        except ValueError:
            pass

    weather_bracket = _profile_section_for_projection(parsed_profile, "weather_bracket")
    _profile_bool(wallet, weather_bracket, "bracket_strategy_enabled", "enabled")
    _profile_float(wallet, weather_bracket, "bracket_buy_size_usdc", "buy_size_usdc", minimum=0.0, exclusive_min=True)
    _profile_float(wallet, weather_bracket, "bracket_stop_loss_pct", "stop_loss_pct", minimum=0.0)
    _profile_int(wallet, weather_bracket, "bracket_max_open_events", "max_open_events", minimum=0)
    allowed_patterns = weather_bracket.get("allowed_patterns")
    if allowed_patterns is not None:
        try:
            wallet["bracket_allowed_patterns"] = clean_weather_patterns(allowed_patterns)
        except ValueError:
            pass

    repeat_buy = _profile_section_for_projection(parsed_profile, "repeat_buy")
    _profile_bool(wallet, repeat_buy, "repeat_buy_strategy_enabled", "enabled")
    _profile_float(wallet, repeat_buy, "repeat_buy_size_usdc", "buy_size_usdc", minimum=0.0, exclusive_min=True)
    _profile_float(wallet, repeat_buy, "repeat_buy_stop_loss_pct", "stop_loss_pct", minimum=0.0)
    _profile_float(wallet, repeat_buy, "repeat_buy_min_source_notional_usdc", "min_source_notional_usdc", minimum=0.0)
    _profile_int(wallet, repeat_buy, "repeat_buy_min_buy_count", "min_buy_count", minimum=2)
    _profile_float(wallet, repeat_buy, "repeat_buy_min_avg_price", "min_avg_price", minimum=0.0, maximum=1.0, exclusive_min=True)
    _profile_float(wallet, repeat_buy, "repeat_buy_max_avg_price", "max_avg_price", minimum=0.0, maximum=1.0, exclusive_min=True)
    _profile_float(wallet, repeat_buy, "repeat_buy_max_total_exposure_usdc", "max_total_exposure_usdc", minimum=0.0)
    _profile_list(wallet, repeat_buy, "repeat_buy_blocked_title_patterns", "blocked_title_patterns")
    _profile_list(wallet, repeat_buy, "repeat_buy_allowed_sports", "allowed_sports", lower=True)
    _profile_list(wallet, repeat_buy, "repeat_buy_allowed_bet_types", "allowed_bet_types", lower=True)
    if wallet["repeat_buy_min_avg_price"] > wallet["repeat_buy_max_avg_price"]:
        wallet["repeat_buy_min_avg_price"] = float(_source_value(row, wallet, "repeat_buy_min_avg_price", 0.01) or 0.01)
        wallet["repeat_buy_max_avg_price"] = float(_source_value(row, wallet, "repeat_buy_max_avg_price", 1.0) or 1.0)

    event_follow = _profile_section_for_projection(parsed_profile, "event_follow")
    _profile_bool(wallet, event_follow, "event_follow_strategy_enabled", "enabled")
    _profile_float(wallet, event_follow, "event_follow_buy_size_usdc", "buy_size_usdc", minimum=0.0, exclusive_min=True)
    _profile_float(wallet, event_follow, "event_follow_max_event_exposure_usdc", "max_event_exposure_usdc", minimum=0.0, exclusive_min=True)
    _profile_float(wallet, event_follow, "event_follow_max_total_exposure_usdc", "max_total_exposure_usdc", minimum=0.0, exclusive_min=True)
    _profile_float(wallet, event_follow, "event_follow_min_source_trade_usdc", "min_source_trade_usdc", minimum=0.0)
    _profile_float(
        wallet,
        event_follow,
        "event_follow_min_event_source_notional_usdc",
        "min_event_source_notional_usdc",
        minimum=0.0,
    )
    _profile_int(wallet, event_follow, "event_follow_min_event_buy_count", "min_event_buy_count", minimum=1)
    _profile_float(wallet, event_follow, "event_follow_min_avg_price", "min_avg_price", minimum=0.0, maximum=1.0, exclusive_min=True)
    _profile_float(wallet, event_follow, "event_follow_max_avg_price", "max_avg_price", minimum=0.0, maximum=1.0, exclusive_min=True)
    if wallet["event_follow_min_avg_price"] > wallet["event_follow_max_avg_price"]:
        wallet["event_follow_min_avg_price"] = float(_source_value(row, wallet, "event_follow_min_avg_price", 0.20) or 0.20)
        wallet["event_follow_max_avg_price"] = float(_source_value(row, wallet, "event_follow_max_avg_price", 0.80) or 0.80)

    sports_trailing = _profile_section_for_projection(parsed_profile, "sports_trailing")
    _profile_bool(wallet, sports_trailing, "sports_trailing_stop_enabled", "enabled")
    _profile_float(wallet, sports_trailing, "sports_trailing_activation_pct", "activation_pct", minimum=0.0)
    _profile_float(wallet, sports_trailing, "sports_trailing_stop_pct", "stop_pct", minimum=0.0, maximum=100.0, exclusive_min=True)
    _profile_float(wallet, sports_trailing, "sports_trailing_floor_delta", "floor_delta", minimum=0.0)

    risk = _profile_section_for_projection(parsed_profile, "risk")
    _profile_float(wallet, risk, "reserved_cash_usdc", "reserved_cash_usdc", minimum=0.0)


def wallet_profile(wallet: dict[str, object] | None) -> dict[str, Any]:
    if not wallet:
        return {}
    profile = wallet.get("profile_json")
    return profile if isinstance(profile, dict) else {}


def wallet_profile_section(wallet: dict[str, object] | None, section: str) -> dict[str, Any]:
    profile = wallet_profile(wallet)
    value = profile.get(section)
    return value if isinstance(value, dict) else {}


def wallet_profile_has(wallet: dict[str, object] | None, section: str, key: str) -> bool:
    return key in wallet_profile_section(wallet, section)


def wallet_profile_bool(wallet: dict[str, object] | None, section: str, key: str, default: bool) -> bool:
    value = wallet_profile_section(wallet, section).get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, int | float):
        return bool(value)
    return default


def wallet_profile_float(wallet: dict[str, object] | None, section: str, key: str, default: float) -> float:
    try:
        return float(wallet_profile_section(wallet, section).get(key, default))
    except (TypeError, ValueError):
        return default


def wallet_profile_int(wallet: dict[str, object] | None, section: str, key: str, default: int) -> int:
    try:
        return int(wallet_profile_section(wallet, section).get(key, default))
    except (TypeError, ValueError):
        return default


def wallet_profile_list(
    wallet: dict[str, object] | None,
    section: str,
    key: str,
    default: Iterable[Any],
    *,
    lower: bool = False,
) -> list[str]:
    value = wallet_profile_section(wallet, section).get(key, default)
    if not isinstance(value, list | tuple):
        value = default
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return [item.lower() for item in cleaned] if lower else cleaned


def clean_market_types(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return list(MARKET_TYPES)
    if isinstance(values, str):
        values = [values]
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return [value for value in cleaned if value in MARKET_TYPES] or list(MARKET_TYPES)


def clean_weather_patterns(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return list(WEATHER_BRACKET_PATTERNS)
    if isinstance(values, str):
        values = [values]
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return [value for value in cleaned if value in WEATHER_BRACKET_PATTERNS] or list(WEATHER_BRACKET_PATTERNS)


def _wallet_value(wallet: Any, key: str, default: Any = None) -> Any:
    if isinstance(wallet, Mapping):
        return wallet.get(key, default)
    return getattr(wallet, key, default)


def _source_value(row: Mapping[str, Any] | None, wallet: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if row is not None:
        try:
            return row[key]
        except (KeyError, IndexError):
            pass
    return wallet.get(key, default)


def _wallet_profile_section_payload(raw: Any, name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WalletProfileError(f"{name} must be a JSON object")
    return {str(key): _json_compatible(value, f"{name}.{key}") for key, value in raw.items()}


def _json_compatible(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item, f"{name}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item, name) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise WalletProfileError(f"{name} must be JSON-compatible")


def _validate_wallet_profile_numbers(profile: dict[str, Any], name: str) -> None:
    for section_key in WALLET_PROFILE_SECTIONS:
        if not isinstance(profile.get(section_key), dict):
            raise WalletProfileError(f"{name}.{section_key} must be a JSON object")

    market_filters = profile["market_filters"]
    if "allowed_market_types" in market_filters:
        market_filters["allowed_market_types"] = list(
            _market_types(market_filters["allowed_market_types"], f"{name}.market_filters.allowed_market_types")
        )

    weather_bracket = profile["weather_bracket"]
    _optional_profile_bool(weather_bracket, "enabled", f"{name}.weather_bracket")
    _optional_profile_bool(weather_bracket, "copy_source_leg_size", f"{name}.weather_bracket")
    _optional_profile_float(weather_bracket, "buy_size_usdc", f"{name}.weather_bracket", minimum=0.0, exclusive_min=True)
    _optional_profile_float(weather_bracket, "stop_loss_pct", f"{name}.weather_bracket", minimum=0.0)
    _optional_profile_int(weather_bracket, "max_open_events", f"{name}.weather_bracket", minimum=0)
    if "allowed_patterns" in weather_bracket:
        weather_bracket["allowed_patterns"] = list(
            _weather_patterns(weather_bracket["allowed_patterns"], f"{name}.weather_bracket.allowed_patterns")
        )

    repeat_buy = profile["repeat_buy"]
    _optional_profile_bool(repeat_buy, "enabled", f"{name}.repeat_buy")
    _optional_profile_float(repeat_buy, "buy_size_usdc", f"{name}.repeat_buy", minimum=0.0, exclusive_min=True)
    _optional_profile_float(repeat_buy, "stop_loss_pct", f"{name}.repeat_buy", minimum=0.0)
    _optional_profile_float(repeat_buy, "min_source_notional_usdc", f"{name}.repeat_buy", minimum=0.0)
    _optional_profile_int(repeat_buy, "min_buy_count", f"{name}.repeat_buy", minimum=2)
    _optional_profile_float(repeat_buy, "min_avg_price", f"{name}.repeat_buy", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(repeat_buy, "max_avg_price", f"{name}.repeat_buy", minimum=0.0, maximum=1.0, exclusive_min=True)
    if repeat_buy["min_avg_price"] > repeat_buy["max_avg_price"]:
        raise WalletProfileError(f"{name}.repeat_buy price band must be within 0-1")
    _optional_profile_float(repeat_buy, "max_total_exposure_usdc", f"{name}.repeat_buy", minimum=0.0)
    _optional_profile_string_list(repeat_buy, "blocked_title_patterns", f"{name}.repeat_buy")
    _optional_profile_string_list(repeat_buy, "allowed_sports", f"{name}.repeat_buy", lower=True)
    _optional_profile_string_list(repeat_buy, "allowed_bet_types", f"{name}.repeat_buy", lower=True)

    event_follow = profile["event_follow"]
    _optional_profile_bool(event_follow, "enabled", f"{name}.event_follow")
    _optional_profile_float(event_follow, "buy_size_usdc", f"{name}.event_follow", minimum=0.0, exclusive_min=True)
    _optional_profile_float(event_follow, "max_event_exposure_usdc", f"{name}.event_follow", minimum=0.0, exclusive_min=True)
    _optional_profile_float(event_follow, "max_total_exposure_usdc", f"{name}.event_follow", minimum=0.0, exclusive_min=True)
    _optional_profile_float(event_follow, "min_source_trade_usdc", f"{name}.event_follow", minimum=0.0)
    _optional_profile_float(event_follow, "min_event_source_notional_usdc", f"{name}.event_follow", minimum=0.0)
    _optional_profile_int(event_follow, "min_event_buy_count", f"{name}.event_follow", minimum=1)
    _optional_profile_float(event_follow, "min_avg_price", f"{name}.event_follow", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(event_follow, "max_avg_price", f"{name}.event_follow", minimum=0.0, maximum=1.0, exclusive_min=True)
    if event_follow["min_avg_price"] > event_follow["max_avg_price"]:
        raise WalletProfileError(f"{name}.event_follow price band must be within 0-1")
    _optional_profile_string_list(event_follow, "allowed_sports", f"{name}.event_follow", lower=True)
    _optional_profile_string_list(event_follow, "allowed_bet_types", f"{name}.event_follow", lower=True)

    sports_trailing = profile["sports_trailing"]
    _optional_profile_bool(sports_trailing, "enabled", f"{name}.sports_trailing")
    _optional_profile_float(sports_trailing, "activation_pct", f"{name}.sports_trailing", minimum=0.0)
    _optional_profile_float(sports_trailing, "stop_pct", f"{name}.sports_trailing", minimum=0.0, maximum=100.0, exclusive_min=True)
    if sports_trailing["stop_pct"] >= 100:
        raise WalletProfileError(f"{name}.sports_trailing.stop_pct must be between 0 and 100")
    _optional_profile_float(sports_trailing, "floor_delta", f"{name}.sports_trailing", minimum=0.0)

    risk = profile["risk"]
    _optional_profile_float(risk, "reserved_cash_usdc", f"{name}.risk", minimum=0.0)
    _optional_profile_bool(risk, "local_stop_loss_enabled", f"{name}.risk")

    source_follow = profile["source_follow"]
    filter_copy = profile["filter_copy"]
    event_book = profile["event_book"]
    fixed_buy = profile["fixed_buy"]
    binary_hedge = profile["binary_hedge"]
    limit_copy = profile["limit_copy"]
    tier_sizing = profile["tier_sizing"]
    esports_repeat_buy = profile["esports_repeat_buy"]
    high_conviction = profile["high_conviction"]
    strategy = profile["strategy"]
    _optional_profile_bool(strategy, "custom", f"{name}.strategy")
    _optional_profile_bool(strategy, "copy_buys_enabled", f"{name}.strategy")
    _optional_profile_float(source_follow, "copy_scale", f"{name}.source_follow", minimum=0.0)
    _optional_profile_bool(source_follow, "enabled", f"{name}.source_follow")
    _optional_profile_float(source_follow, "max_asset_exposure_usdc", f"{name}.source_follow", minimum=0.0, exclusive_min=True)
    _optional_profile_float(source_follow, "min_trade_usdc", f"{name}.source_follow", minimum=0.0)
    _optional_profile_bool(filter_copy, "enabled", f"{name}.filter_copy")
    _optional_profile_float(filter_copy, "max_source_price", f"{name}.filter_copy", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(filter_copy, "min_source_price", f"{name}.filter_copy", minimum=0.0, maximum=1.0, exclusive_min=True)
    if filter_copy["min_source_price"] > filter_copy["max_source_price"]:
        raise WalletProfileError(f"{name}.filter_copy price band must be within 0-1")
    _optional_profile_float(filter_copy, "min_single_fill_usdc", f"{name}.filter_copy", minimum=0.0)
    _optional_profile_float(filter_copy, "min_cumulative_source_usdc", f"{name}.filter_copy", minimum=0.0)
    _optional_profile_int(filter_copy, "accumulation_window_seconds", f"{name}.filter_copy", minimum=0)
    _optional_profile_float(filter_copy, "daily_deployed_cap_usdc", f"{name}.filter_copy", minimum=0.0)
    _optional_profile_float(filter_copy, "source_sell_exit_fraction", f"{name}.filter_copy", minimum=0.0, maximum=1.0)
    _optional_profile_float(filter_copy, "same_event_hedge_max_fraction", f"{name}.filter_copy", minimum=0.0, maximum=1.0)
    _optional_profile_bool(filter_copy, "scale_up_enabled", f"{name}.filter_copy")
    _optional_profile_float(filter_copy, "scale_up_max_position_usdc", f"{name}.filter_copy", minimum=0.0)
    _optional_profile_float(filter_copy, "in_event_stop_loss_pct", f"{name}.filter_copy", minimum=0.0, maximum=100.0)
    _optional_profile_string_list(filter_copy, "allowed_sports", f"{name}.filter_copy", lower=True)
    _optional_profile_string_list(filter_copy, "paused_sports", f"{name}.filter_copy", lower=True)
    _optional_profile_string_list(filter_copy, "allowed_bet_types", f"{name}.filter_copy", lower=True)
    _optional_profile_string_list(filter_copy, "blocked_title_patterns", f"{name}.filter_copy", lower=True)
    _validate_filter_copy_sport_rules(filter_copy, f"{name}.filter_copy")
    _validate_filter_copy_rebalance(filter_copy, f"{name}.filter_copy")
    _optional_profile_tiers(filter_copy, f"{name}.filter_copy")
    _optional_profile_float(event_book, "min_source_notional_usdc", f"{name}.event_book", minimum=0.0)
    _optional_profile_float(event_book, "min_avg_price", f"{name}.event_book", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(event_book, "max_avg_price", f"{name}.event_book", minimum=0.0, maximum=1.0, exclusive_min=True)
    if "min_avg_price" in event_book and "max_avg_price" in event_book and event_book["min_avg_price"] > event_book["max_avg_price"]:
        raise WalletProfileError(f"{name}.event_book price band must be within 0-1")
    _optional_profile_float(event_book, "min_dominance_share", f"{name}.event_book", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(event_book, "min_dominance_ratio", f"{name}.event_book", minimum=0.0, exclusive_min=True)
    _optional_profile_float(event_book, "planner_rn1_max_rebalance_order_usdc", f"{name}.event_book", minimum=0.0)
    _optional_profile_float(event_book, "planner_rn1_soccer_min_event_source_usdc", f"{name}.event_book", minimum=0.0)
    _optional_profile_float(event_book, "planner_rn1_mlb_min_event_source_usdc", f"{name}.event_book", minimum=0.0)
    _optional_profile_float(event_book, "planner_fresh_min_price", f"{name}.event_book", minimum=0.0, maximum=1.0)
    _optional_profile_float(event_book, "planner_fresh_max_price", f"{name}.event_book", minimum=0.0, maximum=1.0)
    if (
        "planner_fresh_min_price" in event_book
        and "planner_fresh_max_price" in event_book
        and event_book["planner_fresh_min_price"] > event_book["planner_fresh_max_price"]
    ):
        raise WalletProfileError(f"{name}.event_book planner fresh price band must be within 0-1")
    _optional_profile_float(event_book, "planner_rebalance_min_price", f"{name}.event_book", minimum=0.0, maximum=1.0)
    _optional_profile_float(event_book, "planner_rebalance_max_price", f"{name}.event_book", minimum=0.0, maximum=1.0)
    if (
        "planner_rebalance_min_price" in event_book
        and "planner_rebalance_max_price" in event_book
        and event_book["planner_rebalance_min_price"] > event_book["planner_rebalance_max_price"]
    ):
        raise WalletProfileError(f"{name}.event_book planner rebalance price band must be within 0-1")
    _optional_profile_float(
        event_book,
        "planner_rebalance_min_worst_case_improvement_fraction",
        f"{name}.event_book",
        minimum=0.0,
        maximum=1.0,
    )
    _optional_profile_bool(fixed_buy, "enabled", f"{name}.fixed_buy")
    _optional_profile_float(fixed_buy, "buy_size_usdc", f"{name}.fixed_buy", minimum=0.0, exclusive_min=True)
    if "market_types" in fixed_buy:
        fixed_buy["market_types"] = list(_market_types(fixed_buy["market_types"], f"{name}.fixed_buy.market_types"))
    _optional_profile_bool(binary_hedge, "enabled", f"{name}.binary_hedge")
    _optional_profile_float(limit_copy, "limit_price_premium", f"{name}.limit_copy", minimum=0.0)
    _optional_profile_float(limit_copy, "limit_price_multiple", f"{name}.limit_copy", minimum=0.0, exclusive_min=True)
    _optional_profile_float(limit_copy, "source_copy_scale", f"{name}.limit_copy", minimum=0.0)
    _optional_profile_tiers(tier_sizing, f"{name}.tier_sizing")
    _optional_profile_int(esports_repeat_buy, "min_buy_count", f"{name}.esports_repeat_buy", minimum=1)
    _optional_profile_float(esports_repeat_buy, "min_source_notional_usdc", f"{name}.esports_repeat_buy", minimum=0.0)
    _optional_profile_float(esports_repeat_buy, "min_avg_price", f"{name}.esports_repeat_buy", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(esports_repeat_buy, "max_avg_price", f"{name}.esports_repeat_buy", minimum=0.0, maximum=1.0, exclusive_min=True)
    if (
        "min_avg_price" in esports_repeat_buy
        and "max_avg_price" in esports_repeat_buy
        and esports_repeat_buy["min_avg_price"] > esports_repeat_buy["max_avg_price"]
    ):
        raise WalletProfileError(f"{name}.esports_repeat_buy price band must be within 0-1")
    _optional_profile_string_list(esports_repeat_buy, "allowed_bet_types", f"{name}.esports_repeat_buy", lower=True)
    _optional_profile_int(high_conviction, "min_buy_count", f"{name}.high_conviction", minimum=1)
    _optional_profile_float(high_conviction, "min_source_notional_usdc", f"{name}.high_conviction", minimum=0.0)
    _optional_profile_float(high_conviction, "min_avg_price", f"{name}.high_conviction", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(high_conviction, "max_avg_price", f"{name}.high_conviction", minimum=0.0, maximum=1.0, exclusive_min=True)
    if "min_avg_price" in high_conviction and "max_avg_price" in high_conviction and high_conviction["min_avg_price"] > high_conviction["max_avg_price"]:
        raise WalletProfileError(f"{name}.high_conviction price band must be within 0-1")


def _validate_filter_copy_sport_rules(filter_copy: dict[str, Any], name: str) -> None:
    if "sport_rules" not in filter_copy:
        return
    sport_rules = filter_copy["sport_rules"]
    if not isinstance(sport_rules, dict):
        raise WalletProfileError(f"{name}.sport_rules must be a JSON object")
    cleaned: dict[str, dict[str, Any]] = {}
    for raw_sport, raw_rule in sport_rules.items():
        sport = str(raw_sport).strip().lower()
        if not sport:
            continue
        if not isinstance(raw_rule, dict):
            raise WalletProfileError(f"{name}.sport_rules.{sport} must be a JSON object")
        rule = {str(key): _json_compatible(value, f"{name}.sport_rules.{sport}.{key}") for key, value in raw_rule.items()}
        rule_name = f"{name}.sport_rules.{sport}"
        _optional_profile_bool(rule, "enabled", rule_name)
        _optional_profile_bool(rule, "require_event_book_dominant", rule_name)
        _optional_profile_int(rule, "min_buy_count", rule_name, minimum=1)
        _optional_profile_float(rule, "min_source_notional_usdc", rule_name, minimum=0.0)
        _optional_profile_float(rule, "min_price", rule_name, minimum=0.0, maximum=1.0)
        _optional_profile_float(rule, "max_price", rule_name, minimum=0.0, maximum=1.0, exclusive_min=True)
        _optional_profile_float(rule, "extended_min_price", rule_name, minimum=0.0, maximum=1.0)
        _optional_profile_float(rule, "extended_max_price", rule_name, minimum=0.0, maximum=1.0, exclusive_min=True)
        _optional_profile_float(rule, "buy_size_usdc", rule_name, minimum=0.0, exclusive_min=True)
        _optional_profile_float(rule, "extended_buy_size_usdc", rule_name, minimum=0.0, exclusive_min=True)
        if "min_price" in rule and "max_price" in rule and rule["min_price"] > rule["max_price"]:
            raise WalletProfileError(f"{rule_name} price band must be within 0-1")
        if (
            "extended_min_price" in rule
            and "extended_max_price" in rule
            and rule["extended_min_price"] > rule["extended_max_price"]
        ):
            raise WalletProfileError(f"{rule_name} extended price band must be within 0-1")
        _optional_profile_string_list(rule, "allowed_bet_types", rule_name, lower=True)
        cleaned[sport] = rule
    filter_copy["sport_rules"] = cleaned


def _validate_filter_copy_rebalance(filter_copy: dict[str, Any], name: str) -> None:
    if "rebalance" not in filter_copy:
        return
    rebalance = filter_copy["rebalance"]
    if not isinstance(rebalance, dict):
        raise WalletProfileError(f"{name}.rebalance must be a JSON object")
    _optional_profile_bool(rebalance, "enabled", f"{name}.rebalance")
    _optional_profile_float(rebalance, "max_source_price", f"{name}.rebalance", minimum=0.0, maximum=1.0, exclusive_min=True)
    _optional_profile_float(
        rebalance,
        "strong_max_source_price",
        f"{name}.rebalance",
        minimum=0.0,
        maximum=1.0,
        exclusive_min=True,
    )
    _optional_profile_float(rebalance, "min_source_notional_usdc", f"{name}.rebalance", minimum=0.0)
    _optional_profile_float(rebalance, "strong_min_source_notional_usdc", f"{name}.rebalance", minimum=0.0)
    _optional_profile_float(rebalance, "min_event_share", f"{name}.rebalance", minimum=0.0, maximum=1.0)
    _optional_profile_float(rebalance, "strong_min_event_share", f"{name}.rebalance", minimum=0.0, maximum=1.0)
    _optional_profile_float(
        rebalance,
        "min_repair_to_existing_source_ratio",
        f"{name}.rebalance",
        minimum=0.0,
        exclusive_min=True,
    )
    _optional_profile_float(rebalance, "max_repair_buy_usdc", f"{name}.rebalance", minimum=0.0)
    _optional_profile_float(rebalance, "normal_event_cap_usdc", f"{name}.rebalance", minimum=0.0)
    _optional_profile_float(rebalance, "extra_repair_event_cap_usdc", f"{name}.rebalance", minimum=0.0)
    _optional_profile_string_list(rebalance, "allowed_sports", f"{name}.rebalance", lower=True)


def _optional_profile_tiers(section: dict[str, Any], name: str) -> None:
    if "tiers" not in section:
        return
    tiers = section["tiers"]
    if not isinstance(tiers, list):
        raise WalletProfileError(f"{name}.tiers must be a list")
    clean_tiers: list[dict[str, float]] = []
    for index, tier in enumerate(tiers):
        tier_name = f"{name}.tiers[{index}]"
        if not isinstance(tier, dict):
            raise WalletProfileError(f"{tier_name} must be a JSON object")
        clean_tier = {str(key): _json_compatible(value, f"{tier_name}.{key}") for key, value in tier.items()}
        _optional_profile_float(clean_tier, "min_price", tier_name, minimum=0.0, maximum=1.0)
        _optional_profile_float(clean_tier, "max_price", tier_name, minimum=0.0, maximum=1.0, exclusive_min=True)
        _optional_profile_float(clean_tier, "buy_size_usdc", tier_name, minimum=0.0, exclusive_min=True)
        for required_key in ("min_price", "max_price", "buy_size_usdc"):
            if required_key not in clean_tier:
                raise WalletProfileError(f"{tier_name}.{required_key} is required")
        if clean_tier["min_price"] > clean_tier["max_price"]:
            raise WalletProfileError(f"{tier_name} price band must be within 0-1")
        clean_tiers.append(clean_tier)
    section["tiers"] = clean_tiers


def _optional_profile_float(
    section: dict[str, Any],
    key: str,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_min: bool = False,
) -> None:
    if key not in section:
        return
    try:
        value = float(section[key])
    except (TypeError, ValueError) as exc:
        raise WalletProfileError(f"{name}.{key} must be numeric") from exc
    if minimum is not None and (value <= minimum if exclusive_min else value < minimum):
        comparator = "greater than" if exclusive_min else "at least"
        raise WalletProfileError(f"{name}.{key} must be {comparator} {minimum:g}")
    if maximum is not None and value > maximum:
        raise WalletProfileError(f"{name}.{key} must be at most {maximum:g}")
    section[key] = value


def _optional_profile_int(
    section: dict[str, Any],
    key: str,
    name: str,
    *,
    minimum: int | None = None,
) -> None:
    if key not in section:
        return
    try:
        value = int(section[key])
    except (TypeError, ValueError) as exc:
        raise WalletProfileError(f"{name}.{key} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise WalletProfileError(f"{name}.{key} must be at least {minimum:g}")
    section[key] = value


def _optional_profile_bool(section: dict[str, Any], key: str, name: str) -> None:
    if key not in section:
        return
    if not isinstance(section[key], bool):
        raise WalletProfileError(f"{name}.{key} must be true or false")


def _optional_profile_string_list(section: dict[str, Any], key: str, name: str, *, lower: bool = False) -> None:
    if key not in section:
        return
    values = _string_tuple(section[key], f"{name}.{key}")
    section[key] = [value.lower() for value in values] if lower else list(values)


def _market_types(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        raise WalletProfileError(f"{name} must be a list")
    values = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    unknown = [item for item in values if item not in MARKET_TYPES]
    if unknown:
        raise WalletProfileError(f"{name} contains unsupported market type: {', '.join(unknown)}")
    return values or MARKET_TYPES


def _weather_patterns(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        raise WalletProfileError(f"{name} must be a list")
    values = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    unknown = [item for item in values if item not in WEATHER_BRACKET_PATTERNS]
    if unknown:
        raise WalletProfileError(f"{name} contains unsupported weather bracket pattern: {', '.join(unknown)}")
    return values or WEATHER_BRACKET_PATTERNS


def _string_tuple(raw: Any, name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        raise WalletProfileError(f"{name} must be a list")
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _profile_section_for_projection(profile: dict[str, Any], key: str) -> dict[str, Any]:
    value = profile.get(key)
    if not isinstance(value, dict):
        return {}
    default_value = default_wallet_profile_json().get(key)
    if isinstance(default_value, dict) and value == default_value:
        return {}
    return value


def _profile_bool(wallet: dict[str, Any], section: dict[str, Any], wallet_key: str, profile_key: str) -> None:
    if profile_key in section and isinstance(section[profile_key], bool):
        wallet[wallet_key] = section[profile_key]


def _profile_float(
    wallet: dict[str, Any],
    section: dict[str, Any],
    wallet_key: str,
    profile_key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_min: bool = False,
) -> None:
    if profile_key not in section:
        return
    try:
        value = float(section[profile_key])
    except (TypeError, ValueError):
        return
    if minimum is not None and (value <= minimum if exclusive_min else value < minimum):
        return
    if maximum is not None and value > maximum:
        return
    wallet[wallet_key] = value


def _profile_int(
    wallet: dict[str, Any],
    section: dict[str, Any],
    wallet_key: str,
    profile_key: str,
    *,
    minimum: int | None = None,
) -> None:
    if profile_key not in section:
        return
    try:
        value = int(section[profile_key])
    except (TypeError, ValueError):
        return
    if minimum is not None and value < minimum:
        return
    wallet[wallet_key] = value


def _profile_list(
    wallet: dict[str, Any],
    section: dict[str, Any],
    wallet_key: str,
    profile_key: str,
    *,
    lower: bool = False,
) -> None:
    value = section.get(profile_key)
    if not isinstance(value, list | tuple):
        return
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    wallet[wallet_key] = [item.lower() for item in cleaned] if lower else cleaned
