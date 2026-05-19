from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Any

import yaml

from polymarket_copy_trading.wallet_profile import (
    MARKET_TYPES,
    WEATHER_BRACKET_PATTERNS,
    WalletProfileError,
    default_wallet_profile_json as _default_wallet_profile_json,
    parse_wallet_profile_json as _parse_wallet_profile_json,
    wallet_profile_json_from_wallet_config as _wallet_profile_json_from_wallet_config,
)


WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class ConfigError(ValueError):
    """Raised when local runtime configuration is unsafe or invalid."""


def default_wallet_profile_json() -> dict[str, Any]:
    return _default_wallet_profile_json()


def parse_wallet_profile_json(raw: Any, name: str = "profile_json") -> dict[str, Any]:
    try:
        return _parse_wallet_profile_json(raw, name)
    except WalletProfileError as exc:
        raise ConfigError(str(exc)) from exc


def wallet_profile_json_from_wallet_config(wallet: "WalletConfig", profile_json: Any = None) -> dict[str, Any]:
    try:
        return _wallet_profile_json_from_wallet_config(wallet, profile_json)
    except WalletProfileError as exc:
        raise ConfigError(str(exc)) from exc


@dataclass(frozen=True)
class ModeConfig:
    trading_mode: str = "paper"
    paper_trading: bool = True
    live_trading: bool = False


@dataclass(frozen=True)
class WalletConfig:
    name: str
    address: str
    enabled: bool = True
    strategy_label: str = "Standard"
    strategy_notes: str = ""
    allowed_market_types: tuple[str, ...] = MARKET_TYPES
    bracket_strategy_enabled: bool = False
    bracket_buy_size_usdc: float = 10.0
    bracket_stop_loss_pct: float = 0.0
    bracket_max_open_events: int = 0
    bracket_allowed_patterns: tuple[str, ...] = WEATHER_BRACKET_PATTERNS
    repeat_buy_strategy_enabled: bool = False
    repeat_buy_size_usdc: float = 5.0
    repeat_buy_stop_loss_pct: float = 0.0
    repeat_buy_min_source_notional_usdc: float = 0.0
    repeat_buy_min_buy_count: int = 2
    repeat_buy_min_avg_price: float = 0.01
    repeat_buy_max_avg_price: float = 1.0
    repeat_buy_max_total_exposure_usdc: float = 0.0
    repeat_buy_blocked_title_patterns: tuple[str, ...] = ()
    repeat_buy_allowed_sports: tuple[str, ...] = ()
    repeat_buy_allowed_bet_types: tuple[str, ...] = ()
    event_follow_strategy_enabled: bool = False
    event_follow_buy_size_usdc: float = 2.0
    event_follow_max_event_exposure_usdc: float = 4.0
    event_follow_max_total_exposure_usdc: float = 50.0
    event_follow_min_source_trade_usdc: float = 20.0
    event_follow_min_event_source_notional_usdc: float = 250.0
    event_follow_min_event_buy_count: int = 3
    event_follow_min_avg_price: float = 0.20
    event_follow_max_avg_price: float = 0.80
    sports_trailing_stop_enabled: bool = False
    sports_trailing_activation_pct: float = 35.0
    sports_trailing_stop_pct: float = 25.0
    sports_trailing_floor_delta: float = 0.03
    reserved_cash_usdc: float = 0.0
    profile_json: dict[str, Any] = field(default_factory=lambda: default_wallet_profile_json())


@dataclass(frozen=True)
class SizingConfig:
    strategy: str = "scaled_source"
    copy_scale: float = 1.0
    max_trade_usdc: float = 100.0
    max_position_usdc: float = 10.0
    min_trade_usdc: float = 5.0
    max_entry_price_source_premium: float = 0.25
    max_entry_price_source_multiple: float = 2.00


@dataclass(frozen=True)
class PaperConfig:
    starting_cash_usdc: float = 100.0
    slippage_pct: float = 5.0
    settlement_slippage_pct: float = 0.0


@dataclass(frozen=True)
class ExitConfig:
    mirror_source_sells: bool = True
    stop_loss_pct: float = 25.0
    take_profit_pct: float = 50.0
    max_holding_minutes: int = 1440
    market_profiles: dict[str, "ExitProfileConfig"] | None = None

    def profile_for(self, market_type: str | None) -> "ExitProfileConfig":
        fallback = ExitProfileConfig(
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            max_holding_minutes=self.max_holding_minutes,
        )
        profiles = self.market_profiles or {}
        return profiles.get((market_type or "other").lower(), fallback)


@dataclass(frozen=True)
class ExitProfileConfig:
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_minutes: int


@dataclass(frozen=True)
class MarketFilterConfig:
    enabled_market_types: tuple[str, ...] = MARKET_TYPES


@dataclass(frozen=True)
class WatcherConfig:
    exchange_contracts: tuple[str, ...] = ("ctf_exchange", "neg_risk_ctf_exchange")
    confirmations: int = 1
    backfill_blocks: int = 500
    ws_ping_interval_seconds: float = 15.0
    ws_ping_timeout_seconds: float = 45.0
    ws_close_timeout_seconds: float = 5.0
    ws_reconnect_max_seconds: float = 30.0


@dataclass(frozen=True)
class PriceMonitorConfig:
    enabled: bool = True
    poll_interval_seconds: float = 30.0
    idle_poll_interval_seconds: float = 300.0


@dataclass(frozen=True)
class WinnerCaptureConfig:
    enabled: bool = False
    entry_price_max: float = 0.35
    recover_stake_multiple: float = 2.0
    first_scale_multiple: float = 4.0
    first_scale_sell_pct: float = 35.0
    high_price_threshold: float = 0.50
    high_price_sell_pct: float = 50.0
    runner_pct: float = 15.0
    trailing_drawdown_pct: float = 30.0
    high_price_absolute_trail: float = 0.12
    sports_mid_entry_price_max: float = 0.70
    sports_mid_partial_price_threshold: float = 0.75
    sports_mid_partial_profit_pct: float = 35.0
    sports_mid_partial_stake_pct: float = 50.0
    sports_mid_full_stake_price_threshold: float = 0.85
    sports_mid_high_price_threshold: float = 0.92
    sports_mid_high_price_sell_pct: float = 75.0
    sports_mid_runner_pct: float = 15.0
    sports_dead_cut_price: float = 0.08
    sports_dead_cut_max_peak_gain_pct: float = 15.0


@dataclass(frozen=True)
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8789
    database_url: str = "sqlite:///data/polymarket-copy-trading.sqlite3"
    live_database_url: str = "sqlite:///data/polymarket-copy-trading-live.sqlite3"


@dataclass(frozen=True)
class AppSettings:
    mode: ModeConfig
    wallets: tuple[WalletConfig, ...]
    sizing: SizingConfig
    paper: PaperConfig
    exits: ExitConfig
    market_filters: MarketFilterConfig
    watcher: WatcherConfig
    price_monitor: PriceMonitorConfig
    winner_capture: WinnerCaptureConfig
    app: AppConfig


def load_config(path: str | Path) -> AppSettings:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    mode = _mode(raw.get("mode", {}))
    if mode.trading_mode == "paper" and not mode.paper_trading:
        raise ConfigError("paper_trading must be true when trading_mode is paper")
    if mode.trading_mode == "live" and mode.paper_trading:
        raise ConfigError("paper_trading must be false when trading_mode is live")

    wallets = _wallets(raw.get("wallets", []))
    return AppSettings(
        mode=mode,
        wallets=wallets,
        sizing=_sizing(raw.get("sizing", {})),
        paper=_paper(raw.get("paper", {})),
        exits=_exits(raw.get("exits", {})),
        market_filters=_market_filters(raw.get("market_filters", {})),
        watcher=_watcher(raw.get("watcher", {})),
        price_monitor=_price_monitor(raw.get("price_monitor", {})),
        winner_capture=_winner_capture(raw.get("winner_capture", {})),
        app=_app(raw.get("app", {})),
    )


def _mode(raw: Any) -> ModeConfig:
    data = _mapping(raw, "mode")
    explicit_mode = str(data.get("trading_mode", "")).strip().lower()
    if explicit_mode:
        if explicit_mode not in {"paper", "live"}:
            raise ConfigError("mode.trading_mode must be paper or live")
        return ModeConfig(
            trading_mode=explicit_mode,
            paper_trading=explicit_mode == "paper",
            live_trading=explicit_mode == "live",
        )
    paper_trading = bool(data.get("paper_trading", True))
    live_trading = bool(data.get("live_trading", False))
    if paper_trading and live_trading:
        raise ConfigError("paper_trading and live_trading cannot both be true")
    return ModeConfig(
        trading_mode="live" if live_trading else "paper",
        paper_trading=paper_trading,
        live_trading=live_trading,
    )


def _wallets(raw: Any) -> tuple[WalletConfig, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("wallets must contain at least one configured wallet")
    wallets: list[WalletConfig] = []
    for index, item in enumerate(raw):
        data = _mapping(item, f"wallets[{index}]")
        name = str(data.get("name", "")).strip()
        address = str(data.get("address", "")).strip()
        if not name:
            raise ConfigError(f"wallets[{index}] name is required")
        if not WALLET_RE.match(address):
            raise ConfigError(f"wallet {name} has invalid address")
        raw_profile_json = data.get("profile_json")
        has_profile_json = raw_profile_json is not None and raw_profile_json != ""
        wallets.append(
            WalletConfig(
                name=name,
                address=address.lower(),
                enabled=bool(data.get("enabled", True)),
                strategy_label=str(data.get("strategy_label", "Standard")).strip() or "Standard",
                strategy_notes=str(data.get("strategy_notes", "")).strip(),
                allowed_market_types=_market_types(data.get("allowed_market_types", MARKET_TYPES), f"wallets[{index}].allowed_market_types"),
                bracket_strategy_enabled=bool(data.get("bracket_strategy_enabled", False)),
                bracket_buy_size_usdc=_float(data, "bracket_buy_size_usdc", 10.0),
                bracket_stop_loss_pct=_float(data, "bracket_stop_loss_pct", 0.0),
                bracket_max_open_events=int(data.get("bracket_max_open_events", 0)),
                bracket_allowed_patterns=_weather_patterns(
                    data.get("bracket_allowed_patterns", WEATHER_BRACKET_PATTERNS),
                    f"wallets[{index}].bracket_allowed_patterns",
                ),
                repeat_buy_strategy_enabled=bool(data.get("repeat_buy_strategy_enabled", False)),
                repeat_buy_size_usdc=_float(data, "repeat_buy_size_usdc", 5.0),
                repeat_buy_stop_loss_pct=_float(data, "repeat_buy_stop_loss_pct", 0.0),
                repeat_buy_min_source_notional_usdc=_float(data, "repeat_buy_min_source_notional_usdc", 0.0),
                repeat_buy_min_buy_count=int(data.get("repeat_buy_min_buy_count", 2)),
                repeat_buy_min_avg_price=_float(data, "repeat_buy_min_avg_price", 0.01),
                repeat_buy_max_avg_price=_float(data, "repeat_buy_max_avg_price", 1.0),
                repeat_buy_max_total_exposure_usdc=_float(data, "repeat_buy_max_total_exposure_usdc", 0.0),
                repeat_buy_blocked_title_patterns=_string_tuple(
                    data.get("repeat_buy_blocked_title_patterns", []),
                    f"wallets[{index}].repeat_buy_blocked_title_patterns",
                ),
                repeat_buy_allowed_sports=_string_tuple(
                    data.get("repeat_buy_allowed_sports", []),
                    f"wallets[{index}].repeat_buy_allowed_sports",
                ),
                repeat_buy_allowed_bet_types=_string_tuple(
                    data.get("repeat_buy_allowed_bet_types", []),
                    f"wallets[{index}].repeat_buy_allowed_bet_types",
                ),
                event_follow_strategy_enabled=bool(data.get("event_follow_strategy_enabled", False)),
                event_follow_buy_size_usdc=_float(data, "event_follow_buy_size_usdc", 2.0),
                event_follow_max_event_exposure_usdc=_float(data, "event_follow_max_event_exposure_usdc", 4.0),
                event_follow_max_total_exposure_usdc=_float(data, "event_follow_max_total_exposure_usdc", 50.0),
                event_follow_min_source_trade_usdc=_float(data, "event_follow_min_source_trade_usdc", 20.0),
                event_follow_min_event_source_notional_usdc=_float(data, "event_follow_min_event_source_notional_usdc", 250.0),
                event_follow_min_event_buy_count=int(data.get("event_follow_min_event_buy_count", 3)),
                event_follow_min_avg_price=_float(data, "event_follow_min_avg_price", 0.20),
                event_follow_max_avg_price=_float(data, "event_follow_max_avg_price", 0.80),
                sports_trailing_stop_enabled=bool(data.get("sports_trailing_stop_enabled", False)),
                sports_trailing_activation_pct=_float(data, "sports_trailing_activation_pct", 35.0),
                sports_trailing_stop_pct=_float(data, "sports_trailing_stop_pct", 25.0),
                sports_trailing_floor_delta=_float(data, "sports_trailing_floor_delta", 0.03),
                reserved_cash_usdc=_float(data, "reserved_cash_usdc", 0.0),
                profile_json=parse_wallet_profile_json(raw_profile_json, f"wallets[{index}].profile_json"),
            )
        )
        wallets[-1] = replace(
            wallets[-1],
            profile_json=wallet_profile_json_from_wallet_config(
                wallets[-1],
                raw_profile_json if has_profile_json else None,
            ),
        )
        if wallets[-1].bracket_buy_size_usdc <= 0:
            raise ConfigError(f"wallets[{index}].bracket_buy_size_usdc must be positive")
        if wallets[-1].bracket_stop_loss_pct < 0:
            raise ConfigError(f"wallets[{index}].bracket_stop_loss_pct cannot be negative")
        if wallets[-1].bracket_max_open_events < 0:
            raise ConfigError(f"wallets[{index}].bracket_max_open_events cannot be negative")
        if wallets[-1].repeat_buy_size_usdc <= 0:
            raise ConfigError(f"wallets[{index}].repeat_buy_size_usdc must be positive")
        if wallets[-1].repeat_buy_stop_loss_pct < 0:
            raise ConfigError(f"wallets[{index}].repeat_buy_stop_loss_pct cannot be negative")
        if wallets[-1].repeat_buy_min_source_notional_usdc < 0:
            raise ConfigError(f"wallets[{index}].repeat_buy_min_source_notional_usdc cannot be negative")
        if wallets[-1].repeat_buy_min_buy_count < 2:
            raise ConfigError(f"wallets[{index}].repeat_buy_min_buy_count must be at least 2")
        if not 0 < wallets[-1].repeat_buy_min_avg_price <= wallets[-1].repeat_buy_max_avg_price <= 1:
            raise ConfigError(f"wallets[{index}].repeat_buy price band must be within 0-1")
        if wallets[-1].repeat_buy_max_total_exposure_usdc < 0:
            raise ConfigError(f"wallets[{index}].repeat_buy_max_total_exposure_usdc cannot be negative")
        if wallets[-1].event_follow_buy_size_usdc <= 0:
            raise ConfigError(f"wallets[{index}].event_follow_buy_size_usdc must be positive")
        if wallets[-1].event_follow_max_event_exposure_usdc <= 0:
            raise ConfigError(f"wallets[{index}].event_follow_max_event_exposure_usdc must be positive")
        if wallets[-1].event_follow_max_total_exposure_usdc <= 0:
            raise ConfigError(f"wallets[{index}].event_follow_max_total_exposure_usdc must be positive")
        if wallets[-1].event_follow_min_source_trade_usdc < 0:
            raise ConfigError(f"wallets[{index}].event_follow_min_source_trade_usdc cannot be negative")
        if wallets[-1].event_follow_min_event_source_notional_usdc < 0:
            raise ConfigError(f"wallets[{index}].event_follow_min_event_source_notional_usdc cannot be negative")
        if wallets[-1].event_follow_min_event_buy_count < 1:
            raise ConfigError(f"wallets[{index}].event_follow_min_event_buy_count must be at least 1")
        if not 0 < wallets[-1].event_follow_min_avg_price <= wallets[-1].event_follow_max_avg_price <= 1:
            raise ConfigError(f"wallets[{index}].event_follow price band must be within 0-1")
        if wallets[-1].sports_trailing_activation_pct < 0:
            raise ConfigError(f"wallets[{index}].sports_trailing_activation_pct cannot be negative")
        if not 0 < wallets[-1].sports_trailing_stop_pct < 100:
            raise ConfigError(f"wallets[{index}].sports_trailing_stop_pct must be between 0 and 100")
        if wallets[-1].sports_trailing_floor_delta < 0:
            raise ConfigError(f"wallets[{index}].sports_trailing_floor_delta cannot be negative")
        if wallets[-1].reserved_cash_usdc < 0:
            raise ConfigError(f"wallets[{index}].reserved_cash_usdc cannot be negative")
    return tuple(wallets)


def _sizing(raw: Any) -> SizingConfig:
    data = _mapping(raw, "sizing")
    config = SizingConfig(
        strategy=str(data.get("strategy", "scaled_source")),
        copy_scale=_float(data, "copy_scale", 1.0),
        max_trade_usdc=_float(data, "max_trade_usdc", 100.0),
        max_position_usdc=_float(data, "max_position_usdc", 10.0),
        min_trade_usdc=_float(data, "min_trade_usdc", 5.0),
        max_entry_price_source_premium=_float(data, "max_entry_price_source_premium", 0.25),
        max_entry_price_source_multiple=_float(data, "max_entry_price_source_multiple", 2.00),
    )
    if config.strategy != "scaled_source":
        raise ConfigError("sizing.strategy must be scaled_source for the MVP")
    if min(config.max_trade_usdc, config.max_position_usdc, config.min_trade_usdc) <= 0:
        raise ConfigError("sizing dollar limits must be positive")
    if config.max_entry_price_source_premium < 0:
        raise ConfigError("sizing.max_entry_price_source_premium cannot be negative")
    if config.max_entry_price_source_multiple < 1:
        raise ConfigError("sizing.max_entry_price_source_multiple must be at least 1")
    return config


def _paper(raw: Any) -> PaperConfig:
    data = _mapping(raw, "paper")
    config = PaperConfig(
        starting_cash_usdc=_float(data, "starting_cash_usdc", 100.0),
        slippage_pct=_float(data, "slippage_pct", 5.0),
        settlement_slippage_pct=_float(data, "settlement_slippage_pct", 0.0),
    )
    if config.starting_cash_usdc <= 0:
        raise ConfigError("paper.starting_cash_usdc must be positive")
    if config.slippage_pct < 0:
        raise ConfigError("paper.slippage_pct cannot be negative")
    if config.settlement_slippage_pct < 0:
        raise ConfigError("paper.settlement_slippage_pct cannot be negative")
    return config


def _exits(raw: Any) -> ExitConfig:
    data = _mapping(raw, "exits")
    profiles_raw = _mapping(data.get("market_profiles", {}), "exits.market_profiles")
    profiles = {
        market_type: _exit_profile(profile, f"exits.market_profiles.{market_type}")
        for market_type, profile in profiles_raw.items()
        if market_type in MARKET_TYPES
    }
    return ExitConfig(
        mirror_source_sells=bool(data.get("mirror_source_sells", True)),
        stop_loss_pct=_float(data, "stop_loss_pct", 25.0),
        take_profit_pct=_float(data, "take_profit_pct", 50.0),
        max_holding_minutes=int(data.get("max_holding_minutes", 1440)),
        market_profiles=profiles,
    )


def _exit_profile(raw: Any, name: str) -> ExitProfileConfig:
    data = _mapping(raw, name)
    return ExitProfileConfig(
        stop_loss_pct=_float(data, "stop_loss_pct", 0.0),
        take_profit_pct=_float(data, "take_profit_pct", 0.0),
        max_holding_minutes=int(data.get("max_holding_minutes", 0)),
    )


def _market_filters(raw: Any) -> MarketFilterConfig:
    data = _mapping(raw, "market_filters")
    return MarketFilterConfig(
        enabled_market_types=_market_types(data.get("enabled_market_types", MARKET_TYPES), "market_filters.enabled_market_types")
    )


def _watcher(raw: Any) -> WatcherConfig:
    data = _mapping(raw, "watcher")
    contracts = data.get("exchange_contracts", ["ctf_exchange", "neg_risk_ctf_exchange"])
    if not isinstance(contracts, list) or not contracts:
        raise ConfigError("watcher.exchange_contracts must be a non-empty list")
    return WatcherConfig(
        exchange_contracts=tuple(str(contract) for contract in contracts),
        confirmations=int(data.get("confirmations", 1)),
        backfill_blocks=int(data.get("backfill_blocks", 500)),
        ws_ping_interval_seconds=_float(data, "ws_ping_interval_seconds", 15.0),
        ws_ping_timeout_seconds=_float(data, "ws_ping_timeout_seconds", 45.0),
        ws_close_timeout_seconds=_float(data, "ws_close_timeout_seconds", 5.0),
        ws_reconnect_max_seconds=_float(data, "ws_reconnect_max_seconds", 30.0),
    )


def _price_monitor(raw: Any) -> PriceMonitorConfig:
    data = _mapping(raw, "price_monitor")
    config = PriceMonitorConfig(
        enabled=bool(data.get("enabled", True)),
        poll_interval_seconds=_float(data, "poll_interval_seconds", 30.0),
        idle_poll_interval_seconds=_float(data, "idle_poll_interval_seconds", 300.0),
    )
    if config.poll_interval_seconds <= 0:
        raise ConfigError("price_monitor.poll_interval_seconds must be positive")
    if config.idle_poll_interval_seconds <= 0:
        raise ConfigError("price_monitor.idle_poll_interval_seconds must be positive")
    return config


def _winner_capture(raw: Any) -> WinnerCaptureConfig:
    data = _mapping(raw, "winner_capture")
    config = WinnerCaptureConfig(
        enabled=bool(data.get("enabled", False)),
        entry_price_max=_float(data, "entry_price_max", 0.35),
        recover_stake_multiple=_float(data, "recover_stake_multiple", 2.0),
        first_scale_multiple=_float(data, "first_scale_multiple", 4.0),
        first_scale_sell_pct=_float(data, "first_scale_sell_pct", 35.0),
        high_price_threshold=_float(data, "high_price_threshold", 0.50),
        high_price_sell_pct=_float(data, "high_price_sell_pct", 50.0),
        runner_pct=_float(data, "runner_pct", 15.0),
        trailing_drawdown_pct=_float(data, "trailing_drawdown_pct", 30.0),
        high_price_absolute_trail=_float(data, "high_price_absolute_trail", 0.12),
        sports_mid_entry_price_max=_float(data, "sports_mid_entry_price_max", 0.70),
        sports_mid_partial_price_threshold=_float(data, "sports_mid_partial_price_threshold", 0.75),
        sports_mid_partial_profit_pct=_float(data, "sports_mid_partial_profit_pct", 35.0),
        sports_mid_partial_stake_pct=_float(data, "sports_mid_partial_stake_pct", 50.0),
        sports_mid_full_stake_price_threshold=_float(data, "sports_mid_full_stake_price_threshold", 0.85),
        sports_mid_high_price_threshold=_float(data, "sports_mid_high_price_threshold", 0.92),
        sports_mid_high_price_sell_pct=_float(data, "sports_mid_high_price_sell_pct", 75.0),
        sports_mid_runner_pct=_float(data, "sports_mid_runner_pct", 15.0),
        sports_dead_cut_price=_float(data, "sports_dead_cut_price", 0.08),
        sports_dead_cut_max_peak_gain_pct=_float(data, "sports_dead_cut_max_peak_gain_pct", 15.0),
    )
    if not 0 < config.entry_price_max <= 1:
        raise ConfigError("winner_capture.entry_price_max must be within 0-1")
    if config.recover_stake_multiple <= 1:
        raise ConfigError("winner_capture.recover_stake_multiple must be greater than 1")
    if config.first_scale_multiple < config.recover_stake_multiple:
        raise ConfigError("winner_capture.first_scale_multiple must be >= recover_stake_multiple")
    for key, value in (
        ("first_scale_sell_pct", config.first_scale_sell_pct),
        ("high_price_sell_pct", config.high_price_sell_pct),
        ("runner_pct", config.runner_pct),
        ("trailing_drawdown_pct", config.trailing_drawdown_pct),
    ):
        if not 0 < value < 100:
            raise ConfigError(f"winner_capture.{key} must be between 0 and 100")
    if not 0 < config.high_price_threshold <= 1:
        raise ConfigError("winner_capture.high_price_threshold must be within 0-1")
    if config.high_price_absolute_trail < 0:
        raise ConfigError("winner_capture.high_price_absolute_trail cannot be negative")
    if not config.entry_price_max <= config.sports_mid_entry_price_max <= 1:
        raise ConfigError("winner_capture.sports_mid_entry_price_max must be between entry_price_max and 1")
    if not 0 < config.sports_dead_cut_price < 1:
        raise ConfigError("winner_capture.sports_dead_cut_price must be within 0-1")
    for key, value in (
        ("sports_mid_partial_stake_pct", config.sports_mid_partial_stake_pct),
        ("sports_mid_high_price_sell_pct", config.sports_mid_high_price_sell_pct),
        ("sports_mid_runner_pct", config.sports_mid_runner_pct),
        ("sports_dead_cut_max_peak_gain_pct", config.sports_dead_cut_max_peak_gain_pct),
    ):
        if not 0 < value < 100:
            raise ConfigError(f"winner_capture.{key} must be between 0 and 100")
    for key, value in (
        ("sports_mid_partial_price_threshold", config.sports_mid_partial_price_threshold),
        ("sports_mid_full_stake_price_threshold", config.sports_mid_full_stake_price_threshold),
        ("sports_mid_high_price_threshold", config.sports_mid_high_price_threshold),
    ):
        if not 0 < value <= 1:
            raise ConfigError(f"winner_capture.{key} must be within 0-1")
    return config


def _app(raw: Any) -> AppConfig:
    data = _mapping(raw, "app")
    return AppConfig(
        host=str(data.get("host", "127.0.0.1")),
        port=int(data.get("port", 8789)),
        database_url=str(data.get("database_url", "sqlite:///data/polymarket-copy-trading.sqlite3")),
        live_database_url=str(data.get("live_database_url", "sqlite:///data/polymarket-copy-trading-live.sqlite3")),
    )


def _mapping(raw: Any, name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name} must be a mapping")
    return raw


def _market_types(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        raise ConfigError(f"{name} must be a list")
    values = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    unknown = [item for item in values if item not in MARKET_TYPES]
    if unknown:
        raise ConfigError(f"{name} contains unsupported market type: {', '.join(unknown)}")
    return values or MARKET_TYPES


def _weather_patterns(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        raise ConfigError(f"{name} must be a list")
    values = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    unknown = [item for item in values if item not in WEATHER_BRACKET_PATTERNS]
    if unknown:
        raise ConfigError(f"{name} contains unsupported weather bracket pattern: {', '.join(unknown)}")
    return values or WEATHER_BRACKET_PATTERNS


def _string_tuple(raw: Any, name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        raise ConfigError(f"{name} must be a list")
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _float(data: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be numeric") from exc
