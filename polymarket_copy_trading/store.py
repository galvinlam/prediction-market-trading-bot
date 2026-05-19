from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from polymarket_copy_trading.config import (
    WALLET_RE,
    WalletConfig,
)
from polymarket_copy_trading.wallet_profile import (
    MARKET_TYPES,
    WEATHER_BRACKET_PATTERNS,
    apply_wallet_profile_overrides as _apply_wallet_profile_overrides,
    default_wallet_profile_json,
    parse_wallet_profile_json,
    profile_json_to_text as _profile_json_to_text,
    wallet_profile_json_from_legacy_wallet as _profile_json_from_legacy_wallet,
    wallet_profile_json_from_wallet_config,
)
from polymarket_copy_trading.models import PaperFill, SourceTrade


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.executescript(INDEXES)

    def sync_wallets(self, wallets: Iterable[WalletConfig]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                insert into wallets (
                  address, name, enabled, strategy_label, strategy_notes, allowed_market_types,
                  bracket_strategy_enabled, bracket_buy_size_usdc, bracket_stop_loss_pct, bracket_max_open_events, bracket_allowed_patterns,
                  repeat_buy_strategy_enabled, repeat_buy_size_usdc, repeat_buy_stop_loss_pct,
                  repeat_buy_min_source_notional_usdc, repeat_buy_min_buy_count,
                  repeat_buy_min_avg_price, repeat_buy_max_avg_price, repeat_buy_max_total_exposure_usdc,
                  repeat_buy_blocked_title_patterns, repeat_buy_allowed_sports, repeat_buy_allowed_bet_types,
                  event_follow_strategy_enabled, event_follow_buy_size_usdc, event_follow_max_event_exposure_usdc,
                  event_follow_max_total_exposure_usdc, event_follow_min_source_trade_usdc,
                  event_follow_min_event_source_notional_usdc, event_follow_min_event_buy_count,
                  event_follow_min_avg_price, event_follow_max_avg_price,
                  sports_trailing_stop_enabled, sports_trailing_activation_pct,
                  sports_trailing_stop_pct, sports_trailing_floor_delta, reserved_cash_usdc, profile_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(address) do update set
                  name = excluded.name,
                  strategy_label = excluded.strategy_label,
                  strategy_notes = excluded.strategy_notes,
                  allowed_market_types = excluded.allowed_market_types,
                  bracket_strategy_enabled = excluded.bracket_strategy_enabled,
                  bracket_buy_size_usdc = excluded.bracket_buy_size_usdc,
                  bracket_stop_loss_pct = excluded.bracket_stop_loss_pct,
                  bracket_max_open_events = excluded.bracket_max_open_events,
                  bracket_allowed_patterns = excluded.bracket_allowed_patterns,
                  repeat_buy_strategy_enabled = excluded.repeat_buy_strategy_enabled,
                  repeat_buy_size_usdc = excluded.repeat_buy_size_usdc,
                  repeat_buy_stop_loss_pct = excluded.repeat_buy_stop_loss_pct,
                  repeat_buy_min_source_notional_usdc = excluded.repeat_buy_min_source_notional_usdc,
                  repeat_buy_min_buy_count = excluded.repeat_buy_min_buy_count,
                  repeat_buy_min_avg_price = excluded.repeat_buy_min_avg_price,
                  repeat_buy_max_avg_price = excluded.repeat_buy_max_avg_price,
                  repeat_buy_max_total_exposure_usdc = excluded.repeat_buy_max_total_exposure_usdc,
                  repeat_buy_blocked_title_patterns = excluded.repeat_buy_blocked_title_patterns,
                  repeat_buy_allowed_sports = excluded.repeat_buy_allowed_sports,
                  repeat_buy_allowed_bet_types = excluded.repeat_buy_allowed_bet_types,
                  event_follow_strategy_enabled = excluded.event_follow_strategy_enabled,
                  event_follow_buy_size_usdc = excluded.event_follow_buy_size_usdc,
                  event_follow_max_event_exposure_usdc = excluded.event_follow_max_event_exposure_usdc,
                  event_follow_max_total_exposure_usdc = excluded.event_follow_max_total_exposure_usdc,
                  event_follow_min_source_trade_usdc = excluded.event_follow_min_source_trade_usdc,
                  event_follow_min_event_source_notional_usdc = excluded.event_follow_min_event_source_notional_usdc,
                  event_follow_min_event_buy_count = excluded.event_follow_min_event_buy_count,
                  event_follow_min_avg_price = excluded.event_follow_min_avg_price,
                  event_follow_max_avg_price = excluded.event_follow_max_avg_price,
                  sports_trailing_stop_enabled = excluded.sports_trailing_stop_enabled,
                  sports_trailing_activation_pct = excluded.sports_trailing_activation_pct,
                  sports_trailing_stop_pct = excluded.sports_trailing_stop_pct,
                  sports_trailing_floor_delta = excluded.sports_trailing_floor_delta,
                  reserved_cash_usdc = excluded.reserved_cash_usdc,
                  profile_json = excluded.profile_json
                """,
                [
                    (
                        wallet.address.lower(),
                        wallet.name,
                        int(wallet.enabled),
                        wallet.strategy_label,
                        wallet.strategy_notes,
                        _market_types_to_text(wallet.allowed_market_types),
                        int(wallet.bracket_strategy_enabled),
                        wallet.bracket_buy_size_usdc,
                        wallet.bracket_stop_loss_pct,
                        wallet.bracket_max_open_events,
                        _weather_patterns_to_text(wallet.bracket_allowed_patterns),
                        int(wallet.repeat_buy_strategy_enabled),
                        wallet.repeat_buy_size_usdc,
                        wallet.repeat_buy_stop_loss_pct,
                        wallet.repeat_buy_min_source_notional_usdc,
                        wallet.repeat_buy_min_buy_count,
                        wallet.repeat_buy_min_avg_price,
                        wallet.repeat_buy_max_avg_price,
                        wallet.repeat_buy_max_total_exposure_usdc,
                        _string_list_to_text(wallet.repeat_buy_blocked_title_patterns),
                        _string_list_to_text(wallet.repeat_buy_allowed_sports),
                        _string_list_to_text(wallet.repeat_buy_allowed_bet_types),
                        int(wallet.event_follow_strategy_enabled),
                        wallet.event_follow_buy_size_usdc,
                        wallet.event_follow_max_event_exposure_usdc,
                        wallet.event_follow_max_total_exposure_usdc,
                        wallet.event_follow_min_source_trade_usdc,
                        wallet.event_follow_min_event_source_notional_usdc,
                        wallet.event_follow_min_event_buy_count,
                        wallet.event_follow_min_avg_price,
                        wallet.event_follow_max_avg_price,
                        int(wallet.sports_trailing_stop_enabled),
                        wallet.sports_trailing_activation_pct,
                        wallet.sports_trailing_stop_pct,
                        wallet.sports_trailing_floor_delta,
                        wallet.reserved_cash_usdc,
                        _profile_json_to_text(wallet.profile_json),
                    )
                    for wallet in (_effective_wallet_config(wallet) for wallet in wallets)
                ],
            )

    def seed_wallets_if_empty(self, wallets: Iterable[WalletConfig]) -> bool:
        with self._connect() as conn:
            row = conn.execute("select count(*) as count from wallets").fetchone()
        if row and int(row["count"]) > 0:
            return False
        self.sync_wallets(wallets)
        return True

    def import_wallets_if_empty(self, source: "Store") -> bool:
        with self._connect() as conn:
            row = conn.execute("select count(*) as count from wallets").fetchone()
        if row and int(row["count"]) > 0:
            return False
        for wallet in source.list_wallets():
            self.upsert_wallet(**wallet)
        return True

    def list_wallets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  name, address, enabled, strategy_label, strategy_notes, allowed_market_types,
                  bracket_strategy_enabled, bracket_buy_size_usdc, bracket_stop_loss_pct, bracket_max_open_events, bracket_allowed_patterns,
                  repeat_buy_strategy_enabled, repeat_buy_size_usdc, repeat_buy_stop_loss_pct,
                  repeat_buy_min_source_notional_usdc, repeat_buy_min_buy_count,
                  repeat_buy_min_avg_price, repeat_buy_max_avg_price, repeat_buy_max_total_exposure_usdc,
                  repeat_buy_blocked_title_patterns, repeat_buy_allowed_sports, repeat_buy_allowed_bet_types,
                  event_follow_strategy_enabled, event_follow_buy_size_usdc, event_follow_max_event_exposure_usdc,
                  event_follow_max_total_exposure_usdc, event_follow_min_source_trade_usdc,
                  event_follow_min_event_source_notional_usdc, event_follow_min_event_buy_count,
                  event_follow_min_avg_price, event_follow_max_avg_price,
                  sports_trailing_stop_enabled, sports_trailing_activation_pct,
                  sports_trailing_stop_pct, sports_trailing_floor_delta, reserved_cash_usdc, profile_json
                from wallets
                order by name
                """
            ).fetchall()
        return [_wallet_payload(row) for row in rows]

    def upsert_wallet(
        self,
        *,
        name: str,
        address: str,
        enabled: bool,
        strategy_label: str = "Standard",
        strategy_notes: str = "",
        allowed_market_types: Iterable[str] | None = None,
        bracket_strategy_enabled: bool = False,
        bracket_buy_size_usdc: float = 10.0,
        bracket_stop_loss_pct: float = 0.0,
        bracket_max_open_events: int = 0,
        bracket_allowed_patterns: Iterable[str] | None = None,
        repeat_buy_strategy_enabled: bool = False,
        repeat_buy_size_usdc: float = 5.0,
        repeat_buy_stop_loss_pct: float = 0.0,
        repeat_buy_min_source_notional_usdc: float = 0.0,
        repeat_buy_min_buy_count: int = 2,
        repeat_buy_min_avg_price: float = 0.01,
        repeat_buy_max_avg_price: float = 1.0,
        repeat_buy_max_total_exposure_usdc: float = 0.0,
        repeat_buy_blocked_title_patterns: Iterable[str] | None = None,
        repeat_buy_allowed_sports: Iterable[str] | None = None,
        repeat_buy_allowed_bet_types: Iterable[str] | None = None,
        event_follow_strategy_enabled: bool = False,
        event_follow_buy_size_usdc: float = 2.0,
        event_follow_max_event_exposure_usdc: float = 4.0,
        event_follow_max_total_exposure_usdc: float = 50.0,
        event_follow_min_source_trade_usdc: float = 20.0,
        event_follow_min_event_source_notional_usdc: float = 250.0,
        event_follow_min_event_buy_count: int = 3,
        event_follow_min_avg_price: float = 0.20,
        event_follow_max_avg_price: float = 0.80,
        sports_trailing_stop_enabled: bool = False,
        sports_trailing_activation_pct: float = 35.0,
        sports_trailing_stop_pct: float = 25.0,
        sports_trailing_floor_delta: float = 0.03,
        reserved_cash_usdc: float = 0.0,
        profile_json: Any = None,
    ) -> dict[str, Any]:
        wallet = self._clean_wallet(
            name=name,
            address=address,
            enabled=enabled,
            strategy_label=strategy_label,
            strategy_notes=strategy_notes,
            allowed_market_types=allowed_market_types,
            bracket_strategy_enabled=bracket_strategy_enabled,
            bracket_buy_size_usdc=bracket_buy_size_usdc,
            bracket_stop_loss_pct=bracket_stop_loss_pct,
            bracket_max_open_events=bracket_max_open_events,
            bracket_allowed_patterns=bracket_allowed_patterns,
            repeat_buy_strategy_enabled=repeat_buy_strategy_enabled,
            repeat_buy_size_usdc=repeat_buy_size_usdc,
            repeat_buy_stop_loss_pct=repeat_buy_stop_loss_pct,
            repeat_buy_min_source_notional_usdc=repeat_buy_min_source_notional_usdc,
            repeat_buy_min_buy_count=repeat_buy_min_buy_count,
            repeat_buy_min_avg_price=repeat_buy_min_avg_price,
            repeat_buy_max_avg_price=repeat_buy_max_avg_price,
            repeat_buy_max_total_exposure_usdc=repeat_buy_max_total_exposure_usdc,
            repeat_buy_blocked_title_patterns=repeat_buy_blocked_title_patterns,
            repeat_buy_allowed_sports=repeat_buy_allowed_sports,
            repeat_buy_allowed_bet_types=repeat_buy_allowed_bet_types,
            event_follow_strategy_enabled=event_follow_strategy_enabled,
            event_follow_buy_size_usdc=event_follow_buy_size_usdc,
            event_follow_max_event_exposure_usdc=event_follow_max_event_exposure_usdc,
            event_follow_max_total_exposure_usdc=event_follow_max_total_exposure_usdc,
            event_follow_min_source_trade_usdc=event_follow_min_source_trade_usdc,
            event_follow_min_event_source_notional_usdc=event_follow_min_event_source_notional_usdc,
            event_follow_min_event_buy_count=event_follow_min_event_buy_count,
            event_follow_min_avg_price=event_follow_min_avg_price,
            event_follow_max_avg_price=event_follow_max_avg_price,
            sports_trailing_stop_enabled=sports_trailing_stop_enabled,
            sports_trailing_activation_pct=sports_trailing_activation_pct,
            sports_trailing_stop_pct=sports_trailing_stop_pct,
            sports_trailing_floor_delta=sports_trailing_floor_delta,
            reserved_cash_usdc=reserved_cash_usdc,
            profile_json=profile_json,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into wallets (
                  address, name, enabled, strategy_label, strategy_notes, allowed_market_types,
                  bracket_strategy_enabled, bracket_buy_size_usdc, bracket_stop_loss_pct, bracket_max_open_events, bracket_allowed_patterns,
                  repeat_buy_strategy_enabled, repeat_buy_size_usdc, repeat_buy_stop_loss_pct,
                  repeat_buy_min_source_notional_usdc, repeat_buy_min_buy_count,
                  repeat_buy_min_avg_price, repeat_buy_max_avg_price, repeat_buy_max_total_exposure_usdc,
                  repeat_buy_blocked_title_patterns, repeat_buy_allowed_sports, repeat_buy_allowed_bet_types,
                  event_follow_strategy_enabled, event_follow_buy_size_usdc, event_follow_max_event_exposure_usdc,
                  event_follow_max_total_exposure_usdc, event_follow_min_source_trade_usdc,
                  event_follow_min_event_source_notional_usdc, event_follow_min_event_buy_count,
                  event_follow_min_avg_price, event_follow_max_avg_price,
                  sports_trailing_stop_enabled, sports_trailing_activation_pct,
                  sports_trailing_stop_pct, sports_trailing_floor_delta, reserved_cash_usdc, profile_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(address) do update set
                  name = excluded.name,
                  enabled = excluded.enabled,
                  strategy_label = excluded.strategy_label,
                  strategy_notes = excluded.strategy_notes,
                  allowed_market_types = excluded.allowed_market_types,
                  bracket_strategy_enabled = excluded.bracket_strategy_enabled,
                  bracket_buy_size_usdc = excluded.bracket_buy_size_usdc,
                  bracket_stop_loss_pct = excluded.bracket_stop_loss_pct,
                  bracket_max_open_events = excluded.bracket_max_open_events,
                  bracket_allowed_patterns = excluded.bracket_allowed_patterns,
                  repeat_buy_strategy_enabled = excluded.repeat_buy_strategy_enabled,
                  repeat_buy_size_usdc = excluded.repeat_buy_size_usdc,
                  repeat_buy_stop_loss_pct = excluded.repeat_buy_stop_loss_pct,
                  repeat_buy_min_source_notional_usdc = excluded.repeat_buy_min_source_notional_usdc,
                  repeat_buy_min_buy_count = excluded.repeat_buy_min_buy_count,
                  repeat_buy_min_avg_price = excluded.repeat_buy_min_avg_price,
                  repeat_buy_max_avg_price = excluded.repeat_buy_max_avg_price,
                  repeat_buy_max_total_exposure_usdc = excluded.repeat_buy_max_total_exposure_usdc,
                  repeat_buy_blocked_title_patterns = excluded.repeat_buy_blocked_title_patterns,
                  repeat_buy_allowed_sports = excluded.repeat_buy_allowed_sports,
                  repeat_buy_allowed_bet_types = excluded.repeat_buy_allowed_bet_types,
                  event_follow_strategy_enabled = excluded.event_follow_strategy_enabled,
                  event_follow_buy_size_usdc = excluded.event_follow_buy_size_usdc,
                  event_follow_max_event_exposure_usdc = excluded.event_follow_max_event_exposure_usdc,
                  event_follow_max_total_exposure_usdc = excluded.event_follow_max_total_exposure_usdc,
                  event_follow_min_source_trade_usdc = excluded.event_follow_min_source_trade_usdc,
                  event_follow_min_event_source_notional_usdc = excluded.event_follow_min_event_source_notional_usdc,
                  event_follow_min_event_buy_count = excluded.event_follow_min_event_buy_count,
                  event_follow_min_avg_price = excluded.event_follow_min_avg_price,
                  event_follow_max_avg_price = excluded.event_follow_max_avg_price,
                  sports_trailing_stop_enabled = excluded.sports_trailing_stop_enabled,
                  sports_trailing_activation_pct = excluded.sports_trailing_activation_pct,
                  sports_trailing_stop_pct = excluded.sports_trailing_stop_pct,
                  sports_trailing_floor_delta = excluded.sports_trailing_floor_delta,
                  reserved_cash_usdc = excluded.reserved_cash_usdc,
                  profile_json = excluded.profile_json
                """,
                (
                    wallet["address"],
                    wallet["name"],
                    int(wallet["enabled"]),
                    wallet["strategy_label"],
                    wallet["strategy_notes"],
                    _market_types_to_text(wallet["allowed_market_types"]),
                    int(wallet["bracket_strategy_enabled"]),
                    wallet["bracket_buy_size_usdc"],
                    wallet["bracket_stop_loss_pct"],
                    wallet["bracket_max_open_events"],
                    _weather_patterns_to_text(wallet["bracket_allowed_patterns"]),
                    int(wallet["repeat_buy_strategy_enabled"]),
                    wallet["repeat_buy_size_usdc"],
                    wallet["repeat_buy_stop_loss_pct"],
                    wallet["repeat_buy_min_source_notional_usdc"],
                    wallet["repeat_buy_min_buy_count"],
                    wallet["repeat_buy_min_avg_price"],
                    wallet["repeat_buy_max_avg_price"],
                    wallet["repeat_buy_max_total_exposure_usdc"],
                    _string_list_to_text(wallet["repeat_buy_blocked_title_patterns"]),
                    _string_list_to_text(wallet["repeat_buy_allowed_sports"]),
                    _string_list_to_text(wallet["repeat_buy_allowed_bet_types"]),
                    int(wallet["event_follow_strategy_enabled"]),
                    wallet["event_follow_buy_size_usdc"],
                    wallet["event_follow_max_event_exposure_usdc"],
                    wallet["event_follow_max_total_exposure_usdc"],
                    wallet["event_follow_min_source_trade_usdc"],
                    wallet["event_follow_min_event_source_notional_usdc"],
                    wallet["event_follow_min_event_buy_count"],
                    wallet["event_follow_min_avg_price"],
                    wallet["event_follow_max_avg_price"],
                    int(wallet["sports_trailing_stop_enabled"]),
                    wallet["sports_trailing_activation_pct"],
                    wallet["sports_trailing_stop_pct"],
                    wallet["sports_trailing_floor_delta"],
                    wallet["reserved_cash_usdc"],
                    _profile_json_to_text(wallet["profile_json"]),
                ),
            )
        return wallet

    def update_wallet(
        self,
        address: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        strategy_label: str | None = None,
        strategy_notes: str | None = None,
        allowed_market_types: Iterable[str] | None = None,
        bracket_strategy_enabled: bool | None = None,
        bracket_buy_size_usdc: float | None = None,
        bracket_stop_loss_pct: float | None = None,
        bracket_max_open_events: int | None = None,
        bracket_allowed_patterns: Iterable[str] | None = None,
        repeat_buy_strategy_enabled: bool | None = None,
        repeat_buy_size_usdc: float | None = None,
        repeat_buy_stop_loss_pct: float | None = None,
        repeat_buy_min_source_notional_usdc: float | None = None,
        repeat_buy_min_buy_count: int | None = None,
        repeat_buy_min_avg_price: float | None = None,
        repeat_buy_max_avg_price: float | None = None,
        repeat_buy_max_total_exposure_usdc: float | None = None,
        repeat_buy_blocked_title_patterns: Iterable[str] | None = None,
        repeat_buy_allowed_sports: Iterable[str] | None = None,
        repeat_buy_allowed_bet_types: Iterable[str] | None = None,
        event_follow_strategy_enabled: bool | None = None,
        event_follow_buy_size_usdc: float | None = None,
        event_follow_max_event_exposure_usdc: float | None = None,
        event_follow_max_total_exposure_usdc: float | None = None,
        event_follow_min_source_trade_usdc: float | None = None,
        event_follow_min_event_source_notional_usdc: float | None = None,
        event_follow_min_event_buy_count: int | None = None,
        event_follow_min_avg_price: float | None = None,
        event_follow_max_avg_price: float | None = None,
        sports_trailing_stop_enabled: bool | None = None,
        sports_trailing_activation_pct: float | None = None,
        sports_trailing_stop_pct: float | None = None,
        sports_trailing_floor_delta: float | None = None,
        reserved_cash_usdc: float | None = None,
        profile_json: Any = None,
    ) -> dict[str, Any]:
        current = self.get_wallet(address)
        if current is None:
            raise ValueError("wallet not found")
        next_profile_json = profile_json
        if profile_json is None:
            legacy_profile_wallet = {**current}
            for key, value in {
                "allowed_market_types": allowed_market_types,
                "bracket_strategy_enabled": bracket_strategy_enabled,
                "bracket_buy_size_usdc": bracket_buy_size_usdc,
                "bracket_stop_loss_pct": bracket_stop_loss_pct,
                "bracket_max_open_events": bracket_max_open_events,
                "bracket_allowed_patterns": bracket_allowed_patterns,
                "repeat_buy_strategy_enabled": repeat_buy_strategy_enabled,
                "repeat_buy_size_usdc": repeat_buy_size_usdc,
                "repeat_buy_stop_loss_pct": repeat_buy_stop_loss_pct,
                "repeat_buy_min_source_notional_usdc": repeat_buy_min_source_notional_usdc,
                "repeat_buy_min_buy_count": repeat_buy_min_buy_count,
                "repeat_buy_min_avg_price": repeat_buy_min_avg_price,
                "repeat_buy_max_avg_price": repeat_buy_max_avg_price,
                "repeat_buy_max_total_exposure_usdc": repeat_buy_max_total_exposure_usdc,
                "repeat_buy_blocked_title_patterns": repeat_buy_blocked_title_patterns,
                "repeat_buy_allowed_sports": repeat_buy_allowed_sports,
                "repeat_buy_allowed_bet_types": repeat_buy_allowed_bet_types,
                "event_follow_strategy_enabled": event_follow_strategy_enabled,
                "event_follow_buy_size_usdc": event_follow_buy_size_usdc,
                "event_follow_max_event_exposure_usdc": event_follow_max_event_exposure_usdc,
                "event_follow_max_total_exposure_usdc": event_follow_max_total_exposure_usdc,
                "event_follow_min_source_trade_usdc": event_follow_min_source_trade_usdc,
                "event_follow_min_event_source_notional_usdc": event_follow_min_event_source_notional_usdc,
                "event_follow_min_event_buy_count": event_follow_min_event_buy_count,
                "event_follow_min_avg_price": event_follow_min_avg_price,
                "event_follow_max_avg_price": event_follow_max_avg_price,
                "sports_trailing_stop_enabled": sports_trailing_stop_enabled,
                "sports_trailing_activation_pct": sports_trailing_activation_pct,
                "sports_trailing_stop_pct": sports_trailing_stop_pct,
                "sports_trailing_floor_delta": sports_trailing_floor_delta,
                "reserved_cash_usdc": reserved_cash_usdc,
            }.items():
                if value is not None:
                    legacy_profile_wallet[key] = value
            next_profile_json = _profile_json_from_legacy_wallet(
                legacy_profile_wallet,
                preserve_profile=current.get("profile_json"),
            )
        return self.upsert_wallet(
            name=current["name"] if name is None else name,
            address=current["address"],
            enabled=current["enabled"] if enabled is None else enabled,
            strategy_label=current["strategy_label"] if strategy_label is None else strategy_label,
            strategy_notes=current["strategy_notes"] if strategy_notes is None else strategy_notes,
            allowed_market_types=current["allowed_market_types"] if allowed_market_types is None else allowed_market_types,
            bracket_strategy_enabled=current["bracket_strategy_enabled"] if bracket_strategy_enabled is None else bracket_strategy_enabled,
            bracket_buy_size_usdc=current["bracket_buy_size_usdc"] if bracket_buy_size_usdc is None else bracket_buy_size_usdc,
            bracket_stop_loss_pct=current["bracket_stop_loss_pct"] if bracket_stop_loss_pct is None else bracket_stop_loss_pct,
            bracket_max_open_events=current["bracket_max_open_events"] if bracket_max_open_events is None else bracket_max_open_events,
            bracket_allowed_patterns=current["bracket_allowed_patterns"] if bracket_allowed_patterns is None else bracket_allowed_patterns,
            repeat_buy_strategy_enabled=current["repeat_buy_strategy_enabled"] if repeat_buy_strategy_enabled is None else repeat_buy_strategy_enabled,
            repeat_buy_size_usdc=current["repeat_buy_size_usdc"] if repeat_buy_size_usdc is None else repeat_buy_size_usdc,
            repeat_buy_stop_loss_pct=current["repeat_buy_stop_loss_pct"] if repeat_buy_stop_loss_pct is None else repeat_buy_stop_loss_pct,
            repeat_buy_min_source_notional_usdc=current["repeat_buy_min_source_notional_usdc"] if repeat_buy_min_source_notional_usdc is None else repeat_buy_min_source_notional_usdc,
            repeat_buy_min_buy_count=current["repeat_buy_min_buy_count"] if repeat_buy_min_buy_count is None else repeat_buy_min_buy_count,
            repeat_buy_min_avg_price=current["repeat_buy_min_avg_price"] if repeat_buy_min_avg_price is None else repeat_buy_min_avg_price,
            repeat_buy_max_avg_price=current["repeat_buy_max_avg_price"] if repeat_buy_max_avg_price is None else repeat_buy_max_avg_price,
            repeat_buy_max_total_exposure_usdc=current["repeat_buy_max_total_exposure_usdc"] if repeat_buy_max_total_exposure_usdc is None else repeat_buy_max_total_exposure_usdc,
            repeat_buy_blocked_title_patterns=current["repeat_buy_blocked_title_patterns"] if repeat_buy_blocked_title_patterns is None else repeat_buy_blocked_title_patterns,
            repeat_buy_allowed_sports=current["repeat_buy_allowed_sports"] if repeat_buy_allowed_sports is None else repeat_buy_allowed_sports,
            repeat_buy_allowed_bet_types=current["repeat_buy_allowed_bet_types"] if repeat_buy_allowed_bet_types is None else repeat_buy_allowed_bet_types,
            event_follow_strategy_enabled=current["event_follow_strategy_enabled"] if event_follow_strategy_enabled is None else event_follow_strategy_enabled,
            event_follow_buy_size_usdc=current["event_follow_buy_size_usdc"] if event_follow_buy_size_usdc is None else event_follow_buy_size_usdc,
            event_follow_max_event_exposure_usdc=current["event_follow_max_event_exposure_usdc"] if event_follow_max_event_exposure_usdc is None else event_follow_max_event_exposure_usdc,
            event_follow_max_total_exposure_usdc=current["event_follow_max_total_exposure_usdc"] if event_follow_max_total_exposure_usdc is None else event_follow_max_total_exposure_usdc,
            event_follow_min_source_trade_usdc=current["event_follow_min_source_trade_usdc"] if event_follow_min_source_trade_usdc is None else event_follow_min_source_trade_usdc,
            event_follow_min_event_source_notional_usdc=current["event_follow_min_event_source_notional_usdc"] if event_follow_min_event_source_notional_usdc is None else event_follow_min_event_source_notional_usdc,
            event_follow_min_event_buy_count=current["event_follow_min_event_buy_count"] if event_follow_min_event_buy_count is None else event_follow_min_event_buy_count,
            event_follow_min_avg_price=current["event_follow_min_avg_price"] if event_follow_min_avg_price is None else event_follow_min_avg_price,
            event_follow_max_avg_price=current["event_follow_max_avg_price"] if event_follow_max_avg_price is None else event_follow_max_avg_price,
            sports_trailing_stop_enabled=current["sports_trailing_stop_enabled"] if sports_trailing_stop_enabled is None else sports_trailing_stop_enabled,
            sports_trailing_activation_pct=current["sports_trailing_activation_pct"] if sports_trailing_activation_pct is None else sports_trailing_activation_pct,
            sports_trailing_stop_pct=current["sports_trailing_stop_pct"] if sports_trailing_stop_pct is None else sports_trailing_stop_pct,
            sports_trailing_floor_delta=current["sports_trailing_floor_delta"] if sports_trailing_floor_delta is None else sports_trailing_floor_delta,
            reserved_cash_usdc=current["reserved_cash_usdc"] if reserved_cash_usdc is None else reserved_cash_usdc,
            profile_json=next_profile_json,
        )

    def delete_wallet(self, address: str) -> None:
        clean_address = self._clean_address(address)
        with self._connect() as conn:
            conn.execute("delete from wallets where address = ?", (clean_address,))

    def get_wallet(self, address: str) -> dict[str, Any] | None:
        clean_address = self._clean_address(address)
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                  name, address, enabled, strategy_label, strategy_notes, allowed_market_types,
                  bracket_strategy_enabled, bracket_buy_size_usdc, bracket_stop_loss_pct, bracket_max_open_events, bracket_allowed_patterns,
                  repeat_buy_strategy_enabled, repeat_buy_size_usdc, repeat_buy_stop_loss_pct,
                  repeat_buy_min_source_notional_usdc, repeat_buy_min_buy_count,
                  repeat_buy_min_avg_price, repeat_buy_max_avg_price, repeat_buy_max_total_exposure_usdc,
                  repeat_buy_blocked_title_patterns, repeat_buy_allowed_sports, repeat_buy_allowed_bet_types,
                  event_follow_strategy_enabled, event_follow_buy_size_usdc, event_follow_max_event_exposure_usdc,
                  event_follow_max_total_exposure_usdc, event_follow_min_source_trade_usdc,
                  event_follow_min_event_source_notional_usdc, event_follow_min_event_buy_count,
                  event_follow_min_avg_price, event_follow_max_avg_price,
                  sports_trailing_stop_enabled, sports_trailing_activation_pct,
                  sports_trailing_stop_pct, sports_trailing_floor_delta, reserved_cash_usdc, profile_json
                from wallets
                where address = ?
                """,
                (clean_address,),
            ).fetchone()
        if row is None:
            return None
        return _wallet_payload(row)

    def is_wallet_enabled(self, address: str) -> bool:
        wallet = self.get_wallet(address)
        return bool(wallet and wallet["enabled"])

    def insert_source_trade(self, trade: SourceTrade) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert or ignore into source_trades (
                  idempotency_key, copy_trade_key, chain_id, exchange_contract, tx_hash, block_number,
                  block_timestamp, log_index, source_wallet, side, asset_id, condition_id,
                  market_id, outcome, price, quantity, notional_usdc
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.idempotency_key,
                    trade.normalized_copy_trade_key,
                    trade.chain_id,
                    trade.exchange_contract,
                    trade.tx_hash,
                    trade.block_number,
                    trade.block_timestamp,
                    trade.log_index,
                    trade.source_wallet.lower(),
                    trade.side,
                    trade.asset_id,
                    trade.condition_id,
                    trade.market_id,
                    trade.outcome,
                    trade.price,
                    trade.quantity,
                    trade.notional_usdc,
                ),
            )
            return cursor.rowcount == 1

    def record_paper_fill(
        self,
        fill: PaperFill,
        *,
        cash_after_usdc: float,
        position_quantity: float,
        avg_entry_price: float,
    ) -> int:
        with self._connect() as conn:
            source = conn.execute(
                "select copy_trade_key from source_trades where idempotency_key = ?",
                (fill.source_idempotency_key,),
            ).fetchone()
            copy_trade_key = source["copy_trade_key"] if source else None
            cursor = conn.execute(
                """
                insert into paper_trades (
                  source_idempotency_key, copy_trade_key, side, asset_id, source_wallet, observed_price,
                  fill_price, quantity, notional_usdc, realized_pnl_usdc, close_reason
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.source_idempotency_key,
                    copy_trade_key,
                    fill.side,
                    fill.asset_id,
                    fill.source_wallet.lower(),
                    fill.observed_price,
                    fill.fill_price,
                    fill.quantity,
                    fill.notional_usdc,
                    fill.realized_pnl_usdc,
                    fill.close_reason,
                ),
            )
            conn.execute(
                """
                insert into positions (
                  asset_id, source_wallet, quantity, avg_entry_price, realized_pnl_usdc, status,
                  trailing_peak_price, trailing_activated,
                  winner_capture_stake_recovered, winner_capture_first_scale_done, winner_capture_high_price_done
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(asset_id, source_wallet) do update set
                  quantity = excluded.quantity,
                  avg_entry_price = excluded.avg_entry_price,
                  realized_pnl_usdc = positions.realized_pnl_usdc + excluded.realized_pnl_usdc,
                  status = excluded.status,
                  trailing_peak_price = case
                    when excluded.quantity > 0 then max(coalesce(positions.trailing_peak_price, 0), coalesce(excluded.trailing_peak_price, 0))
                    else positions.trailing_peak_price
                  end,
                  trailing_activated = case
                    when excluded.quantity > 0 then positions.trailing_activated
                    else 0
                  end,
                  winner_capture_stake_recovered = case
                    when excluded.quantity > 0 then positions.winner_capture_stake_recovered
                    else 0
                  end,
                  winner_capture_first_scale_done = case
                    when excluded.quantity > 0 then positions.winner_capture_first_scale_done
                    else 0
                  end,
                  winner_capture_high_price_done = case
                    when excluded.quantity > 0 then positions.winner_capture_high_price_done
                    else 0
                  end,
                  updated_at = current_timestamp
                """,
                (
                    fill.asset_id,
                    fill.source_wallet.lower(),
                    position_quantity,
                    avg_entry_price,
                    fill.realized_pnl_usdc,
                    "open" if position_quantity > 0 else "closed",
                    max(float(avg_entry_price or 0), float(fill.fill_price or 0)) if position_quantity > 0 else None,
                    0,
                    0,
                    0,
                    0,
                ),
            )
            conn.execute(
                """
                insert into runtime_state (key, value)
                values ('paper_cash_usdc', ?)
                on conflict(key) do update set value = excluded.value
                """,
                (str(round(cash_after_usdc, 6)),),
            )
            return int(cursor.lastrowid)

    def has_executed_copy_trade(self, trade: SourceTrade, *, source_wallet_scoped: bool = False) -> bool:
        wallet_clause = " and source_wallet = ?" if source_wallet_scoped else ""
        params: tuple[object, ...] = (trade.normalized_copy_trade_key, trade.source_wallet.lower()) if source_wallet_scoped else (trade.normalized_copy_trade_key,)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                select 1 from source_trade_attributions
                where copy_trade_key = ?{wallet_clause} and executed = 1
                limit 1
                """,
                params,
            ).fetchone()
        return row is not None

    def has_source_trade_attribution(self, source_idempotency_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1 from source_trade_attributions
                where source_idempotency_key = ?
                limit 1
                """,
                (str(source_idempotency_key),),
            ).fetchone()
        return row is not None

    def record_copy_attribution(
        self,
        trade: SourceTrade,
        *,
        executed: bool,
        paper_trade_id: int | None,
        skip_reason: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into source_trade_attributions (
                  copy_trade_key, source_idempotency_key, source_wallet, paper_trade_id,
                  executed, skip_reason, source_notional_usdc
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.normalized_copy_trade_key,
                    trade.idempotency_key,
                    trade.source_wallet.lower(),
                    paper_trade_id,
                    int(executed),
                    None if executed else skip_reason,
                    trade.notional_usdc,
                ),
            )

    def create_live_order_intent(
        self,
        *,
        source_trade: SourceTrade,
        side: str,
        price: float,
        size: float,
        notional_usdc: float,
        status: str = "pending",
    ) -> dict[str, Any]:
        clean_side = str(side).strip().lower()
        if clean_side not in {"buy", "sell"}:
            raise ValueError("live order intent side must be 'buy' or 'sell'")
        now = _now_pdt()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert or ignore into live_order_intents (
                  source_idempotency_key, source_wallet, asset_id, token_id, side,
                  price, size, notional_usdc, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_trade.idempotency_key,
                    source_trade.source_wallet.lower(),
                    source_trade.asset_id,
                    source_trade.asset_id,
                    clean_side,
                    float(price),
                    float(size),
                    float(notional_usdc),
                    str(status).strip().lower() or "pending",
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 1:
                intent_id = int(cursor.lastrowid)
            else:
                existing = conn.execute(
                    """
                    select id from live_order_intents
                    where source_idempotency_key = ? and side = ?
                    """,
                    (source_trade.idempotency_key, clean_side),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("failed to create or find live order intent")
                intent_id = int(existing["id"])
            row = conn.execute("select * from live_order_intents where id = ?", (intent_id,)).fetchone()
        if row is None:
            raise RuntimeError("live order intent disappeared after create")
        return _live_order_intent_payload(row)

    def update_live_order_intent_status(
        self,
        intent_id: int,
        *,
        status: str,
        clob_order_id: str | None = None,
        error: str | None = None,
        response: Any = None,
    ) -> dict[str, Any]:
        clean_status = str(status).strip().lower()
        if not clean_status:
            raise ValueError("live order intent status is required")
        response_json = _json_response_to_text(response)
        with self._connect() as conn:
            conn.execute(
                """
                update live_order_intents
                set status = ?,
                    clob_order_id = coalesce(?, clob_order_id),
                    error = ?,
                    response_json = coalesce(?, response_json),
                    updated_at = ?
                where id = ?
                """,
                (
                    clean_status,
                    clob_order_id,
                    error,
                    response_json,
                    _now_pdt(),
                    int(intent_id),
                ),
            )
            row = conn.execute("select * from live_order_intents where id = ?", (int(intent_id),)).fetchone()
        if row is None:
            raise KeyError(f"live order intent not found: {intent_id}")
        return _live_order_intent_payload(row)

    def record_live_shadow_audit(
        self,
        *,
        source_trade: SourceTrade,
        paper_trade_id: int,
        side: str,
        paper_entry_price: float,
        best_ask_at_decision: float | None,
        order_price: float,
        requested_notional_usdc: float,
        requested_size: float,
        decision_latency_ms: int | None = None,
        available_size_at_price: float | None = None,
        would_fill_size: float | None = None,
        post_submit_book_price: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        clean_side = str(side).strip().lower()
        if clean_side not in {"buy", "sell"}:
            raise ValueError("live shadow audit side must be 'buy' or 'sell'")
        now = _now_pdt()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert or ignore into live_shadow_audits (
                  source_idempotency_key, paper_trade_id, source_wallet, asset_id, token_id, side,
                  paper_entry_price, best_ask_at_decision, order_price, requested_notional_usdc,
                  requested_size, available_size_at_price, would_fill_size, decision_latency_ms,
                  post_submit_book_price, notes, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_trade.idempotency_key,
                    int(paper_trade_id),
                    source_trade.source_wallet.lower(),
                    source_trade.asset_id,
                    source_trade.asset_id,
                    clean_side,
                    float(paper_entry_price),
                    None if best_ask_at_decision is None else float(best_ask_at_decision),
                    float(order_price),
                    float(requested_notional_usdc),
                    float(requested_size),
                    None if available_size_at_price is None else float(available_size_at_price),
                    None if would_fill_size is None else float(would_fill_size),
                    None if decision_latency_ms is None else int(decision_latency_ms),
                    None if post_submit_book_price is None else float(post_submit_book_price),
                    notes,
                    now,
                ),
            )
            if cursor.rowcount == 1:
                audit_id = int(cursor.lastrowid)
            else:
                existing = conn.execute(
                    "select id from live_shadow_audits where paper_trade_id = ?",
                    (int(paper_trade_id),),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("failed to create or find live shadow audit")
                audit_id = int(existing["id"])
            row = conn.execute("select * from live_shadow_audits where id = ?", (audit_id,)).fetchone()
        if row is None:
            raise RuntimeError("live shadow audit disappeared after create")
        return _live_shadow_audit_payload(row)

    def list_live_shadow_audits(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from live_shadow_audits
                order by id desc
                limit ?
                """,
                (int(limit),),
            ).fetchall()
        return [_live_shadow_audit_payload(row) for row in rows]

    def get_live_order_intent(self, intent_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from live_order_intents where id = ?", (int(intent_id),)).fetchone()
        return _live_order_intent_payload(row) if row else None

    def get_live_order_intent_for_source(self, source_idempotency_key: str, *, side: str) -> dict[str, Any] | None:
        clean_side = str(side).strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from live_order_intents
                where source_idempotency_key = ? and side = ?
                """,
                (str(source_idempotency_key), clean_side),
            ).fetchone()
        return _live_order_intent_payload(row) if row else None

    def get_live_order_intent_for_position(
        self,
        *,
        asset_id: str,
        source_wallet: str,
        side: str,
    ) -> dict[str, Any] | None:
        clean_side = str(side).strip().lower()
        terminal_statuses = ("filled", "cancelled", "canceled")
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from live_order_intents
                where asset_id = ?
                  and source_wallet = ?
                  and side = ?
                  and status not in (?, ?, ?)
                order by id desc
                limit 1
                """,
                (
                    str(asset_id),
                    self._clean_address(source_wallet),
                    clean_side,
                    *terminal_statuses,
                ),
            ).fetchone()
        return _live_order_intent_payload(row) if row else None

    def list_live_order_intents(
        self,
        *,
        source_idempotency_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_idempotency_key is not None:
            clauses.append("source_idempotency_key = ?")
            params.append(str(source_idempotency_key))
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status).strip().lower())
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from live_order_intents
                {where}
                order by id desc
                limit ?
                """,
                params,
            ).fetchall()
        return [_live_order_intent_payload(row) for row in rows]

    def create_live_settlement_intent(
        self,
        *,
        source_trade: SourceTrade,
        condition_id: str,
        quantity: float,
        resolution_price: float,
        status: str = "planned",
    ) -> dict[str, Any]:
        clean_condition_id = str(condition_id).strip()
        if not clean_condition_id:
            raise ValueError("live settlement condition_id is required")
        clean_quantity = float(quantity)
        if clean_quantity <= 0:
            raise ValueError("live settlement quantity must be positive")
        clean_resolution_price = float(resolution_price)
        if clean_resolution_price not in {0.0, 1.0}:
            raise ValueError("live settlement resolution_price must be 0 or 1")
        now = _now_pdt()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert or ignore into live_settlement_intents (
                  source_idempotency_key, source_wallet, asset_id, token_id,
                  condition_id, quantity, resolution_price, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_trade.idempotency_key,
                    source_trade.source_wallet.lower(),
                    source_trade.asset_id,
                    source_trade.asset_id,
                    clean_condition_id,
                    clean_quantity,
                    clean_resolution_price,
                    str(status).strip().lower() or "planned",
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 1:
                intent_id = int(cursor.lastrowid)
            else:
                existing = conn.execute(
                    """
                    select id from live_settlement_intents
                    where source_wallet = ? and asset_id = ?
                    """,
                    (source_trade.source_wallet.lower(), source_trade.asset_id),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("failed to create or find live settlement intent")
                intent_id = int(existing["id"])
            row = conn.execute("select * from live_settlement_intents where id = ?", (intent_id,)).fetchone()
        if row is None:
            raise RuntimeError("live settlement intent disappeared after create")
        return _live_settlement_intent_payload(row)

    def update_live_settlement_intent_status(
        self,
        intent_id: int,
        *,
        status: str,
        redemption_tx_hash: str | None = None,
        error: str | None = None,
        response: Any = None,
    ) -> dict[str, Any]:
        clean_status = str(status).strip().lower()
        if not clean_status:
            raise ValueError("live settlement intent status is required")
        response_json = _json_response_to_text(response)
        with self._connect() as conn:
            conn.execute(
                """
                update live_settlement_intents
                set status = ?,
                    redemption_tx_hash = coalesce(?, redemption_tx_hash),
                    error = ?,
                    response_json = coalesce(?, response_json),
                    updated_at = ?
                where id = ?
                """,
                (
                    clean_status,
                    redemption_tx_hash,
                    error,
                    response_json,
                    _now_pdt(),
                    int(intent_id),
                ),
            )
            row = conn.execute("select * from live_settlement_intents where id = ?", (int(intent_id),)).fetchone()
        if row is None:
            raise KeyError(f"live settlement intent not found: {intent_id}")
        return _live_settlement_intent_payload(row)

    def get_live_settlement_intent(self, intent_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from live_settlement_intents where id = ?", (int(intent_id),)).fetchone()
        return _live_settlement_intent_payload(row) if row else None

    def get_live_settlement_intent_for_position(self, *, asset_id: str, source_wallet: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from live_settlement_intents
                where asset_id = ? and source_wallet = ?
                """,
                (str(asset_id), self._clean_address(source_wallet)),
            ).fetchone()
        return _live_settlement_intent_payload(row) if row else None

    def list_live_settlement_intents(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status).strip().lower())
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from live_settlement_intents
                {where}
                order by id desc
                limit ?
                """,
                params,
            ).fetchall()
        return [_live_settlement_intent_payload(row) for row in rows]

    def update_position_trailing_state(
        self,
        *,
        asset_id: str,
        source_wallet: str,
        peak_price: float,
        activated: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update positions
                set trailing_peak_price = ?, trailing_activated = ?, updated_at = current_timestamp
                where asset_id = ? and source_wallet = ?
                """,
                (float(peak_price), int(bool(activated)), str(asset_id), self._clean_address(source_wallet)),
            )

    def mark_position_winner_capture(self, *, asset_id: str, source_wallet: str, field: str) -> None:
        allowed = {
            "winner_capture_stake_recovered",
            "winner_capture_first_scale_done",
            "winner_capture_high_price_done",
        }
        if field not in allowed:
            raise ValueError("invalid winner capture field")
        with self._connect() as conn:
            conn.execute(
                f"""
                update positions
                set {field} = 1, updated_at = current_timestamp
                where asset_id = ? and source_wallet = ?
                """,
                (str(asset_id), self._clean_address(source_wallet)),
            )

    def list_positions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  p.asset_id, p.source_wallet, w.name as source_wallet_name,
                  p.quantity, p.avg_entry_price, p.realized_pnl_usdc, p.status,
                  p.trailing_peak_price, p.trailing_activated,
                  p.winner_capture_stake_recovered, p.winner_capture_first_scale_done, p.winner_capture_high_price_done,
                  p.updated_at, mm.market_id, mm.condition_id, mm.outcome, mm.title, mm.market_slug,
                  mm.market_url, mm.current_price, mm.price_source, mm.last_price_at,
                  mm.market_type, mm.event_slug, mm.event_title,
                  mm.market_close_time, mm.market_close_time_kind, mm.is_closed, mm.resolution_price,
                  (
                    select min(pt.created_at)
                    from paper_trades pt
                    where pt.asset_id = p.asset_id
                      and pt.source_wallet = p.source_wallet
                      and pt.side = 'buy'
                  ) as buy_time,
                  (
                    select st.tx_hash
                    from paper_trades pt
                    left join source_trades st on st.idempotency_key = pt.source_idempotency_key
                    where pt.asset_id = p.asset_id
                      and pt.source_wallet = p.source_wallet
                      and pt.side = 'buy'
                    order by pt.created_at asc, pt.id asc
                    limit 1
                  ) as buy_tx_hash,
                  (
                    select coalesce(sum(pt.quantity), 0)
                    from paper_trades pt
                    where pt.asset_id = p.asset_id
                      and pt.source_wallet = p.source_wallet
                      and pt.side = 'buy'
                  ) as total_buy_quantity,
                  (
                    select coalesce(sum(pt.notional_usdc), 0)
                    from paper_trades pt
                    where pt.asset_id = p.asset_id
                      and pt.source_wallet = p.source_wallet
                      and pt.side = 'buy'
                  ) as total_buy_notional_usdc
                from positions p
                left join market_metadata mm on mm.asset_id = p.asset_id
                left join wallets w on w.address = p.source_wallet
                where p.quantity > 0
                order by p.updated_at desc
                """
            ).fetchall()
        return [_position_payload(row) for row in rows]

    def list_closed_positions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                with closed as (
                  select
                    pt.asset_id,
                    pt.source_wallet,
                    0 as quantity,
                    0 as avg_entry_price,
                    sum(pt.realized_pnl_usdc) as realized_pnl_usdc,
                    'closed' as status,
                    max(pt.created_at) as updated_at,
                    (
                      select min(buy.created_at)
                      from paper_trades buy
                      where buy.asset_id = pt.asset_id
                        and buy.source_wallet = pt.source_wallet
                        and buy.side = 'buy'
                    ) as buy_time,
                    max(pt.created_at) as close_time,
                    (
                      select st.tx_hash
                      from paper_trades buy
                      left join source_trades st on st.idempotency_key = buy.source_idempotency_key
                      where buy.asset_id = pt.asset_id
                        and buy.source_wallet = pt.source_wallet
                        and buy.side = 'buy'
                      order by buy.created_at asc, buy.id asc
                      limit 1
                    ) as buy_tx_hash,
                    (
                      select st.tx_hash
                      from paper_trades sell
                      left join source_trades st on st.idempotency_key = sell.source_idempotency_key
                      where sell.asset_id = pt.asset_id
                        and sell.source_wallet = pt.source_wallet
                        and sell.side = 'sell'
                      order by sell.created_at desc, sell.id desc
                      limit 1
                    ) as sell_tx_hash,
                    (
                      select sum(buy.notional_usdc) / nullif(sum(buy.quantity), 0)
                      from paper_trades buy
                      where buy.asset_id = pt.asset_id
                        and buy.source_wallet = pt.source_wallet
                        and buy.side = 'buy'
                    ) as entry_price,
                    sum(pt.notional_usdc) / nullif(sum(pt.quantity), 0) as exit_price,
                    sum(pt.quantity) as closed_quantity,
                    sum(pt.notional_usdc) as closed_notional_usdc,
                    (
                      select latest.close_reason
                      from paper_trades latest
                      where latest.asset_id = pt.asset_id
                        and latest.source_wallet = pt.source_wallet
                        and latest.side = 'sell'
                      order by latest.created_at desc, latest.id desc
                      limit 1
                    ) as close_reason
                  from paper_trades pt
                  left join positions p on p.asset_id = pt.asset_id and p.source_wallet = pt.source_wallet
                  where pt.side = 'sell'
                    and (p.asset_id is null or p.quantity <= 0)
                  group by pt.asset_id, pt.source_wallet
                )
                select
                  closed.asset_id, closed.source_wallet, w.name as source_wallet_name,
                  closed.quantity, closed.avg_entry_price,
                  closed.realized_pnl_usdc, closed.status, closed.updated_at,
                  closed.buy_time, closed.close_time, closed.buy_tx_hash, closed.sell_tx_hash,
                  mm.market_id, mm.condition_id, mm.outcome, mm.title, mm.market_slug,
                  mm.market_url, mm.current_price, mm.price_source, mm.last_price_at,
                  mm.market_type, mm.event_slug, mm.event_title,
                  mm.market_close_time, mm.market_close_time_kind, mm.is_closed, mm.resolution_price,
                  closed.entry_price, closed.exit_price, closed.closed_quantity,
                  closed.closed_notional_usdc, closed.close_reason
                from closed
                left join market_metadata mm on mm.asset_id = closed.asset_id
                left join wallets w on w.address = closed.source_wallet
                order by closed.updated_at desc
                """
            ).fetchall()
        return [_closed_position_payload(row) for row in rows]

    def list_trades(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        clean_limit = None if limit is None else max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                with recent_source_trades as (
                  select *
                  from source_trades
                  order by block_number desc, log_index desc
                  limit coalesce(?, -1)
                )
                select
                  st.idempotency_key, st.copy_trade_key, st.source_wallet, sw.name as source_wallet_name,
                  st.side as source_side, st.block_timestamp as source_time, st.asset_id,
                  st.market_id, st.outcome, st.price as source_price, st.quantity as source_quantity,
                  st.notional_usdc as source_notional_usdc, pt.side as paper_side,
                  pt.fill_price, pt.quantity as paper_quantity, pt.notional_usdc as paper_notional_usdc,
                  pt.realized_pnl_usdc, pt.close_reason, pt.created_at as paper_time, direct_sta.skip_reason,
                  (
                    select sum(buy.notional_usdc) / nullif(sum(buy.quantity), 0)
                    from paper_trades buy
                    where pt.id is not null
                      and buy.asset_id = pt.asset_id
                      and buy.source_wallet = pt.source_wallet
                      and buy.side = 'buy'
                      and (
                        buy.created_at < pt.created_at
                        or (buy.created_at = pt.created_at and buy.id <= pt.id)
                      )
                  ) as entry_price,
                  mm.title, mm.outcome as market_outcome,
                  mm.market_slug, mm.market_url, mm.current_price, mm.price_source, mm.last_price_at,
                  mm.market_type, mm.is_closed, mm.resolution_price,
                  (
                    select count(*)
                    from source_trade_attributions sta
                    where sta.copy_trade_key = st.copy_trade_key
                  ) as copied_from_count,
                  (
                    select group_concat(sta.source_wallet, ',')
                    from source_trade_attributions sta
                    where sta.copy_trade_key = st.copy_trade_key
                    order by sta.id
                  ) as copied_from_wallets,
                  (
                    select group_concat(coalesce(w.name, sta.source_wallet), ',')
                    from source_trade_attributions sta
                    left join wallets w on w.address = sta.source_wallet
                    where sta.copy_trade_key = st.copy_trade_key
                    order by sta.id
                  ) as copied_from_wallet_names
                from recent_source_trades st
                left join paper_trades pt on pt.copy_trade_key = st.copy_trade_key
                left join source_trade_attributions direct_sta on direct_sta.source_idempotency_key = st.idempotency_key
                left join market_metadata mm on mm.asset_id = st.asset_id
                left join wallets sw on sw.address = st.source_wallet
                order by st.block_number desc, st.log_index desc
                """,
                (clean_limit,),
            ).fetchall()
        trades: list[dict[str, Any]] = []
        for row in rows:
            item = _row_dict(row)
            item["paper_time"] = _utc_sqlite_timestamp_to_pdt(item.get("paper_time"))
            wallets = item.get("copied_from_wallets")
            item["copied_from_wallets"] = wallets.split(",") if wallets else []
            wallet_names = item.get("copied_from_wallet_names")
            item["copied_from_wallet_names"] = wallet_names.split(",") if wallet_names else []
            current_price = _optional_float(item.get("current_price"))
            fill_price = _optional_float(item.get("fill_price"))
            entry_price = _optional_float(item.get("entry_price"))
            quantity = _optional_float(item.get("paper_quantity")) or 0.0
            item["current_price"] = current_price
            item["entry_price"] = round(entry_price, 6) if entry_price is not None else None
            item["entry_notional_usdc"] = round(entry_price * quantity, 6) if entry_price is not None else None
            item["unrealized_pnl_usdc"] = (
                round((current_price - fill_price) * quantity, 6)
                if current_price is not None and fill_price is not None and item.get("paper_side") == "buy"
                else None
            )
            trades.append(item)
        return trades

    def skip_reason_summary(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  skip_reason,
                  count(*) as count,
                  coalesce(sum(source_notional_usdc), 0) as source_notional_usdc
                from source_trade_attributions
                where executed = 0
                  and skip_reason is not null
                group by skip_reason
                order by count(*) desc, skip_reason
                """
            ).fetchall()
        return [
            {
                "skip_reason": row["skip_reason"],
                "count": int(row["count"]),
                "source_notional_usdc": round(float(row["source_notional_usdc"] or 0), 6),
            }
            for row in rows
        ]

    def list_open_asset_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select distinct asset_id
                from positions
                where quantity > 0
                order by updated_at desc
                """
            ).fetchall()
        return [str(row["asset_id"]) for row in rows]

    def list_price_monitor_asset_ids(self, *, recent_trade_limit: int = 50) -> list[str]:
        asset_ids = self.list_open_asset_ids()
        seen = set(asset_ids)
        clean_limit = max(1, int(recent_trade_limit))
        scan_limit = max(clean_limit * 50, 1000)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select asset_id
                from source_trades
                order by block_number desc, log_index desc
                limit ?
                """,
                (scan_limit,),
            ).fetchall()
        added_recent = 0
        for row in rows:
            asset_id = str(row["asset_id"])
            if asset_id not in seen:
                asset_ids.append(asset_id)
                seen.add(asset_id)
                added_recent += 1
                if added_recent >= clean_limit:
                    break
        return asset_ids

    def get_market_metadata(self, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from market_metadata where asset_id = ?", (str(asset_id),)).fetchone()
        return _row_dict(row) if row else None

    def source_inventory_quantity_before(self, trade: SourceTrade) -> float:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                  coalesce(sum(case when side = 'buy' then quantity else -quantity end), 0) as quantity
                from source_trades
                where source_wallet = ?
                  and asset_id = ?
                  and idempotency_key != ?
                  and (
                    block_number < ?
                    or (block_number = ? and log_index < ?)
                  )
                """,
                (
                    trade.source_wallet.lower(),
                    trade.asset_id,
                    trade.idempotency_key,
                    trade.block_number,
                    trade.block_number,
                    trade.log_index,
                ),
            ).fetchone()
        return float(row["quantity"] or 0)

    def source_position_summary(
        self,
        *,
        source_wallet: str,
        asset_id: str,
        anchor_trade: SourceTrade | None = None,
        window_seconds: int = 0,
    ) -> dict[str, float | int]:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select side, price, quantity, notional_usdc, block_timestamp, block_number, log_index, idempotency_key
                from source_trades
                where source_wallet = ?
                  and asset_id = ?
                order by block_number, log_index
                """,
                (clean_wallet, str(asset_id)),
            ).fetchall()

        anchor_time = _parse_source_timestamp(anchor_trade.block_timestamp) if anchor_trade is not None else None
        since_time = anchor_time - timedelta(seconds=int(window_seconds)) if anchor_time is not None and window_seconds > 0 else None
        buy_count = 0
        buy_notional = 0.0
        buy_quantity = 0.0
        sell_notional = 0.0
        sell_quantity = 0.0
        for row in rows:
            if anchor_trade is not None and _source_row_after_trade(row, anchor_trade):
                continue
            row_time = _parse_source_timestamp(row["block_timestamp"])
            if since_time is not None and row_time is not None and row_time < since_time:
                continue
            side = str(row["side"] or "").lower()
            quantity = float(row["quantity"] or 0)
            notional = float(row["notional_usdc"] or 0)
            if side == "buy":
                buy_count += 1
                buy_notional += notional
                buy_quantity += quantity
            elif side == "sell":
                sell_notional += notional
                sell_quantity += quantity
        net_quantity = buy_quantity - sell_quantity
        avg_buy_price = buy_notional / buy_quantity if buy_quantity > 0 else 0.0
        return {
            "buy_count": buy_count,
            "buy_notional_usdc": round(buy_notional, 6),
            "buy_quantity": round(buy_quantity, 6),
            "sell_notional_usdc": round(sell_notional, 6),
            "sell_quantity": round(sell_quantity, 6),
            "net_quantity": round(net_quantity, 6),
            "net_notional_usdc": round(max(0.0, net_quantity) * avg_buy_price, 6),
            "avg_buy_price": round(avg_buy_price, 6),
        }

    def source_event_position_summaries(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        anchor_trade: SourceTrade | None = None,
    ) -> list[dict[str, Any]]:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug or "").strip()
        if not clean_event:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  st.asset_id, st.side, st.price, st.quantity, st.notional_usdc,
                  st.block_timestamp, st.block_number, st.log_index, st.idempotency_key,
                  mm.title, mm.outcome, mm.event_slug
                from source_trades st
                join market_metadata mm on mm.asset_id = st.asset_id
                where st.source_wallet = ?
                  and mm.event_slug = ?
                order by st.block_number, st.log_index
                """,
                (clean_wallet, clean_event),
            ).fetchall()

        by_asset: dict[str, dict[str, Any]] = {}
        for row in rows:
            if anchor_trade is not None and _source_row_after_trade(row, anchor_trade):
                continue
            asset_id = str(row["asset_id"])
            item = by_asset.setdefault(
                asset_id,
                {
                    "asset_id": asset_id,
                    "title": row["title"],
                    "outcome": row["outcome"],
                    "buy_count": 0,
                    "buy_notional_usdc": 0.0,
                    "buy_quantity": 0.0,
                    "sell_notional_usdc": 0.0,
                    "sell_quantity": 0.0,
                },
            )
            side = str(row["side"] or "").lower()
            quantity = float(row["quantity"] or 0)
            notional = float(row["notional_usdc"] or 0)
            if side == "buy":
                item["buy_count"] += 1
                item["buy_notional_usdc"] += notional
                item["buy_quantity"] += quantity
            elif side == "sell":
                item["sell_notional_usdc"] += notional
                item["sell_quantity"] += quantity

        summaries = []
        for item in by_asset.values():
            buy_quantity = float(item["buy_quantity"] or 0)
            buy_notional = float(item["buy_notional_usdc"] or 0)
            net_quantity = float(item["buy_quantity"] or 0) - float(item["sell_quantity"] or 0)
            avg_buy_price = buy_notional / buy_quantity if buy_quantity > 0 else 0.0
            summaries.append(
                {
                    **item,
                    "buy_notional_usdc": round(buy_notional, 6),
                    "buy_quantity": round(buy_quantity, 6),
                    "sell_notional_usdc": round(float(item["sell_notional_usdc"] or 0), 6),
                    "sell_quantity": round(float(item["sell_quantity"] or 0), 6),
                    "net_quantity": round(net_quantity, 6),
                    "net_notional_usdc": round(max(0.0, net_quantity) * avg_buy_price, 6),
                    "avg_buy_price": round(avg_buy_price, 6),
                }
            )
        return sorted(summaries, key=lambda item: float(item["net_notional_usdc"] or 0), reverse=True)

    def latest_source_trade_for_asset(
        self,
        *,
        source_wallet: str,
        asset_id: str,
        anchor_trade: SourceTrade | None = None,
        side: str = "buy",
    ) -> SourceTrade | None:
        clean_wallet = self._clean_address(source_wallet)
        clean_side = str(side or "").strip().lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  idempotency_key, chain_id, exchange_contract, tx_hash, block_number, block_timestamp,
                  log_index, source_wallet, side, asset_id, condition_id, market_id, outcome, price,
                  quantity, notional_usdc, copy_trade_key
                from source_trades
                where source_wallet = ?
                  and asset_id = ?
                  and side = ?
                order by block_number desc, log_index desc
                """,
                (clean_wallet, str(asset_id), clean_side),
            ).fetchall()
        for row in rows:
            if anchor_trade is not None and _source_row_after_trade(row, anchor_trade):
                continue
            return SourceTrade(
                idempotency_key=str(row["idempotency_key"]),
                chain_id=int(row["chain_id"]),
                exchange_contract=str(row["exchange_contract"]),
                tx_hash=str(row["tx_hash"]),
                block_number=int(row["block_number"]),
                block_timestamp=str(row["block_timestamp"]),
                log_index=int(row["log_index"]),
                source_wallet=str(row["source_wallet"]),
                side=str(row["side"]),
                asset_id=str(row["asset_id"]),
                condition_id=row["condition_id"],
                market_id=row["market_id"],
                outcome=row["outcome"],
                price=float(row["price"]),
                quantity=float(row["quantity"]),
                notional_usdc=float(row["notional_usdc"]),
                copy_trade_key=row["copy_trade_key"],
            )
        return None

    def paper_buy_notional_for_wallet_since(self, *, source_wallet: str, since_utc: datetime) -> float:
        clean_wallet = self._clean_address(source_wallet)
        since_text = since_utc.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            row = conn.execute(
                """
                select coalesce(sum(notional_usdc), 0) as total
                from paper_trades
                where source_wallet = ?
                  and side = 'buy'
                  and created_at >= ?
                """,
                (clean_wallet, since_text),
            ).fetchone()
        return float(row["total"] or 0)

    def database_maintenance_report(
        self,
        *,
        retention_hours: int = 72,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cutoff = _retention_cutoff_pdt(retention_hours, now=now)
        with self._connect() as conn:
            _populate_source_history_prune_ids(conn, cutoff)
            page_size = int(conn.execute("pragma page_size").fetchone()[0])
            page_count = int(conn.execute("pragma page_count").fetchone()[0])
            freelist_count = int(conn.execute("pragma freelist_count").fetchone()[0])
            journal_mode = str(conn.execute("pragma journal_mode").fetchone()[0])
            row_counts = {
                table: int(conn.execute(f'select count(*) from "{table}"').fetchone()[0])
                for table in _table_names(conn)
            }
            prune = _source_history_prune_stats(conn)
            orphan_attributions = int(
                conn.execute(
                    """
                    select count(*)
                    from source_trade_attributions sta
                    left join source_trades st on st.idempotency_key = sta.source_idempotency_key
                    where st.idempotency_key is null
                    """
                ).fetchone()[0]
            )
        return {
            "database_path": str(self.path),
            "database_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "wal_bytes": self.path.with_name(self.path.name + "-wal").stat().st_size
            if self.path.with_name(self.path.name + "-wal").exists()
            else 0,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "used_bytes": page_size * max(0, page_count - freelist_count),
            "journal_mode": journal_mode,
            "retention_hours": int(retention_hours),
            "cutoff_pdt": cutoff,
            "row_counts": row_counts,
            "source_history_prune_candidates": prune,
            "orphan_source_trade_attributions": orphan_attributions,
        }

    def prune_old_source_history(
        self,
        *,
        retention_hours: int = 72,
        apply: bool = False,
        vacuum: bool = False,
        analyze: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cutoff = _retention_cutoff_pdt(retention_hours, now=now)
        with self._connect() as conn:
            _populate_source_history_prune_ids(conn, cutoff)
            stats = _source_history_prune_stats(conn)
            orphan_attributions = int(
                conn.execute(
                    """
                    select count(*)
                    from source_trade_attributions sta
                    left join source_trades st on st.idempotency_key = sta.source_idempotency_key
                    where st.idempotency_key is null
                    """
                ).fetchone()[0]
            )
            result = {
                "applied": False,
                "retention_hours": int(retention_hours),
                "cutoff_pdt": cutoff,
                "candidates": stats,
                "orphan_source_trade_attributions": orphan_attributions,
                "deleted_source_trade_attributions": 0,
                "deleted_source_trades": 0,
                "vacuumed": False,
                "analyzed": False,
            }
            if not apply:
                return result
            attribution_cursor = conn.execute(
                """
                delete from source_trade_attributions
                where source_idempotency_key in (select idempotency_key from temp.source_history_prune_ids)
                   or not exists (
                        select 1
                        from source_trades st
                        where st.idempotency_key = source_trade_attributions.source_idempotency_key
                   )
                """
            )
            source_cursor = conn.execute(
                """
                delete from source_trades
                where idempotency_key in (select idempotency_key from temp.source_history_prune_ids)
                """
            )
            result["applied"] = True
            result["deleted_source_trade_attributions"] = max(0, int(attribution_cursor.rowcount))
            result["deleted_source_trades"] = max(0, int(source_cursor.rowcount))
        if vacuum:
            with self._connect() as conn:
                conn.execute("pragma wal_checkpoint(truncate)")
                conn.execute("vacuum")
            result["vacuumed"] = True
        if analyze:
            self.optimize_database(analyze=True)
            result["analyzed"] = True
        return result

    def optimize_database(self, *, analyze: bool = False) -> dict[str, Any]:
        with self._connect() as conn:
            if analyze:
                conn.execute("analyze")
            conn.execute("pragma optimize")
            checkpoint = conn.execute("pragma wal_checkpoint(passive)").fetchone()
        return {
            "analyzed": bool(analyze),
            "wal_checkpoint": tuple(checkpoint) if checkpoint is not None else None,
        }

    def upsert_market_metadata(
        self,
        *,
        asset_id: str,
        current_price: float | None = None,
        price_source: str | None = None,
        market_id: str | None = None,
        condition_id: str | None = None,
        outcome: str | None = None,
        outcome_side: str | None = None,
        title: str | None = None,
        market_slug: str | None = None,
        market_url: str | None = None,
        market_type: str | None = None,
        sport_key: str | None = None,
        bet_type: str | None = None,
        series_slug: str | None = None,
        sports_market_type: str | None = None,
        category_slug: str | None = None,
        market_close_time: str | None = None,
        market_close_time_kind: str | None = None,
        event_slug: str | None = None,
        event_title: str | None = None,
        neg_risk: bool | None = None,
        mergeable: bool | None = None,
        is_closed: bool | None = None,
        resolution_price: float | None = None,
        last_price_at: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into market_metadata (
                  asset_id, market_id, condition_id, outcome, outcome_side, title, market_slug, market_url,
                  current_price, price_source, last_price_at, market_type, sport_key, bet_type,
                  series_slug, sports_market_type, category_slug, event_slug, event_title,
                  market_close_time, market_close_time_kind, neg_risk, mergeable, is_closed, resolution_price, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                on conflict(asset_id) do update set
                  market_id = coalesce(excluded.market_id, market_metadata.market_id),
                  condition_id = coalesce(excluded.condition_id, market_metadata.condition_id),
                  outcome = coalesce(excluded.outcome, market_metadata.outcome),
                  outcome_side = coalesce(excluded.outcome_side, market_metadata.outcome_side),
                  title = coalesce(excluded.title, market_metadata.title),
                  market_slug = coalesce(excluded.market_slug, market_metadata.market_slug),
                  market_url = coalesce(excluded.market_url, market_metadata.market_url),
                  current_price = coalesce(excluded.current_price, market_metadata.current_price),
                  price_source = coalesce(excluded.price_source, market_metadata.price_source),
                  last_price_at = coalesce(excluded.last_price_at, market_metadata.last_price_at),
                  market_type = coalesce(excluded.market_type, market_metadata.market_type),
                  sport_key = coalesce(excluded.sport_key, market_metadata.sport_key),
                  bet_type = coalesce(excluded.bet_type, market_metadata.bet_type),
                  series_slug = coalesce(excluded.series_slug, market_metadata.series_slug),
                  sports_market_type = coalesce(excluded.sports_market_type, market_metadata.sports_market_type),
                  category_slug = coalesce(excluded.category_slug, market_metadata.category_slug),
                  market_close_time = coalesce(excluded.market_close_time, market_metadata.market_close_time),
                  market_close_time_kind = coalesce(excluded.market_close_time_kind, market_metadata.market_close_time_kind),
                  event_slug = coalesce(excluded.event_slug, market_metadata.event_slug),
                  event_title = coalesce(excluded.event_title, market_metadata.event_title),
                  neg_risk = coalesce(excluded.neg_risk, market_metadata.neg_risk),
                  mergeable = coalesce(excluded.mergeable, market_metadata.mergeable),
                  is_closed = coalesce(excluded.is_closed, market_metadata.is_closed),
                  resolution_price = coalesce(excluded.resolution_price, market_metadata.resolution_price),
                  updated_at = current_timestamp
                """,
                (
                    str(asset_id),
                    market_id,
                    condition_id,
                    outcome,
                    outcome_side,
                    title,
                    market_slug,
                    market_url,
                    current_price,
                    price_source,
                    last_price_at,
                    market_type,
                    sport_key,
                    bet_type,
                    series_slug,
                    sports_market_type,
                    category_slug,
                    event_slug,
                    event_title,
                    market_close_time,
                    market_close_time_kind,
                    int(neg_risk) if neg_risk is not None else None,
                    int(mergeable) if mergeable is not None else None,
                    int(is_closed) if is_closed is not None else None,
                    resolution_price,
                ),
            )

    def record_weather_bracket_source_buy(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        event_title: str | None,
        trade: SourceTrade,
        market_slug: str | None,
        title: str | None,
        event_budget_usdc: float,
    ) -> dict[str, Any]:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug).strip()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert into weather_brackets (source_wallet, event_slug, event_title)
                values (?, ?, ?)
                on conflict(source_wallet, event_slug) do update set
                  event_title = coalesce(excluded.event_title, weather_brackets.event_title),
                  updated_at = current_timestamp
                returning id
                """,
                (clean_wallet, clean_event, event_title),
            )
            bracket_id = int(cursor.fetchone()["id"])
            conn.execute(
                """
                insert into weather_bracket_legs (
                  bracket_id, asset_id, outcome, market_slug, title, source_quantity, source_notional_usdc
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(bracket_id, asset_id) do update set
                  outcome = coalesce(excluded.outcome, weather_bracket_legs.outcome),
                  market_slug = coalesce(excluded.market_slug, weather_bracket_legs.market_slug),
                  title = coalesce(excluded.title, weather_bracket_legs.title),
                  source_quantity = weather_bracket_legs.source_quantity + excluded.source_quantity,
                  source_notional_usdc = weather_bracket_legs.source_notional_usdc + excluded.source_notional_usdc,
                  updated_at = current_timestamp
                """,
                (
                    bracket_id,
                    trade.asset_id,
                    trade.outcome,
                    market_slug,
                    title,
                    trade.quantity,
                    trade.notional_usdc,
                ),
            )
            total_row = conn.execute(
                "select coalesce(sum(source_notional_usdc), 0) as total from weather_bracket_legs where bracket_id = ?",
                (bracket_id,),
            ).fetchone()
            source_total = float(total_row["total"] or 0)
            target_total = min(float(event_budget_usdc), source_total) if source_total > 0 else 0.0
            legs = conn.execute(
                "select id, asset_id, source_notional_usdc, copied_notional_usdc from weather_bracket_legs where bracket_id = ?",
                (bracket_id,),
            ).fetchall()
            for leg in legs:
                target = target_total * (float(leg["source_notional_usdc"] or 0) / source_total) if source_total > 0 else 0.0
                conn.execute(
                    "update weather_bracket_legs set target_notional_usdc = ?, updated_at = current_timestamp where id = ?",
                    (round(target, 6), leg["id"]),
                )
            conn.execute(
                """
                update weather_brackets
                set source_notional_usdc = ?,
                    target_notional_usdc = ?,
                    updated_at = current_timestamp
                where id = ?
                """,
                (round(source_total, 6), round(target_total, 6), bracket_id),
            )
            row = conn.execute(
                """
                select
                  wb.id as bracket_id, wb.source_wallet, wb.event_slug, wb.event_title,
                  wb.source_notional_usdc, wb.target_notional_usdc, wb.copied_notional_usdc,
                  wbl.asset_id, wbl.source_notional_usdc as leg_source_notional_usdc,
                  wbl.target_notional_usdc as leg_target_notional_usdc,
                  wbl.copied_notional_usdc as leg_copied_notional_usdc
                from weather_brackets wb
                join weather_bracket_legs wbl on wbl.bracket_id = wb.id
                where wb.id = ? and wbl.asset_id = ?
                """,
                (bracket_id, trade.asset_id),
            ).fetchone()
        return _row_dict(row)

    def record_weather_bracket_copied_buy(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        asset_id: str,
        copied_notional_usdc: float,
    ) -> None:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                "select id from weather_brackets where source_wallet = ? and event_slug = ?",
                (clean_wallet, event_slug),
            ).fetchone()
            if row is None:
                return
            bracket_id = int(row["id"])
            conn.execute(
                """
                update weather_bracket_legs
                set copied_notional_usdc = copied_notional_usdc + ?,
                    updated_at = current_timestamp
                where bracket_id = ? and asset_id = ?
                """,
                (copied_notional_usdc, bracket_id, asset_id),
            )
            conn.execute(
                """
                update weather_brackets
                set copied_notional_usdc = (
                    select coalesce(sum(copied_notional_usdc), 0)
                    from weather_bracket_legs
                    where bracket_id = ?
                  ),
                  updated_at = current_timestamp
                where id = ?
                """,
                (bracket_id, bracket_id),
            )

    def record_repeat_buy_source_buy(
        self,
        *,
        source_wallet: str,
        trade: SourceTrade,
        market_id: str | None,
        title: str | None,
        outcome: str | None,
    ) -> dict[str, Any]:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into repeat_buy_signals (
                  source_wallet, asset_id, market_id, title, outcome,
                  buy_count, source_notional_usdc, source_quantity
                )
                values (?, ?, ?, ?, ?, 1, ?, ?)
                on conflict(source_wallet, asset_id) do update set
                  market_id = coalesce(excluded.market_id, repeat_buy_signals.market_id),
                  title = coalesce(excluded.title, repeat_buy_signals.title),
                  outcome = coalesce(excluded.outcome, repeat_buy_signals.outcome),
                  buy_count = repeat_buy_signals.buy_count + 1,
                  source_notional_usdc = repeat_buy_signals.source_notional_usdc + excluded.source_notional_usdc,
                  source_quantity = repeat_buy_signals.source_quantity + excluded.source_quantity,
                  updated_at = current_timestamp
                returning *
                """,
                (
                    clean_wallet,
                    trade.asset_id,
                    market_id,
                    title,
                    outcome or trade.outcome,
                    trade.notional_usdc,
                    trade.quantity,
                ),
            ).fetchone()
        return _repeat_buy_payload(row)

    def record_repeat_buy_copied(
        self,
        *,
        source_wallet: str,
        asset_id: str,
        paper_trade_id: int,
        copied_notional_usdc: float,
    ) -> None:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            conn.execute(
                """
                update repeat_buy_signals
                set copied = 1,
                    paper_trade_id = ?,
                    copied_notional_usdc = copied_notional_usdc + ?,
                    updated_at = current_timestamp
                where source_wallet = ? and asset_id = ?
                """,
                (paper_trade_id, copied_notional_usdc, clean_wallet, asset_id),
            )

    def get_repeat_buy_signal(self, source_wallet: str, asset_id: str) -> dict[str, Any] | None:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                "select * from repeat_buy_signals where source_wallet = ? and asset_id = ?",
                (clean_wallet, asset_id),
            ).fetchone()
        return _repeat_buy_payload(row) if row else None

    def record_event_follow_source_buy(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        event_title: str | None,
        market_type: str | None,
        trade: SourceTrade,
        market_slug: str | None,
        title: str | None,
    ) -> dict[str, Any]:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug).strip()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert into event_follow_signals (
                  source_wallet, event_slug, event_title, market_type,
                  buy_count, source_notional_usdc, source_quantity
                )
                values (?, ?, ?, ?, 1, ?, ?)
                on conflict(source_wallet, event_slug) do update set
                  event_title = coalesce(excluded.event_title, event_follow_signals.event_title),
                  market_type = coalesce(excluded.market_type, event_follow_signals.market_type),
                  buy_count = event_follow_signals.buy_count + 1,
                  source_notional_usdc = event_follow_signals.source_notional_usdc + excluded.source_notional_usdc,
                  source_quantity = event_follow_signals.source_quantity + excluded.source_quantity,
                  updated_at = current_timestamp
                returning id
                """,
                (clean_wallet, clean_event, event_title, market_type, trade.notional_usdc, trade.quantity),
            )
            signal_id = int(cursor.fetchone()["id"])
            conn.execute(
                """
                insert into event_follow_legs (
                  signal_id, asset_id, outcome, market_slug, title,
                  buy_count, source_notional_usdc, source_quantity
                )
                values (?, ?, ?, ?, ?, 1, ?, ?)
                on conflict(signal_id, asset_id) do update set
                  outcome = coalesce(excluded.outcome, event_follow_legs.outcome),
                  market_slug = coalesce(excluded.market_slug, event_follow_legs.market_slug),
                  title = coalesce(excluded.title, event_follow_legs.title),
                  buy_count = event_follow_legs.buy_count + 1,
                  source_notional_usdc = event_follow_legs.source_notional_usdc + excluded.source_notional_usdc,
                  source_quantity = event_follow_legs.source_quantity + excluded.source_quantity,
                  updated_at = current_timestamp
                """,
                (
                    signal_id,
                    trade.asset_id,
                    trade.outcome,
                    market_slug,
                    title,
                    trade.notional_usdc,
                    trade.quantity,
                ),
            )
            row = conn.execute("select * from event_follow_signals where id = ?", (signal_id,)).fetchone()
        return _event_follow_payload(row)

    def record_event_follow_copied_buy(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        asset_id: str,
        copied_notional_usdc: float,
    ) -> None:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                "select id from event_follow_signals where source_wallet = ? and event_slug = ?",
                (clean_wallet, event_slug),
            ).fetchone()
            if row is None:
                return
            signal_id = int(row["id"])
            conn.execute(
                """
                update event_follow_legs
                set copied_notional_usdc = copied_notional_usdc + ?,
                    updated_at = current_timestamp
                where signal_id = ? and asset_id = ?
                """,
                (copied_notional_usdc, signal_id, asset_id),
            )
            conn.execute(
                """
                update event_follow_signals
                set copied_notional_usdc = (
                    select coalesce(sum(copied_notional_usdc), 0)
                    from event_follow_legs
                    where signal_id = ?
                  ),
                  updated_at = current_timestamp
                where id = ?
                """,
                (signal_id, signal_id),
            )

    def paper_buy_notional_for_asset(self, *, source_wallet: str, asset_id: str) -> float:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                """
                select coalesce(sum(notional_usdc), 0) as total
                from paper_trades
                where source_wallet = ?
                  and asset_id = ?
                  and side = 'buy'
                """,
                (clean_wallet, str(asset_id)),
            ).fetchone()
        return float(row["total"] or 0)

    def record_sports_bracket_candidate(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        event_title: str | None,
        pattern: str,
        legs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug).strip()
        source_total = sum(float(leg.get("source_notional_usdc") or 0) for leg in legs)
        target_total = sum(float(leg.get("target_notional_usdc") or 0) for leg in legs)
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into sports_brackets (
                  source_wallet, event_slug, event_title, pattern,
                  source_notional_usdc, target_notional_usdc
                )
                values (?, ?, ?, ?, ?, ?)
                on conflict(source_wallet, event_slug, pattern) do update set
                  event_title = coalesce(excluded.event_title, sports_brackets.event_title),
                  source_notional_usdc = excluded.source_notional_usdc,
                  target_notional_usdc = excluded.target_notional_usdc,
                  updated_at = current_timestamp
                returning id
                """,
                (
                    clean_wallet,
                    clean_event,
                    event_title,
                    pattern,
                    round(source_total, 6),
                    round(target_total, 6),
                ),
            ).fetchone()
            bracket_id = int(row["id"])
            for leg in legs:
                conn.execute(
                    """
                    insert into sports_bracket_legs (
                      bracket_id, asset_id, outcome, market_slug, title,
                      source_quantity, source_notional_usdc, target_notional_usdc,
                      copied_notional_usdc
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(bracket_id, asset_id) do update set
                      outcome = coalesce(excluded.outcome, sports_bracket_legs.outcome),
                      market_slug = coalesce(excluded.market_slug, sports_bracket_legs.market_slug),
                      title = coalesce(excluded.title, sports_bracket_legs.title),
                      source_quantity = excluded.source_quantity,
                      source_notional_usdc = excluded.source_notional_usdc,
                      target_notional_usdc = excluded.target_notional_usdc,
                      copied_notional_usdc = max(sports_bracket_legs.copied_notional_usdc, excluded.copied_notional_usdc),
                      updated_at = current_timestamp
                    """,
                    (
                        bracket_id,
                        str(leg.get("asset_id") or ""),
                        leg.get("outcome"),
                        leg.get("market_slug"),
                        leg.get("title"),
                        float(leg.get("source_quantity") or 0),
                        float(leg.get("source_notional_usdc") or 0),
                        float(leg.get("target_notional_usdc") or 0),
                        float(leg.get("copied_notional_usdc") or 0),
                    ),
                )
            conn.execute(
                """
                update sports_brackets
                set copied_notional_usdc = (
                    select coalesce(sum(copied_notional_usdc), 0)
                    from sports_bracket_legs
                    where bracket_id = ?
                  ),
                  updated_at = current_timestamp
                where id = ?
                """,
                (bracket_id, bracket_id),
            )
            saved = conn.execute("select * from sports_brackets where id = ?", (bracket_id,)).fetchone()
        return _sports_bracket_payload(saved)

    def record_sports_bracket_copied_buy(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        pattern: str,
        asset_id: str,
        copied_notional_usdc: float,
    ) -> None:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug).strip()
        with self._connect() as conn:
            row = conn.execute(
                """
                select id from sports_brackets
                where source_wallet = ? and event_slug = ? and pattern = ?
                """,
                (clean_wallet, clean_event, pattern),
            ).fetchone()
            if row is None:
                return
            bracket_id = int(row["id"])
            conn.execute(
                """
                update sports_bracket_legs
                set copied_notional_usdc = copied_notional_usdc + ?,
                    updated_at = current_timestamp
                where bracket_id = ? and asset_id = ?
                """,
                (float(copied_notional_usdc), bracket_id, str(asset_id)),
            )
            conn.execute(
                """
                update sports_brackets
                set copied_notional_usdc = (
                    select coalesce(sum(copied_notional_usdc), 0)
                    from sports_bracket_legs
                    where bracket_id = ?
                  ),
                  status = case
                    when (
                      select count(*)
                      from sports_bracket_legs sbl
                      left join positions p
                        on p.asset_id = sbl.asset_id
                       and p.source_wallet = sports_brackets.source_wallet
                      where sbl.bracket_id = ?
                        and coalesce(p.quantity, 0) > 0
                    ) > 0 then 'open'
                    else status
                  end,
                  updated_at = current_timestamp
                where id = ?
                """,
                (bracket_id, bracket_id, bracket_id),
            )

    def list_sports_brackets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                with leg_paper as (
                  select
                    asset_id,
                    source_wallet,
                    sum(case when side = 'buy' then notional_usdc else 0 end) as buy_notional_usdc,
                    sum(case when side = 'buy' then quantity else 0 end) as buy_quantity,
                    sum(case when side = 'sell' then notional_usdc else 0 end) as sell_notional_usdc,
                    sum(case when side = 'sell' then quantity else 0 end) as sell_quantity,
                    sum(realized_pnl_usdc) as realized_pnl_usdc,
                    min(case when side = 'buy' then created_at end) as buy_time,
                    max(case when side = 'sell' then created_at end) as sell_time,
                    (
                      select st.tx_hash
                      from paper_trades buy
                      left join source_trades st on st.idempotency_key = buy.source_idempotency_key
                      where buy.asset_id = paper_trades.asset_id
                        and buy.source_wallet = paper_trades.source_wallet
                        and buy.side = 'buy'
                      order by buy.created_at asc, buy.id asc
                      limit 1
                    ) as buy_tx_hash,
                    (
                      select st.tx_hash
                      from paper_trades sell
                      left join source_trades st on st.idempotency_key = sell.source_idempotency_key
                      where sell.asset_id = paper_trades.asset_id
                        and sell.source_wallet = paper_trades.source_wallet
                        and sell.side = 'sell'
                      order by sell.created_at desc, sell.id desc
                      limit 1
                    ) as sell_tx_hash
                  from paper_trades
                  group by paper_trades.asset_id, paper_trades.source_wallet
                )
                select
                  sb.id as bracket_id, sb.source_wallet, w.name as source_wallet_name,
                  sb.event_slug, sb.event_title, sb.pattern, sb.status,
                  sb.source_notional_usdc as bracket_source_notional_usdc,
                  sb.target_notional_usdc as bracket_target_notional_usdc,
                  sb.copied_notional_usdc as bracket_copied_notional_usdc,
                  sb.created_at as bracket_created_at, sb.updated_at as bracket_updated_at,
                  sbl.asset_id, sbl.outcome, sbl.market_slug, sbl.title,
                  sbl.source_quantity, sbl.source_notional_usdc, sbl.target_notional_usdc,
                  sbl.copied_notional_usdc,
                  mm.market_url, mm.current_price, mm.market_close_time, mm.market_close_time_kind, mm.is_closed,
                  p.quantity as open_quantity, p.avg_entry_price,
                  lp.buy_notional_usdc, lp.buy_quantity, lp.sell_notional_usdc,
                  lp.sell_quantity, lp.realized_pnl_usdc, lp.buy_time, lp.sell_time,
                  lp.buy_tx_hash, lp.sell_tx_hash
                from sports_brackets sb
                join sports_bracket_legs sbl on sbl.bracket_id = sb.id
                left join wallets w on w.address = sb.source_wallet
                left join market_metadata mm on mm.asset_id = sbl.asset_id
                left join positions p on p.asset_id = sbl.asset_id and p.source_wallet = sb.source_wallet
                left join leg_paper lp on lp.asset_id = sbl.asset_id and lp.source_wallet = sb.source_wallet
                where sb.copied_notional_usdc > 0
                order by sb.updated_at desc, sbl.source_notional_usdc desc
                """
            ).fetchall()

        brackets: dict[int, dict[str, Any]] = {}
        for row in rows:
            bracket_id = int(row["bracket_id"])
            bracket = brackets.setdefault(
                bracket_id,
                {
                    "id": bracket_id,
                    "source_wallet": row["source_wallet"],
                    "source_wallet_name": row["source_wallet_name"],
                    "event_slug": row["event_slug"],
                    "event_title": row["event_title"],
                    "pattern": row["pattern"],
                    "status": row["status"],
                    "source_notional_usdc": round(float(row["bracket_source_notional_usdc"] or 0), 6),
                    "target_notional_usdc": round(float(row["bracket_target_notional_usdc"] or 0), 6),
                    "copied_notional_usdc": round(float(row["bracket_copied_notional_usdc"] or 0), 6),
                    "buy_time": None,
                    "sell_time": None,
                    "current_value_usdc": 0.0,
                    "cost_basis_usdc": 0.0,
                    "realized_pnl_usdc": 0.0,
                    "unrealized_pnl_usdc": 0.0,
                    "pnl_usdc": 0.0,
                    "legs": [],
                },
            )
            leg = _sports_bracket_leg_payload(row)
            if (
                leg["copied_notional_usdc"] <= 0
                and leg["cost_basis_usdc"] <= 0
                and leg["realized_pnl_usdc"] == 0
                and leg["open_quantity"] <= 0
            ):
                continue
            bracket["legs"].append(leg)
            bracket["current_value_usdc"] += leg["current_value_usdc"]
            bracket["cost_basis_usdc"] += leg["cost_basis_usdc"]
            bracket["realized_pnl_usdc"] += leg["realized_pnl_usdc"]
            bracket["unrealized_pnl_usdc"] += leg["unrealized_pnl_usdc"]
            if leg.get("buy_time") and (bracket["buy_time"] is None or leg["buy_time"] < bracket["buy_time"]):
                bracket["buy_time"] = leg["buy_time"]
            if leg.get("sell_time") and (bracket["sell_time"] is None or leg["sell_time"] > bracket["sell_time"]):
                bracket["sell_time"] = leg["sell_time"]
        for bracket in brackets.values():
            if not bracket["legs"]:
                continue
            bracket["current_value_usdc"] = round(bracket["current_value_usdc"], 6)
            bracket["cost_basis_usdc"] = round(bracket["cost_basis_usdc"], 6)
            bracket["realized_pnl_usdc"] = round(bracket["realized_pnl_usdc"], 6)
            bracket["unrealized_pnl_usdc"] = round(bracket["unrealized_pnl_usdc"], 6)
            bracket["pnl_usdc"] = round(bracket["realized_pnl_usdc"] + bracket["unrealized_pnl_usdc"], 6)
            bracket["status"] = "open" if any(float(leg.get("open_quantity") or 0) > 0 for leg in bracket["legs"]) else "closed"
        return [bracket for bracket in brackets.values() if bracket["legs"]]

    def get_event_follow_signal(self, source_wallet: str, event_slug: str) -> dict[str, Any] | None:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                "select * from event_follow_signals where source_wallet = ? and event_slug = ?",
                (clean_wallet, str(event_slug).strip()),
            ).fetchone()
        return _event_follow_payload(row) if row else None

    def list_event_follow_legs(self, source_wallet: str, event_slug: str) -> list[dict[str, Any]]:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug).strip()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  efl.id, efl.signal_id, efl.asset_id,
                  coalesce(efl.outcome, mm.outcome) as outcome,
                  coalesce(efl.market_slug, mm.market_slug) as market_slug,
                  coalesce(efl.title, mm.title) as title,
                  efs.event_slug, efs.event_title, efs.market_type,
                  efl.buy_count, efl.source_notional_usdc, efl.source_quantity,
                  efl.copied_notional_usdc, efl.created_at, efl.updated_at
                from event_follow_legs efl
                join event_follow_signals efs on efs.id = efl.signal_id
                left join market_metadata mm on mm.asset_id = efl.asset_id
                where efs.source_wallet = ? and efs.event_slug = ?
                order by efl.source_notional_usdc desc, efl.id asc
                """,
                (clean_wallet, clean_event),
            ).fetchall()
        return [_event_follow_leg_payload(row) for row in rows]

    def strongest_opposing_event_follow_leg(
        self,
        *,
        source_wallet: str,
        event_slug: str | None,
        title: str | None,
        asset_id: str,
        min_source_notional_usdc: float,
    ) -> dict[str, Any] | None:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug or "").strip()
        clean_title = str(title or "").strip().lower()
        if not clean_event or not clean_title:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                  efs.source_wallet, w.name as source_wallet_name,
                  efs.event_slug, efs.event_title,
                  efl.asset_id, efl.outcome, efl.title,
                  efl.buy_count, efl.source_notional_usdc, efl.source_quantity,
                  efl.copied_notional_usdc
                from event_follow_signals efs
                join event_follow_legs efl on efl.signal_id = efs.id
                join wallets w on w.address = efs.source_wallet
                where efs.source_wallet != ?
                  and w.enabled = 1
                  and w.event_follow_strategy_enabled = 1
                  and efs.event_slug = ?
                  and lower(trim(coalesce(efl.title, ''))) = ?
                  and efl.asset_id != ?
                  and efl.source_notional_usdc >= ?
                order by efl.source_notional_usdc desc, efl.updated_at desc
                limit 1
                """,
                (clean_wallet, clean_event, clean_title, str(asset_id), float(min_source_notional_usdc)),
            ).fetchone()
        return _event_follow_leg_payload(row) if row else None

    def open_cost_basis_for_wallet(self, source_wallet: str) -> float:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                """
                select coalesce(sum(quantity * avg_entry_price), 0) as total
                from positions
                where source_wallet = ? and quantity > 0
                """,
                (clean_wallet,),
            ).fetchone()
        return float(row["total"] or 0)

    def get_weather_bracket(self, source_wallet: str, event_slug: str) -> dict[str, Any] | None:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                "select * from weather_brackets where source_wallet = ? and event_slug = ?",
                (clean_wallet, event_slug),
            ).fetchone()
        return _row_dict(row) if row else None

    def list_weather_bracket_legs(self, source_wallet: str, event_slug: str) -> list[dict[str, Any]]:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select wbl.*
                from weather_bracket_legs wbl
                join weather_brackets wb on wb.id = wbl.bracket_id
                where wb.source_wallet = ? and wb.event_slug = ?
                order by wbl.source_notional_usdc desc
                """,
                (clean_wallet, event_slug),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def has_open_weather_event(self, source_wallet: str, event_slug: str) -> bool:
        clean_wallet = self._clean_address(source_wallet)
        clean_event = str(event_slug).strip()
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from positions p
                join market_metadata mm on mm.asset_id = p.asset_id
                where p.source_wallet = ?
                  and p.quantity > 0
                  and mm.market_type = 'weather'
                  and mm.event_slug = ?
                limit 1
                """,
                (clean_wallet, clean_event),
            ).fetchone()
        return row is not None

    def count_open_weather_events(self, source_wallet: str) -> int:
        clean_wallet = self._clean_address(source_wallet)
        with self._connect() as conn:
            row = conn.execute(
                """
                select count(distinct mm.event_slug) as count
                from positions p
                join market_metadata mm on mm.asset_id = p.asset_id
                where p.source_wallet = ?
                  and p.quantity > 0
                  and mm.market_type = 'weather'
                  and mm.event_slug is not null
                  and mm.event_slug != ''
                """,
                (clean_wallet,),
            ).fetchone()
        return int(row["count"] or 0)

    def overview(self) -> dict[str, Any]:
        with self._connect() as conn:
            cash_row = conn.execute("select value from runtime_state where key = 'paper_cash_usdc'").fetchone()
            watcher_status = conn.execute("select value from runtime_state where key = 'paper_watcher_status'").fetchone()
            watcher_block = conn.execute("select value from runtime_state where key = 'watcher_last_processed_block'").fetchone()
            price_status = conn.execute("select value from runtime_state where key = 'price_monitor_status'").fetchone()
            open_positions = conn.execute("select count(*) as count from positions where quantity > 0").fetchone()
            marks = conn.execute(
                """
                select coalesce(sum(p.quantity * coalesce(mm.current_price, p.avg_entry_price)), 0) as current_value
                from positions p
                left join market_metadata mm on mm.asset_id = p.asset_id
                where p.quantity > 0
                """
            ).fetchone()
            realized = conn.execute("select coalesce(sum(realized_pnl_usdc), 0) as total from paper_trades").fetchone()
            wallets = conn.execute("select count(*) as count from wallets where enabled = 1").fetchone()
        cash = float(cash_row["value"]) if cash_row else 0.0
        current_value = float(marks["current_value"])
        return {
            "paper_cash_usdc": cash,
            "paper_watcher_status": watcher_status["value"] if watcher_status else "stopped",
            "price_monitor_status": price_status["value"] if price_status else "stopped",
            "watcher_last_processed_block": int(watcher_block["value"]) if watcher_block else None,
            "open_positions": int(open_positions["count"]),
            "realized_pnl_usdc": float(realized["total"]),
            "portfolio_value_usdc": cash + current_value,
            "enabled_wallets": int(wallets["count"]),
        }

    def paper_cash_from_ledger(self, *, starting_cash_usdc: float) -> float:
        with self._connect() as conn:
            cash_flows = conn.execute(
                """
                select
                  coalesce(sum(case when side = 'buy' then notional_usdc else 0 end), 0) as buys,
                  coalesce(sum(case when side = 'sell' then notional_usdc else 0 end), 0) as sells
                from paper_trades
                """
            ).fetchone()
        return float(starting_cash_usdc) - float(cash_flows["buys"]) + float(cash_flows["sells"])

    def paper_trade_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("select count(*) as count from paper_trades").fetchone()
        return int(row["count"])

    def pnl_summary(self, *, starting_cash_usdc: float | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            cash_row = conn.execute("select value from runtime_state where key = 'paper_cash_usdc'").fetchone()
            marks = conn.execute(
                """
                select
                  coalesce(sum(p.quantity * p.avg_entry_price), 0) as cost_basis,
                  coalesce(sum(p.quantity * coalesce(mm.current_price, p.avg_entry_price)), 0) as current_value
                from positions p
                left join market_metadata mm on mm.asset_id = p.asset_id
                where p.quantity > 0
                """
            ).fetchone()
            realized = conn.execute("select coalesce(sum(realized_pnl_usdc), 0) as total from paper_trades").fetchone()
            rows = conn.execute(
                """
                select created_at, side, notional_usdc, realized_pnl_usdc
                from paper_trades
                order by created_at asc, id asc
                """
            ).fetchall()
        cash = float(cash_row["value"]) if cash_row else 0.0
        cost_basis_usdc = float(marks["cost_basis"])
        exposure_usdc = float(marks["current_value"])
        realized_total = float(realized["total"])
        unrealized_total = exposure_usdc - cost_basis_usdc
        portfolio_value = cash + exposure_usdc
        if starting_cash_usdc is None:
            total_pnl = realized_total + unrealized_total
            starting_value = portfolio_value - total_pnl
            points = _pnl_points(rows, starting_value=starting_value, current_portfolio_value=portfolio_value)
            series_by_range = _pnl_series_by_range(
                rows,
                starting_value=starting_value,
                current_portfolio_value=portfolio_value,
            )
            day_pnl = _series_delta(series_by_range["day"])
            week_pnl = _series_delta(series_by_range["week"])
            month_pnl = _series_delta(series_by_range["month"])
        else:
            starting_value = float(starting_cash_usdc)
            cash = self.paper_cash_from_ledger(starting_cash_usdc=starting_value)
            portfolio_value = cash + exposure_usdc
            total_pnl = portfolio_value - starting_value
            points = _pnl_points(rows, starting_value=starting_value, current_portfolio_value=portfolio_value)
            series_by_range = _pnl_series_by_range(
                rows,
                starting_value=starting_value,
                current_portfolio_value=portfolio_value,
            )
            day_pnl = _series_delta(series_by_range["day"])
            week_pnl = _series_delta(series_by_range["week"])
            month_pnl = _series_delta(series_by_range["month"])
        return {
            "portfolio_value_usdc": portfolio_value,
            "starting_cash_usdc": starting_value,
            "cash_usdc": cash,
            "exposure_usdc": exposure_usdc,
            "cost_basis_usdc": cost_basis_usdc,
            "realized_pnl_usdc": realized_total,
            "unrealized_pnl_usdc": unrealized_total,
            "pnl": {
                "day": day_pnl,
                "week": week_pnl,
                "month": month_pnl,
                "lifetime": total_pnl,
            },
            "series": points,
            "series_by_range": series_by_range,
        }

    def wallet_performance_summary(self, *, hours: int = 24) -> dict[str, Any]:
        clean_hours = max(1, min(int(hours), 720))
        window_start = datetime.now(timezone.utc) - timedelta(hours=clean_hours)
        with self._connect() as conn:
            wallets = conn.execute(
                """
                select name, address
                from wallets
                where enabled = 1
                order by name
                """
            ).fetchall()
            realized_rows = conn.execute(
                """
                select
                  pt.source_wallet,
                  pt.asset_id,
                  pt.realized_pnl_usdc,
                  pt.notional_usdc,
                  pt.created_at,
                  mm.market_type,
                  mm.sport_key,
                  mm.bet_type,
                  mm.title,
                  mm.market_slug,
                  mm.event_slug,
                  mm.event_title
                from paper_trades pt
                left join market_metadata mm on mm.asset_id = pt.asset_id
                where pt.side = 'sell'
                  and pt.created_at >= ?
                """,
                (window_start.strftime("%Y-%m-%d %H:%M:%S"),),
            ).fetchall()
            open_rows = conn.execute(
                """
                select
                  p.source_wallet,
                  p.asset_id,
                  p.quantity,
                  p.avg_entry_price,
                  min(pt.created_at) as first_buy_at,
                  mm.current_price,
                  mm.market_type,
                  mm.sport_key,
                  mm.bet_type,
                  mm.title,
                  mm.market_slug,
                  mm.event_slug,
                  mm.event_title
                from positions p
                join paper_trades pt on pt.asset_id = p.asset_id
                  and pt.source_wallet = p.source_wallet
                  and pt.side = 'buy'
                left join market_metadata mm on mm.asset_id = p.asset_id
                where p.quantity > 0
                group by p.source_wallet, p.asset_id
                having first_buy_at >= ?
                """,
                (window_start.strftime("%Y-%m-%d %H:%M:%S"),),
            ).fetchall()

        wallet_map: dict[str, dict[str, Any]] = {}
        for row in wallets:
            address = str(row["address"]).lower()
            wallet_map[address] = {
                "wallet_name": row["name"],
                "source_wallet": address,
                "realized_pnl_24h_usdc": 0.0,
                "unrealized_pnl_24h_usdc": 0.0,
                "pnl_24h_usdc": 0.0,
                "trades_24h": 0,
                "markets": {},
            }

        for row in realized_rows:
            wallet = wallet_map.get(str(row["source_wallet"]).lower())
            if wallet is None:
                continue
            market = _performance_market_bucket(row)
            bucket = _performance_bucket(wallet, market)
            pnl = float(row["realized_pnl_usdc"] or 0)
            wallet["realized_pnl_24h_usdc"] += pnl
            wallet["pnl_24h_usdc"] += pnl
            wallet["trades_24h"] += 1
            bucket["realized_pnl_usdc"] += pnl
            bucket["pnl_24h_usdc"] += pnl
            bucket["trades"] += 1
            bucket["closed_notional_usdc"] += float(row["notional_usdc"] or 0)

        for row in open_rows:
            wallet = wallet_map.get(str(row["source_wallet"]).lower())
            if wallet is None:
                continue
            quantity = float(row["quantity"] or 0)
            entry = float(row["avg_entry_price"] or 0)
            mark = _optional_float(row["current_price"])
            if mark is None:
                mark = entry
            cost = quantity * entry
            current_value = quantity * mark
            pnl = current_value - cost
            market = _performance_market_bucket(row)
            bucket = _performance_bucket(wallet, market)
            wallet["unrealized_pnl_24h_usdc"] += pnl
            wallet["pnl_24h_usdc"] += pnl
            bucket["unrealized_pnl_usdc"] += pnl
            bucket["pnl_24h_usdc"] += pnl
            bucket["open_positions"] += 1
            bucket["open_cost_usdc"] += cost
            bucket["current_value_usdc"] += current_value

        payload_wallets: list[dict[str, Any]] = []
        for wallet in wallet_map.values():
            markets = sorted(
                wallet.pop("markets").values(),
                key=lambda item: (abs(float(item["pnl_24h_usdc"])), item["market"]),
                reverse=True,
            )
            for key in ("realized_pnl_24h_usdc", "unrealized_pnl_24h_usdc", "pnl_24h_usdc"):
                wallet[key] = round(float(wallet[key]), 6)
            wallet["realized_pnl_window_usdc"] = wallet["realized_pnl_24h_usdc"]
            wallet["unrealized_pnl_window_usdc"] = wallet["unrealized_pnl_24h_usdc"]
            wallet["pnl_window_usdc"] = wallet["pnl_24h_usdc"]
            wallet["trades_window"] = wallet["trades_24h"]
            for market in markets:
                for key in (
                    "realized_pnl_usdc",
                    "unrealized_pnl_usdc",
                    "pnl_24h_usdc",
                    "closed_notional_usdc",
                    "open_cost_usdc",
                    "current_value_usdc",
                ):
                    market[key] = round(float(market[key]), 6)
                market["pnl_window_usdc"] = market["pnl_24h_usdc"]
            wallet["markets"] = markets
            payload_wallets.append(wallet)

        return {
            "window_hours": clean_hours,
            "window_start": _utc_sqlite_timestamp_to_pdt(window_start.strftime("%Y-%m-%d %H:%M:%S")),
            "wallets": payload_wallets,
        }

    def set_runtime_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into runtime_state (key, value)
                values (?, ?)
                on conflict(key) do update set value = excluded.value
                """,
                (key, value),
            )

    def get_runtime_state(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("select value from runtime_state where key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        conn.execute("pragma busy_timeout = 30000")
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma synchronous = normal")
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute("drop index if exists idx_source_trades_wallet_asset")
        conn.execute("drop index if exists idx_source_trades_block_time")
        conn.execute("drop index if exists idx_source_trade_attributions_unexecuted_skip")
        _add_column(conn, "source_trades", "copy_trade_key", "text")
        _add_column(conn, "paper_trades", "copy_trade_key", "text")
        _add_column(conn, "source_trade_attributions", "skip_reason", "text")
        added_source_notional = _add_column(conn, "source_trade_attributions", "source_notional_usdc", "real")
        _add_column(conn, "market_metadata", "condition_id", "text")
        _add_column(conn, "market_metadata", "market_slug", "text")
        _add_column(conn, "market_metadata", "market_url", "text")
        _add_column(conn, "market_metadata", "outcome_side", "text")
        _add_column(conn, "market_metadata", "current_price", "real")
        _add_column(conn, "market_metadata", "price_source", "text")
        _add_column(conn, "market_metadata", "last_price_at", "text")
        _add_column(conn, "market_metadata", "market_type", "text")
        _add_column(conn, "market_metadata", "sport_key", "text")
        _add_column(conn, "market_metadata", "bet_type", "text")
        _add_column(conn, "market_metadata", "series_slug", "text")
        _add_column(conn, "market_metadata", "sports_market_type", "text")
        _add_column(conn, "market_metadata", "category_slug", "text")
        _add_column(conn, "market_metadata", "market_close_time", "text")
        _add_column(conn, "market_metadata", "market_close_time_kind", "text")
        _add_column(conn, "market_metadata", "event_slug", "text")
        _add_column(conn, "market_metadata", "event_title", "text")
        _add_column(conn, "market_metadata", "neg_risk", "integer")
        _add_column(conn, "market_metadata", "mergeable", "integer")
        _add_column(conn, "market_metadata", "is_closed", "integer")
        _add_column(conn, "market_metadata", "resolution_price", "real")
        _add_column(conn, "wallets", "allowed_market_types", "text")
        _add_column(conn, "wallets", "strategy_label", "text not null default 'Standard'")
        _add_column(conn, "wallets", "strategy_notes", "text not null default ''")
        _add_column(conn, "wallets", "bracket_strategy_enabled", "integer not null default 0")
        _add_column(conn, "wallets", "bracket_buy_size_usdc", "real not null default 10")
        _add_column(conn, "wallets", "bracket_stop_loss_pct", "real not null default 0")
        _add_column(conn, "wallets", "bracket_max_open_events", "integer not null default 0")
        _add_column(conn, "wallets", "bracket_allowed_patterns", "text")
        _add_column(conn, "wallets", "repeat_buy_strategy_enabled", "integer not null default 0")
        _add_column(conn, "wallets", "repeat_buy_size_usdc", "real not null default 5")
        _add_column(conn, "wallets", "repeat_buy_stop_loss_pct", "real not null default 0")
        _add_column(conn, "wallets", "repeat_buy_min_source_notional_usdc", "real not null default 0")
        _add_column(conn, "wallets", "repeat_buy_min_buy_count", "integer not null default 2")
        _add_column(conn, "wallets", "repeat_buy_min_avg_price", "real not null default 0.01")
        _add_column(conn, "wallets", "repeat_buy_max_avg_price", "real not null default 1.0")
        _add_column(conn, "wallets", "repeat_buy_max_total_exposure_usdc", "real not null default 0")
        _add_column(conn, "wallets", "repeat_buy_blocked_title_patterns", "text")
        _add_column(conn, "wallets", "repeat_buy_allowed_sports", "text")
        _add_column(conn, "wallets", "repeat_buy_allowed_bet_types", "text")
        _add_column(conn, "wallets", "event_follow_strategy_enabled", "integer not null default 0")
        _add_column(conn, "wallets", "event_follow_buy_size_usdc", "real not null default 2")
        _add_column(conn, "wallets", "event_follow_max_event_exposure_usdc", "real not null default 4")
        _add_column(conn, "wallets", "event_follow_max_total_exposure_usdc", "real not null default 50")
        _add_column(conn, "wallets", "event_follow_min_source_trade_usdc", "real not null default 20")
        _add_column(conn, "wallets", "event_follow_min_event_source_notional_usdc", "real not null default 250")
        _add_column(conn, "wallets", "event_follow_min_event_buy_count", "integer not null default 3")
        _add_column(conn, "wallets", "event_follow_min_avg_price", "real not null default 0.20")
        _add_column(conn, "wallets", "event_follow_max_avg_price", "real not null default 0.80")
        _add_column(conn, "wallets", "sports_trailing_stop_enabled", "integer not null default 0")
        _add_column(conn, "wallets", "sports_trailing_activation_pct", "real not null default 35")
        _add_column(conn, "wallets", "sports_trailing_stop_pct", "real not null default 25")
        _add_column(conn, "wallets", "sports_trailing_floor_delta", "real not null default 0.03")
        _add_column(conn, "wallets", "reserved_cash_usdc", "real not null default 0")
        _add_column(conn, "wallets", "profile_json", "text")
        _add_column(conn, "positions", "trailing_peak_price", "real")
        _add_column(conn, "positions", "trailing_activated", "integer not null default 0")
        _add_column(conn, "positions", "winner_capture_stake_recovered", "integer not null default 0")
        _add_column(conn, "positions", "winner_capture_first_scale_done", "integer not null default 0")
        _add_column(conn, "positions", "winner_capture_high_price_done", "integer not null default 0")
        conn.execute(
            "update wallets set allowed_market_types = ? where allowed_market_types is null or allowed_market_types = ''",
            (_market_types_to_text(MARKET_TYPES),),
        )
        conn.execute("update wallets set strategy_label = 'Standard' where strategy_label is null or strategy_label = ''")
        conn.execute("update wallets set strategy_notes = '' where strategy_notes is null")
        conn.execute(
            "update wallets set bracket_allowed_patterns = ? where bracket_allowed_patterns is null or bracket_allowed_patterns = ''",
            (_weather_patterns_to_text(WEATHER_BRACKET_PATTERNS),),
        )
        conn.execute(
            """
            update source_trades
            set copy_trade_key = lower(side) || ':' || asset_id || ':' ||
              printf('%.6f', price) || ':' || printf('%.6f', notional_usdc)
            where copy_trade_key is null
            """
        )
        conn.execute(
            """
            update paper_trades
            set copy_trade_key = (
              select st.copy_trade_key
              from source_trades st
              where st.idempotency_key = paper_trades.source_idempotency_key
            )
            where copy_trade_key is null
            """
        )
        conn.execute(
            """
            insert or ignore into source_trade_attributions (
              copy_trade_key, source_idempotency_key, source_wallet, paper_trade_id, executed, source_notional_usdc
            )
            select st.copy_trade_key, st.idempotency_key, st.source_wallet, pt.id, 1, st.notional_usdc
            from source_trades st
            join paper_trades pt on pt.source_idempotency_key = st.idempotency_key
            where st.copy_trade_key is not null
            """
        )
        if added_source_notional:
            conn.execute(
                """
                update source_trade_attributions
                set source_notional_usdc = (
                  select st.notional_usdc
                  from source_trades st
                  where st.idempotency_key = source_trade_attributions.source_idempotency_key
                )
                where source_notional_usdc is null
                """
            )

    def _clean_wallet(
        self,
        *,
        name: str,
        address: str,
        enabled: bool,
        strategy_label: str,
        strategy_notes: str,
        allowed_market_types: Iterable[str] | None,
        bracket_strategy_enabled: bool,
        bracket_buy_size_usdc: float,
        bracket_stop_loss_pct: float,
        bracket_max_open_events: int,
        bracket_allowed_patterns: Iterable[str] | None,
        repeat_buy_strategy_enabled: bool,
        repeat_buy_size_usdc: float,
        repeat_buy_stop_loss_pct: float,
        repeat_buy_min_source_notional_usdc: float,
        repeat_buy_min_buy_count: int,
        repeat_buy_min_avg_price: float,
        repeat_buy_max_avg_price: float,
        repeat_buy_max_total_exposure_usdc: float,
        repeat_buy_blocked_title_patterns: Iterable[str] | None,
        repeat_buy_allowed_sports: Iterable[str] | None,
        repeat_buy_allowed_bet_types: Iterable[str] | None,
        event_follow_strategy_enabled: bool,
        event_follow_buy_size_usdc: float,
        event_follow_max_event_exposure_usdc: float,
        event_follow_max_total_exposure_usdc: float,
        event_follow_min_source_trade_usdc: float,
        event_follow_min_event_source_notional_usdc: float,
        event_follow_min_event_buy_count: int,
        event_follow_min_avg_price: float,
        event_follow_max_avg_price: float,
        sports_trailing_stop_enabled: bool,
        sports_trailing_activation_pct: float,
        sports_trailing_stop_pct: float,
        sports_trailing_floor_delta: float,
        reserved_cash_usdc: float,
        profile_json: Any,
    ) -> dict[str, Any]:
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("wallet name is required")
        clean_strategy_label = str(strategy_label or "Standard").strip() or "Standard"
        clean_strategy_notes = str(strategy_notes or "").strip()
        clean_buy_size = float(bracket_buy_size_usdc)
        clean_stop_loss = float(bracket_stop_loss_pct)
        if clean_buy_size <= 0:
            raise ValueError("bracket buy size must be positive")
        if clean_stop_loss < 0:
            raise ValueError("bracket stop loss cannot be negative")
        clean_bracket_max_open_events = int(bracket_max_open_events)
        if clean_bracket_max_open_events < 0:
            raise ValueError("bracket max open events cannot be negative")
        clean_repeat_buy_size = float(repeat_buy_size_usdc)
        clean_repeat_stop_loss = float(repeat_buy_stop_loss_pct)
        if clean_repeat_buy_size <= 0:
            raise ValueError("repeat buy size must be positive")
        if clean_repeat_stop_loss < 0:
            raise ValueError("repeat buy stop loss cannot be negative")
        clean_repeat_min_source = float(repeat_buy_min_source_notional_usdc)
        clean_repeat_min_count = int(repeat_buy_min_buy_count)
        clean_repeat_min_price = float(repeat_buy_min_avg_price)
        clean_repeat_max_price = float(repeat_buy_max_avg_price)
        clean_repeat_max_total = float(repeat_buy_max_total_exposure_usdc)
        if clean_repeat_min_source < 0:
            raise ValueError("repeat buy min source notional cannot be negative")
        if clean_repeat_min_count < 2:
            raise ValueError("repeat buy min buy count must be at least 2")
        if not 0 < clean_repeat_min_price <= clean_repeat_max_price <= 1:
            raise ValueError("repeat buy price band must be within 0-1")
        if clean_repeat_max_total < 0:
            raise ValueError("repeat buy max total exposure cannot be negative")
        clean_event_buy_size = float(event_follow_buy_size_usdc)
        clean_event_max_event = float(event_follow_max_event_exposure_usdc)
        clean_event_max_total = float(event_follow_max_total_exposure_usdc)
        clean_event_min_source = float(event_follow_min_source_trade_usdc)
        clean_event_min_event_source = float(event_follow_min_event_source_notional_usdc)
        clean_event_min_count = int(event_follow_min_event_buy_count)
        clean_event_min_price = float(event_follow_min_avg_price)
        clean_event_max_price = float(event_follow_max_avg_price)
        if clean_event_buy_size <= 0:
            raise ValueError("event follow buy size must be positive")
        if clean_event_max_event <= 0:
            raise ValueError("event follow max event exposure must be positive")
        if clean_event_max_total <= 0:
            raise ValueError("event follow max total exposure must be positive")
        if clean_event_min_source < 0:
            raise ValueError("event follow min source trade cannot be negative")
        if clean_event_min_event_source < 0:
            raise ValueError("event follow min event source notional cannot be negative")
        if clean_event_min_count < 1:
            raise ValueError("event follow min buy count must be at least 1")
        if not 0 < clean_event_min_price <= clean_event_max_price <= 1:
            raise ValueError("event follow price band must be within 0-1")
        clean_trailing_activation = float(sports_trailing_activation_pct)
        clean_trailing_stop = float(sports_trailing_stop_pct)
        clean_trailing_floor = float(sports_trailing_floor_delta)
        if clean_trailing_activation < 0:
            raise ValueError("sports trailing activation cannot be negative")
        if not 0 < clean_trailing_stop < 100:
            raise ValueError("sports trailing stop must be between 0 and 100")
        if clean_trailing_floor < 0:
            raise ValueError("sports trailing floor delta cannot be negative")
        clean_reserved_cash = float(reserved_cash_usdc)
        if clean_reserved_cash < 0:
            raise ValueError("reserved cash cannot be negative")
        has_profile_json = profile_json is not None and profile_json != ""
        clean_profile_json = None if not has_profile_json else parse_wallet_profile_json(profile_json)
        wallet = {
            "name": clean_name,
            "address": self._clean_address(address),
            "enabled": bool(enabled),
            "strategy_label": clean_strategy_label,
            "strategy_notes": clean_strategy_notes,
            "allowed_market_types": _clean_market_types(allowed_market_types),
            "bracket_strategy_enabled": bool(bracket_strategy_enabled),
            "bracket_buy_size_usdc": clean_buy_size,
            "bracket_stop_loss_pct": clean_stop_loss,
            "bracket_max_open_events": clean_bracket_max_open_events,
            "bracket_allowed_patterns": _clean_weather_patterns(bracket_allowed_patterns),
            "repeat_buy_strategy_enabled": bool(repeat_buy_strategy_enabled),
            "repeat_buy_size_usdc": clean_repeat_buy_size,
            "repeat_buy_stop_loss_pct": clean_repeat_stop_loss,
            "repeat_buy_min_source_notional_usdc": clean_repeat_min_source,
            "repeat_buy_min_buy_count": clean_repeat_min_count,
            "repeat_buy_min_avg_price": clean_repeat_min_price,
            "repeat_buy_max_avg_price": clean_repeat_max_price,
            "repeat_buy_max_total_exposure_usdc": clean_repeat_max_total,
            "repeat_buy_blocked_title_patterns": _clean_string_list(repeat_buy_blocked_title_patterns),
            "repeat_buy_allowed_sports": [item.lower() for item in _clean_string_list(repeat_buy_allowed_sports)],
            "repeat_buy_allowed_bet_types": [item.lower() for item in _clean_string_list(repeat_buy_allowed_bet_types)],
            "event_follow_strategy_enabled": bool(event_follow_strategy_enabled),
            "event_follow_buy_size_usdc": clean_event_buy_size,
            "event_follow_max_event_exposure_usdc": clean_event_max_event,
            "event_follow_max_total_exposure_usdc": clean_event_max_total,
            "event_follow_min_source_trade_usdc": clean_event_min_source,
            "event_follow_min_event_source_notional_usdc": clean_event_min_event_source,
            "event_follow_min_event_buy_count": clean_event_min_count,
            "event_follow_min_avg_price": clean_event_min_price,
            "event_follow_max_avg_price": clean_event_max_price,
            "sports_trailing_stop_enabled": bool(sports_trailing_stop_enabled),
            "sports_trailing_activation_pct": clean_trailing_activation,
            "sports_trailing_stop_pct": clean_trailing_stop,
            "sports_trailing_floor_delta": clean_trailing_floor,
            "reserved_cash_usdc": clean_reserved_cash,
            "profile_json": clean_profile_json,
        }
        wallet["profile_json"] = _profile_json_from_legacy_wallet(wallet, profile_json if has_profile_json else None)
        _apply_wallet_profile_overrides(wallet, wallet["profile_json"], wallet)
        return wallet

    def _clean_address(self, address: str) -> str:
        clean_address = str(address).strip().lower()
        if not WALLET_RE.match(clean_address):
            raise ValueError("wallet address must be a 0x-prefixed 40-byte hex address")
        return clean_address


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _live_order_intent_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    for key in ("price", "size", "notional_usdc"):
        item[key] = round(float(item.get(key) or 0), 6)
    item["response_json"] = _json_response_from_text(item.get("response_json"))
    return item


def _live_shadow_audit_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    for key in (
        "paper_entry_price",
        "best_ask_at_decision",
        "order_price",
        "requested_notional_usdc",
        "requested_size",
        "available_size_at_price",
        "would_fill_size",
        "post_submit_book_price",
    ):
        if item.get(key) is not None:
            item[key] = round(float(item[key]), 6)
    return item


def _live_settlement_intent_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    for key in ("quantity", "resolution_price"):
        item[key] = round(float(item.get(key) or 0), 6)
    item["response_json"] = _json_response_from_text(item.get("response_json"))
    return item


def _effective_wallet_config(wallet: WalletConfig) -> WalletConfig:
    raw_profile_json = None if wallet.profile_json == default_wallet_profile_json() else wallet.profile_json
    profile_json = wallet_profile_json_from_wallet_config(wallet, raw_profile_json)
    payload = {
        "allowed_market_types": list(wallet.allowed_market_types),
        "bracket_strategy_enabled": wallet.bracket_strategy_enabled,
        "bracket_buy_size_usdc": wallet.bracket_buy_size_usdc,
        "bracket_stop_loss_pct": wallet.bracket_stop_loss_pct,
        "bracket_max_open_events": wallet.bracket_max_open_events,
        "bracket_allowed_patterns": list(wallet.bracket_allowed_patterns),
        "repeat_buy_strategy_enabled": wallet.repeat_buy_strategy_enabled,
        "repeat_buy_size_usdc": wallet.repeat_buy_size_usdc,
        "repeat_buy_stop_loss_pct": wallet.repeat_buy_stop_loss_pct,
        "repeat_buy_min_source_notional_usdc": wallet.repeat_buy_min_source_notional_usdc,
        "repeat_buy_min_buy_count": wallet.repeat_buy_min_buy_count,
        "repeat_buy_min_avg_price": wallet.repeat_buy_min_avg_price,
        "repeat_buy_max_avg_price": wallet.repeat_buy_max_avg_price,
        "repeat_buy_max_total_exposure_usdc": wallet.repeat_buy_max_total_exposure_usdc,
        "repeat_buy_blocked_title_patterns": list(wallet.repeat_buy_blocked_title_patterns),
        "repeat_buy_allowed_sports": list(wallet.repeat_buy_allowed_sports),
        "repeat_buy_allowed_bet_types": list(wallet.repeat_buy_allowed_bet_types),
        "event_follow_strategy_enabled": wallet.event_follow_strategy_enabled,
        "event_follow_buy_size_usdc": wallet.event_follow_buy_size_usdc,
        "event_follow_max_event_exposure_usdc": wallet.event_follow_max_event_exposure_usdc,
        "event_follow_max_total_exposure_usdc": wallet.event_follow_max_total_exposure_usdc,
        "event_follow_min_source_trade_usdc": wallet.event_follow_min_source_trade_usdc,
        "event_follow_min_event_source_notional_usdc": wallet.event_follow_min_event_source_notional_usdc,
        "event_follow_min_event_buy_count": wallet.event_follow_min_event_buy_count,
        "event_follow_min_avg_price": wallet.event_follow_min_avg_price,
        "event_follow_max_avg_price": wallet.event_follow_max_avg_price,
        "sports_trailing_stop_enabled": wallet.sports_trailing_stop_enabled,
        "sports_trailing_activation_pct": wallet.sports_trailing_activation_pct,
        "sports_trailing_stop_pct": wallet.sports_trailing_stop_pct,
        "sports_trailing_floor_delta": wallet.sports_trailing_floor_delta,
        "reserved_cash_usdc": wallet.reserved_cash_usdc,
        "profile_json": profile_json,
    }
    _apply_wallet_profile_overrides(payload, profile_json, payload)
    return replace(
        wallet,
        allowed_market_types=tuple(payload["allowed_market_types"]),
        bracket_strategy_enabled=payload["bracket_strategy_enabled"],
        bracket_buy_size_usdc=payload["bracket_buy_size_usdc"],
        bracket_stop_loss_pct=payload["bracket_stop_loss_pct"],
        bracket_max_open_events=payload["bracket_max_open_events"],
        bracket_allowed_patterns=tuple(payload["bracket_allowed_patterns"]),
        repeat_buy_strategy_enabled=payload["repeat_buy_strategy_enabled"],
        repeat_buy_size_usdc=payload["repeat_buy_size_usdc"],
        repeat_buy_stop_loss_pct=payload["repeat_buy_stop_loss_pct"],
        repeat_buy_min_source_notional_usdc=payload["repeat_buy_min_source_notional_usdc"],
        repeat_buy_min_buy_count=payload["repeat_buy_min_buy_count"],
        repeat_buy_min_avg_price=payload["repeat_buy_min_avg_price"],
        repeat_buy_max_avg_price=payload["repeat_buy_max_avg_price"],
        repeat_buy_max_total_exposure_usdc=payload["repeat_buy_max_total_exposure_usdc"],
        repeat_buy_blocked_title_patterns=tuple(payload["repeat_buy_blocked_title_patterns"]),
        repeat_buy_allowed_sports=tuple(payload["repeat_buy_allowed_sports"]),
        repeat_buy_allowed_bet_types=tuple(payload["repeat_buy_allowed_bet_types"]),
        event_follow_strategy_enabled=payload["event_follow_strategy_enabled"],
        event_follow_buy_size_usdc=payload["event_follow_buy_size_usdc"],
        event_follow_max_event_exposure_usdc=payload["event_follow_max_event_exposure_usdc"],
        event_follow_max_total_exposure_usdc=payload["event_follow_max_total_exposure_usdc"],
        event_follow_min_source_trade_usdc=payload["event_follow_min_source_trade_usdc"],
        event_follow_min_event_source_notional_usdc=payload["event_follow_min_event_source_notional_usdc"],
        event_follow_min_event_buy_count=payload["event_follow_min_event_buy_count"],
        event_follow_min_avg_price=payload["event_follow_min_avg_price"],
        event_follow_max_avg_price=payload["event_follow_max_avg_price"],
        sports_trailing_stop_enabled=payload["sports_trailing_stop_enabled"],
        sports_trailing_activation_pct=payload["sports_trailing_activation_pct"],
        sports_trailing_stop_pct=payload["sports_trailing_stop_pct"],
        sports_trailing_floor_delta=payload["sports_trailing_floor_delta"],
        reserved_cash_usdc=payload["reserved_cash_usdc"],
        profile_json=profile_json,
    )


def _wallet_payload(row: sqlite3.Row) -> dict[str, Any]:
    wallet = {
        "name": row["name"],
        "address": row["address"],
        "enabled": bool(row["enabled"]),
        "strategy_label": row["strategy_label"] or "Standard",
        "strategy_notes": row["strategy_notes"] or "",
        "allowed_market_types": _market_types_from_text(row["allowed_market_types"]),
        "bracket_strategy_enabled": bool(row["bracket_strategy_enabled"]),
        "bracket_buy_size_usdc": float(row["bracket_buy_size_usdc"] or 10.0),
        "bracket_stop_loss_pct": float(row["bracket_stop_loss_pct"] or 0.0),
        "bracket_max_open_events": int(row["bracket_max_open_events"] or 0),
        "bracket_allowed_patterns": _weather_patterns_from_text(row["bracket_allowed_patterns"]),
        "repeat_buy_strategy_enabled": bool(row["repeat_buy_strategy_enabled"]),
        "repeat_buy_size_usdc": float(row["repeat_buy_size_usdc"] or 5.0),
        "repeat_buy_stop_loss_pct": float(row["repeat_buy_stop_loss_pct"] or 0.0),
        "repeat_buy_min_source_notional_usdc": float(row["repeat_buy_min_source_notional_usdc"] or 0.0),
        "repeat_buy_min_buy_count": int(row["repeat_buy_min_buy_count"] or 2),
        "repeat_buy_min_avg_price": float(row["repeat_buy_min_avg_price"] or 0.01),
        "repeat_buy_max_avg_price": float(row["repeat_buy_max_avg_price"] or 1.0),
        "repeat_buy_max_total_exposure_usdc": float(row["repeat_buy_max_total_exposure_usdc"] or 0.0),
        "repeat_buy_blocked_title_patterns": _string_list_from_text(row["repeat_buy_blocked_title_patterns"]),
        "repeat_buy_allowed_sports": _string_list_from_text(row["repeat_buy_allowed_sports"]),
        "repeat_buy_allowed_bet_types": _string_list_from_text(row["repeat_buy_allowed_bet_types"]),
        "event_follow_strategy_enabled": bool(row["event_follow_strategy_enabled"]),
        "event_follow_buy_size_usdc": float(row["event_follow_buy_size_usdc"] or 2.0),
        "event_follow_max_event_exposure_usdc": float(row["event_follow_max_event_exposure_usdc"] or 4.0),
        "event_follow_max_total_exposure_usdc": float(row["event_follow_max_total_exposure_usdc"] or 50.0),
        "event_follow_min_source_trade_usdc": _float_default(row["event_follow_min_source_trade_usdc"], 20.0),
        "event_follow_min_event_source_notional_usdc": _float_default(row["event_follow_min_event_source_notional_usdc"], 250.0),
        "event_follow_min_event_buy_count": int(row["event_follow_min_event_buy_count"] or 3),
        "event_follow_min_avg_price": float(row["event_follow_min_avg_price"] or 0.20),
        "event_follow_max_avg_price": float(row["event_follow_max_avg_price"] or 0.80),
        "sports_trailing_stop_enabled": bool(row["sports_trailing_stop_enabled"]),
        "sports_trailing_activation_pct": float(row["sports_trailing_activation_pct"] or 35.0),
        "sports_trailing_stop_pct": float(row["sports_trailing_stop_pct"] or 25.0),
        "sports_trailing_floor_delta": float(row["sports_trailing_floor_delta"] or 0.03),
        "reserved_cash_usdc": float(row["reserved_cash_usdc"] or 0.0),
    }
    profile_json = _profile_json_from_legacy_wallet(wallet, row["profile_json"])
    wallet["profile_json"] = profile_json
    _apply_wallet_profile_overrides(wallet, profile_json, row)
    return wallet


def _repeat_buy_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    item["copied"] = bool(item.get("copied"))
    item["buy_count"] = int(item.get("buy_count") or 0)
    for key in ("source_notional_usdc", "source_quantity", "copied_notional_usdc"):
        item[key] = round(float(item.get(key) or 0), 6)
    return item


def _event_follow_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    item["buy_count"] = int(item.get("buy_count") or 0)
    for key in ("source_notional_usdc", "source_quantity", "copied_notional_usdc"):
        item[key] = round(float(item.get(key) or 0), 6)
    source_quantity = float(item.get("source_quantity") or 0)
    item["source_avg_price"] = round(float(item.get("source_notional_usdc") or 0) / source_quantity, 6) if source_quantity else 0.0
    return item


def _event_follow_leg_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    item["buy_count"] = int(item.get("buy_count") or 0)
    for key in ("source_notional_usdc", "source_quantity", "copied_notional_usdc"):
        item[key] = round(float(item.get(key) or 0), 6)
    source_quantity = float(item.get("source_quantity") or 0)
    item["source_avg_price"] = round(float(item.get("source_notional_usdc") or 0) / source_quantity, 6) if source_quantity else 0.0
    return item


def _sports_bracket_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    for key in ("source_notional_usdc", "target_notional_usdc", "copied_notional_usdc", "realized_pnl_usdc"):
        item[key] = round(float(item.get(key) or 0), 6)
    return item


def _sports_bracket_leg_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    source_quantity = float(item.get("source_quantity") or 0)
    source_notional = float(item.get("source_notional_usdc") or 0)
    open_quantity = float(item.get("open_quantity") or 0)
    buy_quantity = float(item.get("buy_quantity") or 0)
    cost_basis = float(item.get("buy_notional_usdc") or 0)
    avg_entry = _optional_float(item.get("avg_entry_price"))
    if (avg_entry is None or avg_entry <= 0) and buy_quantity > 0:
        avg_entry = cost_basis / buy_quantity
    current_price = _optional_float(item.get("current_price"))
    mark_price = current_price if current_price is not None else avg_entry
    current_value = open_quantity * mark_price if mark_price is not None else 0.0
    realized = float(item.get("realized_pnl_usdc") or 0)
    item["source_avg_price"] = round(source_notional / source_quantity, 6) if source_quantity else 0.0
    item["source_notional_usdc"] = round(source_notional, 6)
    item["target_notional_usdc"] = round(float(item.get("target_notional_usdc") or 0), 6)
    item["copied_notional_usdc"] = round(float(item.get("copied_notional_usdc") or 0), 6)
    item["open_quantity"] = round(open_quantity, 6)
    item["avg_entry_price"] = round(avg_entry, 6) if avg_entry is not None else None
    item["current_price"] = current_price
    item["cost_basis_usdc"] = round(cost_basis, 6)
    item["current_value_usdc"] = round(current_value, 6)
    item["realized_pnl_usdc"] = round(realized, 6)
    item["unrealized_pnl_usdc"] = round(current_value - cost_basis, 6) if open_quantity > 0 else 0.0
    item["buy_time"] = _utc_sqlite_timestamp_to_pdt(item.get("buy_time"))
    item["sell_time"] = _utc_sqlite_timestamp_to_pdt(item.get("sell_time"))
    return item


def _position_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    item["buy_time"] = _utc_sqlite_timestamp_to_pdt(item.get("buy_time"))
    quantity = float(item.get("quantity") or 0)
    avg_entry_price = float(item.get("avg_entry_price") or 0)
    current_price = _optional_float(item.get("current_price"))
    mark_price = current_price if current_price is not None else avg_entry_price
    cost_basis = quantity * avg_entry_price
    current_value = quantity * mark_price
    unrealized = current_value - cost_basis
    item["current_price"] = current_price
    trailing_peak = _optional_float(item.get("trailing_peak_price"))
    item["trailing_peak_price"] = round(trailing_peak, 6) if trailing_peak is not None else None
    item["trailing_activated"] = bool(item.get("trailing_activated"))
    item["winner_capture_stake_recovered"] = bool(item.get("winner_capture_stake_recovered"))
    item["winner_capture_first_scale_done"] = bool(item.get("winner_capture_first_scale_done"))
    item["winner_capture_high_price_done"] = bool(item.get("winner_capture_high_price_done"))
    item["total_buy_quantity"] = round(float(item.get("total_buy_quantity") or quantity), 6)
    item["total_buy_notional_usdc"] = round(float(item.get("total_buy_notional_usdc") or cost_basis), 6)
    item["cost_basis_usdc"] = round(cost_basis, 6)
    item["current_value_usdc"] = round(current_value, 6)
    item["unrealized_pnl_usdc"] = round(unrealized, 6)
    item["unrealized_pnl_pct"] = round((unrealized / cost_basis) * 100, 6) if cost_basis else 0.0
    return item


def _closed_position_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = _row_dict(row)
    item["buy_time"] = _utc_sqlite_timestamp_to_pdt(item.get("buy_time"))
    item["close_time"] = _utc_sqlite_timestamp_to_pdt(item.get("close_time"))
    item["current_price"] = _optional_float(item.get("current_price"))
    for key in ["entry_price", "exit_price", "closed_quantity", "closed_notional_usdc", "realized_pnl_usdc"]:
        value = _optional_float(item.get(key))
        item[key] = round(value, 6) if value is not None else None
    return item


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_default(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _performance_bucket(wallet: dict[str, Any], market: str) -> dict[str, Any]:
    buckets = wallet["markets"]
    if market not in buckets:
        buckets[market] = {
            "market": market,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 0.0,
            "pnl_24h_usdc": 0.0,
            "trades": 0,
            "open_positions": 0,
            "closed_notional_usdc": 0.0,
            "open_cost_usdc": 0.0,
            "current_value_usdc": 0.0,
        }
    return buckets[market]


def _performance_market_bucket(row: sqlite3.Row | dict[str, Any]) -> str:
    keys = set(row.keys())
    sport_key = _performance_normalized_value(row["sport_key"]) if "sport_key" in keys else ""
    if sport_key:
        if sport_key in {"atp", "wta", "tennis"}:
            return "tennis"
        if sport_key in {"mlb", "nba", "nfl", "nhl", "soccer", "esports"}:
            return sport_key
        if sport_key in {"football", "mls", "epl", "uefa", "ucl", "uel"}:
            return "soccer"
    text = " ".join(
        str(row[key] or "")
        for key in ("market_type", "title", "market_slug", "event_slug", "event_title")
        if key in keys
    ).lower()
    if any(token in text for token in ("counter-strike", "cs2", "league-of-legends", "dota", "valorant", "esport")):
        return "esports"
    if "mlb" in text or "baseball" in text:
        return "mlb"
    if "nba" in text or "basketball" in text:
        return "nba"
    if "nfl" in text or "american football" in text:
        return "nfl"
    if "nhl" in text or "hockey" in text:
        return "nhl"
    if any(token in text for token in ("tennis", "atp", "wta")):
        return "tennis"
    if (
        "soccer" in text
        or "football" in text
        or "premier-league" in text
        or "champions-league" in text
        or "laliga" in text
        or "serie-a" in text
        or "bundesliga" in text
        or " epl-" in f" {text}"
        or " fc " in f" {text} "
        or " win on " in text
    ):
        return "soccer"
    market_type = str(row["market_type"] or "other").lower() if "market_type" in keys else "other"
    return market_type if market_type in MARKET_TYPES else "other"


def _performance_normalized_value(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


def _utc_sqlite_timestamp_to_pdt(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.endswith(" PDT") or text.endswith(" PST"):
        return text
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return text
    local = parsed.astimezone(ZoneInfo("America/Los_Angeles"))
    return local.strftime("%Y-%m-%d %H:%M PDT")


def _now_pdt() -> str:
    return datetime.now(tz=ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M PDT")


def _retention_cutoff_pdt(retention_hours: int, *, now: datetime | None = None) -> str:
    clean_hours = max(1, int(retention_hours))
    current = now or datetime.now(tz=ZoneInfo("America/Los_Angeles"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    cutoff = current.astimezone(ZoneInfo("America/Los_Angeles")) - timedelta(hours=clean_hours)
    return cutoff.strftime("%Y-%m-%d %H:%M PDT")


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(
            """
            select name
            from sqlite_master
            where type = 'table'
              and name not like 'sqlite_%'
            order by name
            """
        ).fetchall()
    ]


def _populate_source_history_prune_ids(conn: sqlite3.Connection, cutoff_pdt: str) -> None:
    conn.execute("drop table if exists temp.source_history_prune_ids")
    conn.execute("create temp table source_history_prune_ids (idempotency_key text primary key)")
    conn.execute(
        """
        insert into temp.source_history_prune_ids (idempotency_key)
        select st.idempotency_key
        from source_trades st
        left join market_metadata mm on mm.asset_id = st.asset_id
        where st.block_timestamp < ?
          and not exists (
            select 1
            from paper_trades pt
            where pt.source_idempotency_key = st.idempotency_key
          )
          and not exists (
            select 1
            from live_order_intents loi
            where loi.source_idempotency_key = st.idempotency_key
          )
          and not exists (
            select 1
            from live_shadow_audits lsa
            where lsa.source_idempotency_key = st.idempotency_key
          )
          and not exists (
            select 1
            from live_settlement_intents lsi
            where lsi.source_idempotency_key = st.idempotency_key
          )
          and not exists (
            select 1
            from positions p
            where p.asset_id = st.asset_id
              and p.source_wallet = st.source_wallet
              and p.quantity > 0
          )
          and (
            coalesce(mm.is_closed, 0) = 1
            or (
              mm.market_close_time is not null
              and mm.market_close_time != ''
              and mm.market_close_time < ?
            )
          )
        """,
        (cutoff_pdt, cutoff_pdt),
    )


def _source_history_prune_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        select
          count(*) as source_trades,
          count(distinct st.asset_id) as assets,
          min(st.block_timestamp) as oldest_source_time,
          max(st.block_timestamp) as newest_source_time,
          coalesce(sum(length(st.idempotency_key)), 0)
            + coalesce(sum(length(coalesce(st.copy_trade_key, ''))), 0)
            + coalesce(sum(length(st.tx_hash)), 0)
            + coalesce(sum(length(st.asset_id)), 0)
            + coalesce(sum(length(coalesce(st.condition_id, ''))), 0) as approximate_key_text_bytes
        from source_trades st
        join temp.source_history_prune_ids prune on prune.idempotency_key = st.idempotency_key
        """
    ).fetchone()
    attributions = conn.execute(
        """
        select count(*)
        from source_trade_attributions
        where source_idempotency_key in (select idempotency_key from temp.source_history_prune_ids)
        """
    ).fetchone()[0]
    return {
        "source_trades": int(row["source_trades"] or 0),
        "source_trade_attributions": int(attributions or 0),
        "assets": int(row["assets"] or 0),
        "oldest_source_time": row["oldest_source_time"],
        "newest_source_time": row["newest_source_time"],
        "approximate_key_text_bytes": int(row["approximate_key_text_bytes"] or 0),
    }


def _json_response_to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
        except json.JSONDecodeError:
            return json.dumps(text, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_response_from_text(value: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return value


def _add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")
        return True
    return False


def _clean_market_types(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return list(MARKET_TYPES)
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return [value for value in cleaned if value in MARKET_TYPES] or list(MARKET_TYPES)


def _clean_weather_patterns(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return list(WEATHER_BRACKET_PATTERNS)
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return [value for value in cleaned if value in WEATHER_BRACKET_PATTERNS] or list(WEATHER_BRACKET_PATTERNS)


def _clean_string_list(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _market_types_to_text(values: Iterable[str]) -> str:
    return ",".join(_clean_market_types(values))


def _market_types_from_text(value: str | None) -> list[str]:
    if not value:
        return list(MARKET_TYPES)
    return _clean_market_types(value.split(","))


def _weather_patterns_to_text(values: Iterable[str]) -> str:
    return ",".join(_clean_weather_patterns(values))


def _weather_patterns_from_text(value: str | None) -> list[str]:
    if not value:
        return list(WEATHER_BRACKET_PATTERNS)
    return _clean_weather_patterns(value.split(","))


def _string_list_to_text(values: Iterable[str]) -> str:
    return "\n".join(_clean_string_list(values))


def _string_list_from_text(value: str | None) -> list[str]:
    if not value:
        return []
    return _clean_string_list(str(value).splitlines())


def _pnl_points(
    rows: list[sqlite3.Row],
    *,
    starting_value: float,
    current_portfolio_value: float | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return [{"label": "Start", "value": round(current_portfolio_value if current_portfolio_value is not None else starting_value, 6)}]
    value = starting_value
    points = [{"label": "Start", "value": round(value, 6)}]
    for index, row in enumerate(rows, start=1):
        value += _portfolio_value_delta(row)
        points.append({"label": _utc_sqlite_timestamp_to_pdt(row["created_at"]) or str(index), "value": round(value, 6)})
    if current_portfolio_value is not None and round(value, 6) != round(current_portfolio_value, 6):
        points.append({"label": "Mark", "value": round(current_portfolio_value, 6)})
    return points


def _pnl_series_by_range(
    rows: list[sqlite3.Row],
    *,
    starting_value: float,
    current_portfolio_value: float,
) -> dict[str, list[dict[str, Any]]]:
    now = datetime.now(tz=ZoneInfo("UTC"))
    return {
        "day": _pnl_bucket_points(
            rows,
            starting_value=starting_value,
            current_portfolio_value=current_portfolio_value,
            window_start=now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23),
            bucket="hour",
        ),
        "week": _pnl_bucket_points(
            rows,
            starting_value=starting_value,
            current_portfolio_value=current_portfolio_value,
            window_start=now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6),
            bucket="day",
        ),
        "month": _pnl_bucket_points(
            rows,
            starting_value=starting_value,
            current_portfolio_value=current_portfolio_value,
            window_start=now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29),
            bucket="day",
        ),
        "lifetime": _pnl_points(rows, starting_value=starting_value, current_portfolio_value=current_portfolio_value),
    }


def _pnl_bucket_points(
    rows: list[sqlite3.Row],
    *,
    starting_value: float,
    current_portfolio_value: float,
    window_start: datetime,
    bucket: str,
) -> list[dict[str, Any]]:
    value = float(starting_value)
    buckets: dict[str, float] = {}
    for row in rows:
        created_at = _parse_sqlite_utc(row["created_at"])
        delta = _portfolio_value_delta(row)
        if created_at is None:
            continue
        if created_at < window_start:
            value += delta
            continue
        bucket_time = created_at.replace(minute=0, second=0, microsecond=0) if bucket == "hour" else created_at.replace(hour=0, minute=0, second=0, microsecond=0)
        label = _format_pdt_bucket(bucket_time, bucket=bucket)
        buckets[label] = buckets.get(label, 0.0) + delta
    window_label = _format_pdt_bucket(window_start, bucket=bucket)
    points = [{"label": window_label, "value": round(value, 6)}]
    for label, delta in buckets.items():
        value += delta
        if len(points) == 1 and label == window_label:
            points[0]["value"] = round(value, 6)
        else:
            points.append({"label": label, "value": round(value, 6)})
    if round(value, 6) != round(current_portfolio_value, 6):
        points.append({"label": "Mark", "value": round(current_portfolio_value, 6)})
    return points


def _portfolio_value_delta(row: sqlite3.Row) -> float:
    side = str(row["side"] or "").lower()
    if side == "buy":
        return 0.0
    if side == "sell":
        return float(row["realized_pnl_usdc"] or 0)
    return 0.0


def _series_delta(points: list[dict[str, Any]]) -> float:
    if len(points) < 2:
        return 0.0
    return float(points[-1]["value"] or 0) - float(points[0]["value"] or 0)


def _parse_sqlite_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    except ValueError:
        return None


def _parse_source_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for suffix, zone in ((" PDT", "America/Los_Angeles"), (" PST", "America/Los_Angeles")):
        if text.endswith(suffix):
            try:
                return datetime.strptime(text.removesuffix(suffix), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(zone))
            except ValueError:
                return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _source_row_after_trade(row: sqlite3.Row, trade: SourceTrade) -> bool:
    block_number = int(row["block_number"] or 0)
    log_index = int(row["log_index"] or 0)
    if block_number != int(trade.block_number):
        return block_number > int(trade.block_number)
    if log_index != int(trade.log_index):
        return log_index > int(trade.log_index)
    return str(row["idempotency_key"] or "") > str(trade.idempotency_key)


def _format_pdt_bucket(value: datetime, *, bucket: str) -> str:
    pdt = value.astimezone(ZoneInfo("America/Los_Angeles"))
    return pdt.strftime("%m/%d %H:%M") if bucket == "hour" else pdt.strftime("%m/%d")


SCHEMA = """
create table if not exists wallets (
  address text primary key,
  name text not null,
  enabled integer not null default 1,
  strategy_label text not null default 'Standard',
  strategy_notes text not null default '',
  allowed_market_types text,
  bracket_strategy_enabled integer not null default 0,
  bracket_buy_size_usdc real not null default 10,
  bracket_stop_loss_pct real not null default 0,
  bracket_max_open_events integer not null default 0,
  bracket_allowed_patterns text,
  repeat_buy_strategy_enabled integer not null default 0,
  repeat_buy_size_usdc real not null default 5,
  repeat_buy_stop_loss_pct real not null default 0,
  repeat_buy_min_source_notional_usdc real not null default 0,
  repeat_buy_min_buy_count integer not null default 2,
  repeat_buy_min_avg_price real not null default 0.01,
  repeat_buy_max_avg_price real not null default 1.0,
  repeat_buy_max_total_exposure_usdc real not null default 0,
  repeat_buy_blocked_title_patterns text,
  repeat_buy_allowed_sports text,
  repeat_buy_allowed_bet_types text,
  event_follow_strategy_enabled integer not null default 0,
  event_follow_buy_size_usdc real not null default 2,
  event_follow_max_event_exposure_usdc real not null default 4,
  event_follow_max_total_exposure_usdc real not null default 50,
  event_follow_min_source_trade_usdc real not null default 20,
  event_follow_min_event_source_notional_usdc real not null default 250,
  event_follow_min_event_buy_count integer not null default 3,
  event_follow_min_avg_price real not null default 0.20,
  event_follow_max_avg_price real not null default 0.80,
  sports_trailing_stop_enabled integer not null default 0,
  sports_trailing_activation_pct real not null default 35,
  sports_trailing_stop_pct real not null default 25,
  sports_trailing_floor_delta real not null default 0.03,
  reserved_cash_usdc real not null default 0,
  profile_json text
);

create table if not exists source_trades (
  idempotency_key text primary key,
  copy_trade_key text,
  chain_id integer not null,
  exchange_contract text not null,
  tx_hash text not null,
  block_number integer not null,
  block_timestamp text not null,
  log_index integer not null,
  source_wallet text not null,
  side text not null check(side in ('buy', 'sell')),
  asset_id text not null,
  condition_id text,
  market_id text,
  outcome text,
  price real not null,
  quantity real not null,
  notional_usdc real not null
);

create table if not exists paper_trades (
  id integer primary key autoincrement,
  source_idempotency_key text not null,
  copy_trade_key text,
  side text not null check(side in ('buy', 'sell', 'skip')),
  asset_id text not null,
  source_wallet text not null,
  observed_price real not null,
  fill_price real not null,
  quantity real not null,
  notional_usdc real not null,
  realized_pnl_usdc real not null default 0,
  close_reason text,
  created_at text not null default current_timestamp
);

create table if not exists source_trade_attributions (
  id integer primary key autoincrement,
  copy_trade_key text not null,
  source_idempotency_key text not null unique,
  source_wallet text not null,
  paper_trade_id integer,
  executed integer not null default 0,
  skip_reason text,
  source_notional_usdc real,
  created_at text not null default current_timestamp
);

create table if not exists live_order_intents (
  id integer primary key autoincrement,
  source_idempotency_key text not null,
  source_wallet text not null,
  asset_id text not null,
  token_id text not null,
  side text not null check(side in ('buy', 'sell')),
  price real not null,
  size real not null,
  notional_usdc real not null,
  status text not null default 'pending',
  clob_order_id text,
  error text,
  response_json text,
  created_at text not null,
  updated_at text not null,
  unique(source_idempotency_key, side),
  foreign key(source_idempotency_key) references source_trades(idempotency_key)
);

create table if not exists live_shadow_audits (
  id integer primary key autoincrement,
  source_idempotency_key text not null,
  paper_trade_id integer not null unique,
  source_wallet text not null,
  asset_id text not null,
  token_id text not null,
  side text not null check(side in ('buy', 'sell')),
  paper_entry_price real not null,
  best_ask_at_decision real,
  order_price real not null,
  requested_notional_usdc real not null,
  requested_size real not null,
  available_size_at_price real,
  would_fill_size real,
  decision_latency_ms integer,
  post_submit_book_price real,
  notes text,
  created_at text not null,
  foreign key(source_idempotency_key) references source_trades(idempotency_key),
  foreign key(paper_trade_id) references paper_trades(id)
);

create table if not exists live_settlement_intents (
  id integer primary key autoincrement,
  source_idempotency_key text not null,
  source_wallet text not null,
  asset_id text not null,
  token_id text not null,
  condition_id text not null,
  quantity real not null,
  resolution_price real not null,
  status text not null default 'planned',
  redemption_tx_hash text,
  error text,
  response_json text,
  created_at text not null,
  updated_at text not null,
  unique(source_wallet, asset_id),
  foreign key(source_idempotency_key) references source_trades(idempotency_key)
);

create table if not exists positions (
  asset_id text not null,
  source_wallet text not null,
  quantity real not null,
  avg_entry_price real not null,
  realized_pnl_usdc real not null default 0,
  status text not null,
  trailing_peak_price real,
  trailing_activated integer not null default 0,
  winner_capture_stake_recovered integer not null default 0,
  winner_capture_first_scale_done integer not null default 0,
  winner_capture_high_price_done integer not null default 0,
  updated_at text not null default current_timestamp,
  primary key (asset_id, source_wallet)
);

create table if not exists ledger_entries (
  id integer primary key autoincrement,
  entry_type text not null,
  asset_id text,
  amount_usdc real not null,
  details text,
  created_at text not null default current_timestamp
);

create table if not exists runtime_state (
  key text primary key,
  value text not null
);

create table if not exists market_metadata (
  asset_id text primary key,
  market_id text,
  condition_id text,
  outcome text,
  outcome_side text,
  title text,
  market_slug text,
  market_url text,
  current_price real,
  price_source text,
  last_price_at text,
  market_type text,
  sport_key text,
  bet_type text,
  series_slug text,
  sports_market_type text,
  category_slug text,
  market_close_time text,
  market_close_time_kind text,
  event_slug text,
  event_title text,
  neg_risk integer,
  mergeable integer,
  is_closed integer,
  resolution_price real,
  updated_at text not null default current_timestamp
);

create table if not exists portfolio_snapshots (
  id integer primary key autoincrement,
  paper_cash_usdc real not null,
  exposure_usdc real not null,
  realized_pnl_usdc real not null,
  unrealized_pnl_usdc real not null,
  created_at text not null default current_timestamp
);

create table if not exists weather_brackets (
  id integer primary key autoincrement,
  source_wallet text not null,
  event_slug text not null,
  event_title text,
  status text not null default 'open',
  source_notional_usdc real not null default 0,
  target_notional_usdc real not null default 0,
  copied_notional_usdc real not null default 0,
  realized_pnl_usdc real not null default 0,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(source_wallet, event_slug)
);

create table if not exists weather_bracket_legs (
  id integer primary key autoincrement,
  bracket_id integer not null,
  asset_id text not null,
  outcome text,
  market_slug text,
  title text,
  source_quantity real not null default 0,
  source_notional_usdc real not null default 0,
  target_notional_usdc real not null default 0,
  copied_notional_usdc real not null default 0,
  updated_at text not null default current_timestamp,
  unique(bracket_id, asset_id),
  foreign key(bracket_id) references weather_brackets(id)
);

create table if not exists sports_brackets (
  id integer primary key autoincrement,
  source_wallet text not null,
  event_slug text not null,
  event_title text,
  pattern text not null,
  status text not null default 'tracking',
  source_notional_usdc real not null default 0,
  target_notional_usdc real not null default 0,
  copied_notional_usdc real not null default 0,
  realized_pnl_usdc real not null default 0,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(source_wallet, event_slug, pattern)
);

create table if not exists sports_bracket_legs (
  id integer primary key autoincrement,
  bracket_id integer not null,
  asset_id text not null,
  outcome text,
  market_slug text,
  title text,
  source_quantity real not null default 0,
  source_notional_usdc real not null default 0,
  target_notional_usdc real not null default 0,
  copied_notional_usdc real not null default 0,
  updated_at text not null default current_timestamp,
  unique(bracket_id, asset_id),
  foreign key(bracket_id) references sports_brackets(id)
);

create table if not exists repeat_buy_signals (
  id integer primary key autoincrement,
  source_wallet text not null,
  asset_id text not null,
  market_id text,
  title text,
  outcome text,
  buy_count integer not null default 0,
  source_notional_usdc real not null default 0,
  source_quantity real not null default 0,
  copied integer not null default 0,
  paper_trade_id integer,
  copied_notional_usdc real not null default 0,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(source_wallet, asset_id)
);

create table if not exists event_follow_signals (
  id integer primary key autoincrement,
  source_wallet text not null,
  event_slug text not null,
  event_title text,
  market_type text,
  buy_count integer not null default 0,
  source_notional_usdc real not null default 0,
  source_quantity real not null default 0,
  copied_notional_usdc real not null default 0,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(source_wallet, event_slug)
);

create table if not exists event_follow_legs (
  id integer primary key autoincrement,
  signal_id integer not null,
  asset_id text not null,
  outcome text,
  market_slug text,
  title text,
  buy_count integer not null default 0,
  source_notional_usdc real not null default 0,
  source_quantity real not null default 0,
  copied_notional_usdc real not null default 0,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(signal_id, asset_id),
  foreign key(signal_id) references event_follow_signals(id)
);
"""

INDEXES = """
create index if not exists idx_source_trades_recent
  on source_trades (block_number desc, log_index desc);

create index if not exists idx_source_trades_wallet_asset_time
  on source_trades (source_wallet, asset_id, block_number, log_index);

create index if not exists idx_source_trade_attributions_copy_key
  on source_trade_attributions (copy_trade_key);

create index if not exists idx_source_trade_attributions_source_key
  on source_trade_attributions (source_idempotency_key);

create index if not exists idx_source_trade_attributions_unexecuted_skip_notional
  on source_trade_attributions (skip_reason, source_notional_usdc)
  where executed = 0 and skip_reason is not null;

create index if not exists idx_live_order_intents_status_created
  on live_order_intents (status, created_at desc);

create index if not exists idx_live_order_intents_wallet_asset
  on live_order_intents (source_wallet, asset_id, created_at desc);

create index if not exists idx_live_shadow_audits_created
  on live_shadow_audits (created_at desc, id desc);

create index if not exists idx_live_shadow_audits_wallet_asset
  on live_shadow_audits (source_wallet, asset_id, created_at desc);

create unique index if not exists idx_live_order_intents_clob_order_id
  on live_order_intents (clob_order_id)
  where clob_order_id is not null;

create index if not exists idx_live_settlement_intents_status_created
  on live_settlement_intents (status, created_at desc);

create unique index if not exists idx_live_settlement_intents_tx_hash
  on live_settlement_intents (redemption_tx_hash)
  where redemption_tx_hash is not null;

create index if not exists idx_paper_trades_copy_key
  on paper_trades (copy_trade_key);

create index if not exists idx_paper_trades_source_key
  on paper_trades (source_idempotency_key);

create index if not exists idx_paper_trades_asset_wallet
  on paper_trades (asset_id, source_wallet, side, created_at desc, id desc);

create index if not exists idx_positions_open
  on positions (quantity, updated_at desc);

create index if not exists idx_market_metadata_event_asset
  on market_metadata (event_slug, asset_id);

create index if not exists idx_weather_brackets_wallet_event
  on weather_brackets (source_wallet, event_slug);

create index if not exists idx_weather_bracket_legs_bracket_asset
  on weather_bracket_legs (bracket_id, asset_id);

create index if not exists idx_sports_brackets_wallet_event
  on sports_brackets (source_wallet, event_slug, pattern);

create index if not exists idx_sports_bracket_legs_bracket_asset
  on sports_bracket_legs (bracket_id, asset_id);

create index if not exists idx_repeat_buy_signals_wallet_asset
  on repeat_buy_signals (source_wallet, asset_id);

create index if not exists idx_event_follow_signals_wallet_event
  on event_follow_signals (source_wallet, event_slug);

create index if not exists idx_event_follow_legs_signal_asset
  on event_follow_legs (signal_id, asset_id);
"""
