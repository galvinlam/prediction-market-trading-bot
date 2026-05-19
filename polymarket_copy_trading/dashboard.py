from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
import yaml

from polymarket_copy_trading.config import (
    AppSettings,
    MARKET_TYPES,
    WEATHER_BRACKET_PATTERNS,
    default_wallet_profile_json,
    load_config,
    parse_wallet_profile_json,
)
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.paper import PaperExecutionError
from polymarket_copy_trading.store import Store


STATIC_DIR = Path(__file__).with_name("static")


def create_app(*, store: Store, config: AppSettings | None = None, config_path: Path | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    config_state = {"settings": config}

    @app.after_request
    def no_store_app_shell(response):
        path = request.path
        if path == "/" or path == "/service-worker.js" or path == "/manifest.webmanifest" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(STATIC_DIR, "manifest.webmanifest")

    @app.get("/service-worker.js")
    def service_worker():
        return send_from_directory(STATIC_DIR, "service-worker.js")

    @app.get("/api/overview")
    def overview():
        return jsonify(store.overview())

    @app.get("/api/holdings")
    def holdings():
        return jsonify({"holdings": store.list_positions()})

    @app.post("/api/holdings/sell")
    def sell_holding():
        settings = _current_settings()
        if settings is None:
            return jsonify({"error": "manual sell requires dashboard config"}), 400
        if not settings.mode.paper_trading:
            return jsonify({"error": "manual sell is only enabled for paper trading"}), 400
        payload = request.get_json(silent=True) or {}
        asset_id = str(payload.get("asset_id", "")).strip()
        source_wallet = str(payload.get("source_wallet", "")).strip()
        if not asset_id or not source_wallet:
            return jsonify({"error": "asset_id and source_wallet are required"}), 400

        engine = CopyTradingEngine(config=settings, store=store)
        try:
            sold = engine.process_manual_sell(asset_id=asset_id, source_wallet=source_wallet)
        except PaperExecutionError as exc:
            return jsonify({"error": str(exc)}), 400
        if not sold:
            return jsonify({"error": "open holding was not found or could not be sold"}), 404
        return jsonify(
            {
                "sold": True,
                "overview": store.overview(),
                "holdings": store.list_positions(),
                "closed_positions": store.list_closed_positions(),
            }
        )

    @app.get("/api/closed-positions")
    def closed_positions():
        return jsonify({"closed_positions": store.list_closed_positions()})

    @app.get("/api/sports-brackets")
    def sports_brackets():
        return jsonify({"sports_brackets": store.list_sports_brackets()})

    @app.get("/api/trades")
    def trades():
        raw_limit = request.args.get("limit", "250")
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 250
        return jsonify({"trades": store.list_trades(limit=limit)})

    @app.get("/api/skip-reasons")
    def skip_reasons():
        return jsonify({"skip_reasons": store.skip_reason_summary()})

    @app.get("/api/pnl")
    def pnl():
        settings = _current_settings()
        starting_cash = settings.paper.starting_cash_usdc if settings is not None else None
        return jsonify(store.pnl_summary(starting_cash_usdc=starting_cash))

    @app.get("/api/performance")
    def performance():
        raw_hours = request.args.get("hours", "24")
        try:
            hours = int(raw_hours)
        except ValueError:
            hours = 24
        return jsonify(store.wallet_performance_summary(hours=hours))

    @app.get("/api/wallets")
    def wallets():
        return jsonify({"wallets": store.list_wallets()})

    @app.get("/api/wallet-profile/default")
    def default_wallet_profile():
        return jsonify({"default_wallet_profile_json": default_wallet_profile_json()})

    @app.post("/api/wallets")
    def add_wallet():
        payload = request.get_json(silent=True) or {}
        wallet = store.upsert_wallet(**_wallet_create_kwargs(payload))
        return jsonify({"wallet": store.get_wallet(wallet["address"]) or wallet}), 201

    @app.patch("/api/wallets/<address>")
    def edit_wallet(address: str):
        payload = request.get_json(silent=True) or {}
        current = store.get_wallet(address)
        if current is None:
            return jsonify({"error": "wallet not found"}), 404
        wallet = store.update_wallet(address, **_wallet_update_kwargs(payload, current))
        return jsonify({"wallet": store.get_wallet(wallet["address"]) or wallet})

    @app.delete("/api/wallets/<address>")
    def remove_wallet(address: str):
        store.delete_wallet(address)
        return jsonify({"deleted": True})

    @app.get("/api/settings")
    def settings():
        return jsonify({"settings": _settings_payload(_current_settings())})

    @app.patch("/api/settings")
    def update_settings():
        if config_path is None:
            return jsonify({"error": "settings editing requires a config file"}), 400
        payload = request.get_json(silent=True) or {}
        if bool(payload.get("live_trading", False)):
            return jsonify({"error": "real trading is disabled for the MVP"}), 400
        updated = update_config_file(config_path, payload)
        config_state["settings"] = updated
        return jsonify({"settings": _settings_payload(updated), "restart_required": True})

    @app.errorhandler(Exception)
    def handle_error(exc: Exception):
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description}), exc.code or 500
        app.logger.exception("dashboard request failed")
        return jsonify({"error": str(exc)}), 500

    def _current_settings() -> AppSettings | None:
        if config_path is not None:
            config_state["settings"] = load_config(config_path)
        return config_state["settings"]

    return app


EDITABLE_SETTINGS = {
    "paper_trading": ("mode", "paper_trading", bool),
    "copy_scale": ("sizing", "copy_scale", float),
    "max_trade_usdc": ("sizing", "max_trade_usdc", float),
    "max_position_usdc": ("sizing", "max_position_usdc", float),
    "min_trade_usdc": ("sizing", "min_trade_usdc", float),
    "max_entry_price_source_premium": ("sizing", "max_entry_price_source_premium", float),
    "max_entry_price_source_multiple": ("sizing", "max_entry_price_source_multiple", float),
    "starting_cash_usdc": ("paper", "starting_cash_usdc", float),
    "slippage_pct": ("paper", "slippage_pct", float),
    "settlement_slippage_pct": ("paper", "settlement_slippage_pct", float),
    "mirror_source_sells": ("exits", "mirror_source_sells", bool),
    "stop_loss_pct": ("exits", "stop_loss_pct", float),
    "take_profit_pct": ("exits", "take_profit_pct", float),
    "max_holding_minutes": ("exits", "max_holding_minutes", int),
    "ws_ping_interval_seconds": ("watcher", "ws_ping_interval_seconds", float),
    "ws_ping_timeout_seconds": ("watcher", "ws_ping_timeout_seconds", float),
    "ws_close_timeout_seconds": ("watcher", "ws_close_timeout_seconds", float),
    "ws_reconnect_max_seconds": ("watcher", "ws_reconnect_max_seconds", float),
    "price_monitor_enabled": ("price_monitor", "enabled", bool),
    "price_monitor_poll_interval_seconds": ("price_monitor", "poll_interval_seconds", float),
    "price_monitor_idle_poll_interval_seconds": ("price_monitor", "idle_poll_interval_seconds", float),
    "winner_capture_enabled": ("winner_capture", "enabled", bool),
    "winner_capture_entry_price_max": ("winner_capture", "entry_price_max", float),
    "winner_capture_recover_stake_multiple": ("winner_capture", "recover_stake_multiple", float),
    "winner_capture_first_scale_multiple": ("winner_capture", "first_scale_multiple", float),
    "winner_capture_first_scale_sell_pct": ("winner_capture", "first_scale_sell_pct", float),
    "winner_capture_high_price_threshold": ("winner_capture", "high_price_threshold", float),
    "winner_capture_high_price_sell_pct": ("winner_capture", "high_price_sell_pct", float),
    "winner_capture_runner_pct": ("winner_capture", "runner_pct", float),
    "winner_capture_trailing_drawdown_pct": ("winner_capture", "trailing_drawdown_pct", float),
    "winner_capture_high_price_absolute_trail": ("winner_capture", "high_price_absolute_trail", float),
}


PROFILE_SECTION_LEGACY_FIELDS = {
    "market_filters": ("allowed_market_types",),
    "weather_bracket": (
        "bracket_strategy_enabled",
        "bracket_buy_size_usdc",
        "bracket_stop_loss_pct",
        "bracket_max_open_events",
        "bracket_allowed_patterns",
    ),
    "repeat_buy": (
        "repeat_buy_strategy_enabled",
        "repeat_buy_size_usdc",
        "repeat_buy_stop_loss_pct",
        "repeat_buy_min_source_notional_usdc",
        "repeat_buy_min_buy_count",
        "repeat_buy_min_avg_price",
        "repeat_buy_max_avg_price",
        "repeat_buy_max_total_exposure_usdc",
        "repeat_buy_blocked_title_patterns",
        "repeat_buy_allowed_sports",
        "repeat_buy_allowed_bet_types",
    ),
    "event_follow": (
        "event_follow_strategy_enabled",
        "event_follow_buy_size_usdc",
        "event_follow_max_event_exposure_usdc",
        "event_follow_max_total_exposure_usdc",
        "event_follow_min_source_trade_usdc",
        "event_follow_min_event_source_notional_usdc",
        "event_follow_min_event_buy_count",
        "event_follow_min_avg_price",
        "event_follow_max_avg_price",
    ),
    "sports_trailing": (
        "sports_trailing_stop_enabled",
        "sports_trailing_activation_pct",
        "sports_trailing_stop_pct",
        "sports_trailing_floor_delta",
    ),
    "risk": ("reserved_cash_usdc",),
    "strategy": ("strategy_label",),
}


def update_config_file(config_path: Path, payload: dict[str, Any]) -> AppSettings:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    for public_key, value in payload.items():
        if public_key == "trading_mode":
            mode = str(value).strip().lower()
            if mode not in {"paper", "live"}:
                continue
            raw.setdefault("mode", {})
            raw["mode"]["trading_mode"] = mode
            raw["mode"]["paper_trading"] = mode == "paper"
            raw["mode"]["live_trading"] = mode == "live"
            continue
        if public_key == "live_trading":
            mode = "live" if bool(value) else "paper"
            raw.setdefault("mode", {})
            raw["mode"]["trading_mode"] = mode
            raw["mode"]["paper_trading"] = mode == "paper"
            raw["mode"]["live_trading"] = mode == "live"
            continue
        if public_key == "enabled_market_types":
            raw.setdefault("market_filters", {})
            raw["market_filters"]["enabled_market_types"] = _clean_market_types(value)
            continue
        if public_key not in EDITABLE_SETTINGS:
            continue
        section, key, caster = EDITABLE_SETTINGS[public_key]
        raw.setdefault(section, {})
        raw[section][key] = caster(value)
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(config_path)


def _settings_payload(config: AppSettings | None) -> dict[str, Any]:
    if config is None:
        return {}
    return {
        "trading_mode": config.mode.trading_mode,
        "paper_trading": config.mode.paper_trading,
        "live_trading": config.mode.live_trading,
        "copy_scale": config.sizing.copy_scale,
        "max_trade_usdc": config.sizing.max_trade_usdc,
        "max_position_usdc": config.sizing.max_position_usdc,
        "min_trade_usdc": config.sizing.min_trade_usdc,
        "max_entry_price_source_premium": config.sizing.max_entry_price_source_premium,
        "max_entry_price_source_multiple": config.sizing.max_entry_price_source_multiple,
        "starting_cash_usdc": config.paper.starting_cash_usdc,
        "slippage_pct": config.paper.slippage_pct,
        "settlement_slippage_pct": config.paper.settlement_slippage_pct,
        "mirror_source_sells": config.exits.mirror_source_sells,
        "stop_loss_pct": config.exits.stop_loss_pct,
        "take_profit_pct": config.exits.take_profit_pct,
        "max_holding_minutes": config.exits.max_holding_minutes,
        "ws_ping_interval_seconds": config.watcher.ws_ping_interval_seconds,
        "ws_ping_timeout_seconds": config.watcher.ws_ping_timeout_seconds,
        "ws_close_timeout_seconds": config.watcher.ws_close_timeout_seconds,
        "ws_reconnect_max_seconds": config.watcher.ws_reconnect_max_seconds,
        "price_monitor_enabled": config.price_monitor.enabled,
        "price_monitor_poll_interval_seconds": config.price_monitor.poll_interval_seconds,
        "price_monitor_idle_poll_interval_seconds": config.price_monitor.idle_poll_interval_seconds,
        "winner_capture_enabled": config.winner_capture.enabled,
        "winner_capture_entry_price_max": config.winner_capture.entry_price_max,
        "winner_capture_recover_stake_multiple": config.winner_capture.recover_stake_multiple,
        "winner_capture_first_scale_multiple": config.winner_capture.first_scale_multiple,
        "winner_capture_first_scale_sell_pct": config.winner_capture.first_scale_sell_pct,
        "winner_capture_high_price_threshold": config.winner_capture.high_price_threshold,
        "winner_capture_high_price_sell_pct": config.winner_capture.high_price_sell_pct,
        "winner_capture_runner_pct": config.winner_capture.runner_pct,
        "winner_capture_trailing_drawdown_pct": config.winner_capture.trailing_drawdown_pct,
        "winner_capture_high_price_absolute_trail": config.winner_capture.high_price_absolute_trail,
        "enabled_market_types": list(config.market_filters.enabled_market_types),
    }


def _wallet_create_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    kwargs = {
        "name": str(payload.get("name", "")),
        "address": str(payload.get("address", "")),
        "enabled": bool(payload.get("enabled", True)),
        "strategy_label": str(payload.get("strategy_label", "Standard")),
        "strategy_notes": str(payload.get("strategy_notes", "")),
        "allowed_market_types": payload.get("allowed_market_types"),
        "bracket_strategy_enabled": bool(payload.get("bracket_strategy_enabled", False)),
        "bracket_buy_size_usdc": float(payload.get("bracket_buy_size_usdc", 10.0)),
        "bracket_stop_loss_pct": float(payload.get("bracket_stop_loss_pct", 0.0)),
        "bracket_max_open_events": int(payload.get("bracket_max_open_events", 0)),
        "bracket_allowed_patterns": payload.get("bracket_allowed_patterns"),
        "repeat_buy_strategy_enabled": bool(payload.get("repeat_buy_strategy_enabled", False)),
        "repeat_buy_size_usdc": float(payload.get("repeat_buy_size_usdc", 5.0)),
        "repeat_buy_stop_loss_pct": float(payload.get("repeat_buy_stop_loss_pct", 0.0)),
        "repeat_buy_min_source_notional_usdc": float(payload.get("repeat_buy_min_source_notional_usdc", 0.0)),
        "repeat_buy_min_buy_count": int(payload.get("repeat_buy_min_buy_count", 2)),
        "repeat_buy_min_avg_price": float(payload.get("repeat_buy_min_avg_price", 0.01)),
        "repeat_buy_max_avg_price": float(payload.get("repeat_buy_max_avg_price", 1.0)),
        "repeat_buy_max_total_exposure_usdc": float(payload.get("repeat_buy_max_total_exposure_usdc", 0.0)),
        "repeat_buy_blocked_title_patterns": payload.get("repeat_buy_blocked_title_patterns"),
        "repeat_buy_allowed_sports": payload.get("repeat_buy_allowed_sports"),
        "repeat_buy_allowed_bet_types": payload.get("repeat_buy_allowed_bet_types"),
        "event_follow_strategy_enabled": bool(payload.get("event_follow_strategy_enabled", False)),
        "event_follow_buy_size_usdc": float(payload.get("event_follow_buy_size_usdc", 2.0)),
        "event_follow_max_event_exposure_usdc": float(payload.get("event_follow_max_event_exposure_usdc", 4.0)),
        "event_follow_max_total_exposure_usdc": float(payload.get("event_follow_max_total_exposure_usdc", 50.0)),
        "event_follow_min_source_trade_usdc": float(payload.get("event_follow_min_source_trade_usdc", 20.0)),
        "event_follow_min_event_source_notional_usdc": float(payload.get("event_follow_min_event_source_notional_usdc", 250.0)),
        "event_follow_min_event_buy_count": int(payload.get("event_follow_min_event_buy_count", 3)),
        "event_follow_min_avg_price": float(payload.get("event_follow_min_avg_price", 0.20)),
        "event_follow_max_avg_price": float(payload.get("event_follow_max_avg_price", 0.80)),
        "sports_trailing_stop_enabled": bool(payload.get("sports_trailing_stop_enabled", False)),
        "sports_trailing_activation_pct": float(payload.get("sports_trailing_activation_pct", 35.0)),
        "sports_trailing_stop_pct": float(payload.get("sports_trailing_stop_pct", 25.0)),
        "sports_trailing_floor_delta": float(payload.get("sports_trailing_floor_delta", 0.03)),
        "reserved_cash_usdc": float(payload.get("reserved_cash_usdc", 0.0)),
        "profile_json": payload.get("profile_json"),
    }
    kwargs["profile_json"] = _wallet_profile_from_payload(payload, kwargs)
    _drop_explicit_profile_legacy_fields(kwargs, payload)
    return kwargs


def _wallet_update_kwargs(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    kwargs = {
        "name": payload.get("name"),
        "enabled": payload.get("enabled") if "enabled" in payload else None,
        "strategy_label": payload.get("strategy_label") if "strategy_label" in payload else None,
        "strategy_notes": payload.get("strategy_notes") if "strategy_notes" in payload else None,
        "allowed_market_types": payload.get("allowed_market_types"),
        "bracket_strategy_enabled": payload.get("bracket_strategy_enabled") if "bracket_strategy_enabled" in payload else None,
        "bracket_buy_size_usdc": payload.get("bracket_buy_size_usdc") if "bracket_buy_size_usdc" in payload else None,
        "bracket_stop_loss_pct": payload.get("bracket_stop_loss_pct") if "bracket_stop_loss_pct" in payload else None,
        "bracket_max_open_events": payload.get("bracket_max_open_events") if "bracket_max_open_events" in payload else None,
        "bracket_allowed_patterns": payload.get("bracket_allowed_patterns") if "bracket_allowed_patterns" in payload else None,
        "repeat_buy_strategy_enabled": payload.get("repeat_buy_strategy_enabled") if "repeat_buy_strategy_enabled" in payload else None,
        "repeat_buy_size_usdc": payload.get("repeat_buy_size_usdc") if "repeat_buy_size_usdc" in payload else None,
        "repeat_buy_stop_loss_pct": payload.get("repeat_buy_stop_loss_pct") if "repeat_buy_stop_loss_pct" in payload else None,
        "repeat_buy_min_source_notional_usdc": payload.get("repeat_buy_min_source_notional_usdc") if "repeat_buy_min_source_notional_usdc" in payload else None,
        "repeat_buy_min_buy_count": payload.get("repeat_buy_min_buy_count") if "repeat_buy_min_buy_count" in payload else None,
        "repeat_buy_min_avg_price": payload.get("repeat_buy_min_avg_price") if "repeat_buy_min_avg_price" in payload else None,
        "repeat_buy_max_avg_price": payload.get("repeat_buy_max_avg_price") if "repeat_buy_max_avg_price" in payload else None,
        "repeat_buy_max_total_exposure_usdc": payload.get("repeat_buy_max_total_exposure_usdc") if "repeat_buy_max_total_exposure_usdc" in payload else None,
        "repeat_buy_blocked_title_patterns": payload.get("repeat_buy_blocked_title_patterns") if "repeat_buy_blocked_title_patterns" in payload else None,
        "repeat_buy_allowed_sports": payload.get("repeat_buy_allowed_sports") if "repeat_buy_allowed_sports" in payload else None,
        "repeat_buy_allowed_bet_types": payload.get("repeat_buy_allowed_bet_types") if "repeat_buy_allowed_bet_types" in payload else None,
        "event_follow_strategy_enabled": payload.get("event_follow_strategy_enabled") if "event_follow_strategy_enabled" in payload else None,
        "event_follow_buy_size_usdc": payload.get("event_follow_buy_size_usdc") if "event_follow_buy_size_usdc" in payload else None,
        "event_follow_max_event_exposure_usdc": payload.get("event_follow_max_event_exposure_usdc") if "event_follow_max_event_exposure_usdc" in payload else None,
        "event_follow_max_total_exposure_usdc": payload.get("event_follow_max_total_exposure_usdc") if "event_follow_max_total_exposure_usdc" in payload else None,
        "event_follow_min_source_trade_usdc": payload.get("event_follow_min_source_trade_usdc") if "event_follow_min_source_trade_usdc" in payload else None,
        "event_follow_min_event_source_notional_usdc": payload.get("event_follow_min_event_source_notional_usdc") if "event_follow_min_event_source_notional_usdc" in payload else None,
        "event_follow_min_event_buy_count": payload.get("event_follow_min_event_buy_count") if "event_follow_min_event_buy_count" in payload else None,
        "event_follow_min_avg_price": payload.get("event_follow_min_avg_price") if "event_follow_min_avg_price" in payload else None,
        "event_follow_max_avg_price": payload.get("event_follow_max_avg_price") if "event_follow_max_avg_price" in payload else None,
        "sports_trailing_stop_enabled": payload.get("sports_trailing_stop_enabled") if "sports_trailing_stop_enabled" in payload else None,
        "sports_trailing_activation_pct": payload.get("sports_trailing_activation_pct") if "sports_trailing_activation_pct" in payload else None,
        "sports_trailing_stop_pct": payload.get("sports_trailing_stop_pct") if "sports_trailing_stop_pct" in payload else None,
        "sports_trailing_floor_delta": payload.get("sports_trailing_floor_delta") if "sports_trailing_floor_delta" in payload else None,
        "reserved_cash_usdc": payload.get("reserved_cash_usdc") if "reserved_cash_usdc" in payload else None,
        "profile_json": payload.get("profile_json") if "profile_json" in payload else None,
    }
    kwargs["profile_json"] = _wallet_profile_from_payload(payload, kwargs, current)
    _drop_explicit_profile_legacy_fields(kwargs, payload)
    return kwargs


def _wallet_profile_from_payload(
    payload: dict[str, Any],
    kwargs: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit_profile = "profile_json" in payload
    profile_raw = payload.get("profile_json") if "profile_json" in payload else (current or {}).get("profile_json")
    raw_profile = _raw_profile_object(profile_raw)
    profile = _profile_patch_from_raw(raw_profile) if explicit_profile else parse_wallet_profile_json(profile_raw)
    if explicit_profile:
        return profile

    allowed_market_types = _effective_wallet_value("allowed_market_types", kwargs, current)
    if allowed_market_types is not None:
        profile.setdefault("market_filters", {})["allowed_market_types"] = allowed_market_types

    _merge_legacy_section(
        profile,
        raw_profile,
        kwargs,
        current,
        explicit_profile,
        "weather_bracket",
        {
            "enabled": "bracket_strategy_enabled",
            "buy_size_usdc": "bracket_buy_size_usdc",
            "stop_loss_pct": "bracket_stop_loss_pct",
            "max_open_events": "bracket_max_open_events",
            "allowed_patterns": "bracket_allowed_patterns",
        },
    )
    _merge_legacy_section(
        profile,
        raw_profile,
        kwargs,
        current,
        explicit_profile,
        "repeat_buy",
        {
            "enabled": "repeat_buy_strategy_enabled",
            "buy_size_usdc": "repeat_buy_size_usdc",
            "stop_loss_pct": "repeat_buy_stop_loss_pct",
            "min_source_notional_usdc": "repeat_buy_min_source_notional_usdc",
            "min_buy_count": "repeat_buy_min_buy_count",
            "min_avg_price": "repeat_buy_min_avg_price",
            "max_avg_price": "repeat_buy_max_avg_price",
            "max_total_exposure_usdc": "repeat_buy_max_total_exposure_usdc",
            "blocked_title_patterns": "repeat_buy_blocked_title_patterns",
            "allowed_sports": "repeat_buy_allowed_sports",
            "allowed_bet_types": "repeat_buy_allowed_bet_types",
        },
    )
    _merge_legacy_section(
        profile,
        raw_profile,
        kwargs,
        current,
        explicit_profile,
        "event_follow",
        {
            "enabled": "event_follow_strategy_enabled",
            "buy_size_usdc": "event_follow_buy_size_usdc",
            "max_event_exposure_usdc": "event_follow_max_event_exposure_usdc",
            "max_total_exposure_usdc": "event_follow_max_total_exposure_usdc",
            "min_source_trade_usdc": "event_follow_min_source_trade_usdc",
            "min_event_source_notional_usdc": "event_follow_min_event_source_notional_usdc",
            "min_event_buy_count": "event_follow_min_event_buy_count",
            "min_avg_price": "event_follow_min_avg_price",
            "max_avg_price": "event_follow_max_avg_price",
        },
    )
    _merge_legacy_section(
        profile,
        raw_profile,
        kwargs,
        current,
        explicit_profile,
        "sports_trailing",
        {
            "enabled": "sports_trailing_stop_enabled",
            "activation_pct": "sports_trailing_activation_pct",
            "stop_pct": "sports_trailing_stop_pct",
            "floor_delta": "sports_trailing_floor_delta",
        },
    )
    _merge_legacy_section(
        profile,
        raw_profile,
        kwargs,
        current,
        explicit_profile,
        "risk",
        {"reserved_cash_usdc": "reserved_cash_usdc"},
    )
    return profile


def _profile_patch_from_raw(raw_profile: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_wallet_profile_json(raw_profile)
    patch: dict[str, Any] = {}
    for key, value in raw_profile.items():
        clean_key = str(key)
        if clean_key == "version":
            patch["version"] = parsed["version"]
        elif isinstance(value, dict):
            parsed_section = parsed.get(clean_key)
            if isinstance(parsed_section, dict):
                patch[clean_key] = {str(section_key): parsed_section.get(str(section_key)) for section_key in value}
        else:
            patch[clean_key] = parsed.get(clean_key)
    return patch


def _profile_section(profile: dict[str, Any], key: str) -> dict[str, Any]:
    section = profile.get(key)
    return section if isinstance(section, dict) else {}


def _raw_profile_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = yaml.safe_load(value)
        except yaml.YAMLError:
            return {}
    return value if isinstance(value, dict) else {}


def _merge_legacy_section(
    profile: dict[str, Any],
    raw_profile: dict[str, Any],
    kwargs: dict[str, Any],
    current: dict[str, Any] | None,
    explicit_profile: bool,
    section_name: str,
    key_map: dict[str, str],
) -> None:
    if explicit_profile and section_name in raw_profile:
        return
    section = profile.setdefault(section_name, {})
    for profile_key, wallet_key in key_map.items():
        value = _effective_wallet_value(wallet_key, kwargs, current)
        if value is not None:
            section[profile_key] = value


def _effective_wallet_value(wallet_key: str, kwargs: dict[str, Any], current: dict[str, Any] | None) -> Any:
    value = kwargs.get(wallet_key)
    if value is not None:
        return value
    if current is not None:
        return current.get(wallet_key)
    return None


def _drop_explicit_profile_legacy_fields(kwargs: dict[str, Any], payload: dict[str, Any]) -> None:
    if "profile_json" not in payload:
        return
    for legacy_fields in PROFILE_SECTION_LEGACY_FIELDS.values():
        for wallet_key in legacy_fields:
            kwargs.pop(wallet_key, None)


def _clean_market_types(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(MARKET_TYPES)
    cleaned = [str(item).strip().lower() for item in value if str(item).strip().lower() in MARKET_TYPES]
    return cleaned or list(MARKET_TYPES)


def _clean_weather_patterns(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(WEATHER_BRACKET_PATTERNS)
    cleaned = [str(item).strip().lower() for item in value if str(item).strip().lower() in WEATHER_BRACKET_PATTERNS]
    return cleaned or list(WEATHER_BRACKET_PATTERNS)
