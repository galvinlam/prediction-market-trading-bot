from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import math
import re
import time
from typing import Any, Callable

from polymarket_copy_trading.bet_sizing import ScaledSourceSizer
from polymarket_copy_trading.config import AppSettings, WinnerCaptureConfig
from polymarket_copy_trading.event_book_planner import (
    EventBookLeg,
    EventBookPlannerSettings,
    PlannerDecision,
    plan_event_book_buys,
)
from polymarket_copy_trading.models import Position, PositionLot, SourceTrade
from polymarket_copy_trading.paper import PaperBroker, PaperExecutionError
from polymarket_copy_trading.store import Store
from polymarket_copy_trading.wallet_profile import (
    wallet_profile_bool as _wallet_profile_bool,
    wallet_profile_float as _wallet_profile_float,
    wallet_profile_has as _wallet_profile_has,
    wallet_profile_int as _wallet_profile_int,
    wallet_profile_list as _wallet_profile_list,
    wallet_profile_section as _wallet_profile_section,
)


PDT = timezone(timedelta(hours=-7), "PDT")
RN1_WALLET = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
POLYMARKET_MIN_BUY_NOTIONAL_USDC = 1.0
BUY_BELOW_MIN_NOTIONAL_SKIP = "buy_below_min_notional"
RN1_ALLOWED_EVENT_SPORTS = {"soccer", "mlb", "nba", "nhl", "esports"}
RN1_ALLOWED_EVENT_BET_TYPES = {"moneyline_winlose", "map_or_game_winner"}
RN1_CONVICTION_SOURCE_NOTIONAL_USDC = 3000.0
RN1_EVENT_BOOK_MIN_DOMINANCE_SHARE = 0.60
RN1_EVENT_BOOK_MIN_DOMINANCE_RATIO = 1.75
RN1_ESPORTS_MIN_BUY_COUNT = 40
RN1_ESPORTS_MIN_SOURCE_NOTIONAL_USDC = RN1_CONVICTION_SOURCE_NOTIONAL_USDC
RN1_ESPORTS_MIN_AVG_PRICE = 0.40
RN1_ESPORTS_MAX_AVG_PRICE = 0.70
RN1_ESPORTS_ALLOWED_BET_TYPES = {"moneyline_winlose"}
RN1_SOURCE_FOLLOW_COPY_SCALE = 0.0005
RN1_SOURCE_FOLLOW_MAX_ASSET_EXPOSURE_USDC = 25.0
RN1_FILTER_COPY_MAX_SOURCE_PRICE = 0.60
RN1_FILTER_COPY_MIN_SINGLE_FILL_USDC = 0.0
RN1_FILTER_COPY_MIN_CUMULATIVE_SOURCE_USDC = 3000.0
RN1_FILTER_COPY_ALT_MIN_CUMULATIVE_SOURCE_USDC = 5000.0
RN1_FILTER_COPY_SOCCER_MIN_CUMULATIVE_SOURCE_USDC = 10000.0
RN1_FILTER_COPY_MLB_MIN_CUMULATIVE_SOURCE_USDC = 5000.0
RN1_FILTER_COPY_TENNIS_MIN_CUMULATIVE_SOURCE_USDC = 1500.0
RN1_FILTER_COPY_TENNIS_MIN_BUY_COUNT = 20
RN1_FILTER_COPY_TENNIS_MAX_SOURCE_PRICE = 0.60
RN1_FILTER_COPY_TENNIS_OPPOSITE_MAX_RATIO = 2.0
RN1_FILTER_COPY_TENNIS_FRESH_MIN_DOMINANCE_SHARE = 0.70
RN1_FILTER_COPY_TENNIS_FRESH_MIN_DOMINANCE_RATIO = 2.0
RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_SHARE = 0.80
RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_RATIO = 3.0
RN1_FILTER_COPY_REBALANCE_MAX_ORDER_USDC = 3.0
RN1_FILTER_COPY_REBALANCE_MIN_WORST_CASE_IMPROVEMENT_FRACTION = 0.15
RN1_FILTER_COPY_WINDOW_SECONDS = 60
GREERFEW_WALLET = "0x64f6f18af2db92021efcd0894f9a94dfa0fc15a2"
GREERFEW_SOURCE_COPY_SCALE = 0.25
GREERFEW_LIMIT_PRICE_PREMIUM = 0.003
GREERFEW_LIMIT_PRICE_MULTIPLE = 1.20
SWISSTONY_WALLET = "0x204f72f35326db932158cba6adff0b9a1da95e14"
VIP68_WALLET = "0x8d0930676d559cc8fb7d8af0c555791c1820143f"
SWISSTONY_TIER_A_MIN_PRICE = 0.30
SWISSTONY_TIER_A_MAX_PRICE = 0.65
SWISSTONY_TIER_A_NOTIONAL_USDC = 3.0
SWISSTONY_TIER_B_MAX_PRICE = 0.80
SWISSTONY_TIER_B_NOTIONAL_USDC = 2.0
SWISSTONY_SOURCE_FOLLOW_COPY_SCALE = 0.001
SWISSTONY_SOURCE_FOLLOW_MAX_ASSET_EXPOSURE_USDC = 25.0
SWISSTONY_FILTER_COPY_MAX_SOURCE_PRICE = 0.60
SWISSTONY_FILTER_COPY_MIN_SINGLE_FILL_USDC = 250.0
SWISSTONY_FILTER_COPY_MIN_CUMULATIVE_SOURCE_USDC = 3000.0
SWISSTONY_FILTER_COPY_WINDOW_SECONDS = 1800
FILTER_COPY_MIN_SOURCE_PRICE = 0.20
FILTER_COPY_DAILY_DEPLOYED_CAP_USDC = 100.0
FILTER_COPY_SOURCE_SELL_EXIT_FRACTION = 0.0
FILTER_COPY_SAME_EVENT_HEDGE_MAX_FRACTION = 0.25
FILTER_COPY_IN_PLAY_HEDGE_MAX_FRACTION = 0.10
FILTER_COPY_REBALANCE_MAX_SOURCE_PRICE = 0.82
FILTER_COPY_REBALANCE_STRONG_MAX_SOURCE_PRICE = 0.88
FILTER_COPY_REBALANCE_MIN_SOURCE_NOTIONAL_USDC = 3000.0
FILTER_COPY_REBALANCE_STRONG_MIN_SOURCE_NOTIONAL_USDC = 10000.0
FILTER_COPY_REBALANCE_MIN_EVENT_SHARE = 0.45
FILTER_COPY_REBALANCE_STRONG_MIN_EVENT_SHARE = 0.60
FILTER_COPY_REBALANCE_MIN_REPAIR_RATIO = 1.15
FILTER_COPY_REBALANCE_MAX_REPAIR_BUY_USDC = 30.0
FILTER_COPY_SWISSTONY_REBALANCE_MAX_REPAIR_BUY_USDC = 22.0
FILTER_COPY_REBALANCE_NORMAL_EVENT_CAP_USDC = 25.0
FILTER_COPY_REBALANCE_EXTRA_EVENT_CAP_USDC = 20.0
FILTER_COPY_EVENT_BOOK_CO_DOMINANT_RATIO = 0.75
FILTER_COPY_EVENT_BOOK_CO_DOMINANT_SHARE = 0.35
FILTER_COPY_CAP_CREDIT_PRICE = 0.95
FILTER_COPY_RN1_REPAIR_MAX_LOCAL_PRICE = 0.95
FILTER_COPY_SCALE_UP_MAX_POSITION_USDC = 60.0
FILTER_COPY_MIN_TOP_UP_USDC = 3.0
FILTER_COPY_IN_EVENT_STOP_LOSS_PCT = 0.0
FILTER_COPY_RN1_SPORTS = {"nba", "nhl", "mlb", "soccer", "atp", "wta", "tennis", "esports"}
FILTER_COPY_SWISSTONY_SPORTS = {"soccer", "mlb", "nba", "nhl", "nfl", "esports", "atp", "wta", "tennis", "other"}
FILTER_COPY_RN1_REBALANCE_SPORTS = {"soccer", "mlb", "nba"}
FILTER_COPY_SWISSTONY_REBALANCE_SPORTS = {"soccer", "mlb", "nba", "nhl", "nfl", "atp", "wta", "tennis"}
FILTER_COPY_ALLOWED_BET_TYPES = {
    "moneyline_winlose",
    "total_or_over_under",
    "spread_handicap",
    "both_teams_score",
    "map_or_game_winner",
}
RN1_FILTER_COPY_TENNIS_SPORTS = {"atp", "wta", "tennis"}
FILTER_COPY_OPPOSITE_RANK_FLIP_MIN_DOMINANCE_SHARE = 0.60
FILTER_COPY_EVENT_BOOK_MIN_ASSET_SOURCE_NOTIONAL_USDC = 1000.0
SHARP_0X8A091_WALLET = "0x8a091656e5f4c6bc4fdf37b2585be0235f68e317"
SHARP_0X8A091_BUY_SIZE_USDC = 5.0
SPORTS_DOUBLE_WIN_BRACKET_PATTERN = "sports_double_win_bracket"
SPORTS_TWO_OUTCOME_BRACKET_PATTERN = "sports_two_outcome_bracket"
SPORTS_TOTAL_LADDER_BRACKET_PATTERN = "sports_total_ladder_bracket"
SPORTS_SPREAD_LADDER_BRACKET_PATTERN = "sports_spread_ladder_bracket"
SPORTS_MULTI_LEG_BRACKET_PATTERN = "sports_multi_leg_bracket"
NEAR_ZERO_EXIT_PRICE = 0.005
NEAR_ZERO_AFTER_CLOSE_GRACE_MINUTES = 30
SPORTS_QUOTED_LOSER_AFTER_CLOSE_GRACE_MINUTES = 360
SPORTS_PRE_END_LOCK_PRICE = 0.95
SPORTS_PRE_END_LOCK_PROFIT_MULTIPLE = 1.20


class CopyTradingEngine:
    def __init__(
        self,
        *,
        config: AppSettings,
        store: Store,
        buy_price_resolver: Callable[[str], float | None] | None = None,
        market_metadata_resolver: Callable[[str], dict[str, Any] | None] | None = None,
        source_position_resolver: Callable[[str, str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.buy_price_resolver = buy_price_resolver
        self.market_metadata_resolver = market_metadata_resolver
        self.source_position_resolver = source_position_resolver
        self.sizer = ScaledSourceSizer(config.sizing)
        existing_cash = store.get_runtime_state("paper_cash_usdc")
        ledger_cash = store.paper_cash_from_ledger(starting_cash_usdc=config.paper.starting_cash_usdc)
        should_reconcile_cash = existing_cash is not None and store.paper_trade_count() > 0
        starting_cash = (
            ledger_cash
            if should_reconcile_cash
            else float(existing_cash) if existing_cash is not None else config.paper.starting_cash_usdc
        )
        self.broker = PaperBroker(
            starting_cash_usdc=starting_cash,
            slippage_pct=config.paper.slippage_pct,
            settlement_slippage_pct=config.paper.settlement_slippage_pct,
        )
        self._hydrate_open_positions()
        if existing_cash is None:
            self.store.set_runtime_state("paper_cash_usdc", str(config.paper.starting_cash_usdc))
        elif should_reconcile_cash and round(float(existing_cash), 6) != round(ledger_cash, 6):
            self.store.set_runtime_state("paper_cash_usdc", str(round(ledger_cash, 6)))

    def process_trades(self, trades: Iterable[SourceTrade]) -> dict[str, int]:
        stats = {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        for trade in trades:
            result = self.process_trade(trade)
            stats[result] += 1
        return stats

    def process_trade(self, trade: SourceTrade) -> str:
        if not self.store.is_wallet_enabled(trade.source_wallet):
            return "ignored"
        if not self.store.insert_source_trade(trade):
            return "duplicates"
        wallet = self.store.get_wallet(trade.source_wallet) or {}
        if (
            trade.side == "buy"
            and self.store.has_executed_copy_trade(
                trade,
                source_wallet_scoped=_filter_copy_enabled(trade.source_wallet, wallet),
            )
            and not _repeat_buy_strategy_enabled(wallet)
            and not _event_follow_strategy_enabled(wallet)
        ):
            self._record_skip(trade, "already_copied")
            return "attributed"

        if trade.side == "buy":
            return self._process_buy(trade)
        if trade.side == "sell":
            if not self.config.exits.mirror_source_sells:
                return self._record_skip(trade, "source_sells_disabled")
            return self._process_sell(trade, close_reason="source_sell")
        return self._record_skip(trade, "unsupported_side")

    def _process_buy(self, trade: SourceTrade) -> str:
        metadata = self._metadata_for(trade.asset_id)
        market_type = self._market_type_from_metadata(metadata)
        wallet = self.store.get_wallet(trade.source_wallet) or {}
        if not _copy_buys_enabled(wallet):
            return self._record_skip(trade, "copy_buys_disabled")
        if trade.source_wallet.lower() == SWISSTONY_WALLET and market_type == "other" and _event_sport_group(metadata) != "other":
            market_type = "sports"
        if not self._market_type_allowed(trade.source_wallet, market_type):
            return self._record_skip(trade, "market_type_blocked")
        if _market_is_closed_for_new_buy(metadata, market_type=market_type):
            return self._record_skip(trade, "market_closed")
        paused_reason = _source_wallet_paused_sport_reason(trade.source_wallet, metadata, wallet)
        if paused_reason is not None:
            return self._record_skip(trade, paused_reason)
        if _filter_copy_enabled(trade.source_wallet, wallet):
            return self._process_filter_copy_buy(trade, metadata, wallet)
        if market_type == "weather" and _weather_bracket_strategy_enabled(wallet) and metadata.get("event_slug"):
            return self._process_weather_bracket_buy(trade, metadata, wallet)
        if _event_follow_strategy_enabled(wallet):
            return self._process_event_follow_buy(trade, metadata, wallet, market_type)
        if _repeat_buy_strategy_enabled(wallet):
            return self._process_repeat_buy(trade, metadata, wallet)
        if _sharp_simple_crypto_copy_enabled(trade.source_wallet, wallet, market_type):
            return self._process_fixed_notional_buy(
                trade,
                notional_usdc=_wallet_profile_float(wallet, "fixed_buy", "buy_size_usdc", SHARP_0X8A091_BUY_SIZE_USDC),
                source_reference_price=trade.price,
            )

        position = self.broker.get_position(trade.asset_id, trade.source_wallet)
        current_position_usdc = position.cost_basis_usdc if position else 0.0
        decision = self.sizer.size_buy(
            trade,
            current_position_usdc=current_position_usdc,
            available_cash_usdc=self._available_cash_for_wallet(trade.source_wallet),
        )
        if not decision.should_trade:
            return self._record_skip(trade, decision.reason)

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        block_reason = self._buy_price_block_reason(observed_price or trade.price, trade.price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)

        try:
            self._execute_buy(trade, notional_usdc=decision.notional_usdc, observed_price=observed_price)
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        return "processed"

    def _process_fixed_notional_buy(
        self,
        trade: SourceTrade,
        *,
        notional_usdc: float,
        source_reference_price: float,
    ) -> str:
        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        notional = min(float(notional_usdc), available_cash)
        if notional < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        block_reason = self._buy_price_block_reason(observed_price or trade.price, source_reference_price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)

        try:
            self._execute_buy(trade, notional_usdc=round(notional, 6), observed_price=observed_price)
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        return "processed"

    def _process_filter_copy_buy(
        self,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str:
        if _event_book_planner_enabled(wallet):
            event_book_result = self._process_filter_copy_event_book_planner_buy(trade, metadata, wallet)
            if event_book_result is not None:
                return event_book_result

        source_position = self.store.source_position_summary(
            source_wallet=trade.source_wallet,
            asset_id=trade.asset_id,
            anchor_trade=trade,
            window_seconds=0,
        )
        source_position = self._source_position_with_snapshot_floor(
            source_wallet=trade.source_wallet,
            asset_id=trade.asset_id,
            position=source_position,
        )
        source_notional = float(source_position.get("net_notional_usdc") or source_position.get("buy_notional_usdc") or 0)
        min_cumulative = _filter_copy_min_cumulative_source_usdc(trade.source_wallet, wallet, metadata)
        source_reference_price = _filter_copy_source_reference_price(source_position, fallback_price=trade.price)
        event_book_role = self._filter_copy_source_event_book_role(trade=trade, metadata=metadata)
        market_block = _filter_copy_market_block_reason(trade.source_wallet, metadata, wallet)
        if market_block is not None:
            if _filter_copy_market_blocked_repair_candidate(trade.source_wallet, metadata, wallet):
                event_book_plan = self._filter_copy_event_book_plan(
                    trade=trade,
                    metadata=metadata,
                    wallet=wallet,
                    source_position=source_position,
                    source_reference_price=source_reference_price,
                    blocked_market_repair=True,
                )
                if event_book_plan is not None:
                    return self._process_filter_copy_event_book_buy(
                        trade=trade,
                        metadata=metadata,
                        wallet=wallet,
                        plan=event_book_plan,
                    )
            return self._record_skip(trade, market_block)
        rn1_tennis_block = _rn1_filter_copy_tennis_block_reason(
            trade.source_wallet,
            metadata,
            source_position,
            event_book_role,
        )
        if rn1_tennis_block is not None:
            return self._record_skip(trade, rn1_tennis_block)
        market_rule_block = _filter_copy_market_rule_block_reason(
            trade.source_wallet,
            metadata,
            wallet,
            source_position,
            event_book_role,
        )
        if market_rule_block is not None:
            return self._record_skip(trade, market_rule_block)
        event_book_plan = self._filter_copy_event_book_plan(
            trade=trade,
            metadata=metadata,
            wallet=wallet,
            source_position=source_position,
            source_reference_price=source_reference_price,
        )
        if event_book_plan is not None:
            return self._process_filter_copy_event_book_buy(
                trade=trade,
                metadata=metadata,
                wallet=wallet,
                plan=event_book_plan,
            )
        rebalance_plan = self._filter_copy_rebalance_plan(
            trade=trade,
            metadata=metadata,
            wallet=wallet,
            event_book_role=event_book_role,
            source_notional=source_notional,
            source_reference_price=source_reference_price,
        )
        if rebalance_plan is None and self._filter_copy_opposite_position_rank_flip_blocked(
            trade=trade,
            metadata=metadata,
            event_book_role=event_book_role,
        ):
            return self._record_skip(trade, "filter_copy_opposite_rank_flip_blocked")
        same_event_repair_price_allowed = self._filter_copy_same_event_repair_price_allowed(
            trade=trade,
            metadata=metadata,
            wallet=wallet,
            event_book_role=event_book_role,
            source_notional=source_notional,
            source_reference_price=source_reference_price,
        )
        price_block = _filter_copy_source_price_block_reason(trade.source_wallet, source_reference_price, wallet, metadata)
        if price_block is not None and rebalance_plan is None and not same_event_repair_price_allowed:
            return self._record_skip(trade, price_block)
        base_notional = (
            float(rebalance_plan["notional_usdc"])
            if rebalance_plan is not None
            else _filter_copy_bet_size_usdc(trade.source_wallet, source_reference_price, wallet, metadata)
        )
        existing_position = self.broker.get_position(trade.asset_id, trade.source_wallet)
        hedge_notional = None
        if rebalance_plan is None and (existing_position is None or existing_position.quantity <= 0):
            hedge_notional = self._filter_copy_same_event_hedge_notional(
                trade=trade,
                metadata=metadata,
                wallet=wallet,
                source_notional=source_notional,
                max_fraction=None,
                required_source_asset_id=(
                    str(event_book_role.get("dominant_asset_id") or "")
                    if event_book_role.get("role") == "secondary"
                    else None
                ),
            )

        is_same_event_hedge = hedge_notional is not None
        if base_notional <= 0 and not is_same_event_hedge and rebalance_plan is None and not (
            existing_position is not None
            and existing_position.quantity > 0
            and event_book_role.get("role") == "secondary"
            and same_event_repair_price_allowed
        ):
            return self._record_skip(trade, "filter_copy_price_tier_blocked")
        if (
            rebalance_plan is None
            and event_book_role.get("role") == "secondary"
            and not is_same_event_hedge
            and (existing_position is None or existing_position.quantity <= 0)
            and not _rn1_filter_copy_tennis_secondary_allowed(trade.source_wallet, metadata, event_book_role)
        ):
            reconciled = self._reconcile_filter_copy_event_book(trade=trade, metadata=metadata, wallet=wallet)
            self._record_skip(trade, "filter_copy_same_event_rebalance")
            return "processed" if reconciled > 0 else "skipped"
        is_fresh_initial_entry = (
            rebalance_plan is None
            and not is_same_event_hedge
            and (existing_position is None or existing_position.quantity <= 0)
        )
        min_single_fill = _filter_copy_min_single_fill_usdc(trade.source_wallet, wallet)
        if is_fresh_initial_entry and min_single_fill > 0 and trade.notional_usdc < min_single_fill:
            return self._record_skip(trade, "filter_copy_single_fill_too_small")
        if rebalance_plan is None and not is_same_event_hedge and source_notional < min_cumulative:
            return self._record_skip(trade, "filter_copy_waiting_for_source_position")

        if rebalance_plan is not None:
            notional = float(rebalance_plan["notional_usdc"])
        elif existing_position is not None and existing_position.quantity > 0:
            if event_book_role.get("role") == "secondary":
                if source_notional < min_cumulative:
                    return self._record_skip(trade, "filter_copy_same_event_rebalance")
                hedge_target = self._filter_copy_same_event_hedge_notional(
                    trade=trade,
                    metadata=metadata,
                    wallet=wallet,
                    source_notional=source_notional,
                    max_fraction=1.0,
                    required_source_asset_id=str(event_book_role.get("dominant_asset_id") or ""),
                )
                if hedge_target is None:
                    return self._record_skip(trade, "filter_copy_same_event_rebalance")
                conviction_target = self._filter_copy_target_notional(
                    trade=trade,
                    wallet=wallet,
                    metadata=metadata,
                    base_notional=base_notional,
                    min_cumulative=min_cumulative,
                    source_notional=source_notional,
                )
                target_notional = min(conviction_target, hedge_target) if conviction_target > 0 else hedge_target
                max_position = _filter_copy_target_max_position_usdc(
                    source_wallet=trade.source_wallet,
                    wallet=wallet,
                    metadata=metadata,
                    base_notional=base_notional,
                )
                if max_position > 0:
                    target_notional = min(target_notional, max_position)
                notional = round(max(0.0, target_notional - existing_position.cost_basis_usdc), 6)
            else:
                if base_notional <= 0:
                    return self._record_skip(trade, "filter_copy_price_tier_blocked")
                notional = self._filter_copy_scale_up_notional(
                    trade=trade,
                    wallet=wallet,
                    metadata=metadata,
                    base_notional=base_notional,
                    min_cumulative=min_cumulative,
                    source_notional=source_notional,
                    existing_cost=existing_position.cost_basis_usdc,
                )
            if notional < self.config.sizing.min_trade_usdc:
                return self._record_skip(trade, "filter_copy_scale_target_met")
            if (
                event_book_role.get("role") != "secondary"
                and not same_event_repair_price_allowed
                and notional < _filter_copy_min_top_up_usdc(wallet)
            ):
                return self._record_skip(trade, "filter_copy_top_up_below_min")
        else:
            if hedge_notional is not None:
                if hedge_notional < self.config.sizing.min_trade_usdc:
                    return self._record_skip(trade, "filter_copy_hedge_below_min")
                notional = min(base_notional, hedge_notional) if base_notional > 0 else hedge_notional
            else:
                if base_notional <= 0:
                    return self._record_skip(trade, "filter_copy_price_tier_blocked")
                notional = self._filter_copy_target_notional(
                    trade=trade,
                    wallet=wallet,
                    metadata=metadata,
                    base_notional=base_notional,
                    min_cumulative=min_cumulative,
                    source_notional=source_notional,
                )

        is_repair_buy = rebalance_plan is not None or same_event_repair_price_allowed or is_same_event_hedge
        daily_cap = _filter_copy_daily_deployed_cap_usdc(wallet)
        if daily_cap > 0 and not is_repair_buy:
            deployed = self._filter_copy_deployed_cap_usage_usdc(trade.source_wallet)
            if deployed + notional > daily_cap:
                return self._record_skip(trade, "filter_copy_daily_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        if notional > available_cash:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        local_price_block = _filter_copy_local_price_block_reason(
            trade.source_wallet,
            (observed_price or source_reference_price) * (1 + self.config.paper.slippage_pct / 100),
            wallet,
            metadata,
        )
        if local_price_block is not None and rebalance_plan is None and not same_event_repair_price_allowed:
            return self._record_skip(trade, local_price_block)
        block_reason = self._buy_price_block_reason(observed_price or source_reference_price, source_reference_price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)

        try:
            self._execute_buy(trade, notional_usdc=round(notional, 6), observed_price=observed_price)
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        return "processed"

    def _process_filter_copy_event_book_planner_buy(
        self,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str | None:
        if trade.source_wallet.lower() not in {RN1_WALLET, SWISSTONY_WALLET}:
            return None
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return None

        event_positions = self.store.source_event_position_summaries(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            anchor_trade=trade,
        )
        event_positions = [
            self._source_event_position_with_snapshot_floor(trade.source_wallet, item)
            for item in event_positions
        ]
        positive_positions = [
            item for item in event_positions if float(item.get("net_notional_usdc") or 0) > 0
        ]
        if not positive_positions:
            return None

        total_source_notional = sum(float(item.get("net_notional_usdc") or 0) for item in positive_positions)
        min_event_source = _filter_copy_min_cumulative_source_usdc(trade.source_wallet, wallet, metadata)
        if total_source_notional < min_event_source:
            return self._record_skip(trade, "event_book_waiting_for_source_position")

        local_book = self._event_book_local_legs(source_wallet=trade.source_wallet, event_slug=event_slug)
        has_local_event_exposure = bool(local_book)
        if not has_local_event_exposure:
            min_single_fill = _filter_copy_min_single_fill_usdc(trade.source_wallet, wallet)
            if min_single_fill > 0 and float(trade.notional_usdc or 0) < min_single_fill:
                return self._record_skip(trade, "filter_copy_single_fill_too_small")
        metadata_by_asset: dict[str, dict[str, Any]] = {}
        for item in positive_positions:
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            asset_metadata = metadata if asset_id == trade.asset_id else self._metadata_for(asset_id)
            metadata_by_asset[asset_id] = asset_metadata

        enriched_positions = [
            _event_book_position_with_metadata(item, metadata_by_asset.get(str(item.get("asset_id") or ""), {}))
            for item in positive_positions
        ]
        source_book: list[EventBookLeg] = []
        trigger_in_book = False
        skipped_current_reason: str | None = None
        for item in enriched_positions:
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            asset_metadata = metadata_by_asset.get(asset_id, {})
            block_reason = self._event_book_planner_leg_block_reason(
                source_wallet=trade.source_wallet,
                metadata=asset_metadata,
                wallet=wallet,
                has_local_event_exposure=has_local_event_exposure,
                current_position=item,
                positive_positions=enriched_positions,
            )
            if block_reason is not None:
                if asset_id == trade.asset_id:
                    skipped_current_reason = block_reason
                continue
            leg = self._event_book_source_leg(item, asset_metadata=asset_metadata)
            if leg is not None:
                source_book.append(leg)
                trigger_in_book = trigger_in_book or asset_id == trade.asset_id

        if not source_book:
            return self._record_skip(trade, skipped_current_reason or "event_book_no_copyable_legs")
        if not trigger_in_book and skipped_current_reason is not None and trade.source_wallet.lower() == RN1_WALLET:
            return self._record_skip(trade, skipped_current_reason)
        if not trigger_in_book and skipped_current_reason is not None and not has_local_event_exposure:
            return self._record_skip(trade, skipped_current_reason)
        if trade.source_wallet.lower() == SWISSTONY_WALLET and not has_local_event_exposure:
            quality_block = _swisstony_event_book_fresh_quality_block_reason(
                event_positions=positive_positions,
                metadata_by_asset=metadata_by_asset,
                wallet=wallet,
            )
            if quality_block is not None:
                return self._record_skip(trade, quality_block)

        plan = plan_event_book_buys(
            source_book=source_book,
            local_book=local_book,
            settings=self._event_book_planner_settings(
                source_wallet=trade.source_wallet,
                wallet=wallet,
                metadata=metadata,
            ),
        )
        copied = 0
        first_error: str | None = None
        event_positions = self.store.list_positions()
        for order in plan.orders:
            order_trade = self._event_book_order_source_trade(
                anchor_trade=trade,
                order=order,
                metadata=self._metadata_for(order.asset_id),
            )
            if self.store.has_source_trade_attribution(order_trade.idempotency_key):
                continue
            order_notional = order.notional_usdc
            if trade.source_wallet.lower() == RN1_WALLET and order.decision == "rebalance":
                same_event_positions = [
                    position
                    for position in event_positions
                    if str(position.get("source_wallet") or "").lower() == trade.source_wallet.lower()
                    and str(position.get("event_slug") or "") == event_slug
                    and str(position.get("asset_id") or "") != order.asset_id
                    and float(position.get("quantity") or 0) > 0
                ]
                order_notional = self._filter_copy_material_risk_reducing_repair_notional(
                    same_event_positions=same_event_positions,
                    asset_id=order.asset_id,
                    planned_notional=min(order.notional_usdc, _rn1_filter_copy_rebalance_max_order_usdc(wallet)),
                    executable_price=order.current_price,
                    wallet=wallet,
                )
                if order_notional < self._minimum_buy_notional_usdc():
                    first_error = first_error or "event_book_rebalance_not_risk_reducing"
                    continue
            try:
                self._execute_buy(
                    order_trade,
                    notional_usdc=round(order_notional, 6),
                    observed_price=order.current_price,
                )
            except PaperExecutionError as exc:
                first_error = first_error or self._buy_execution_skip_reason(exc)
                continue
            copied += 1
            event_positions = self.store.list_positions()

        if copied > 0:
            return "processed"
        reason = first_error or self._event_book_plan_skip_reason(plan.rejections)
        return self._record_skip(trade, reason)

    def _event_book_source_leg(
        self,
        item: dict[str, Any],
        *,
        asset_metadata: dict[str, Any],
    ) -> EventBookLeg | None:
        asset_id = str(item.get("asset_id") or "")
        if not asset_id:
            return None
        source_notional = float(item.get("net_notional_usdc") or 0)
        source_quantity = float(item.get("net_quantity") or 0)
        if source_notional <= 0 or source_quantity <= 0:
            return None
        current_price = self._resolve_buy_price(asset_id) if self.buy_price_resolver is not None else None
        avg_price = _filter_copy_source_reference_price(item, fallback_price=source_notional / source_quantity)
        return EventBookLeg(
            asset_id=asset_id,
            title=str(asset_metadata.get("title") or item.get("title") or ""),
            outcome=str(asset_metadata.get("outcome") or item.get("outcome") or ""),
            net_notional_usdc=round(source_notional, 6),
            net_quantity=round(source_quantity, 6),
            avg_price=round(avg_price, 6) if avg_price > 0 else None,
            current_price=round(current_price, 6) if current_price is not None and current_price > 0 else None,
        )

    def _event_book_local_legs(self, *, source_wallet: str, event_slug: str) -> list[EventBookLeg]:
        legs: list[EventBookLeg] = []
        for position in self.store.list_positions():
            if str(position.get("source_wallet") or "").lower() != source_wallet.lower():
                continue
            if str(position.get("event_slug") or "") != event_slug:
                continue
            quantity = float(position.get("quantity") or 0)
            notional = float(position.get("cost_basis_usdc") or 0)
            if quantity <= 0 or notional <= 0:
                continue
            legs.append(
                EventBookLeg(
                    asset_id=str(position.get("asset_id") or ""),
                    title=str(position.get("title") or ""),
                    outcome=str(position.get("outcome") or ""),
                    net_notional_usdc=round(notional, 6),
                    net_quantity=round(quantity, 6),
                    avg_price=round(float(position.get("avg_entry_price") or 0), 6),
                    current_price=_float_or_none(position.get("current_price")),
                )
            )
        return legs

    def _event_book_planner_settings(
        self,
        *,
        source_wallet: str,
        wallet: dict[str, Any],
        metadata: dict[str, Any],
    ) -> EventBookPlannerSettings:
        total_cap = _wallet_profile_float(wallet, "event_book", "planner_total_bankroll_usdc", 100.0)
        reserve_cap = _wallet_profile_float(wallet, "event_book", "planner_reserve_capital_usdc", 20.0)
        normal_cap = max(0.0, total_cap - reserve_cap)
        base_event_cap = _wallet_profile_float(wallet, "event_book", "planner_base_event_budget_usdc", 5.0)
        event_cap = _wallet_profile_float(wallet, "event_book", "planner_max_event_budget_usdc", 10.0)
        max_rebalance_reserve = _wallet_profile_float(
            wallet,
            "event_book",
            "planner_max_rebalance_reserve_usdc",
            min(reserve_cap, 5.0),
        )
        if source_wallet.lower() == RN1_WALLET and _event_sport_group(metadata) in RN1_FILTER_COPY_TENNIS_SPORTS | {"esports"}:
            base_event_cap = _wallet_profile_float(
                wallet,
                "event_book",
                "planner_rn1_tennis_esports_base_event_budget_usdc",
                min(base_event_cap, 5.0),
            )
            event_cap = _wallet_profile_float(
                wallet,
                "event_book",
                "planner_rn1_tennis_esports_max_event_budget_usdc",
                min(event_cap, 10.0),
            )
        if source_wallet.lower() == SWISSTONY_WALLET:
            base_event_cap = _wallet_profile_float(
                wallet,
                "event_book",
                "planner_swisstony_base_event_budget_usdc",
                3.0,
            )
            event_cap = _wallet_profile_float(
                wallet,
                "event_book",
                "planner_swisstony_max_event_budget_usdc",
                8.0,
            )
            max_rebalance_reserve = _wallet_profile_float(
                wallet,
                "event_book",
                "planner_swisstony_max_rebalance_reserve_usdc",
                2.0,
            )
        deployed = self._filter_copy_deployed_cap_usage_usdc(source_wallet)
        normal_remaining = max(0.0, normal_cap - min(deployed, normal_cap))
        reserve_remaining = max(0.0, total_cap - max(deployed, normal_cap))
        cash = max(0.0, self.broker.cash_usdc)
        available_normal = min(cash, normal_remaining)
        available_reserve = min(max(0.0, cash - available_normal), reserve_remaining, reserve_cap)
        return EventBookPlannerSettings(
            total_bankroll_usdc=total_cap,
            normal_capital_usdc=normal_cap,
            reserve_capital_usdc=reserve_cap,
            base_event_budget_usdc=base_event_cap,
            max_event_budget_usdc=min(event_cap, _filter_copy_event_book_max_event_exposure_usdc(wallet)),
            max_rebalance_reserve_usdc=max_rebalance_reserve,
            available_normal_cash_usdc=available_normal,
            available_reserve_cash_usdc=available_reserve,
            min_order_notional_usdc=self._minimum_buy_notional_usdc(),
            fresh_min_price=_wallet_profile_float(wallet, "event_book", "planner_fresh_min_price", 0.01),
            fresh_max_price=_wallet_profile_float(wallet, "event_book", "planner_fresh_max_price", 0.95),
            rebalance_min_price=_wallet_profile_float(wallet, "event_book", "planner_rebalance_min_price", 0.01),
            rebalance_max_price=_wallet_profile_float(wallet, "event_book", "planner_rebalance_max_price", 0.98),
            conviction_floor_source_notional_usdc=_filter_copy_min_cumulative_source_usdc(source_wallet, wallet, metadata),
            reserve_shape_improvement_fraction=_wallet_profile_float(
                wallet,
                "event_book",
                "planner_reserve_shape_improvement_fraction",
                0.20,
            ),
        )

    def _event_book_planner_leg_block_reason(
        self,
        *,
        source_wallet: str,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        has_local_event_exposure: bool,
        current_position: dict[str, Any],
        positive_positions: list[dict[str, Any]],
    ) -> str | None:
        paused_reason = _source_wallet_paused_sport_reason(source_wallet, metadata, wallet)
        if paused_reason is not None:
            return paused_reason
        sport = _event_sport_group(metadata)
        bet_type = _event_bet_type(metadata)
        if sport not in _filter_copy_allowed_sports(source_wallet, wallet):
            return "filter_copy_market_blocked"
        if source_wallet.lower() == RN1_WALLET:
            if not has_local_event_exposure:
                min_asset_source = _filter_copy_event_book_min_asset_source_notional(wallet)
                current_source_notional = float(current_position.get("net_notional_usdc") or 0)
                if min_asset_source > 0 and current_source_notional < min_asset_source:
                    return "event_book_waiting_for_source_position"
            if not has_local_event_exposure:
                max_fresh_legs = _wallet_profile_int(wallet, "event_book", "rn1_fresh_max_source_legs", 0)
                if max_fresh_legs > 0 and len(positive_positions) > max_fresh_legs:
                    return "rn1_event_book_too_complex"
            if bet_type == "map_or_game_winner":
                if "map_or_game_winner" not in _filter_copy_allowed_bet_types(wallet):
                    return "filter_copy_market_blocked"
                if (
                    sport != "esports"
                    or not _rn1_event_book_leg_is_dominant(
                        current_position,
                        _rn1_event_book_dominance_comparison_legs(metadata, current_position, positive_positions),
                        min_dominance_share=_rn1_filter_copy_event_book_min_dominance_share(
                            source_wallet,
                            metadata,
                            wallet,
                            has_event_exposure=has_local_event_exposure,
                        ),
                        min_dominance_ratio=_rn1_filter_copy_event_book_min_dominance_ratio(
                            source_wallet,
                            metadata,
                            wallet,
                            has_event_exposure=has_local_event_exposure,
                        ),
                    )
                ):
                    return "rn1_esports_map_not_extreme_dominant"
                return None
            if not _rn1_filter_copy_is_main_winner_market(metadata):
                return "filter_copy_market_blocked"
            if not has_local_event_exposure and not _rn1_event_book_leg_is_dominant(
                current_position,
                _rn1_event_book_dominance_comparison_legs(metadata, current_position, positive_positions),
                min_dominance_share=_rn1_filter_copy_event_book_min_dominance_share(
                    source_wallet,
                    metadata,
                    wallet,
                    has_event_exposure=False,
                ),
                min_dominance_ratio=_rn1_filter_copy_event_book_min_dominance_ratio(
                    source_wallet,
                    metadata,
                    wallet,
                    has_event_exposure=False,
                ),
            ):
                return "rn1_event_book_not_dominant"
        if source_wallet.lower() == SWISSTONY_WALLET:
            if bet_type == "moneyline_winlose":
                return None
            if has_local_event_exposure and bet_type == "draw":
                return None
            return "filter_copy_market_blocked"
        if bet_type in _filter_copy_allowed_bet_types(wallet):
            return None
        if has_local_event_exposure and _filter_copy_market_blocked_repair_candidate(source_wallet, metadata, wallet):
            return None
        return "filter_copy_market_blocked"

    def _event_book_order_source_trade(
        self,
        *,
        anchor_trade: SourceTrade,
        order: Any,
        metadata: dict[str, Any],
    ) -> SourceTrade:
        if order.asset_id == anchor_trade.asset_id:
            return anchor_trade
        latest_trade = self.store.latest_source_trade_for_asset(
            source_wallet=anchor_trade.source_wallet,
            asset_id=order.asset_id,
            anchor_trade=anchor_trade,
            side="buy",
        )
        if latest_trade is not None:
            return latest_trade
        return SourceTrade(
            idempotency_key=f"{anchor_trade.idempotency_key}:eventbook:{order.asset_id}",
            chain_id=anchor_trade.chain_id,
            exchange_contract=anchor_trade.exchange_contract,
            tx_hash=anchor_trade.tx_hash,
            block_number=anchor_trade.block_number,
            block_timestamp=anchor_trade.block_timestamp,
            log_index=anchor_trade.log_index,
            source_wallet=anchor_trade.source_wallet,
            side="buy",
            asset_id=order.asset_id,
            price=round(float(order.current_price), 6),
            quantity=round(float(order.quantity), 6),
            notional_usdc=round(float(order.notional_usdc), 6),
            condition_id=str(metadata.get("condition_id") or "") or None,
            market_id=str(metadata.get("market_id") or "") or None,
            outcome=str(metadata.get("outcome") or "") or None,
            copy_trade_key=f"event_book:{anchor_trade.idempotency_key}:{order.asset_id}",
        )

    def _event_book_plan_skip_reason(self, rejections: tuple[PlannerDecision, ...]) -> str:
        if not rejections:
            return "event_book_target_met"
        return f"event_book_{rejections[0].reason}"

    def _filter_copy_event_book_plan(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        source_position: dict[str, Any],
        source_reference_price: float,
        blocked_market_repair: bool = False,
    ) -> dict[str, Any] | None:
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return {"skip_reason": "rn1_event_book_required"} if _rn1_filter_copy_requires_event_book_dominance(trade.source_wallet, metadata) else None
        if trade.source_wallet.lower() not in {RN1_WALLET, SWISSTONY_WALLET}:
            return None

        event_positions = self.store.source_event_position_summaries(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            anchor_trade=trade,
        )
        event_positions = [
            self._source_event_position_with_snapshot_floor(trade.source_wallet, item)
            for item in event_positions
        ]
        positive_positions = [
            item for item in event_positions if float(item.get("net_notional_usdc") or 0) > 0
        ]
        if not positive_positions:
            return None
        current_position = next(
            (item for item in positive_positions if str(item.get("asset_id") or "") == trade.asset_id),
            None,
        )
        if current_position is None:
            return None
        if (
            trade.source_wallet.lower() == RN1_WALLET
            and _event_sport_group(metadata) in RN1_FILTER_COPY_TENNIS_SPORTS
            and int(current_position.get("buy_count") or source_position.get("buy_count") or 0) < RN1_FILTER_COPY_TENNIS_MIN_BUY_COUNT
        ):
            return {"skip_reason": "filter_copy_tennis_conviction_blocked"}

        total_source_notional = sum(float(item.get("net_notional_usdc") or 0) for item in positive_positions)
        min_event_source = _filter_copy_min_cumulative_source_usdc(trade.source_wallet, wallet, metadata)
        if total_source_notional < min_event_source:
            return {"skip_reason": "filter_copy_waiting_for_source_position"} if _rn1_filter_copy_requires_event_book_dominance(trade.source_wallet, metadata) else None

        current_source_notional = float(
            current_position.get("net_notional_usdc")
            or source_position.get("net_notional_usdc")
            or source_position.get("buy_notional_usdc")
            or 0
        )
        min_asset_source = _filter_copy_event_book_min_asset_source_notional(wallet)
        if current_source_notional < min_asset_source:
            return {"skip_reason": "filter_copy_waiting_for_source_position"} if _rn1_filter_copy_requires_event_book_dominance(trade.source_wallet, metadata) else None
        existing_position = self.broker.get_position(trade.asset_id, trade.source_wallet)
        same_event_positions = [
            position
            for position in self.store.list_positions()
            if str(position.get("source_wallet") or "").lower() == trade.source_wallet.lower()
            and str(position.get("event_slug") or "") == event_slug
            and float(position.get("quantity") or 0) > 0
        ]
        has_event_exposure = bool(same_event_positions)
        source_book_repair = _rn1_filter_copy_source_book_repair_allowed(
            trade.source_wallet,
            metadata,
            current_position,
            positive_positions,
            has_event_exposure=has_event_exposure,
        )
        if trade.source_wallet.lower() == RN1_WALLET:
            rn1_map_disabled = (
                _event_bet_type(metadata) == "map_or_game_winner"
                and "map_or_game_winner" not in _filter_copy_allowed_bet_types(wallet)
            )
            if rn1_map_disabled:
                return {"skip_reason": "filter_copy_market_blocked"}
            rn1_extreme_esports_map = (
                _event_sport_group(metadata) == "esports"
                and _event_bet_type(metadata) == "map_or_game_winner"
            )
            if not rn1_extreme_esports_map and not _rn1_filter_copy_is_main_winner_market(metadata):
                return {"skip_reason": "filter_copy_market_blocked"}
            if (
                not has_event_exposure
                and not rn1_extreme_esports_map
                and not _rn1_event_book_leg_is_dominant(
                    current_position,
                    _rn1_event_book_dominance_comparison_legs(metadata, current_position, positive_positions),
                    min_dominance_share=_rn1_filter_copy_event_book_min_dominance_share(
                        trade.source_wallet,
                        metadata,
                        wallet,
                        has_event_exposure=False,
                    ),
                    min_dominance_ratio=_rn1_filter_copy_event_book_min_dominance_ratio(
                        trade.source_wallet,
                        metadata,
                        wallet,
                        has_event_exposure=False,
                    ),
                )
            ):
                return {"skip_reason": "rn1_event_book_not_dominant"}
        if (
            _rn1_filter_copy_requires_event_book_dominance(trade.source_wallet, metadata)
            and not source_book_repair
            and not _rn1_event_book_leg_is_dominant(
                current_position,
                _rn1_event_book_dominance_comparison_legs(metadata, current_position, positive_positions),
                min_dominance_share=_rn1_filter_copy_event_book_min_dominance_share(
                    trade.source_wallet,
                    metadata,
                    wallet,
                    has_event_exposure=has_event_exposure,
                ),
                min_dominance_ratio=_rn1_filter_copy_event_book_min_dominance_ratio(
                    trade.source_wallet,
                    metadata,
                    wallet,
                    has_event_exposure=has_event_exposure,
                ),
            )
        ):
            return {"skip_reason": "rn1_event_book_not_dominant"}
        dominant_source_asset_id = str(
            max(
                positive_positions,
                key=lambda item: float(item.get("net_notional_usdc") or 0),
            ).get("asset_id")
            or ""
        )
        has_dominant_local_exposure = any(
            str(position.get("asset_id") or "") == dominant_source_asset_id for position in same_event_positions
        )
        if blocked_market_repair and not has_dominant_local_exposure:
            return {"skip_reason": "filter_copy_market_blocked"}
        target_asset_notional = self._filter_copy_event_book_target_asset_notional(
            source_wallet=trade.source_wallet,
            wallet=wallet,
            total_source_notional=total_source_notional,
            current_source_notional=current_source_notional,
        )
        if has_event_exposure and 0 < target_asset_notional < self._minimum_buy_notional_usdc():
            target_asset_notional = self._minimum_buy_notional_usdc()
        max_asset_notional = _filter_copy_scale_up_max_position_usdc(wallet)
        if max_asset_notional > 0:
            target_asset_notional = min(target_asset_notional, max_asset_notional)

        existing_cost = existing_position.cost_basis_usdc if existing_position is not None else 0.0
        notional = round(max(0.0, target_asset_notional - existing_cost), 6)
        if (
            trade.source_wallet.lower() == RN1_WALLET
            and has_event_exposure
            and (existing_position is None or existing_position.quantity <= 0)
        ):
            capped_notional = min(notional, _rn1_filter_copy_rebalance_max_order_usdc(wallet))
            notional = self._filter_copy_material_risk_reducing_repair_notional(
                same_event_positions=same_event_positions,
                asset_id=trade.asset_id,
                planned_notional=capped_notional,
                executable_price=source_reference_price,
                wallet=wallet,
            )
        if notional < self.config.sizing.min_trade_usdc:
            return {"skip_reason": "filter_copy_scale_target_met"}
        risk_reducing_repair = (
            False
            if source_book_repair
            else self._filter_copy_event_book_risk_reducing_repair_allowed(
                trade=trade,
                metadata=metadata,
                same_event_positions=same_event_positions,
                planned_notional=notional,
                source_reference_price=source_reference_price,
            )
        )
        if (
            existing_position is not None
            and not source_book_repair
            and not risk_reducing_repair
            and notional < _filter_copy_min_top_up_usdc(wallet)
        ):
            return {"skip_reason": "filter_copy_top_up_below_min"}

        return {
            "notional_usdc": notional,
            "target_asset_notional_usdc": target_asset_notional,
            "source_reference_price": float(source_reference_price),
            "is_repair": has_event_exposure,
            "risk_reducing_repair": risk_reducing_repair,
            "source_book_repair": source_book_repair,
            "same_event_positions": same_event_positions,
        }

    def _filter_copy_event_book_target_asset_notional(
        self,
        *,
        source_wallet: str,
        wallet: dict[str, Any],
        total_source_notional: float,
        current_source_notional: float,
    ) -> float:
        if total_source_notional <= 0 or current_source_notional <= 0:
            return 0.0
        event_cap = _filter_copy_event_book_max_event_exposure_usdc(wallet)
        copy_scale = _filter_copy_event_book_copy_scale(source_wallet, wallet)
        target_event_notional = total_source_notional * copy_scale
        if event_cap > 0:
            target_event_notional = min(target_event_notional, event_cap)
        return target_event_notional * current_source_notional / total_source_notional

    def _filter_copy_event_book_risk_reducing_repair_allowed(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        same_event_positions: list[dict[str, Any]],
        planned_notional: float,
        source_reference_price: float,
    ) -> bool:
        if trade.source_wallet.lower() not in {RN1_WALLET, SWISSTONY_WALLET}:
            return False
        if _event_bet_type(metadata) not in {"moneyline_winlose", "draw"}:
            return False
        if planned_notional <= 0 or source_reference_price <= 0:
            return False
        other_positions = [
            position
            for position in same_event_positions
            if str(position.get("asset_id") or "") != trade.asset_id
        ]
        if not other_positions:
            return False
        before_risk = _filter_copy_event_worst_case_loss(other_positions)
        repair_position = {
            "asset_id": trade.asset_id,
            "cost_basis_usdc": planned_notional,
            "quantity": planned_notional / source_reference_price,
        }
        after_risk = _filter_copy_event_worst_case_loss([*other_positions, repair_position])
        return after_risk < before_risk

    def _filter_copy_event_book_underweight_priority(
        self,
        *,
        source_wallet: str,
        wallet: dict[str, Any],
        item: dict[str, Any],
        total_source_notional: float,
    ) -> tuple[float, float]:
        asset_id = str(item.get("asset_id") or "")
        current_source_notional = float(item.get("net_notional_usdc") or 0)
        target = self._filter_copy_event_book_target_asset_notional(
            source_wallet=source_wallet,
            wallet=wallet,
            total_source_notional=total_source_notional,
            current_source_notional=current_source_notional,
        )
        if target <= 0:
            return (0.0, 0.0)
        existing_position = self.broker.get_position(asset_id, source_wallet)
        existing_cost = existing_position.cost_basis_usdc if existing_position is not None else 0.0
        deficit = max(0.0, target - existing_cost)
        return (deficit / target, deficit)

    def _process_filter_copy_event_book_buy(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        plan: dict[str, Any],
        reconcile: bool = True,
    ) -> str:
        skip_reason = str(plan.get("skip_reason") or "")
        if skip_reason:
            return self._record_skip(trade, skip_reason)
        if reconcile:
            self._reconcile_filter_copy_event_book(trade=trade, metadata=metadata, wallet=wallet)

        source_reference_price = float(plan.get("source_reference_price") or trade.price)
        price_block = _filter_copy_event_book_price_block_reason(
            trade.source_wallet,
            source_reference_price,
            wallet,
            metadata,
            is_repair=bool(plan.get("is_repair")),
        )
        risk_reducing_repair = bool(plan.get("risk_reducing_repair"))
        source_book_repair = bool(plan.get("source_book_repair"))
        bypass_repair_guard = risk_reducing_repair or source_book_repair
        if price_block is not None and not bypass_repair_guard:
            return self._record_skip(trade, price_block)
        if (
            price_block is not None
            and source_reference_price > _filter_copy_rn1_repair_max_local_price(wallet)
        ):
            return self._record_skip(trade, price_block)

        notional = float(plan.get("notional_usdc") or 0)
        daily_cap = _filter_copy_daily_deployed_cap_usdc(wallet)
        if daily_cap > 0 and not bool(plan.get("is_repair")):
            deployed = self._filter_copy_deployed_cap_usage_usdc(trade.source_wallet)
            if deployed + notional > daily_cap:
                return self._record_skip(trade, "filter_copy_daily_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        if notional > available_cash:
            if available_cash < self._minimum_buy_notional_usdc():
                return self._record_skip(trade, self._cash_skip_reason(available_cash))
            notional = round(available_cash, 6)

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        executable_price = observed_price or source_reference_price
        local_price_block = _filter_copy_event_book_price_block_reason(
            trade.source_wallet,
            executable_price * (1 + self.config.paper.slippage_pct / 100),
            wallet,
            metadata,
            is_repair=bool(plan.get("is_repair")),
            local=True,
        )
        if local_price_block is not None and not bypass_repair_guard:
            return self._record_skip(trade, local_price_block)
        if (
            local_price_block is not None
            and executable_price > _filter_copy_rn1_repair_max_local_price(wallet)
        ):
            return self._record_skip(trade, local_price_block)
        block_reason = self._buy_price_block_reason(executable_price, source_reference_price)
        if block_reason == "entry_price_at_one" or (block_reason is not None and not bypass_repair_guard):
            return self._record_skip(trade, block_reason)
        if risk_reducing_repair:
            notional = self._filter_copy_risk_reducing_repair_notional(
                same_event_positions=plan.get("same_event_positions"),
                asset_id=trade.asset_id,
                planned_notional=notional,
                executable_price=executable_price * (1 + self.config.paper.slippage_pct / 100),
            )
            if notional < self._minimum_buy_notional_usdc():
                if not source_book_repair:
                    return self._record_skip(trade, "filter_copy_repair_not_risk_reducing")
                notional = self._filter_copy_price_haircut_repair_notional(
                    planned_notional=float(plan.get("notional_usdc") or 0),
                    executable_price=executable_price * (1 + self.config.paper.slippage_pct / 100),
                    wallet=wallet,
                )
        elif source_book_repair and (price_block is not None or local_price_block is not None or block_reason is not None):
            notional = self._filter_copy_price_haircut_repair_notional(
                planned_notional=notional,
                executable_price=executable_price * (1 + self.config.paper.slippage_pct / 100),
                wallet=wallet,
            )
        if source_book_repair and notional < self._minimum_buy_notional_usdc():
            return self._record_skip(trade, "filter_copy_repair_below_min")

        try:
            self._execute_buy(trade, notional_usdc=round(notional, 6), observed_price=observed_price)
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        return "processed"

    def _reconcile_filter_copy_event_book(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
    ) -> int:
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return 0
        copied = 0
        event_positions = self.store.source_event_position_summaries(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            anchor_trade=trade,
        )
        event_positions = [
            self._source_event_position_with_snapshot_floor(trade.source_wallet, item)
            for item in event_positions
        ]
        positive_positions = [
            item for item in event_positions if float(item.get("net_notional_usdc") or 0) > 0
        ]
        total_source_notional = sum(float(item.get("net_notional_usdc") or 0) for item in positive_positions)
        if total_source_notional <= 0:
            return 0
        positive_positions.sort(
            key=lambda item: self._filter_copy_event_book_underweight_priority(
                source_wallet=trade.source_wallet,
                wallet=wallet,
                item=item,
                total_source_notional=total_source_notional,
            ),
            reverse=True,
        )
        for item in positive_positions:
            asset_id = str(item.get("asset_id") or "")
            if not asset_id or asset_id == trade.asset_id:
                continue
            source_trade = self.store.latest_source_trade_for_asset(
                source_wallet=trade.source_wallet,
                asset_id=asset_id,
                anchor_trade=trade,
                side="buy",
            )
            if (
                source_trade is None
                or self.store.has_executed_copy_trade(source_trade, source_wallet_scoped=True)
                or self.store.has_source_trade_attribution(source_trade.idempotency_key)
            ):
                continue
            asset_metadata = self._metadata_for(asset_id)
            paused_reason = _source_wallet_paused_sport_reason(trade.source_wallet, asset_metadata, wallet)
            if paused_reason is not None:
                self._record_skip(source_trade, paused_reason)
                continue
            market_block = _filter_copy_market_block_reason(trade.source_wallet, asset_metadata, wallet)
            if market_block is not None:
                if not _filter_copy_market_blocked_repair_candidate(trade.source_wallet, asset_metadata, wallet):
                    self._record_skip(source_trade, market_block)
                    continue
            source_position = item
            source_reference_price = _filter_copy_source_reference_price(source_position, fallback_price=source_trade.price)
            plan = self._filter_copy_event_book_plan(
                trade=source_trade,
                metadata=asset_metadata,
                wallet=wallet,
                source_position=source_position,
                source_reference_price=source_reference_price,
                blocked_market_repair=market_block is not None,
            )
            if plan is None:
                continue
            result = self._process_filter_copy_event_book_buy(
                trade=source_trade,
                metadata=asset_metadata,
                wallet=wallet,
                plan=plan,
                reconcile=False,
            )
            if result == "processed":
                copied += 1
        return copied

    def _reconcile_filter_copy_event(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
    ) -> int:
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return 0
        event_positions = self.store.source_event_position_summaries(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            anchor_trade=trade,
        )
        event_positions = [
            self._source_event_position_with_snapshot_floor(trade.source_wallet, item)
            for item in event_positions
        ]
        event_positions.sort(key=lambda item: float(item.get("net_notional_usdc") or 0), reverse=True)
        positive_positions = [item for item in event_positions if float(item.get("net_notional_usdc") or 0) > 0]
        if not positive_positions:
            return 0
        dominant_notional = float(positive_positions[0].get("net_notional_usdc") or 0)
        total_notional = sum(float(item.get("net_notional_usdc") or 0) for item in positive_positions)
        copied = 0
        for item in positive_positions:
            asset_id = str(item.get("asset_id") or "")
            if not asset_id or asset_id == trade.asset_id:
                continue
            candidate_notional = float(item.get("net_notional_usdc") or 0)
            candidate_share = candidate_notional / total_notional if total_notional > 0 else 0.0
            candidate_to_dominant = candidate_notional / dominant_notional if dominant_notional > 0 else 0.0
            if asset_id != str(positive_positions[0].get("asset_id") or "") and not (
                candidate_to_dominant >= FILTER_COPY_EVENT_BOOK_CO_DOMINANT_RATIO
                and candidate_share >= FILTER_COPY_EVENT_BOOK_CO_DOMINANT_SHARE
            ):
                continue
            source_trade = self.store.latest_source_trade_for_asset(
                source_wallet=trade.source_wallet,
                asset_id=asset_id,
                anchor_trade=trade,
                side="buy",
            )
            if (
                source_trade is None
                or self.store.has_executed_copy_trade(source_trade, source_wallet_scoped=True)
                or self.store.has_source_trade_attribution(source_trade.idempotency_key)
            ):
                continue
            if self.broker.get_position(asset_id, trade.source_wallet) is not None:
                continue
            asset_metadata = self._metadata_for(asset_id)
            market_block = _filter_copy_market_block_reason(trade.source_wallet, asset_metadata, wallet)
            if market_block is not None:
                self._record_skip(source_trade, market_block)
                continue
            min_cumulative = _filter_copy_min_cumulative_source_usdc(trade.source_wallet, wallet, asset_metadata)
            if candidate_notional < min_cumulative:
                self._record_skip(source_trade, "filter_copy_waiting_for_source_position")
                continue
            source_reference_price = _filter_copy_source_reference_price(item, fallback_price=source_trade.price)
            price_block = _filter_copy_source_price_block_reason(
                trade.source_wallet,
                source_reference_price,
                wallet,
                asset_metadata,
            )
            if price_block is not None:
                self._record_skip(source_trade, price_block)
                continue
            base_notional = _filter_copy_bet_size_usdc(trade.source_wallet, source_reference_price, wallet, asset_metadata)
            if base_notional <= 0:
                self._record_skip(source_trade, "filter_copy_price_tier_blocked")
                continue
            notional = self._filter_copy_target_notional(
                trade=source_trade,
                wallet=wallet,
                metadata=asset_metadata,
                base_notional=base_notional,
                min_cumulative=min_cumulative,
                source_notional=candidate_notional,
            )
            daily_cap = _filter_copy_daily_deployed_cap_usdc(wallet)
            if daily_cap > 0:
                deployed = self._filter_copy_deployed_cap_usage_usdc(trade.source_wallet)
                if deployed + notional > daily_cap:
                    self._record_skip(source_trade, "filter_copy_daily_cap")
                    continue
            available_cash = self._available_cash_for_wallet(trade.source_wallet)
            if notional > available_cash:
                self._record_skip(source_trade, self._cash_skip_reason(available_cash))
                continue
            observed_price = None
            if self.buy_price_resolver is not None:
                observed_price = self._resolve_buy_price(asset_id)
                if observed_price is None:
                    self._record_skip(source_trade, "price_unavailable")
                    continue
            block_reason = self._buy_price_block_reason(
                observed_price or source_reference_price,
                source_reference_price,
            )
            if block_reason is not None:
                self._record_skip(source_trade, "filter_copy_reconcile_price_blocked")
                continue
            try:
                self._execute_buy(source_trade, notional_usdc=round(notional, 6), observed_price=observed_price)
            except PaperExecutionError as exc:
                self._record_skip(source_trade, self._buy_execution_skip_reason(exc))
                continue
            copied += 1
        return copied

    def _filter_copy_same_event_repair_price_allowed(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        event_book_role: dict[str, Any],
        source_notional: float,
        source_reference_price: float,
    ) -> bool:
        if event_book_role.get("role") != "secondary":
            return False
        if not _filter_copy_rebalance_enabled(trade.source_wallet, wallet):
            return False
        if trade.source_wallet.lower() not in {RN1_WALLET, SWISSTONY_WALLET}:
            return False
        if _event_bet_type(metadata) != "moneyline_winlose":
            return False
        if _event_sport_group(metadata) not in _filter_copy_rebalance_allowed_sports(trade.source_wallet, wallet):
            return False
        min_source_notional = _filter_copy_rebalance_float(
            wallet,
            "min_source_notional_usdc",
            FILTER_COPY_REBALANCE_MIN_SOURCE_NOTIONAL_USDC,
        )
        if source_notional < min_source_notional:
            return False
        candidate_share = float(event_book_role.get("candidate_share") or 0)
        candidate_to_dominant = float(event_book_role.get("candidate_to_dominant") or 0)
        min_event_share = _filter_copy_rebalance_float(
            wallet,
            "min_event_share",
            FILTER_COPY_REBALANCE_MIN_EVENT_SHARE,
        )
        min_source_ratio = _filter_copy_same_event_hedge_max_fraction(wallet)
        max_source_price = _filter_copy_rebalance_float(
            wallet,
            "max_source_price",
            FILTER_COPY_REBALANCE_MAX_SOURCE_PRICE,
        )
        if (
            (candidate_share >= min_event_share or candidate_to_dominant >= min_source_ratio)
            and source_reference_price <= max_source_price
        ):
            return True
        strong_min_source = _filter_copy_rebalance_float(
            wallet,
            "strong_min_source_notional_usdc",
            FILTER_COPY_REBALANCE_STRONG_MIN_SOURCE_NOTIONAL_USDC,
        )
        strong_min_share = _filter_copy_rebalance_float(
            wallet,
            "strong_min_event_share",
            FILTER_COPY_REBALANCE_STRONG_MIN_EVENT_SHARE,
        )
        strong_max_source_price = _filter_copy_rebalance_float(
            wallet,
            "strong_max_source_price",
            FILTER_COPY_REBALANCE_STRONG_MAX_SOURCE_PRICE,
        )
        return (
            source_notional >= strong_min_source
            and candidate_share >= strong_min_share
            and source_reference_price <= strong_max_source_price
        )

    def _filter_copy_opposite_position_rank_flip_blocked(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        event_book_role: dict[str, Any],
    ) -> bool:
        if int(event_book_role.get("rank") or 0) != 1:
            return False
        candidate_share = _float_or_none(event_book_role.get("candidate_share"))
        if candidate_share is None or candidate_share >= FILTER_COPY_OPPOSITE_RANK_FLIP_MIN_DOMINANCE_SHARE:
            return False
        if self._opposite_condition_position(source_wallet=trade.source_wallet, asset_id=trade.asset_id) is not None:
            return True
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return False
        source_wallet = trade.source_wallet.lower()
        return any(
            str(position.get("source_wallet") or "").lower() == source_wallet
            and str(position.get("event_slug") or "") == event_slug
            and str(position.get("asset_id") or "") != trade.asset_id
            and float(position.get("quantity") or 0) > 0
            for position in self.store.list_positions()
        )

    def _filter_copy_scale_up_notional(
        self,
        *,
        trade: SourceTrade,
        wallet: dict[str, Any],
        metadata: dict[str, Any],
        base_notional: float,
        min_cumulative: float,
        source_notional: float | None = None,
        existing_cost: float,
    ) -> float:
        target_notional = self._filter_copy_target_notional(
            trade=trade,
            wallet=wallet,
            metadata=metadata,
            base_notional=base_notional,
            min_cumulative=min_cumulative,
            source_notional=source_notional,
        )
        return round(max(0.0, target_notional - existing_cost), 6)

    def _filter_copy_target_notional(
        self,
        *,
        trade: SourceTrade,
        wallet: dict[str, Any],
        metadata: dict[str, Any],
        base_notional: float,
        min_cumulative: float,
        source_notional: float | None = None,
    ) -> float:
        if base_notional <= 0:
            return 0.0
        target_notional = base_notional
        if _filter_copy_scale_up_enabled(wallet) and min_cumulative > 0:
            full_source_notional = source_notional
            if full_source_notional is None:
                full_source_position = self.store.source_position_summary(
                    source_wallet=trade.source_wallet,
                    asset_id=trade.asset_id,
                    anchor_trade=trade,
                    window_seconds=0,
                )
                full_source_notional = float(
                    full_source_position.get("net_notional_usdc") or full_source_position.get("buy_notional_usdc") or 0
                )
            if trade.source_wallet.lower() == RN1_WALLET:
                conviction_ratio = max(1.0, float(full_source_notional or 0) / min_cumulative)
                raw_target = base_notional * math.sqrt(conviction_ratio)
                target_notional = _round_up_to_increment(
                    raw_target,
                    _filter_copy_scale_up_increment_usdc(trade.source_wallet, metadata, base_notional),
                )
            elif trade.source_wallet.lower() == SWISSTONY_WALLET:
                target_notional = base_notional
            else:
                conviction_steps = max(1, int(float(full_source_notional or 0) // min_cumulative))
                target_notional = base_notional * conviction_steps
        max_position = _filter_copy_target_max_position_usdc(
            source_wallet=trade.source_wallet,
            wallet=wallet,
            metadata=metadata,
            base_notional=base_notional,
        )
        if max_position > 0:
            target_notional = min(target_notional, max_position)
        return round(max(0.0, target_notional), 6)

    def _filter_copy_same_event_hedge_notional(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        source_notional: float,
        max_fraction: float | None = None,
        required_source_asset_id: str | None = None,
    ) -> float | None:
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return None
        required_source_asset_id = str(required_source_asset_id or "").strip()
        same_event_positions = [
            position
            for position in self.store.list_positions()
            if str(position.get("source_wallet") or "").lower() == trade.source_wallet.lower()
            and str(position.get("event_slug") or "") == event_slug
            and str(position.get("asset_id") or "") != trade.asset_id
            and (not required_source_asset_id or str(position.get("asset_id") or "") == required_source_asset_id)
            and float(position.get("quantity") or 0) > 0
        ]
        if not same_event_positions:
            return None

        local_event_cost = sum(float(position.get("cost_basis_usdc") or 0) for position in same_event_positions)
        if local_event_cost <= 0:
            return None

        source_existing_notional = 0.0
        for position in same_event_positions:
            summary = self.store.source_position_summary(
                source_wallet=trade.source_wallet,
                asset_id=str(position.get("asset_id") or ""),
                anchor_trade=trade,
                window_seconds=0,
            )
            summary = self._source_position_with_snapshot_floor(
                source_wallet=trade.source_wallet,
                asset_id=str(position.get("asset_id") or ""),
                position=summary,
            )
            source_existing_notional += float(
                summary.get("net_notional_usdc") or summary.get("buy_notional_usdc") or 0
            )

        hedge_max_fraction = (
            _filter_copy_same_event_hedge_max_fraction(wallet) if max_fraction is None else float(max_fraction)
        )
        if hedge_max_fraction <= 0:
            return 0.0
        source_ratio = source_notional / source_existing_notional if source_existing_notional > 0 else hedge_max_fraction
        hedge_fraction = min(hedge_max_fraction, max(0.0, source_ratio))
        return round(local_event_cost * hedge_fraction, 6)

    def _filter_copy_rebalance_plan(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        event_book_role: dict[str, Any],
        source_notional: float,
        source_reference_price: float,
    ) -> dict[str, float] | None:
        if not _filter_copy_rebalance_enabled(trade.source_wallet, wallet):
            return None
        if trade.source_wallet.lower() not in {RN1_WALLET, SWISSTONY_WALLET}:
            return None
        if _event_bet_type(metadata) != "moneyline_winlose":
            return None
        if _event_sport_group(metadata) not in _filter_copy_rebalance_allowed_sports(trade.source_wallet, wallet):
            return None
        if int(event_book_role.get("rank") or 0) != 1:
            return None
        if source_reference_price <= 0:
            return None

        min_source_notional = _filter_copy_rebalance_float(
            wallet,
            "min_source_notional_usdc",
            FILTER_COPY_REBALANCE_MIN_SOURCE_NOTIONAL_USDC,
        )
        if source_notional < min_source_notional:
            return None

        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return None
        same_event_positions = [
            position
            for position in self.store.list_positions()
            if str(position.get("source_wallet") or "").lower() == trade.source_wallet.lower()
            and str(position.get("event_slug") or "") == event_slug
            and str(position.get("asset_id") or "") != trade.asset_id
            and float(position.get("quantity") or 0) > 0
        ]
        if not same_event_positions:
            return None

        existing_source_notional = 0.0
        for position in same_event_positions:
            summary = self.store.source_position_summary(
                source_wallet=trade.source_wallet,
                asset_id=str(position.get("asset_id") or ""),
                anchor_trade=trade,
                window_seconds=0,
            )
            summary = self._source_position_with_snapshot_floor(
                source_wallet=trade.source_wallet,
                asset_id=str(position.get("asset_id") or ""),
                position=summary,
            )
            existing_source_notional = max(
                existing_source_notional,
                float(summary.get("net_notional_usdc") or summary.get("buy_notional_usdc") or 0),
            )
        min_repair_ratio = _filter_copy_rebalance_float(
            wallet,
            "min_repair_to_existing_source_ratio",
            FILTER_COPY_REBALANCE_MIN_REPAIR_RATIO,
        )
        if existing_source_notional <= 0 or source_notional / existing_source_notional < min_repair_ratio:
            return None

        candidate_share = float(event_book_role.get("candidate_share") or 0)
        if candidate_share <= 0 and int(event_book_role.get("rank") or 0) == 1:
            candidate_share = 1.0
        min_event_share = _filter_copy_rebalance_float(
            wallet,
            "min_event_share",
            FILTER_COPY_REBALANCE_MIN_EVENT_SHARE,
        )
        strong_min_source = _filter_copy_rebalance_float(
            wallet,
            "strong_min_source_notional_usdc",
            FILTER_COPY_REBALANCE_STRONG_MIN_SOURCE_NOTIONAL_USDC,
        )
        strong_min_share = _filter_copy_rebalance_float(
            wallet,
            "strong_min_event_share",
            FILTER_COPY_REBALANCE_STRONG_MIN_EVENT_SHARE,
        )
        max_source_price = _filter_copy_rebalance_float(
            wallet,
            "max_source_price",
            FILTER_COPY_REBALANCE_MAX_SOURCE_PRICE,
        )
        strong_max_source_price = _filter_copy_rebalance_float(
            wallet,
            "strong_max_source_price",
            FILTER_COPY_REBALANCE_STRONG_MAX_SOURCE_PRICE,
        )
        normal_price_allowed = candidate_share >= min_event_share and source_reference_price <= max_source_price
        strong_price_allowed = (
            source_notional >= strong_min_source
            and candidate_share >= strong_min_share
            and source_reference_price <= strong_max_source_price
        )
        if not (normal_price_allowed or strong_price_allowed):
            return None

        notional = _filter_copy_rebalance_float(
            wallet,
            "max_repair_buy_usdc",
            FILTER_COPY_SWISSTONY_REBALANCE_MAX_REPAIR_BUY_USDC
            if trade.source_wallet.lower() == SWISSTONY_WALLET
            else FILTER_COPY_REBALANCE_MAX_REPAIR_BUY_USDC,
        )
        if trade.source_wallet.lower() == RN1_WALLET:
            notional = min(notional, _rn1_filter_copy_rebalance_max_order_usdc(wallet))
        if notional < self.config.sizing.min_trade_usdc:
            return None

        before_risk = _filter_copy_event_worst_case_loss(same_event_positions)
        repair_position = {
            "asset_id": trade.asset_id,
            "cost_basis_usdc": notional,
            "quantity": notional / source_reference_price,
        }
        after_risk = _filter_copy_event_worst_case_loss([*same_event_positions, repair_position])
        if after_risk >= before_risk:
            return None
        if trade.source_wallet.lower() == RN1_WALLET:
            min_improvement = _filter_copy_rebalance_min_worst_case_improvement_fraction(wallet)
            if after_risk > before_risk * (1.0 - min_improvement) + 0.000001:
                return None

        event_risk_cap = _filter_copy_rebalance_float(
            wallet,
            "normal_event_cap_usdc",
            FILTER_COPY_REBALANCE_NORMAL_EVENT_CAP_USDC,
        ) + _filter_copy_rebalance_float(
            wallet,
            "extra_repair_event_cap_usdc",
            FILTER_COPY_REBALANCE_EXTRA_EVENT_CAP_USDC,
        )
        if event_risk_cap > 0 and after_risk > event_risk_cap:
            return None
        return {"notional_usdc": round(notional, 6)}

    def _filter_copy_source_event_book_role(
        self,
        *,
        trade: SourceTrade,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return {"role": "standalone"}
        event_positions = self.store.source_event_position_summaries(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            anchor_trade=trade,
        )
        event_positions = [
            self._source_event_position_with_snapshot_floor(trade.source_wallet, item)
            for item in event_positions
        ]
        event_positions.sort(key=lambda item: float(item.get("net_notional_usdc") or 0), reverse=True)
        positive_positions = [item for item in event_positions if float(item.get("net_notional_usdc") or 0) > 0]
        if not positive_positions:
            return {"role": "standalone"}
        candidate = next((item for item in positive_positions if str(item.get("asset_id") or "") == trade.asset_id), None)
        if candidate is None:
            return {"role": "standalone"}
        if len(positive_positions) == 1:
            return {
                "role": "dominant",
                "dominant_asset_id": trade.asset_id,
                "candidate_notional_usdc": float(candidate.get("net_notional_usdc") or 0),
                "rank": 1,
            }

        dominant = positive_positions[0]
        dominant_asset_id = str(dominant.get("asset_id") or "")
        dominant_notional = float(dominant.get("net_notional_usdc") or 0)
        candidate_notional = float(candidate.get("net_notional_usdc") or 0)
        candidate_rank = next(
            (
                index + 1
                for index, item in enumerate(positive_positions)
                if str(item.get("asset_id") or "") == trade.asset_id
            ),
            0,
        )
        total_notional = sum(float(item.get("net_notional_usdc") or 0) for item in positive_positions)
        candidate_share = candidate_notional / total_notional if total_notional > 0 else 0.0
        candidate_to_dominant = candidate_notional / dominant_notional if dominant_notional > 0 else 0.0
        if dominant_asset_id == trade.asset_id or (
            candidate_to_dominant >= FILTER_COPY_EVENT_BOOK_CO_DOMINANT_RATIO
            and candidate_share >= FILTER_COPY_EVENT_BOOK_CO_DOMINANT_SHARE
        ):
            return {
                "role": "dominant",
                "dominant_asset_id": trade.asset_id,
                "candidate_notional_usdc": candidate_notional,
                "candidate_share": candidate_share,
                "candidate_to_dominant": candidate_to_dominant,
                "rank": candidate_rank,
            }
        return {
            "role": "secondary",
            "dominant_asset_id": dominant_asset_id,
            "dominant_notional_usdc": dominant_notional,
            "candidate_notional_usdc": candidate_notional,
            "candidate_share": candidate_share,
            "candidate_to_dominant": candidate_to_dominant,
            "rank": candidate_rank,
        }

    def _source_event_position_with_snapshot_floor(self, source_wallet: str, item: dict[str, Any]) -> dict[str, Any]:
        return self._source_position_with_snapshot_floor(
            source_wallet=source_wallet,
            asset_id=str(item.get("asset_id") or ""),
            position=item,
        )

    def _source_position_with_snapshot_floor(
        self,
        *,
        source_wallet: str,
        asset_id: str,
        position: dict[str, Any],
    ) -> dict[str, Any]:
        if self.source_position_resolver is None:
            return position
        clean_asset = str(asset_id or "").strip()
        if not clean_asset:
            return position
        try:
            snapshot = self.source_position_resolver(source_wallet, clean_asset)
        except Exception:
            return position
        if not isinstance(snapshot, dict):
            return position

        snapshot_notional = _snapshot_source_notional_usdc(snapshot)
        current_notional = float(position.get("net_notional_usdc") or position.get("buy_notional_usdc") or 0)
        if snapshot_notional <= current_notional:
            return position

        merged = dict(position)
        merged["net_notional_usdc"] = round(snapshot_notional, 6)
        merged["buy_notional_usdc"] = round(max(float(merged.get("buy_notional_usdc") or 0), snapshot_notional), 6)
        snapshot_avg_price = _float_or_none(snapshot.get("avg_buy_price") or snapshot.get("avg_price") or snapshot.get("avgPrice"))
        if snapshot_avg_price is not None and snapshot_avg_price > 0:
            merged["avg_buy_price"] = round(snapshot_avg_price, 6)
        snapshot_quantity = _float_or_none(snapshot.get("net_quantity") or snapshot.get("quantity") or snapshot.get("size"))
        if snapshot_quantity is not None and snapshot_quantity > float(merged.get("net_quantity") or 0):
            merged["net_quantity"] = round(snapshot_quantity, 6)
        merged["source_position_snapshot_usdc"] = round(snapshot_notional, 6)
        merged["source_position_snapshot_source"] = str(snapshot.get("source") or "source_position_snapshot")
        return merged

    def _resolve_buy_price(self, asset_id: str) -> float | None:
        if self.buy_price_resolver is None:
            raise RuntimeError("buy price resolver is not configured")
        price = self.buy_price_resolver(asset_id)
        if price is None or price <= 0:
            return None
        return price

    def _process_sell(self, trade: SourceTrade, *, close_reason: str) -> str:
        metadata = self._metadata_for(trade.asset_id)
        wallet = self.store.get_wallet(trade.source_wallet) or {}
        if (
            close_reason == "source_sell"
            and self._market_type_from_metadata(metadata) == "weather"
            and _weather_bracket_strategy_enabled(wallet)
            and metadata.get("event_slug")
        ):
            return self._record_skip(trade, "weather_bracket_hold_to_resolution")
        position = self.broker.get_position(trade.asset_id, trade.source_wallet)
        if position is None or position.quantity <= 0:
            return self._record_skip(trade, "no_position_to_sell")
        wallet = self.store.get_wallet(trade.source_wallet) or {}
        if close_reason == "source_sell" and _filter_copy_enabled(trade.source_wallet, wallet):
            sell_fraction = self._filter_copy_source_sell_fraction(trade)
            if sell_fraction <= _filter_copy_source_sell_exit_fraction(wallet):
                return self._record_skip(trade, "filter_copy_source_trim_ignored")
            sell_quantity = min(position.quantity, position.quantity * sell_fraction)
        else:
            sell_quantity = self._copy_sell_quantity(trade, position.quantity)
        if self.config.mode.trading_mode == "live":
            if self._active_live_sell_intent_exists(asset_id=trade.asset_id, source_wallet=trade.source_wallet):
                return self._record_skip(trade, "live_sell_intent_exists")
            if self._create_live_sell_order_intent(
                trade,
                quantity=sell_quantity,
                price=trade.price,
                close_reason=close_reason,
            ):
                return "processed"
            return self._record_skip(trade, "sell_execution_failed")
        try:
            fill = self.broker.sell(
                trade,
                quantity=sell_quantity,
                close_reason=close_reason,
            )
        except PaperExecutionError:
            return self._record_skip(trade, "sell_execution_failed")
        position = self.broker.get_position(trade.asset_id, trade.source_wallet)
        if position is None:
            return self._record_skip(trade, "sell_execution_failed")
        paper_trade_id = self.store.record_paper_fill(
            fill,
            cash_after_usdc=self.broker.cash_usdc,
            position_quantity=position.quantity,
            avg_entry_price=position.average_entry_price,
        )
        self.store.record_copy_attribution(trade, executed=True, paper_trade_id=paper_trade_id)
        return "processed"

    def _create_live_sell_order_intent(
        self,
        trade: SourceTrade,
        *,
        quantity: float,
        price: float,
        close_reason: str,
    ) -> bool:
        clean_quantity = round(float(quantity), 6)
        clean_price = round(float(price), 6)
        if clean_quantity <= 0 or clean_price <= 0:
            return False
        self.store.create_live_order_intent(
            source_trade=trade,
            side="sell",
            price=clean_price,
            size=clean_quantity,
            notional_usdc=round(clean_quantity * clean_price, 6),
            status="planned",
        )
        self.store.record_copy_attribution(trade, executed=True, paper_trade_id=None)
        return True

    def _active_live_sell_intent_exists(self, *, asset_id: str, source_wallet: str) -> bool:
        return (
            self.store.get_live_order_intent_for_position(
                asset_id=asset_id,
                source_wallet=source_wallet,
                side="sell",
            )
            is not None
        )

    def _record_skip(self, trade: SourceTrade, reason: str) -> str:
        self.store.record_copy_attribution(trade, executed=False, paper_trade_id=None, skip_reason=reason)
        return "skipped"

    def _minimum_buy_notional_usdc(self) -> float:
        return max(POLYMARKET_MIN_BUY_NOTIONAL_USDC, float(self.config.sizing.min_trade_usdc))

    def _buy_execution_skip_reason(self, exc: PaperExecutionError) -> str:
        reason = str(exc)
        if reason == BUY_BELOW_MIN_NOTIONAL_SKIP:
            return BUY_BELOW_MIN_NOTIONAL_SKIP
        return "buy_execution_failed"

    def _execute_buy(
        self,
        trade: SourceTrade,
        *,
        notional_usdc: float,
        observed_price: float | None,
    ) -> tuple[int | None, float]:
        clean_notional = round(float(notional_usdc), 6)
        if clean_notional < self._minimum_buy_notional_usdc():
            raise PaperExecutionError(BUY_BELOW_MIN_NOTIONAL_SKIP)
        executable_price = observed_price if observed_price is not None else trade.price
        if self.config.mode.trading_mode == "live":
            intent = self.store.create_live_order_intent(
                source_trade=trade,
                side="buy",
                price=round(executable_price, 6),
                size=round(clean_notional / executable_price, 6),
                notional_usdc=clean_notional,
                status="planned",
            )
            self.store.record_copy_attribution(trade, executed=True, paper_trade_id=None)
            return int(intent["id"]), clean_notional

        fill = self.broker.buy(trade, notional_usdc=clean_notional, observed_price=observed_price)
        position = self.broker.get_position(trade.asset_id, trade.source_wallet)
        if position is None:
            raise PaperExecutionError("buy_execution_failed")
        paper_trade_id = self.store.record_paper_fill(
            fill,
            cash_after_usdc=self.broker.cash_usdc,
            position_quantity=position.quantity,
            avg_entry_price=position.average_entry_price,
        )
        self.store.record_live_shadow_audit(
            source_trade=trade,
            paper_trade_id=paper_trade_id,
            side="buy",
            paper_entry_price=fill.fill_price,
            best_ask_at_decision=observed_price,
            order_price=executable_price,
            requested_notional_usdc=fill.notional_usdc,
            requested_size=round(float(fill.notional_usdc) / executable_price, 6),
            decision_latency_ms=_decision_latency_ms(trade.block_timestamp),
            notes="orderbook_depth_unavailable",
        )
        self.store.record_copy_attribution(trade, executed=True, paper_trade_id=paper_trade_id)
        return paper_trade_id, fill.notional_usdc

    def _market_type_for(self, asset_id: str) -> str:
        return self._market_type_from_metadata(self._metadata_for(asset_id))

    def _metadata_for(self, asset_id: str) -> dict[str, Any]:
        metadata = self.store.get_market_metadata(asset_id)
        if (
            not metadata
            or not metadata.get("market_type")
            or (metadata.get("market_type") == "weather" and not metadata.get("event_slug"))
            or _metadata_missing_structured_sports_fields(metadata)
        ) and self.market_metadata_resolver is not None:
            metadata = self._resolve_market_metadata(asset_id) or metadata
        return metadata or {}

    def _market_type_from_metadata(self, metadata: dict[str, Any]) -> str:
        market_type = str((metadata or {}).get("market_type") or "other").lower()
        return market_type if market_type in {"crypto", "weather", "sports", "other"} else "other"

    def _resolve_market_metadata(self, asset_id: str) -> dict[str, Any] | None:
        if self.market_metadata_resolver is None:
            return None
        metadata = self.market_metadata_resolver(asset_id)
        if not metadata:
            return None
        self.store.upsert_market_metadata(asset_id=asset_id, **_store_market_metadata(metadata))
        return self.store.get_market_metadata(asset_id)

    def _market_type_allowed(self, source_wallet: str, market_type: str) -> bool:
        if market_type not in self.config.market_filters.enabled_market_types:
            return False
        wallet = self.store.get_wallet(source_wallet)
        legacy_allowed = wallet.get("allowed_market_types", []) if wallet else []
        allowed = _wallet_profile_list(wallet, "market_filters", "allowed_market_types", legacy_allowed, lower=True)
        return market_type in allowed

    def _copy_sell_quantity(self, trade: SourceTrade, position_quantity: float) -> float:
        if trade.idempotency_key.startswith("local:"):
            return min(trade.quantity, position_quantity)
        source_inventory = self.store.source_inventory_quantity_before(trade)
        if source_inventory <= 0:
            return min(trade.quantity, position_quantity)
        sell_fraction = min(1.0, max(0.0, trade.quantity / source_inventory))
        return min(position_quantity, position_quantity * sell_fraction)

    def _filter_copy_source_sell_fraction(self, trade: SourceTrade) -> float:
        if trade.idempotency_key.startswith("local:"):
            return 1.0
        source_inventory = self.store.source_inventory_quantity_before(trade)
        if source_inventory <= 0:
            return 1.0
        return min(1.0, max(0.0, trade.quantity / source_inventory))

    def _process_weather_bracket_buy(
        self,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str:
        event_slug = str(metadata["event_slug"])
        pattern = _weather_bracket_pattern(metadata)
        allowed_patterns = set(
            _wallet_profile_list(
                wallet,
                "weather_bracket",
                "allowed_patterns",
                wallet.get("bracket_allowed_patterns", []),
                lower=True,
            )
        )
        if allowed_patterns and pattern not in allowed_patterns:
            return self._record_skip(trade, "weather_bracket_pattern_blocked")

        if _custom_strategy_enabled(wallet):
            min_source_trade = _wallet_float(wallet, "event_follow_min_source_trade_usdc", 0.0)
            if min_source_trade > 0 and trade.notional_usdc < min_source_trade:
                return self._record_skip(trade, "weather_bracket_source_trade_too_small")

            min_price = _wallet_float(wallet, "event_follow_min_avg_price", 0.01)
            max_price = _wallet_float(wallet, "event_follow_max_avg_price", 1.0)
            if trade.price < min_price or trade.price > max_price:
                return self._record_skip(trade, "weather_bracket_price_band_blocked")

        event_cap = _wallet_int(wallet, "bracket_max_open_events", 0)
        if (
            event_cap > 0
            and not self.store.has_open_weather_event(trade.source_wallet, event_slug)
            and self.store.count_open_weather_events(trade.source_wallet) >= event_cap
        ):
            return self._record_skip(trade, "weather_bracket_event_cap")

        bracket = self.store.record_weather_bracket_source_buy(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            event_title=str(metadata.get("event_title") or metadata.get("title") or ""),
            trade=trade,
            market_slug=str(metadata.get("market_slug") or ""),
            title=str(metadata.get("title") or ""),
            event_budget_usdc=_wallet_float(wallet, "bracket_buy_size_usdc", 10.0),
        )
        delta = self._weather_bracket_delta_usdc(trade, bracket, wallet)
        if delta < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "weather_bracket_waiting_for_threshold")
        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        notional = min(delta, available_cash)
        if notional < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        block_reason = self._buy_price_block_reason(observed_price or trade.price, trade.price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)

        try:
            _execution_id, executed_notional = self._execute_buy(
                trade,
                notional_usdc=round(notional, 6),
                observed_price=observed_price,
            )
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        self.store.record_weather_bracket_copied_buy(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            asset_id=trade.asset_id,
            copied_notional_usdc=executed_notional,
        )
        return "processed"

    def _weather_bracket_delta_usdc(
        self,
        trade: SourceTrade,
        bracket: dict[str, Any],
        wallet: dict[str, Any],
    ) -> float:
        copied = float(bracket["leg_copied_notional_usdc"] or 0)
        wallet_name = str(wallet.get("name") or "").strip().lower()
        legacy_vip68_copy_source_leg = (
            _custom_strategy_enabled(wallet)
            and (trade.source_wallet.lower() == VIP68_WALLET or wallet_name == "vip68")
        )
        if _wallet_profile_bool(wallet, "weather_bracket", "copy_source_leg_size", legacy_vip68_copy_source_leg):
            source_leg_notional = float(bracket["leg_source_notional_usdc"] or 0)
            target = min(source_leg_notional, _wallet_float(wallet, "bracket_buy_size_usdc", 5.0))
            return target - copied
        return float(bracket["leg_target_notional_usdc"] or 0) - copied

    def _process_repeat_buy(
        self,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str:
        signal = self.store.record_repeat_buy_source_buy(
            source_wallet=trade.source_wallet,
            trade=trade,
            market_id=str(metadata.get("market_id") or trade.market_id or ""),
            title=str(metadata.get("title") or ""),
            outcome=str(metadata.get("outcome") or trade.outcome or ""),
        )
        if self._repeat_buy_market_blocked(metadata, wallet) and not _rn1_high_conviction_filter_override(trade, metadata, signal, wallet):
            return self._record_skip(trade, "repeat_buy_market_filter_blocked")
        event_slug = str(metadata.get("event_slug") or "").strip()
        event_signal = None
        if event_slug and self._market_type_from_metadata(metadata) in {"sports", "other"}:
            event_signal = self.store.record_event_follow_source_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                event_title=str(metadata.get("event_title") or metadata.get("title") or ""),
                market_type=self._market_type_from_metadata(metadata),
                trade=trade,
                market_slug=str(metadata.get("market_slug") or ""),
                title=str(metadata.get("title") or ""),
            )
        rn1_esports_block = _rn1_esports_repeat_buy_block_reason(trade, metadata, signal, wallet)
        if rn1_esports_block:
            return self._record_skip(trade, rn1_esports_block)
        rn1_event_book_block = self._rn1_event_book_block_reason(trade, metadata, signal, wallet)
        if rn1_event_book_block:
            return self._record_skip(trade, rn1_event_book_block)
        if event_signal is not None and trade.source_wallet.lower() != RN1_WALLET:
            bracket_result = self._process_sports_bracket_buy(
                trade,
                event_slug,
                event_signal,
                wallet,
                target_notional_func=self._generic_sports_bracket_target_notional,
            )
            if bracket_result == "processed":
                return bracket_result
        if signal["copied"] and not _rn1_source_follow_enabled(trade.source_wallet, wallet):
            return self._record_skip(trade, "repeat_buy_already_copied")
        if int(signal["buy_count"]) < _wallet_int(wallet, "repeat_buy_min_buy_count", 2):
            return self._record_skip(trade, "repeat_buy_waiting_for_second_buy")
        repeat_buy_min_source_notional = _wallet_float(wallet, "repeat_buy_min_source_notional_usdc", 0.0)
        if float(signal["source_notional_usdc"] or 0) < repeat_buy_min_source_notional:
            return self._record_skip(trade, "repeat_buy_waiting_for_source_notional")

        source_avg_price = _signal_avg_price(signal)
        min_avg_price = _wallet_float(wallet, "repeat_buy_min_avg_price", 0.01)
        max_avg_price = _wallet_float(wallet, "repeat_buy_max_avg_price", 1.0)
        if source_avg_price < min_avg_price or source_avg_price > max_avg_price:
            return self._record_skip(trade, "repeat_buy_price_band_blocked")
        opposing_leg = self.store.strongest_opposing_event_follow_leg(
            source_wallet=trade.source_wallet,
            event_slug=str(metadata.get("event_slug") or ""),
            title=str(metadata.get("title") or ""),
            asset_id=trade.asset_id,
            min_source_notional_usdc=max(
                repeat_buy_min_source_notional,
                float(signal["source_notional_usdc"] or 0),
            ),
        )
        if opposing_leg is not None:
            return self._record_skip(trade, "repeat_buy_conflicting_event_follow")
        if _rn1_source_follow_enabled(trade.source_wallet, wallet):
            return self._process_source_follow_buy(
                trade,
                source_notional_usdc=float(signal.get("source_notional_usdc") or 0),
                source_reference_price=source_avg_price if source_avg_price > 0 else trade.price,
                copy_scale=_wallet_profile_float(wallet, "source_follow", "copy_scale", RN1_SOURCE_FOLLOW_COPY_SCALE),
                max_asset_exposure_usdc=_wallet_profile_float(
                    wallet,
                    "source_follow",
                    "max_asset_exposure_usdc",
                    RN1_SOURCE_FOLLOW_MAX_ASSET_EXPOSURE_USDC,
                ),
                max_total_exposure_usdc=_wallet_float(wallet, "repeat_buy_max_total_exposure_usdc", 0.0),
                min_trade_usdc=_wallet_profile_float(wallet, "source_follow", "min_trade_usdc", 1.0),
                repeat_asset_id=trade.asset_id,
                event_slug=event_slug if event_signal is not None else None,
            )

        max_total = _wallet_float(wallet, "repeat_buy_max_total_exposure_usdc", 0.0)
        total_remaining = max_total - self.store.open_cost_basis_for_wallet(trade.source_wallet) if max_total > 0 else None
        if total_remaining is not None and total_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "repeat_buy_total_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        notional = min(_wallet_float(wallet, "repeat_buy_size_usdc", 5.0), available_cash)
        if total_remaining is not None:
            notional = min(notional, total_remaining)
        if notional < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        block_reason = self._buy_price_block_reason(observed_price or trade.price, source_avg_price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)
        notional = self._binary_hedge_adjusted_notional(
            trade=trade,
            observed_price=observed_price or trade.price,
            target_notional=notional,
            wallet=wallet,
        )
        if notional < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "binary_hedge_target_below_min")

        try:
            execution_id, executed_notional = self._execute_buy(
                trade,
                notional_usdc=round(notional, 6),
                observed_price=observed_price,
            )
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        self.store.record_repeat_buy_copied(
            source_wallet=trade.source_wallet,
            asset_id=trade.asset_id,
            paper_trade_id=execution_id or 0,
            copied_notional_usdc=executed_notional,
        )
        if event_signal is not None:
            self.store.record_event_follow_copied_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                asset_id=trade.asset_id,
                copied_notional_usdc=executed_notional,
            )
        return "processed"

    def _process_event_follow_buy(
        self,
        trade: SourceTrade,
        metadata: dict[str, Any],
        wallet: dict[str, Any],
        market_type: str,
    ) -> str:
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return self._record_skip(trade, "event_follow_missing_event")
        if trade.source_wallet.lower() == RN1_WALLET and not _rn1_event_follow_market_allowed(metadata, wallet):
            return self._record_skip(trade, "rn1_market_filter_blocked")
        if self._event_follow_market_blocked(metadata, wallet):
            return self._record_skip(trade, "event_follow_market_filter_blocked")
        min_source_trade = _wallet_float(wallet, "event_follow_min_source_trade_usdc", 20.0)
        if trade.notional_usdc < min_source_trade:
            return self._record_skip(trade, "event_follow_source_trade_too_small")

        signal = self.store.record_event_follow_source_buy(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            event_title=str(metadata.get("event_title") or metadata.get("title") or ""),
            market_type=market_type,
            trade=trade,
            market_slug=str(metadata.get("market_slug") or ""),
            title=str(metadata.get("title") or ""),
        )
        if trade.source_wallet.lower() == GREERFEW_WALLET and market_type == "weather":
            return self._process_greerfew_weather_event_follow_buy(trade, event_slug, signal, wallet)
        if trade.source_wallet.lower() == SWISSTONY_WALLET:
            if _swisstony_source_follow_enabled(wallet):
                return self._process_swisstony_source_follow_buy(trade, event_slug, signal, wallet)
            return self._process_swisstony_event_follow_buy(trade, event_slug, signal, wallet)

        min_buy_count = _wallet_int(wallet, "event_follow_min_event_buy_count", 3)
        min_source_notional = _wallet_float(wallet, "event_follow_min_event_source_notional_usdc", 250.0)
        min_price = _wallet_float(wallet, "event_follow_min_avg_price", 0.20)
        max_price = _wallet_float(wallet, "event_follow_max_avg_price", 0.80)
        buy_size_multiplier = 1.0

        if int(signal["buy_count"]) < min_buy_count:
            return self._record_skip(trade, "event_follow_waiting_for_buy_count")
        if float(signal["source_notional_usdc"] or 0) < min_source_notional:
            return self._record_skip(trade, "event_follow_waiting_for_source_notional")

        avg_price = float(signal["source_avg_price"] or 0)
        if avg_price < min_price or avg_price > max_price:
            return self._record_skip(trade, "event_follow_price_band_blocked")

        event_remaining = _wallet_float(wallet, "event_follow_max_event_exposure_usdc", 4.0) - float(
            signal["copied_notional_usdc"] or 0
        )
        if event_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "event_follow_event_cap")
        total_remaining = _wallet_float(
            wallet,
            "event_follow_max_total_exposure_usdc",
            50.0,
        ) - self.store.open_cost_basis_for_wallet(trade.source_wallet)
        if total_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "event_follow_total_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        configured_buy_size = _wallet_float(wallet, "event_follow_buy_size_usdc", 2.0) * buy_size_multiplier
        notional = min(configured_buy_size, event_remaining, total_remaining, available_cash)
        if notional < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
            if observed_price < min_price or observed_price > max_price:
                return self._record_skip(trade, "event_follow_entry_price_band_blocked")
        block_reason = self._buy_price_block_reason(observed_price or trade.price, avg_price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)

        try:
            _execution_id, executed_notional = self._execute_buy(
                trade,
                notional_usdc=round(notional, 6),
                observed_price=observed_price,
            )
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        self.store.record_event_follow_copied_buy(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            asset_id=trade.asset_id,
            copied_notional_usdc=executed_notional,
        )
        return "processed"

    def _process_greerfew_weather_event_follow_buy(
        self,
        trade: SourceTrade,
        event_slug: str,
        signal: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str:
        if int(signal["buy_count"]) < _wallet_int(wallet, "event_follow_min_event_buy_count", 2):
            return self._record_skip(trade, "event_follow_waiting_for_buy_count")
        if float(signal["source_notional_usdc"] or 0) < _wallet_float(
            wallet,
            "event_follow_min_event_source_notional_usdc",
            0.0,
        ):
            return self._record_skip(trade, "event_follow_waiting_for_source_notional")

        avg_price = float(signal["source_avg_price"] or 0)
        min_price = _wallet_float(wallet, "event_follow_min_avg_price", 0.01)
        max_price = _wallet_float(wallet, "event_follow_max_avg_price", 0.06)
        if avg_price < min_price or avg_price > max_price:
            return self._record_skip(trade, "event_follow_price_band_blocked")

        source_event_notional = float(signal["source_notional_usdc"] or 0)
        if source_event_notional <= 0:
            return self._record_skip(trade, "event_follow_waiting_for_source_notional")

        event_cap = _wallet_float(wallet, "event_follow_max_event_exposure_usdc", 5.0)
        source_scaled_event_cap = source_event_notional * _wallet_profile_float(
            wallet,
            "limit_copy",
            "source_copy_scale",
            GREERFEW_SOURCE_COPY_SCALE,
        )
        event_target_cap = min(event_cap, source_scaled_event_cap)
        event_remaining = event_target_cap - float(signal["copied_notional_usdc"] or 0)
        if event_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "event_follow_event_cap")
        total_remaining = (
            _wallet_float(wallet, "event_follow_max_total_exposure_usdc", 50.0)
            - self.store.open_cost_basis_for_wallet(trade.source_wallet)
        )
        if total_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "event_follow_total_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        if available_cash < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        fills = 0
        blocked = 0
        last_paper_trade_id: int | None = None
        for leg in self.store.list_event_follow_legs(trade.source_wallet, event_slug):
            leg_source_notional = float(leg.get("source_notional_usdc") or 0)
            if leg_source_notional <= 0:
                continue
            target_notional = event_target_cap * (leg_source_notional / source_event_notional)
            delta = target_notional - float(leg.get("copied_notional_usdc") or 0)
            leg_notional = min(delta, event_remaining, total_remaining, available_cash)
            if leg_notional < self.config.sizing.min_trade_usdc:
                continue

            leg_trade = self._greerfew_event_follow_trade_for_leg(trigger_trade=trade, leg=leg)
            if leg_trade.idempotency_key != trade.idempotency_key:
                self.store.insert_source_trade(leg_trade)

            observed_price = self._resolve_buy_price(leg_trade.asset_id) if self.buy_price_resolver is not None else None
            if observed_price is None:
                if self.buy_price_resolver is not None:
                    self.store.record_copy_attribution(
                        leg_trade,
                        executed=False,
                        paper_trade_id=None,
                        skip_reason="price_unavailable",
                    )
                blocked += 1
                continue
            leg_source_price = float(leg.get("source_avg_price") or leg_trade.price or 0)
            effective_entry_price = observed_price * (1 + self.config.paper.slippage_pct / 100)
            max_allowed_price = min(
                max_price,
                leg_source_price
                + _wallet_profile_float(wallet, "limit_copy", "limit_price_premium", GREERFEW_LIMIT_PRICE_PREMIUM),
                leg_source_price
                * _wallet_profile_float(wallet, "limit_copy", "limit_price_multiple", GREERFEW_LIMIT_PRICE_MULTIPLE),
            )
            if effective_entry_price > max_allowed_price:
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason="greerfew_limit_price_blocked",
                )
                blocked += 1
                continue

            try:
                execution_id, executed_notional = self._execute_buy(
                    leg_trade,
                    notional_usdc=round(leg_notional, 6),
                    observed_price=observed_price,
                )
            except PaperExecutionError as exc:
                skip_reason = self._buy_execution_skip_reason(exc)
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason=skip_reason,
                )
                blocked += 1
                continue
            if self.config.mode.trading_mode != "live":
                last_paper_trade_id = execution_id
            self.store.record_event_follow_copied_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                asset_id=leg_trade.asset_id,
                copied_notional_usdc=executed_notional,
            )
            fills += 1
            event_remaining -= executed_notional
            total_remaining -= executed_notional
            available_cash -= executed_notional

        if fills > 0:
            if self.config.mode.trading_mode == "live":
                self.store.record_copy_attribution(trade, executed=True, paper_trade_id=None)
            elif last_paper_trade_id is not None:
                self.store.record_copy_attribution(trade, executed=True, paper_trade_id=last_paper_trade_id)
            return "processed"
        if blocked > 0:
            return self._record_skip(trade, "greerfew_limit_price_blocked")
        return self._record_skip(trade, "event_follow_target_notional_below_min")

    def _process_swisstony_event_follow_buy(
        self,
        trade: SourceTrade,
        event_slug: str,
        signal: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str:
        if int(signal["buy_count"]) < _wallet_int(wallet, "event_follow_min_event_buy_count", 8):
            return self._record_skip(trade, "event_follow_waiting_for_buy_count")
        if float(signal["source_notional_usdc"] or 0) < _wallet_float(
            wallet,
            "event_follow_min_event_source_notional_usdc",
            8000.0,
        ):
            return self._record_skip(trade, "event_follow_waiting_for_source_notional")

        event_remaining = _wallet_float(wallet, "event_follow_max_event_exposure_usdc", 15.0) - float(
            signal["copied_notional_usdc"] or 0
        )
        if event_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "event_follow_event_cap")
        total_remaining = (
            _wallet_float(wallet, "event_follow_max_total_exposure_usdc", 60.0)
            - self.store.open_cost_basis_for_wallet(trade.source_wallet)
        )
        if total_remaining < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, "event_follow_total_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        if available_cash < self.config.sizing.min_trade_usdc:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        sports_bracket_result = self._process_swisstony_sports_bracket_buy(
            trade,
            event_slug,
            signal,
            wallet,
            event_remaining=event_remaining,
            total_remaining=total_remaining,
            available_cash=available_cash,
        )
        if sports_bracket_result is not None:
            return sports_bracket_result

        fills = 0
        blocked = 0
        tier_blocked = 0
        last_paper_trade_id: int | None = None
        for leg in self.store.list_event_follow_legs(trade.source_wallet, event_slug):
            source_price = float(leg.get("source_avg_price") or 0)
            target_notional = _swisstony_leg_target_notional(source_price, wallet)
            if target_notional <= 0:
                if self._opposite_condition_position(
                    source_wallet=trade.source_wallet,
                    asset_id=str(leg.get("asset_id") or ""),
                ) is None:
                    tier_blocked += 1
                    continue
                target_notional = _wallet_float(wallet, "event_follow_buy_size_usdc", SWISSTONY_TIER_B_NOTIONAL_USDC)
            delta = target_notional - float(leg.get("copied_notional_usdc") or 0)
            leg_notional = min(delta, event_remaining, total_remaining, available_cash)
            if leg_notional < self.config.sizing.min_trade_usdc:
                continue

            leg_trade = self._swisstony_event_follow_trade_for_leg(trigger_trade=trade, leg=leg)
            if leg_trade.idempotency_key != trade.idempotency_key:
                self.store.insert_source_trade(leg_trade)

            observed_price = self._resolve_buy_price(leg_trade.asset_id) if self.buy_price_resolver is not None else None
            if observed_price is None:
                if self.buy_price_resolver is not None:
                    self.store.record_copy_attribution(
                        leg_trade,
                        executed=False,
                        paper_trade_id=None,
                        skip_reason="price_unavailable",
                    )
                blocked += 1
                continue
            effective_entry_price = observed_price * (1 + self.config.paper.slippage_pct / 100)
            if (
                _swisstony_leg_target_notional(effective_entry_price, wallet) <= 0
                and self._opposite_condition_position(source_wallet=leg_trade.source_wallet, asset_id=leg_trade.asset_id) is None
            ):
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason="swisstony_entry_tier_blocked",
                )
                blocked += 1
                continue
            block_reason = self._buy_price_block_reason(observed_price, source_price)
            if block_reason is not None:
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason=block_reason,
                )
                blocked += 1
                continue

            leg_notional = self._binary_hedge_adjusted_notional(
                trade=leg_trade,
                observed_price=observed_price,
                target_notional=leg_notional,
                wallet=wallet,
            )
            if leg_notional < self.config.sizing.min_trade_usdc:
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason="binary_hedge_target_below_min",
                )
                blocked += 1
                continue

            try:
                execution_id, executed_notional = self._execute_buy(
                    leg_trade,
                    notional_usdc=round(leg_notional, 6),
                    observed_price=observed_price,
                )
            except PaperExecutionError as exc:
                skip_reason = self._buy_execution_skip_reason(exc)
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason=skip_reason,
                )
                blocked += 1
                continue
            if self.config.mode.trading_mode != "live":
                last_paper_trade_id = execution_id
            self.store.record_event_follow_copied_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                asset_id=leg_trade.asset_id,
                copied_notional_usdc=executed_notional,
            )
            fills += 1
            event_remaining -= executed_notional
            total_remaining -= executed_notional
            available_cash -= executed_notional

        if fills > 0:
            if self.config.mode.trading_mode == "live":
                self.store.record_copy_attribution(trade, executed=True, paper_trade_id=None)
            elif last_paper_trade_id is not None:
                self.store.record_copy_attribution(trade, executed=True, paper_trade_id=last_paper_trade_id)
            return "processed"
        if blocked > 0:
            return self._record_skip(trade, "swisstony_execution_blocked")
        if tier_blocked > 0:
            return self._record_skip(trade, "swisstony_leg_tier_blocked")
        return self._record_skip(trade, "event_follow_target_notional_below_min")

    def _process_swisstony_source_follow_buy(
        self,
        trade: SourceTrade,
        event_slug: str,
        signal: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str:
        if int(signal["buy_count"]) < _wallet_int(wallet, "event_follow_min_event_buy_count", 2):
            return self._record_skip(trade, "event_follow_waiting_for_buy_count")
        if float(signal["source_notional_usdc"] or 0) < _wallet_float(
            wallet,
            "event_follow_min_event_source_notional_usdc",
            0.0,
        ):
            return self._record_skip(trade, "event_follow_waiting_for_source_notional")

        leg = next(
            (item for item in self.store.list_event_follow_legs(trade.source_wallet, event_slug) if str(item.get("asset_id") or "") == trade.asset_id),
            None,
        )
        if leg is None:
            return self._record_skip(trade, "event_follow_missing_leg")
        source_quantity = float(leg.get("source_quantity") or 0)
        source_notional = float(leg.get("source_notional_usdc") or 0)
        source_avg_price = source_notional / source_quantity if source_quantity > 0 else trade.price
        min_price = _wallet_float(wallet, "event_follow_min_avg_price", 0.01)
        max_price = _wallet_float(wallet, "event_follow_max_avg_price", 1.0)
        if source_avg_price < min_price or source_avg_price > max_price:
            return self._record_skip(trade, "event_follow_price_band_blocked")

        return self._process_source_follow_buy(
            trade,
            source_notional_usdc=source_notional,
            source_reference_price=source_avg_price,
            copy_scale=_wallet_profile_float(wallet, "source_follow", "copy_scale", SWISSTONY_SOURCE_FOLLOW_COPY_SCALE),
            max_asset_exposure_usdc=_wallet_profile_float(
                wallet,
                "source_follow",
                "max_asset_exposure_usdc",
                SWISSTONY_SOURCE_FOLLOW_MAX_ASSET_EXPOSURE_USDC,
            ),
            max_event_exposure_usdc=_wallet_float(wallet, "event_follow_max_event_exposure_usdc", 0.0),
            max_total_exposure_usdc=_wallet_float(wallet, "event_follow_max_total_exposure_usdc", 0.0),
            min_trade_usdc=_wallet_profile_float(wallet, "source_follow", "min_trade_usdc", 1.0),
            event_slug=event_slug,
        )

    def _process_source_follow_buy(
        self,
        trade: SourceTrade,
        *,
        source_notional_usdc: float,
        source_reference_price: float,
        copy_scale: float,
        max_asset_exposure_usdc: float,
        max_total_exposure_usdc: float,
        max_event_exposure_usdc: float = 0.0,
        min_trade_usdc: float = 1.0,
        event_slug: str | None = None,
        repeat_asset_id: str | None = None,
    ) -> str:
        min_trade = max(float(self.config.sizing.min_trade_usdc), float(min_trade_usdc))
        if source_notional_usdc <= 0:
            return self._record_skip(trade, "source_follow_waiting_for_source_notional")
        target_notional = min(float(max_asset_exposure_usdc), source_notional_usdc * float(copy_scale))
        copied_notional = self.store.paper_buy_notional_for_asset(
            source_wallet=trade.source_wallet,
            asset_id=trade.asset_id,
        )
        delta = target_notional - copied_notional
        if delta < min_trade:
            return self._record_skip(trade, "source_follow_target_notional_below_min")

        total_remaining = (
            max_total_exposure_usdc - self.store.open_cost_basis_for_wallet(trade.source_wallet)
            if max_total_exposure_usdc > 0
            else delta
        )
        if total_remaining < min_trade:
            return self._record_skip(trade, "source_follow_total_cap")
        event_remaining = max_event_exposure_usdc
        if event_slug and max_event_exposure_usdc > 0:
            signal = self.store.get_event_follow_signal(trade.source_wallet, event_slug)
            copied_event = float(signal.get("copied_notional_usdc") or 0) if signal else 0.0
            event_remaining = max_event_exposure_usdc - copied_event
            if event_remaining < min_trade:
                return self._record_skip(trade, "source_follow_event_cap")

        available_cash = self._available_cash_for_wallet(trade.source_wallet)
        notional = min(delta, total_remaining, available_cash)
        if max_event_exposure_usdc > 0:
            notional = min(notional, event_remaining)
        if notional < min_trade:
            return self._record_skip(trade, self._cash_skip_reason(available_cash))

        observed_price = None
        if self.buy_price_resolver is not None:
            observed_price = self._resolve_buy_price(trade.asset_id)
            if observed_price is None:
                return self._record_skip(trade, "price_unavailable")
        block_reason = self._buy_price_block_reason(observed_price or trade.price, source_reference_price)
        if block_reason is not None:
            return self._record_skip(trade, block_reason)

        notional = self._binary_hedge_adjusted_notional(
            trade=trade,
            observed_price=observed_price or trade.price,
            target_notional=notional,
            wallet=self.store.get_wallet(trade.source_wallet) or {},
        )
        if notional < min_trade:
            return self._record_skip(trade, "binary_hedge_target_below_min")

        try:
            execution_id, copied_notional = self._execute_buy(
                trade,
                notional_usdc=round(notional, 6),
                observed_price=observed_price,
            )
        except PaperExecutionError as exc:
            return self._record_skip(trade, self._buy_execution_skip_reason(exc))
        if repeat_asset_id:
            self.store.record_repeat_buy_copied(
                source_wallet=trade.source_wallet,
                asset_id=repeat_asset_id,
                paper_trade_id=execution_id or 0,
                copied_notional_usdc=copied_notional,
            )
        if event_slug:
            self.store.record_event_follow_copied_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                asset_id=trade.asset_id,
                copied_notional_usdc=copied_notional,
            )
        return "processed"

    def _process_swisstony_sports_bracket_buy(
        self,
        trade: SourceTrade,
        event_slug: str,
        signal: dict[str, Any],
        wallet: dict[str, Any],
        *,
        event_remaining: float | None = None,
        total_remaining: float | None = None,
        available_cash: float | None = None,
    ) -> str | None:
        return self._process_sports_bracket_buy(
            trade,
            event_slug,
            signal,
            wallet,
            target_notional_func=self._swisstony_sports_bracket_target_notional,
            event_remaining=event_remaining,
            total_remaining=total_remaining,
            available_cash=available_cash,
        )

    def _process_sports_bracket_buy(
        self,
        trade: SourceTrade,
        event_slug: str,
        signal: dict[str, Any],
        wallet: dict[str, Any],
        *,
        target_notional_func: Callable[[dict[str, Any], dict[str, Any]], float],
        event_remaining: float | None = None,
        total_remaining: float | None = None,
        available_cash: float | None = None,
    ) -> str | None:
        plan = self._sports_bracket_plan(trade, event_slug, signal, wallet, target_notional_func=target_notional_func)
        if plan is None:
            return None
        event_remaining = (
            _wallet_float(wallet, "event_follow_max_event_exposure_usdc", 15.0)
            - float(signal["copied_notional_usdc"] or 0)
            if event_remaining is None
            else event_remaining
        )
        total_remaining = (
            _wallet_float(wallet, "event_follow_max_total_exposure_usdc", 60.0)
            - self.store.open_cost_basis_for_wallet(trade.source_wallet)
            if total_remaining is None
            else total_remaining
        )
        available_cash = self._available_cash_for_wallet(trade.source_wallet) if available_cash is None else available_cash
        leg_budgets = self._sports_bracket_leg_budgets(
            plan["legs"],
            event_remaining=event_remaining,
            total_remaining=total_remaining,
            available_cash=available_cash,
        )
        if not leg_budgets:
            return None
        planned: list[tuple[SourceTrade, float, float]] = []
        for leg in plan["legs"]:
            leg_key = str(leg.get("asset_id") or "")
            leg_notional = leg_budgets.get(leg_key, 0.0)
            if leg_notional < self.config.sizing.min_trade_usdc:
                continue
            leg_trade = self._swisstony_event_follow_trade_for_leg(trigger_trade=trade, leg=leg)
            observed_price = self._resolve_buy_price(leg_trade.asset_id) if self.buy_price_resolver is not None else None
            if observed_price is None and self.buy_price_resolver is not None:
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason="sports_bracket_price_unavailable",
                )
                return None
            entry_price = observed_price if observed_price is not None else leg_trade.price
            effective_entry_price = entry_price * (1 + self.config.paper.slippage_pct / 100)
            if effective_entry_price >= 1.0:
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason="entry_price_at_one",
                )
                return None
            min_price = _wallet_float(wallet, "event_follow_min_avg_price", SWISSTONY_TIER_A_MIN_PRICE)
            max_price = _wallet_float(wallet, "event_follow_max_avg_price", SWISSTONY_TIER_B_MAX_PRICE)
            if effective_entry_price < min_price or effective_entry_price > max_price:
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason="sports_bracket_entry_price_band_blocked",
                )
                return None
            planned.append((leg_trade, leg_notional, entry_price))

        if not planned:
            return None

        self.store.record_sports_bracket_candidate(
            source_wallet=trade.source_wallet,
            event_slug=event_slug,
            event_title=str(signal.get("event_title") or ""),
            pattern=str(plan["pattern"]),
            legs=[leg for leg in plan["legs"] if str(leg.get("asset_id") or "") in leg_budgets],
        )
        last_paper_trade_id: int | None = None
        for leg_trade, leg_notional, observed_price in planned:
            if leg_trade.idempotency_key != trade.idempotency_key:
                self.store.insert_source_trade(leg_trade)
            try:
                execution_id, executed_notional = self._execute_buy(
                    leg_trade,
                    notional_usdc=round(leg_notional, 6),
                    observed_price=observed_price,
                )
            except PaperExecutionError as exc:
                skip_reason = self._buy_execution_skip_reason(exc)
                self.store.record_copy_attribution(
                    leg_trade,
                    executed=False,
                    paper_trade_id=None,
                    skip_reason=skip_reason,
                )
                return self._record_skip(trade, skip_reason)
            if self.config.mode.trading_mode != "live":
                last_paper_trade_id = execution_id
            self.store.record_event_follow_copied_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                asset_id=leg_trade.asset_id,
                copied_notional_usdc=executed_notional,
            )
            self.store.record_sports_bracket_copied_buy(
                source_wallet=trade.source_wallet,
                event_slug=event_slug,
                pattern=str(plan["pattern"]),
                asset_id=leg_trade.asset_id,
                copied_notional_usdc=executed_notional,
            )
        if self.config.mode.trading_mode == "live":
            self.store.record_copy_attribution(trade, executed=True, paper_trade_id=None)
        elif last_paper_trade_id is not None:
            self.store.record_copy_attribution(trade, executed=True, paper_trade_id=last_paper_trade_id)
        return "processed"

    def _sports_bracket_leg_budgets(
        self,
        legs: list[dict[str, Any]],
        *,
        event_remaining: float,
        total_remaining: float,
        available_cash: float,
    ) -> dict[str, float]:
        desired: list[tuple[dict[str, Any], float]] = []
        for leg in legs:
            delta = float(leg.get("target_notional_usdc") or 0) - float(leg.get("copied_notional_usdc") or 0)
            if delta > 0:
                desired.append((leg, delta))
        total_desired = sum(delta for _, delta in desired)
        budget = min(total_desired, event_remaining, total_remaining, available_cash)
        min_trade = float(self.config.sizing.min_trade_usdc)
        if budget < min_trade:
            return {}

        active = desired
        while active:
            active_desired = sum(delta for _, delta in active)
            if active_desired <= 0:
                return {}
            scale = min(1.0, budget / active_desired)
            allocations = [(leg, delta * scale) for leg, delta in active]
            too_small = [(leg, amount) for leg, amount in allocations if amount < min_trade]
            if not too_small:
                return {str(leg.get("asset_id") or ""): round(amount, 6) for leg, amount in allocations}
            if len(active) == len(too_small):
                if len(active) == 1 and budget >= min_trade:
                    leg, _delta = active[0]
                    return {str(leg.get("asset_id") or ""): round(budget, 6)}
                return {}
            excluded_ids = {id(leg) for leg, _amount in too_small}
            active = [(leg, delta) for leg, delta in active if id(leg) not in excluded_ids]

        return {}

    def _sports_bracket_plan(
        self,
        trade: SourceTrade,
        event_slug: str,
        signal: dict[str, Any],
        wallet: dict[str, Any],
        *,
        target_notional_func: Callable[[dict[str, Any], dict[str, Any]], float],
    ) -> dict[str, Any] | None:
        sport = _event_sport_group({"event_slug": event_slug, "event_title": signal.get("event_title")})
        if sport not in {"soccer", "other", "mlb", "nba", "nhl", "nfl", "esports"}:
            return None
        min_event_source = _wallet_float(wallet, "event_follow_min_event_source_notional_usdc", 0.0)
        min_buy_count = _wallet_int(wallet, "event_follow_min_event_buy_count", 2)
        min_price = _wallet_float(wallet, "event_follow_min_avg_price", SWISSTONY_TIER_A_MIN_PRICE)
        max_price = _wallet_float(wallet, "event_follow_max_avg_price", SWISSTONY_TIER_B_MAX_PRICE)
        qualified: list[dict[str, Any]] = []
        for leg in self.store.list_event_follow_legs(trade.source_wallet, event_slug):
            source_price = float(leg.get("source_avg_price") or 0)
            if source_price < min_price or source_price > max_price:
                continue
            target_notional = target_notional_func(leg, wallet)
            if target_notional <= 0:
                continue
            plan_leg = dict(leg)
            existing_copied = max(
                float(plan_leg.get("copied_notional_usdc") or 0),
                self.store.paper_buy_notional_for_asset(
                    source_wallet=trade.source_wallet,
                    asset_id=str(plan_leg.get("asset_id") or ""),
                ),
            )
            plan_leg["copied_notional_usdc"] = existing_copied
            plan_leg["target_notional_usdc"] = target_notional
            plan_leg["bracket_leg_type"] = _sports_bracket_leg_type(plan_leg)
            qualified.append(plan_leg)
        pattern, legs = _select_sports_bracket_pattern(qualified)
        if pattern is None:
            return None
        if len(legs) < 2:
            return None
        if sum(int(leg.get("buy_count") or 0) for leg in legs) < min_buy_count:
            return None
        if sum(float(leg.get("source_notional_usdc") or 0) for leg in legs) < min_event_source:
            return None
        anchor_scale = max(
            [
                float(leg.get("copied_notional_usdc") or 0) / float(leg.get("target_notional_usdc") or 1)
                for leg in legs
                if float(leg.get("target_notional_usdc") or 0) > 0
            ]
            or [1.0]
        )
        if anchor_scale > 1:
            for leg in legs:
                leg["target_notional_usdc"] = round(float(leg["target_notional_usdc"]) * anchor_scale, 6)
        if pattern == SPORTS_TWO_OUTCOME_BRACKET_PATTERN:
            _apply_two_outcome_hedge_targets(legs)
        legs.sort(key=lambda leg: float(leg.get("source_notional_usdc") or 0), reverse=True)
        return {"pattern": pattern, "legs": legs}

    def _swisstony_sports_bracket_target_notional(self, leg: dict[str, Any], wallet: dict[str, Any]) -> float:
        return _swisstony_leg_target_notional(float(leg.get("source_avg_price") or 0), wallet)

    def _generic_sports_bracket_target_notional(self, leg: dict[str, Any], wallet: dict[str, Any]) -> float:
        event_follow_size = _wallet_float(wallet, "event_follow_buy_size_usdc", 0.0)
        if event_follow_size > 0:
            return event_follow_size
        return _wallet_float(wallet, "repeat_buy_size_usdc", 2.0)

    def _rn1_event_book_block_reason(
        self,
        trade: SourceTrade,
        metadata: dict[str, Any],
        signal: dict[str, Any],
        wallet: dict[str, Any],
    ) -> str | None:
        if trade.source_wallet.lower() != RN1_WALLET:
            return None
        event_slug = str(metadata.get("event_slug") or "").strip()
        if not event_slug:
            return None
        if int(signal.get("buy_count") or 0) < _wallet_int(wallet, "repeat_buy_min_buy_count", 2):
            return None
        if float(signal.get("source_notional_usdc") or 0) < _wallet_float(
            wallet,
            "repeat_buy_min_source_notional_usdc",
            0.0,
        ):
            return None
        source_avg_price = _signal_avg_price(signal)
        min_source_notional = _wallet_profile_float(
            wallet,
            "event_book",
            "min_source_notional_usdc",
            _wallet_float(wallet, "repeat_buy_min_source_notional_usdc", RN1_CONVICTION_SOURCE_NOTIONAL_USDC),
        )
        min_avg_price = _wallet_profile_float(
            wallet,
            "event_book",
            "min_avg_price",
            _wallet_float(wallet, "repeat_buy_min_avg_price", RN1_ESPORTS_MIN_AVG_PRICE),
        )
        max_avg_price = _wallet_profile_float(
            wallet,
            "event_book",
            "max_avg_price",
            _wallet_float(wallet, "repeat_buy_max_avg_price", RN1_ESPORTS_MAX_AVG_PRICE),
        )
        if source_avg_price < min_avg_price or source_avg_price > max_avg_price:
            return None

        legs = self.store.list_event_follow_legs(trade.source_wallet, event_slug)
        current_leg = next((leg for leg in legs if str(leg.get("asset_id") or "") == trade.asset_id), None)
        if current_leg is None:
            return None
        current_leg = dict(current_leg)
        current_leg["buy_count"] = max(int(current_leg.get("buy_count") or 0), int(signal.get("buy_count") or 0))
        current_leg["source_notional_usdc"] = max(
            float(current_leg.get("source_notional_usdc") or 0),
            float(signal.get("source_notional_usdc") or 0),
        )
        current_leg["source_quantity"] = max(
            float(current_leg.get("source_quantity") or 0),
            float(signal.get("source_quantity") or 0),
        )
        source_quantity = float(current_leg.get("source_quantity") or 0)
        current_leg["source_avg_price"] = (
            float(current_leg.get("source_notional_usdc") or 0) / source_quantity
            if source_quantity > 0
            else 0.0
        )
        legs = [current_leg if str(leg.get("asset_id") or "") == trade.asset_id else leg for leg in legs]
        if not _rn1_event_book_leg_in_conviction_band(current_leg, min_source_notional, min_avg_price, max_avg_price):
            return "rn1_event_book_price_band_blocked"
        comparable = _rn1_comparable_event_book_legs(current_leg, legs)
        if len(comparable) < 2:
            return None
        if not _rn1_event_book_leg_is_dominant(
            current_leg,
            comparable,
            min_dominance_share=_wallet_profile_float(
                wallet,
                "event_book",
                "min_dominance_share",
                RN1_EVENT_BOOK_MIN_DOMINANCE_SHARE,
            ),
            min_dominance_ratio=_wallet_profile_float(
                wallet,
                "event_book",
                "min_dominance_ratio",
                RN1_EVENT_BOOK_MIN_DOMINANCE_RATIO,
            ),
        ):
            return "rn1_event_book_not_dominant"
        return None

    def _swisstony_event_follow_trade_for_leg(self, *, trigger_trade: SourceTrade, leg: dict[str, Any]) -> SourceTrade:
        asset_id = str(leg.get("asset_id") or "")
        source_quantity = float(leg.get("source_quantity") or 0)
        source_notional = float(leg.get("source_notional_usdc") or 0)
        source_price = float(leg.get("source_avg_price") or 0)
        if source_price <= 0 and source_quantity > 0:
            source_price = source_notional / source_quantity
        if asset_id == trigger_trade.asset_id:
            return trigger_trade
        unique_suffix = time.time_ns()
        return SourceTrade(
            idempotency_key=f"swisstony-tier:{trigger_trade.source_wallet}:{asset_id}:{unique_suffix}",
            chain_id=trigger_trade.chain_id,
            exchange_contract="event_follow_tier_copy",
            tx_hash=f"swisstony-tier:{trigger_trade.tx_hash}:{asset_id}:{unique_suffix}",
            block_number=trigger_trade.block_number,
            block_timestamp=trigger_trade.block_timestamp,
            log_index=trigger_trade.log_index,
            source_wallet=trigger_trade.source_wallet,
            side="buy",
            asset_id=asset_id,
            price=source_price,
            quantity=source_quantity,
            notional_usdc=source_notional,
            condition_id=trigger_trade.condition_id,
            market_id=trigger_trade.market_id,
            outcome=str(leg.get("outcome") or "") or None,
            copy_trade_key=f"swisstony-tier:{trigger_trade.source_wallet}:{asset_id}:{source_price:.6f}",
        )

    def _synthetic_event_follow_trade(
        self,
        *,
        source_wallet: str,
        event_slug: str,
        leg: dict[str, Any],
        reason: str,
    ) -> SourceTrade:
        now = datetime.now(tz=PDT).strftime("%Y-%m-%d %H:%M PDT")
        now_epoch = int(datetime.now(tz=PDT).timestamp())
        unique_suffix = time.time_ns()
        asset_id = str(leg.get("asset_id") or "")
        source_quantity = float(leg.get("source_quantity") or 0)
        source_notional = float(leg.get("source_notional_usdc") or 0)
        source_price = float(leg.get("source_avg_price") or 0)
        return SourceTrade(
            idempotency_key=f"{reason}:{source_wallet}:{event_slug}:{asset_id}:{unique_suffix}",
            chain_id=137,
            exchange_contract="event_follow_manual_copy",
            tx_hash=f"{reason}:{event_slug}:{asset_id}:{unique_suffix}",
            block_number=now_epoch,
            block_timestamp=now,
            log_index=0,
            source_wallet=source_wallet,
            side="buy",
            asset_id=asset_id,
            price=source_price,
            quantity=source_quantity,
            notional_usdc=source_notional,
            outcome=str(leg.get("outcome") or "") or None,
            copy_trade_key=f"{reason}:{source_wallet}:{event_slug}:{asset_id}",
        )

    def _greerfew_event_follow_trade_for_leg(self, *, trigger_trade: SourceTrade, leg: dict[str, Any]) -> SourceTrade:
        asset_id = str(leg.get("asset_id") or "")
        source_quantity = float(leg.get("source_quantity") or 0)
        source_notional = float(leg.get("source_notional_usdc") or 0)
        source_price = float(leg.get("source_avg_price") or 0)
        if source_price <= 0 and source_quantity > 0:
            source_price = source_notional / source_quantity
        if asset_id == trigger_trade.asset_id:
            return trigger_trade
        unique_suffix = time.time_ns()
        return SourceTrade(
            idempotency_key=f"greerfew-limit:{trigger_trade.source_wallet}:{asset_id}:{unique_suffix}",
            chain_id=trigger_trade.chain_id,
            exchange_contract="event_follow_limit_copy",
            tx_hash=f"greerfew-limit:{trigger_trade.tx_hash}:{asset_id}:{unique_suffix}",
            block_number=trigger_trade.block_number,
            block_timestamp=trigger_trade.block_timestamp,
            log_index=trigger_trade.log_index,
            source_wallet=trigger_trade.source_wallet,
            side="buy",
            asset_id=asset_id,
            price=source_price,
            quantity=source_quantity,
            notional_usdc=source_notional,
            condition_id=trigger_trade.condition_id,
            market_id=trigger_trade.market_id,
            outcome=str(leg.get("outcome") or "") or None,
            copy_trade_key=f"greerfew-limit:{trigger_trade.source_wallet}:{asset_id}:{source_price:.6f}",
        )

    def process_local_exits(self) -> int:
        exits = 0
        for row in self.store.list_positions():
            if self.config.mode.trading_mode == "live" and row.get("is_closed"):
                continue
            row = self._with_updated_trailing_state(row)
            wallet = self.store.get_wallet(str(row.get("source_wallet") or "")) or {}
            if _filter_copy_enabled(str(row.get("source_wallet") or ""), wallet):
                reason = self._filter_copy_local_exit_reason(row, wallet)
                if reason is None:
                    continue
                if self.config.mode.trading_mode == "live" and self._active_live_sell_intent_exists(
                    asset_id=str(row["asset_id"]),
                    source_wallet=str(row["source_wallet"]),
                ):
                    continue
                trade = self._local_exit_trade(row, reason=reason)
                if not self.store.insert_source_trade(trade):
                    continue
                if self._process_sell(trade, close_reason=reason) == "processed":
                    exits += 1
                continue
            winner_exits = self._process_winner_capture_exits(row)
            if winner_exits:
                exits += winner_exits
                continue
            reason = self._local_exit_reason(row)
            if reason is None:
                continue
            if self.config.mode.trading_mode == "live" and self._active_live_sell_intent_exists(
                asset_id=str(row["asset_id"]),
                source_wallet=str(row["source_wallet"]),
            ):
                continue
            trade = self._local_exit_trade(row, reason=reason)
            if not self.store.insert_source_trade(trade):
                continue
            if self._process_sell(trade, close_reason=reason) == "processed":
                exits += 1
        return exits

    def _filter_copy_local_exit_reason(self, row: dict[str, object], wallet: dict[str, object]) -> str | None:
        current_price = _float_or_none(row.get("current_price"))
        avg_entry_price = _float_or_none(row.get("avg_entry_price"))
        if current_price is None or avg_entry_price is None or avg_entry_price <= 0:
            return None
        if _filter_copy_in_event_stop_loss(row, wallet, current_price=current_price, avg_entry_price=avg_entry_price):
            return "filter_copy_in_event_stop_loss"
        return None

    def process_market_settlements(self) -> int:
        settlements = 0
        for row in self.store.list_positions():
            if not row.get("is_closed"):
                continue
            resolution_price = _float_or_none(row.get("resolution_price"))
            if resolution_price is None:
                continue
            if self.config.mode.trading_mode == "live":
                if self._create_live_settlement_intent(row, resolution_price=resolution_price):
                    settlements += 1
                continue
            trade = self._local_exit_trade(row, reason="market_settlement", price=resolution_price)
            if not self.store.insert_source_trade(trade):
                continue
            if self._process_sell(trade, close_reason="market_settlement") == "processed":
                settlements += 1
        return settlements

    def _create_live_settlement_intent(self, row: dict[str, object], *, resolution_price: float) -> bool:
        asset_id = str(row["asset_id"])
        source_wallet = str(row["source_wallet"]).lower()
        if self.store.get_live_settlement_intent_for_position(asset_id=asset_id, source_wallet=source_wallet) is not None:
            return False
        condition_id = str(row.get("condition_id") or "").strip()
        if not condition_id:
            return False
        trade = self._local_exit_trade(row, reason="market_settlement", price=resolution_price)
        if not self.store.insert_source_trade(trade):
            return False
        self.store.create_live_settlement_intent(
            source_trade=trade,
            condition_id=condition_id,
            quantity=float(row["quantity"] or 0),
            resolution_price=resolution_price,
        )
        self.store.record_copy_attribution(trade, executed=True, paper_trade_id=None)
        return True

    def process_manual_sell(self, *, asset_id: str, source_wallet: str) -> bool:
        row = self._position_row(asset_id=asset_id, source_wallet=source_wallet)
        if row is None:
            return False
        if _float_or_none(row.get("current_price")) is None:
            raise PaperExecutionError("manual sell requires a current mark price")
        trade = self._local_exit_trade(row, reason="manual_sell")
        if not self.store.insert_source_trade(trade):
            return False
        return self._process_position_row_sell(trade, row=row, close_reason="manual_sell")

    def process_sports_bracket_event(self, *, source_wallet: str, event_slug: str) -> str:
        wallet = self.store.get_wallet(source_wallet) or {}
        signal = self.store.get_event_follow_signal(source_wallet, event_slug)
        legs = self.store.list_event_follow_legs(source_wallet, event_slug)
        if signal is None or not legs:
            return "skipped"
        trigger_leg = max(legs, key=lambda leg: float(leg.get("source_notional_usdc") or 0))
        trigger_trade = self._synthetic_event_follow_trade(
            source_wallet=source_wallet,
            event_slug=event_slug,
            leg=trigger_leg,
            reason="manual-sports-bracket",
        )
        self.store.insert_source_trade(trigger_trade)
        target_func = (
            self._swisstony_sports_bracket_target_notional
            if source_wallet.lower() == SWISSTONY_WALLET
            else self._generic_sports_bracket_target_notional
        )
        return (
            self._process_sports_bracket_buy(
                trigger_trade,
                event_slug,
                signal,
                wallet,
                target_notional_func=target_func,
            )
            or "skipped"
        )

    def _process_position_row_sell(
        self,
        trade: SourceTrade,
        *,
        row: dict[str, object],
        close_reason: str,
    ) -> bool:
        quantity = float(row["quantity"] or 0)
        avg_entry_price = float(row["avg_entry_price"] or 0)
        if quantity <= 0 or avg_entry_price <= 0:
            return False
        if self.config.mode.trading_mode == "live":
            if self._active_live_sell_intent_exists(asset_id=trade.asset_id, source_wallet=trade.source_wallet):
                return False
            return self._create_live_sell_order_intent(
                trade,
                quantity=quantity,
                price=trade.price,
                close_reason=close_reason,
            )

        broker = PaperBroker(
            starting_cash_usdc=self.broker.cash_usdc,
            slippage_pct=self.config.paper.slippage_pct,
            settlement_slippage_pct=self.config.paper.settlement_slippage_pct,
        )
        broker.positions[broker.position_key(trade.asset_id, trade.source_wallet)] = Position(
            asset_id=trade.asset_id,
            source_wallet=trade.source_wallet,
            lots=[
                PositionLot(
                    quantity=quantity,
                    entry_price=avg_entry_price,
                    source_wallet=trade.source_wallet,
                    source_idempotency_key=f"manual:{trade.asset_id}:{trade.source_wallet}",
                )
            ],
            realized_pnl_usdc=float(row["realized_pnl_usdc"] or 0),
        )
        try:
            fill = broker.sell(trade, quantity=quantity, close_reason=close_reason)
        except PaperExecutionError:
            return False

        position = broker.get_position(trade.asset_id, trade.source_wallet)
        if position is None:
            return False
        paper_trade_id = self.store.record_paper_fill(
            fill,
            cash_after_usdc=broker.cash_usdc,
            position_quantity=position.quantity,
            avg_entry_price=position.average_entry_price,
        )
        self.store.record_copy_attribution(trade, executed=True, paper_trade_id=paper_trade_id)
        return True

    def _position_row(self, *, asset_id: str, source_wallet: str) -> dict[str, object] | None:
        clean_wallet = source_wallet.lower()
        for row in self.store.list_positions():
            if str(row["asset_id"]) == str(asset_id) and str(row["source_wallet"]).lower() == clean_wallet:
                return row
        return None

    def _local_exit_reason(self, row: dict[str, object]) -> str | None:
        current_price = _float_or_none(row.get("current_price"))
        avg_entry_price = _float_or_none(row.get("avg_entry_price"))
        if current_price is None or avg_entry_price is None or avg_entry_price <= 0:
            return None
        wallet = self.store.get_wallet(str(row.get("source_wallet") or ""))
        market_type = str(row.get("market_type") or "other").lower()
        if _sharp_simple_crypto_copy_enabled(str(row.get("source_wallet") or ""), wallet or {}, market_type):
            return None
        if current_price >= 1.0:
            return "price_at_one"
        if _sports_pre_end_lock_profit(row, current_price, avg_entry_price, self.config.paper.slippage_pct):
            return "sports_pre_end_lock_profit"
        live_event_managed = _is_live_event_managed(wallet, market_type)
        if _sports_dead_cut(
            row,
            current_price=current_price,
            avg_entry_price=avg_entry_price,
            live_event_managed=live_event_managed,
            profile=self.config.winner_capture,
        ):
            return "sports_dead_cut"
        if _sports_event_lost_after_close(row, current_price=current_price, live_event_managed=live_event_managed):
            return "sports_event_lost"
        if (
            market_type != "weather"
            and current_price <= NEAR_ZERO_EXIT_PRICE
            and (not live_event_managed or _near_zero_exit_confirmed(row))
        ):
            return "price_near_zero"
        if (
            wallet
            and _weather_bracket_strategy_enabled(wallet)
            and market_type == "weather"
        ):
            stop_loss_pct = _wallet_float(wallet, "bracket_stop_loss_pct", 0.0)
            if stop_loss_pct <= 0:
                return None
            stop_price = avg_entry_price * (1 - stop_loss_pct / 100)
            return "stop_loss" if current_price <= stop_price else None
        trailing_reason = self._sports_trailing_stop_reason(
            row,
            wallet=wallet,
            current_price=current_price,
            avg_entry_price=avg_entry_price,
            market_type=market_type,
        )
        if trailing_reason is not None:
            return trailing_reason
        repeat_buy_managed = bool(wallet and _repeat_buy_strategy_enabled(wallet))
        event_follow_take_profit_managed = bool(
            wallet
            and _event_follow_strategy_enabled(wallet)
            and market_type in {"sports", "weather", "other"}
        )
        event_follow_stop_loss_managed = _event_follow_stop_loss_managed(
            wallet,
            source_wallet=str(row.get("source_wallet") or ""),
            market_type=market_type,
        )
        if wallet and _repeat_buy_strategy_enabled(wallet):
            stop_loss_pct = _wallet_float(wallet, "repeat_buy_stop_loss_pct", 0.0)
            if stop_loss_pct > 0:
                stop_price = avg_entry_price * (1 - stop_loss_pct / 100)
                zero_tick_unconfirmed = (
                    current_price <= NEAR_ZERO_EXIT_PRICE
                    and live_event_managed
                    and not _near_zero_exit_confirmed(row)
                )
                opposite_breakout = self._opposite_condition_breakout(row)
                if current_price <= stop_price and not zero_tick_unconfirmed and not opposite_breakout:
                    return "stop_loss"
        profile = self.config.exits.profile_for(market_type)
        if (
            profile.stop_loss_pct > 0
            and not repeat_buy_managed
            and not event_follow_stop_loss_managed
        ):
            stop_price = avg_entry_price * (1 - profile.stop_loss_pct / 100)
            zero_tick_unconfirmed = (
                current_price <= NEAR_ZERO_EXIT_PRICE
                and live_event_managed
                and not _near_zero_exit_confirmed(row)
            )
            if current_price <= stop_price and not zero_tick_unconfirmed:
                return "stop_loss"
        if profile.take_profit_pct > 0 and not repeat_buy_managed and not event_follow_take_profit_managed:
            take_profit_price = avg_entry_price * (1 + profile.take_profit_pct / 100)
            if current_price >= take_profit_price:
                return "take_profit"
        return None

    def _process_winner_capture_exits(self, row: dict[str, object]) -> int:
        profile = self.config.winner_capture
        if not profile.enabled:
            return 0
        current_price = _float_or_none(row.get("current_price"))
        avg_entry_price = _float_or_none(row.get("avg_entry_price"))
        quantity = _float_or_none(row.get("quantity")) or 0.0
        if current_price is None or avg_entry_price is None or avg_entry_price <= 0 or quantity <= 0:
            return 0
        if current_price >= 1.0:
            return 0
        sports_mid_price = _is_sports_mid_price_winner_capture(row, avg_entry_price, profile)
        if avg_entry_price > profile.entry_price_max and not sports_mid_price:
            return 0

        previous_peak = _float_or_none(row.get("trailing_peak_price")) or avg_entry_price
        peak_price = max(previous_peak, current_price, avg_entry_price)
        if peak_price != previous_peak:
            self.store.update_position_trailing_state(
                asset_id=str(row["asset_id"]),
                source_wallet=str(row["source_wallet"]),
                peak_price=peak_price,
                activated=bool(row.get("trailing_activated")),
            )
            row = dict(row)
            row["trailing_peak_price"] = peak_price

        plans = (
            self._sports_mid_price_winner_capture_plans(row, current_price=current_price, avg_entry_price=avg_entry_price)
            if sports_mid_price
            else self._winner_capture_plans(row, current_price=current_price, avg_entry_price=avg_entry_price)
        )
        exits = 0
        remaining = quantity
        for reason, sell_quantity, state_field in plans:
            sell_quantity = min(remaining, sell_quantity)
            if sell_quantity <= 1e-9:
                continue
            trade = self._local_exit_trade(row, reason=reason, quantity=sell_quantity)
            if not self.store.insert_source_trade(trade):
                continue
            if self._process_sell(trade, close_reason=reason) != "processed":
                continue
            exits += 1
            remaining -= sell_quantity
            if state_field:
                self.store.mark_position_winner_capture(
                    asset_id=str(row["asset_id"]),
                    source_wallet=str(row["source_wallet"]),
                    field=state_field,
                )
            if remaining <= 1e-9:
                break
        return exits

    def _winner_capture_plans(
        self,
        row: dict[str, object],
        *,
        current_price: float,
        avg_entry_price: float,
    ) -> list[tuple[str, float, str | None]]:
        profile = self.config.winner_capture
        quantity = float(row.get("quantity") or 0)
        initial_quantity = float(row.get("total_buy_quantity") or quantity)
        initial_cost = float(row.get("total_buy_notional_usdc") or (initial_quantity * avg_entry_price))
        if quantity <= 0 or initial_quantity <= 0 or initial_cost <= 0:
            return []

        plans: list[tuple[str, float, str | None]] = []
        remaining = quantity
        fill_price = max(0.0, current_price * (1 - self.config.paper.slippage_pct / 100))
        multiple = current_price / avg_entry_price
        stake_recovered = bool(row.get("winner_capture_stake_recovered"))
        first_scale_done = bool(row.get("winner_capture_first_scale_done"))
        high_price_done = bool(row.get("winner_capture_high_price_done"))

        if not stake_recovered and multiple >= profile.recover_stake_multiple and fill_price > 0:
            sell_quantity = min(remaining, initial_cost / fill_price)
            plans.append(("winner_recover_stake", sell_quantity, "winner_capture_stake_recovered"))
            remaining -= sell_quantity
            stake_recovered = True

        if remaining > 1e-9 and not first_scale_done and multiple >= profile.first_scale_multiple:
            sell_quantity = remaining * (profile.first_scale_sell_pct / 100)
            plans.append(("winner_scale", sell_quantity, "winner_capture_first_scale_done"))
            remaining -= sell_quantity
            first_scale_done = True

        if remaining > 1e-9 and not high_price_done and current_price >= profile.high_price_threshold:
            runner_quantity = initial_quantity * (profile.runner_pct / 100)
            scale_quantity = remaining * (profile.high_price_sell_pct / 100)
            runner_limit_quantity = max(0.0, remaining - runner_quantity)
            sell_quantity = max(scale_quantity, runner_limit_quantity)
            plans.append(("winner_high_price", sell_quantity, "winner_capture_high_price_done"))
            remaining -= sell_quantity
            high_price_done = True

        if remaining > 1e-9 and (stake_recovered or first_scale_done or high_price_done):
            peak_price = _float_or_none(row.get("trailing_peak_price")) or current_price
            pct_stop = peak_price * (1 - profile.trailing_drawdown_pct / 100)
            stop_price = pct_stop
            if peak_price >= profile.high_price_threshold and profile.high_price_absolute_trail > 0:
                stop_price = max(stop_price, peak_price - profile.high_price_absolute_trail)
            if current_price < peak_price and current_price <= stop_price:
                plans.append(("winner_trailing_stop", remaining, None))
        return plans

    def _sports_mid_price_winner_capture_plans(
        self,
        row: dict[str, object],
        *,
        current_price: float,
        avg_entry_price: float,
    ) -> list[tuple[str, float, str | None]]:
        profile = self.config.winner_capture
        quantity = float(row.get("quantity") or 0)
        initial_quantity = float(row.get("total_buy_quantity") or quantity)
        initial_cost = float(row.get("total_buy_notional_usdc") or (initial_quantity * avg_entry_price))
        if quantity <= 0 or initial_quantity <= 0 or initial_cost <= 0:
            return []

        fill_price = max(0.0, current_price * (1 - self.config.paper.slippage_pct / 100))
        if fill_price <= 0:
            return []
        profit_pct = ((fill_price - avg_entry_price) / avg_entry_price) * 100
        plans: list[tuple[str, float, str | None]] = []
        remaining = quantity
        half_stake_done = bool(row.get("winner_capture_first_scale_done"))
        full_stake_done = bool(row.get("winner_capture_stake_recovered"))
        high_price_done = bool(row.get("winner_capture_high_price_done"))

        if (
            not half_stake_done
            and current_price >= profile.sports_mid_partial_price_threshold
            and profit_pct >= profile.sports_mid_partial_profit_pct
        ):
            target_proceeds = initial_cost * (profile.sports_mid_partial_stake_pct / 100)
            sell_quantity = min(remaining, target_proceeds / fill_price)
            plans.append(("sports_winner_recover_half_stake", sell_quantity, "winner_capture_first_scale_done"))
            remaining -= sell_quantity
            half_stake_done = True

        if remaining > 1e-9 and not full_stake_done and current_price >= profile.sports_mid_full_stake_price_threshold:
            recovered_proceeds = initial_cost * (profile.sports_mid_partial_stake_pct / 100) if half_stake_done else 0.0
            target_proceeds = max(0.0, initial_cost - recovered_proceeds)
            sell_quantity = min(remaining, target_proceeds / fill_price)
            if sell_quantity > 1e-9:
                plans.append(("sports_winner_recover_stake", sell_quantity, "winner_capture_stake_recovered"))
                remaining -= sell_quantity
            full_stake_done = True

        if remaining > 1e-9 and not high_price_done and current_price >= profile.sports_mid_high_price_threshold:
            runner_quantity = initial_quantity * (profile.sports_mid_runner_pct / 100)
            scale_quantity = remaining * (profile.sports_mid_high_price_sell_pct / 100)
            runner_limit_quantity = max(0.0, remaining - runner_quantity)
            sell_quantity = min(scale_quantity, runner_limit_quantity) if runner_limit_quantity > 0 else scale_quantity
            if sell_quantity > 1e-9:
                plans.append(("sports_winner_high_price", sell_quantity, "winner_capture_high_price_done"))
        return plans

    def _with_updated_trailing_state(self, row: dict[str, object]) -> dict[str, object]:
        current_price = _float_or_none(row.get("current_price"))
        avg_entry_price = _float_or_none(row.get("avg_entry_price"))
        if current_price is None or avg_entry_price is None or avg_entry_price <= 0:
            return row
        wallet = self.store.get_wallet(str(row.get("source_wallet") or ""))
        market_type = str(row.get("market_type") or "other")
        if not wallet or market_type != "sports" or not _sports_trailing_stop_enabled(wallet):
            return row

        previous_peak = _float_or_none(row.get("trailing_peak_price")) or avg_entry_price
        peak_price = max(previous_peak, current_price, avg_entry_price)
        activation_pct = _wallet_float(wallet, "sports_trailing_activation_pct", 0.0)
        peak_gain_pct = ((peak_price - avg_entry_price) / avg_entry_price) * 100
        activated = bool(row.get("trailing_activated")) or peak_gain_pct >= activation_pct
        if peak_price != previous_peak or activated != bool(row.get("trailing_activated")):
            self.store.update_position_trailing_state(
                asset_id=str(row["asset_id"]),
                source_wallet=str(row["source_wallet"]),
                peak_price=peak_price,
                activated=activated,
            )
            updated = dict(row)
            updated["trailing_peak_price"] = peak_price
            updated["trailing_activated"] = activated
            return updated
        return row

    def _sports_trailing_stop_reason(
        self,
        row: dict[str, object],
        *,
        wallet: dict[str, object] | None,
        current_price: float,
        avg_entry_price: float,
        market_type: str,
    ) -> str | None:
        if not wallet or market_type != "sports" or not _sports_trailing_stop_enabled(wallet):
            return None
        if not bool(row.get("trailing_activated")):
            return None
        peak_price = _float_or_none(row.get("trailing_peak_price")) or max(current_price, avg_entry_price)
        stop_pct = _wallet_float(wallet, "sports_trailing_stop_pct", 0.0)
        floor_delta = _wallet_float(wallet, "sports_trailing_floor_delta", 0.0)
        if stop_pct <= 0:
            return None
        trailing_stop_price = max(peak_price * (1 - stop_pct / 100), avg_entry_price + floor_delta)
        expected_fill_price = current_price * (1 - self.config.paper.slippage_pct / 100)
        if expected_fill_price <= avg_entry_price:
            return None
        return "trailing_stop" if current_price <= trailing_stop_price else None

    def _local_exit_trade(
        self,
        row: dict[str, object],
        *,
        reason: str,
        price: float | None = None,
        quantity: float | None = None,
    ) -> SourceTrade:
        now = datetime.now(tz=PDT).strftime("%Y-%m-%d %H:%M PDT")
        now_epoch = int(datetime.now(tz=PDT).timestamp())
        unique_suffix = time.time_ns()
        asset_id = str(row["asset_id"])
        source_wallet = str(row["source_wallet"]).lower()
        position_quantity = float(row["quantity"] or 0)
        quantity = position_quantity if quantity is None else min(float(quantity), position_quantity)
        exit_price = float(row["current_price"] if price is None else price)
        notional = round(quantity * exit_price, 6)
        return SourceTrade(
            idempotency_key=f"local:{reason}:{asset_id}:{source_wallet}:{unique_suffix}",
            chain_id=137,
            exchange_contract="local_exit",
            tx_hash=f"local:{reason}:{asset_id}:{unique_suffix}",
            block_number=now_epoch,
            block_timestamp=now,
            log_index=0,
            source_wallet=source_wallet,
            side="sell",
            asset_id=asset_id,
            price=exit_price,
            quantity=quantity,
            notional_usdc=notional,
            condition_id=str(row["condition_id"]) if row.get("condition_id") else None,
            market_id=str(row["market_id"]) if row.get("market_id") else None,
            outcome=str(row["outcome"]) if row.get("outcome") else None,
            copy_trade_key=f"local:{reason}:{asset_id}:{source_wallet}:{unique_suffix}",
        )

    def _hydrate_open_positions(self) -> None:
        for row in self.store.list_positions():
            quantity = float(row["quantity"] or 0)
            avg_entry_price = float(row["avg_entry_price"] or 0)
            if quantity <= 0:
                continue
            source_wallet = str(row["source_wallet"]).lower()
            position = self.broker.positions.setdefault(
                self.broker.position_key(row["asset_id"], source_wallet),
                Position(asset_id=row["asset_id"], source_wallet=source_wallet),
            )
            position.lots.append(
                PositionLot(
                    quantity=quantity,
                    entry_price=avg_entry_price,
                    source_wallet=source_wallet,
                    source_idempotency_key=f"hydrated:{row['asset_id']}:{source_wallet}",
                )
            )
            position.realized_pnl_usdc = float(row["realized_pnl_usdc"] or 0)

    def _available_cash_for_wallet(self, source_wallet: str) -> float:
        clean_source = source_wallet.lower()
        reserved_for_other_wallets = 0.0
        for wallet in self.store.list_wallets():
            if not wallet.get("enabled"):
                continue
            if str(wallet.get("address") or "").lower() == clean_source:
                continue
            reserved_for_other_wallets += _wallet_float(wallet, "reserved_cash_usdc", 0.0)
        return max(0.0, self.broker.cash_usdc - reserved_for_other_wallets)

    def _filter_copy_deployed_cap_usage_usdc(self, source_wallet: str) -> float:
        # Limit current deployed capital, not gross same-day turnover after positions are closed.
        wallet = self.store.get_wallet(source_wallet) or {}
        cap_credit_price = _filter_copy_cap_credit_price(wallet)
        usage = 0.0
        for position in self.store.list_positions():
            if str(position.get("source_wallet") or "").lower() != source_wallet.lower():
                continue
            if str(position.get("status") or "").lower() != "open" or float(position.get("quantity") or 0) <= 0:
                continue
            mark = _float_or_none(position.get("resolution_price")) if position.get("is_closed") else None
            if mark is None:
                mark = _float_or_none(position.get("current_price"))
            if mark is not None and mark >= cap_credit_price:
                continue
            usage += float(position.get("cost_basis_usdc") or 0)
        return round(usage, 6)

    def _filter_copy_risk_reducing_repair_notional(
        self,
        *,
        same_event_positions: object,
        asset_id: str,
        planned_notional: float,
        executable_price: float,
    ) -> float:
        if not isinstance(same_event_positions, list) or planned_notional <= 0 or executable_price <= 0:
            return 0.0
        before_risk = _filter_copy_event_worst_case_loss(same_event_positions)
        if before_risk <= 0:
            return 0.0
        best_notional = 0.0
        best_risk = before_risk
        steps = 100
        for step in range(1, steps + 1):
            candidate_notional = planned_notional * step / steps
            repair_position = {
                "asset_id": asset_id,
                "cost_basis_usdc": candidate_notional,
                "quantity": candidate_notional / executable_price,
            }
            after_risk = _filter_copy_event_worst_case_loss([*same_event_positions, repair_position])
            if after_risk < before_risk and after_risk <= best_risk:
                best_notional = candidate_notional
                best_risk = after_risk
        return round(best_notional, 6)

    def _filter_copy_material_risk_reducing_repair_notional(
        self,
        *,
        same_event_positions: object,
        asset_id: str,
        planned_notional: float,
        executable_price: float,
        wallet: dict[str, Any],
    ) -> float:
        if not isinstance(same_event_positions, list) or planned_notional <= 0 or executable_price <= 0:
            return 0.0
        before_risk = _filter_copy_event_worst_case_loss(same_event_positions)
        if before_risk <= 0:
            return 0.0
        min_improvement = _filter_copy_rebalance_min_worst_case_improvement_fraction(wallet)
        required_risk = before_risk * (1.0 - min_improvement)
        best_notional = 0.0
        best_risk = before_risk
        steps = 100
        for step in range(1, steps + 1):
            candidate_notional = planned_notional * step / steps
            repair_position = {
                "asset_id": asset_id,
                "cost_basis_usdc": candidate_notional,
                "quantity": candidate_notional / executable_price,
            }
            after_risk = _filter_copy_event_worst_case_loss([*same_event_positions, repair_position])
            if after_risk <= required_risk + 0.000001 and after_risk <= best_risk:
                best_notional = candidate_notional
                best_risk = after_risk
        return round(best_notional, 6)

    def _filter_copy_price_haircut_repair_notional(
        self,
        *,
        planned_notional: float,
        executable_price: float,
        wallet: dict[str, Any],
    ) -> float:
        planned = float(planned_notional or 0)
        if planned <= 0:
            return 0.0
        max_price = _filter_copy_rn1_repair_max_local_price(wallet)
        if executable_price >= max_price:
            return 0.0
        if executable_price <= _filter_copy_max_source_price(RN1_WALLET, wallet):
            return round(planned, 6)
        denominator = max(0.01, max_price - _filter_copy_max_source_price(RN1_WALLET, wallet))
        haircut = max(0.25, min(1.0, (max_price - executable_price) / denominator))
        return round(max(self._minimum_buy_notional_usdc(), planned * haircut), 6)

    def _cash_skip_reason(self, available_cash: float) -> str:
        if self.broker.cash_usdc >= self.config.sizing.min_trade_usdc and available_cash < self.config.sizing.min_trade_usdc:
            return "reserved_cash"
        return "insufficient_cash"

    def _buy_price_block_reason(self, executable_price: float, source_reference_price: float) -> str | None:
        if executable_price <= 0 or source_reference_price <= 0:
            return None
        effective_entry = executable_price * (1 + self.config.paper.slippage_pct / 100)
        if effective_entry >= 1.0:
            return "entry_price_at_one"
        max_allowed = min(
            source_reference_price + self.config.sizing.max_entry_price_source_premium,
            source_reference_price * self.config.sizing.max_entry_price_source_multiple,
        )
        if effective_entry > max_allowed:
            return "entry_price_drift_blocked"
        return None

    def _binary_hedge_adjusted_notional(
        self,
        *,
        trade: SourceTrade,
        observed_price: float,
        target_notional: float,
        wallet: dict[str, Any],
    ) -> float:
        if not _binary_condition_hedge_enabled(trade.source_wallet, wallet):
            return target_notional
        opposite_position = self._opposite_condition_position(
            source_wallet=trade.source_wallet,
            asset_id=trade.asset_id,
        )
        if opposite_position is None:
            return target_notional
        effective_entry_price = observed_price * (1 + self.config.paper.slippage_pct / 100)
        if effective_entry_price <= 0 or effective_entry_price >= 1:
            return target_notional
        open_cost = float(opposite_position.get("cost_basis_usdc") or 0)
        if open_cost <= 0:
            return target_notional
        hedge_notional = open_cost * effective_entry_price / (1 - effective_entry_price)
        return min(target_notional, hedge_notional)

    def _opposite_condition_position(self, *, source_wallet: str, asset_id: str) -> dict[str, Any] | None:
        metadata = self._metadata_for(asset_id)
        condition_id = str(metadata.get("condition_id") or "").strip()
        if not condition_id:
            return None
        source = source_wallet.lower()
        for row in self.store.list_positions():
            if str(row.get("source_wallet") or "").lower() != source:
                continue
            if str(row.get("asset_id") or "") == str(asset_id):
                continue
            if str(row.get("condition_id") or "").strip() == condition_id:
                return row
        return None

    def _opposite_condition_breakout(self, row: dict[str, object]) -> bool:
        condition_id = str(row.get("condition_id") or "").strip()
        if not condition_id:
            return False
        source_wallet = str(row.get("source_wallet") or "").lower()
        asset_id = str(row.get("asset_id") or "")
        profile = self.config.winner_capture
        for other in self.store.list_positions():
            if str(other.get("source_wallet") or "").lower() != source_wallet:
                continue
            if str(other.get("asset_id") or "") == asset_id:
                continue
            if str(other.get("condition_id") or "").strip() != condition_id:
                continue
            if (_float_or_none(other.get("quantity")) or 0.0) <= 0:
                continue
            if any(
                bool(other.get(field))
                for field in (
                    "winner_capture_stake_recovered",
                    "winner_capture_first_scale_done",
                    "winner_capture_high_price_done",
                )
            ):
                return True
            current_price = _float_or_none(other.get("current_price"))
            avg_entry_price = _float_or_none(other.get("avg_entry_price"))
            if current_price is None or avg_entry_price is None or avg_entry_price <= 0:
                continue
            if avg_entry_price <= profile.entry_price_max and current_price >= avg_entry_price * profile.recover_stake_multiple:
                return True
        return False

    def _repeat_buy_market_blocked(self, metadata: dict[str, Any], wallet: dict[str, Any]) -> bool:
        return self._configured_market_filter_blocked(metadata, wallet, section="repeat_buy")

    def _event_follow_market_blocked(self, metadata: dict[str, Any], wallet: dict[str, Any]) -> bool:
        return self._configured_market_filter_blocked(metadata, wallet, section="event_follow")

    def _configured_market_filter_blocked(self, metadata: dict[str, Any], wallet: dict[str, Any], *, section: str) -> bool:
        if section == "repeat_buy":
            patterns = _wallet_profile_list(
                wallet,
                "repeat_buy",
                "blocked_title_patterns",
                wallet.get("repeat_buy_blocked_title_patterns", []),
                lower=True,
            )
            allowed_sports = set(
                _wallet_profile_list(
                    wallet,
                    "repeat_buy",
                    "allowed_sports",
                    wallet.get("repeat_buy_allowed_sports", []),
                    lower=True,
                )
            )
            allowed_bet_types = set(
                _wallet_profile_list(
                    wallet,
                    "repeat_buy",
                    "allowed_bet_types",
                    wallet.get("repeat_buy_allowed_bet_types", []),
                    lower=True,
                )
            )
        else:
            patterns = _wallet_profile_list(wallet, section, "blocked_title_patterns", [], lower=True)
            allowed_sports = set(_wallet_profile_list(wallet, section, "allowed_sports", [], lower=True))
            allowed_bet_types = set(_wallet_profile_list(wallet, section, "allowed_bet_types", [], lower=True))
        text = _metadata_text(metadata)
        if any(pattern in text for pattern in patterns):
            return True
        if allowed_sports and _event_sport_group(metadata) not in allowed_sports:
            return True
        if allowed_bet_types and _event_bet_type(metadata) not in allowed_bet_types:
            return True
        return False


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot_source_notional_usdc(snapshot: dict[str, Any]) -> float:
    for key in ("net_notional_usdc", "notional_usdc", "cost_usdc", "initialValue", "cashPnl"):
        value = _float_or_none(snapshot.get(key))
        if value is not None and value > 0:
            return value
    avg_price = _float_or_none(snapshot.get("avg_buy_price") or snapshot.get("avg_price") or snapshot.get("avgPrice"))
    size = _float_or_none(snapshot.get("net_quantity") or snapshot.get("quantity") or snapshot.get("size"))
    if avg_price is not None and size is not None and avg_price > 0 and size > 0:
        return size * avg_price if avg_price <= 1 else size
    current_value = _float_or_none(snapshot.get("currentValue") or snapshot.get("value"))
    return current_value if current_value is not None and current_value > 0 else 0.0


def _signal_avg_price(signal: dict[str, Any]) -> float:
    quantity = float(signal.get("source_quantity") or 0)
    if quantity <= 0:
        return 0.0
    return float(signal.get("source_notional_usdc") or 0) / quantity


def _store_market_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "current_price",
        "price_source",
        "market_id",
        "condition_id",
        "outcome",
        "title",
        "market_slug",
        "market_url",
        "market_type",
        "sport_key",
        "bet_type",
        "series_slug",
        "sports_market_type",
        "category_slug",
        "market_close_time",
        "market_close_time_kind",
        "event_slug",
        "event_title",
        "neg_risk",
        "mergeable",
        "is_closed",
        "resolution_price",
        "last_price_at",
    }
    return {key: metadata[key] for key in allowed_keys if key in metadata}


def _metadata_missing_structured_sports_fields(metadata: dict[str, Any] | None) -> bool:
    if not metadata or str(metadata.get("market_type") or "").lower() != "sports":
        return False
    return not str(metadata.get("sport_key") or "").strip() or not str(metadata.get("bet_type") or "").strip()


def _weather_bracket_pattern(metadata: dict[str, Any]) -> str:
    text = " ".join(
        str(metadata.get(key) or "")
        for key in ("title", "market_slug", "event_slug", "event_title", "outcome")
    ).lower()
    if any(token in text for token in ("between", "range", " to ", "through")):
        return "range"
    if any(token in text for token in ("or higher", "above", "over ", " at least ", "greater than")):
        return "above_or_higher"
    if any(token in text for token in ("or lower", "below", "under ", " at most ", "less than")):
        return "below_or_lower"
    return "exact_or_binary"


def _near_zero_exit_confirmed(row: dict[str, object]) -> bool:
    if bool(row.get("is_closed")) or _float_or_none(row.get("resolution_price")) is not None:
        return True
    if str(row.get("market_type") or "").lower() == "sports" and str(row.get("event_slug") or "").strip():
        return False
    price_source = str(row.get("price_source") or "").lower()
    return price_source not in {"clob_ws_price_change", "clob_midpoint", "clob_no_orderbook", "clob_sell"}


_WALLET_FLOAT_PROFILE_KEYS: dict[str, tuple[str, str]] = {
    "bracket_buy_size_usdc": ("weather_bracket", "buy_size_usdc"),
    "bracket_stop_loss_pct": ("weather_bracket", "stop_loss_pct"),
    "repeat_buy_size_usdc": ("repeat_buy", "buy_size_usdc"),
    "repeat_buy_stop_loss_pct": ("repeat_buy", "stop_loss_pct"),
    "repeat_buy_min_source_notional_usdc": ("repeat_buy", "min_source_notional_usdc"),
    "repeat_buy_min_avg_price": ("repeat_buy", "min_avg_price"),
    "repeat_buy_max_avg_price": ("repeat_buy", "max_avg_price"),
    "repeat_buy_max_total_exposure_usdc": ("repeat_buy", "max_total_exposure_usdc"),
    "event_follow_buy_size_usdc": ("event_follow", "buy_size_usdc"),
    "event_follow_max_event_exposure_usdc": ("event_follow", "max_event_exposure_usdc"),
    "event_follow_max_total_exposure_usdc": ("event_follow", "max_total_exposure_usdc"),
    "event_follow_min_source_trade_usdc": ("event_follow", "min_source_trade_usdc"),
    "event_follow_min_event_source_notional_usdc": ("event_follow", "min_event_source_notional_usdc"),
    "event_follow_min_avg_price": ("event_follow", "min_avg_price"),
    "event_follow_max_avg_price": ("event_follow", "max_avg_price"),
    "sports_trailing_activation_pct": ("sports_trailing", "activation_pct"),
    "sports_trailing_stop_pct": ("sports_trailing", "stop_pct"),
    "sports_trailing_floor_delta": ("sports_trailing", "floor_delta"),
    "reserved_cash_usdc": ("risk", "reserved_cash_usdc"),
}

_WALLET_INT_PROFILE_KEYS: dict[str, tuple[str, str]] = {
    "bracket_max_open_events": ("weather_bracket", "max_open_events"),
    "repeat_buy_min_buy_count": ("repeat_buy", "min_buy_count"),
    "event_follow_min_event_buy_count": ("event_follow", "min_event_buy_count"),
}


def _wallet_bool_profile(
    wallet: dict[str, object] | None,
    legacy_key: str,
    section: str,
    profile_key: str,
    default: bool = False,
) -> bool:
    legacy_enabled = bool(wallet and wallet.get(legacy_key, default))
    return _wallet_profile_bool(wallet, section, profile_key, legacy_enabled)


def _weather_bracket_strategy_enabled(wallet: dict[str, object] | None) -> bool:
    return _wallet_bool_profile(wallet, "bracket_strategy_enabled", "weather_bracket", "enabled")


def _repeat_buy_strategy_enabled(wallet: dict[str, object] | None) -> bool:
    return _wallet_bool_profile(wallet, "repeat_buy_strategy_enabled", "repeat_buy", "enabled")


def _event_follow_strategy_enabled(wallet: dict[str, object] | None) -> bool:
    return _wallet_bool_profile(wallet, "event_follow_strategy_enabled", "event_follow", "enabled")


def _sports_trailing_stop_enabled(wallet: dict[str, object] | None) -> bool:
    return _wallet_bool_profile(wallet, "sports_trailing_stop_enabled", "sports_trailing", "enabled")


def _legacy_wallet_float(wallet: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(wallet.get(key, default))
    except (TypeError, ValueError):
        return default


def _wallet_float(wallet: dict[str, Any], key: str, default: float) -> float:
    legacy_value = _legacy_wallet_float(wallet, key, default)
    profile_key = _WALLET_FLOAT_PROFILE_KEYS.get(key)
    if profile_key is None:
        return legacy_value
    section, field = profile_key
    return _wallet_profile_float(wallet, section, field, legacy_value)


def _legacy_wallet_int(wallet: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(wallet.get(key, default))
    except (TypeError, ValueError):
        return default


def _wallet_int(wallet: dict[str, Any], key: str, default: int) -> int:
    legacy_value = _legacy_wallet_int(wallet, key, default)
    profile_key = _WALLET_INT_PROFILE_KEYS.get(key)
    if profile_key is None:
        return legacy_value
    section, field = profile_key
    return _wallet_profile_int(wallet, section, field, legacy_value)


def _market_is_closed_for_new_buy(metadata: dict[str, Any], *, market_type: str) -> bool:
    if bool(metadata.get("is_closed")) or _float_or_none(metadata.get("resolution_price")) is not None:
        return True
    if (
        market_type == "sports"
        and metadata.get("event_slug")
        and not bool(metadata.get("is_closed"))
        and _float_or_none(metadata.get("resolution_price")) is None
    ):
        return False
    return _market_close_time_has_passed(metadata.get("market_close_time"))


def _market_close_time_has_passed(value: object, *, grace_minutes: int = 0) -> bool:
    close_time = _parse_market_close_time(value)
    if close_time is None:
        return False
    return datetime.now(tz=PDT) >= close_time + timedelta(minutes=grace_minutes)


def _decision_latency_ms(source_timestamp: object) -> int | None:
    source_time = _parse_market_close_time(source_timestamp)
    if source_time is None:
        return None
    return max(0, int((datetime.now(tz=PDT) - source_time).total_seconds() * 1000))


def _parse_market_close_time(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(PDT) if value.tzinfo else value.replace(tzinfo=PDT)
    text = str(value).strip()
    if not text:
        return None
    for suffix, tz in ((" PDT", PDT), (" PST", timezone(timedelta(hours=-8), "PST"))):
        if text.endswith(suffix):
            try:
                return datetime.strptime(text[: -len(suffix)], "%Y-%m-%d %H:%M").replace(tzinfo=tz).astimezone(PDT)
            except ValueError:
                return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=PDT)
        except ValueError:
            return None
    return parsed.astimezone(PDT) if parsed.tzinfo else parsed.replace(tzinfo=PDT)


def _is_live_event_managed(wallet: dict[str, object] | None, market_type: str) -> bool:
    if market_type not in {"sports", "other"} or not wallet:
        return False
    return _repeat_buy_strategy_enabled(wallet) or _event_follow_strategy_enabled(wallet)


def _event_follow_stop_loss_managed(
    wallet: dict[str, object] | None,
    *,
    source_wallet: str,
    market_type: str,
) -> bool:
    if not wallet or not _event_follow_strategy_enabled(wallet):
        return False
    legacy_managed = market_type == "weather" or (source_wallet.lower() == SWISSTONY_WALLET and market_type == "sports")
    if _wallet_profile_has(wallet, "risk", "local_stop_loss_enabled"):
        return not _wallet_profile_bool(wallet, "risk", "local_stop_loss_enabled", not legacy_managed)
    return legacy_managed


def _is_sports_mid_price_winner_capture(
    row: dict[str, object],
    avg_entry_price: float,
    profile: WinnerCaptureConfig,
) -> bool:
    if str(row.get("market_type") or "").lower() != "sports":
        return False
    if bool(row.get("is_closed")):
        return False
    return profile.entry_price_max < avg_entry_price <= profile.sports_mid_entry_price_max


def _sports_pre_end_lock_profit(
    row: dict[str, object],
    current_price: float,
    avg_entry_price: float,
    slippage_pct: float,
) -> bool:
    if str(row.get("market_type") or "").lower() != "sports":
        return False
    if bool(row.get("is_closed")) or _float_or_none(row.get("resolution_price")) is not None:
        return False
    if current_price < SPORTS_PRE_END_LOCK_PRICE:
        return False
    effective_exit_price = current_price * (1 - max(0.0, float(slippage_pct)) / 100)
    return effective_exit_price >= avg_entry_price * SPORTS_PRE_END_LOCK_PROFIT_MULTIPLE


def _sports_dead_cut(
    row: dict[str, object],
    *,
    current_price: float,
    avg_entry_price: float,
    live_event_managed: bool,
    profile: WinnerCaptureConfig,
) -> bool:
    if not profile.enabled:
        return False
    if str(row.get("market_type") or "").lower() != "sports":
        return False
    if bool(row.get("is_closed")) or not live_event_managed:
        return False
    if current_price <= NEAR_ZERO_EXIT_PRICE:
        return False
    if current_price > profile.sports_dead_cut_price:
        return False
    peak_price = _float_or_none(row.get("trailing_peak_price")) or avg_entry_price
    peak_gain_pct = ((peak_price - avg_entry_price) / avg_entry_price) * 100 if avg_entry_price > 0 else 0.0
    return peak_gain_pct <= profile.sports_dead_cut_max_peak_gain_pct


def _sports_event_lost_after_close(
    row: dict[str, object],
    *,
    current_price: float,
    live_event_managed: bool,
) -> bool:
    if str(row.get("market_type") or "").lower() != "sports":
        return False
    if bool(row.get("is_closed")) or _float_or_none(row.get("resolution_price")) is not None:
        return False
    if not live_event_managed or current_price > NEAR_ZERO_EXIT_PRICE:
        return False
    price_source = str(row.get("price_source") or "").lower()
    if price_source == "clob_no_orderbook":
        grace_minutes = NEAR_ZERO_AFTER_CLOSE_GRACE_MINUTES
    elif price_source in {"clob_sell", "clob_midpoint", "clob_ws_price_change", "gamma_outcome"}:
        grace_minutes = SPORTS_QUOTED_LOSER_AFTER_CLOSE_GRACE_MINUTES
    else:
        return False
    return _market_close_time_has_passed(
        row.get("market_close_time"),
        grace_minutes=grace_minutes,
    )


def _filter_copy_in_event_stop_loss(
    row: dict[str, object],
    wallet: dict[str, object],
    *,
    current_price: float,
    avg_entry_price: float,
) -> bool:
    pct = _filter_copy_in_event_stop_loss_pct(wallet)
    if pct <= 0:
        return False
    if str(row.get("market_type") or "").lower() != "sports":
        return False
    if bool(row.get("is_closed")) or _float_or_none(row.get("resolution_price")) is not None:
        return False
    if not _filter_copy_event_has_started(row):
        return False
    stop_price = avg_entry_price * (1 - pct / 100)
    return current_price <= stop_price


def _filter_copy_event_has_started(row: dict[str, object]) -> bool:
    if str(row.get("market_type") or "").lower() != "sports":
        return False
    kind = str(row.get("market_close_time_kind") or "").lower()
    if kind == "actual_close":
        return False
    if kind not in {"", "event_start"}:
        return False
    return _market_close_time_has_passed(row.get("market_close_time"))


def _binary_condition_hedge_enabled(source_wallet: str, wallet: dict[str, object]) -> bool:
    wallet_name = str(wallet.get("name") or "").strip().lower()
    source = source_wallet.lower()
    legacy_enabled = source in {RN1_WALLET, SWISSTONY_WALLET} or wallet_name in {"rn1", "swisstony"}
    return _wallet_profile_bool(wallet, "binary_hedge", "enabled", legacy_enabled)


def _rn1_source_follow_enabled(source_wallet: str, wallet: dict[str, object]) -> bool:
    legacy_enabled = source_wallet.lower() == RN1_WALLET
    return _wallet_profile_bool(wallet, "source_follow", "enabled", legacy_enabled)


def _swisstony_source_follow_enabled(wallet: dict[str, object]) -> bool:
    legacy_enabled = (
        _wallet_float(wallet, "event_follow_max_event_exposure_usdc", 0.0) >= 50.0
        and _wallet_float(wallet, "event_follow_max_total_exposure_usdc", 0.0) >= 150.0
    )
    return _wallet_profile_bool(wallet, "source_follow", "enabled", legacy_enabled)


def _custom_strategy_enabled(wallet: dict[str, object]) -> bool:
    legacy_enabled = str(wallet.get("strategy_label") or "").strip().lower() == "custom"
    return _wallet_profile_bool(wallet, "strategy", "custom", legacy_enabled)


def _copy_buys_enabled(wallet: dict[str, object]) -> bool:
    return _wallet_profile_bool(wallet, "strategy", "copy_buys_enabled", True)


def _filter_copy_enabled(source_wallet: str, wallet: dict[str, object]) -> bool:
    source = source_wallet.lower()
    legacy_enabled = source in {RN1_WALLET, SWISSTONY_WALLET}
    return _wallet_profile_bool(wallet, "filter_copy", "enabled", legacy_enabled)


def _source_wallet_paused_sport_reason(source_wallet: str, metadata: dict[str, Any], wallet: dict[str, object]) -> str | None:
    default: list[str] = []
    paused_sports = set(_wallet_profile_list(wallet, "filter_copy", "paused_sports", default, lower=True))
    sport = _event_sport_group(metadata)
    if paused_sports and sport in paused_sports:
        if source_wallet.lower() == RN1_WALLET and sport in RN1_FILTER_COPY_TENNIS_SPORTS:
            return "rn1_tennis_paused"
        return f"{sport}_paused" if sport else "sport_paused"
    return None


def _filter_copy_rebalance_section(wallet: dict[str, object]) -> dict[str, Any]:
    section = _wallet_profile_section(wallet, "filter_copy").get("rebalance")
    return section if isinstance(section, dict) else {}


def _filter_copy_rebalance_enabled(source_wallet: str, wallet: dict[str, object]) -> bool:
    value = _filter_copy_rebalance_section(wallet).get("enabled")
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
    return source_wallet.lower() in {RN1_WALLET, SWISSTONY_WALLET}


def _filter_copy_rebalance_float(wallet: dict[str, object], key: str, default: float) -> float:
    try:
        return float(_filter_copy_rebalance_section(wallet).get(key, default))
    except (TypeError, ValueError):
        return default


def _filter_copy_rebalance_allowed_sports(source_wallet: str, wallet: dict[str, object]) -> set[str]:
    default = (
        FILTER_COPY_SWISSTONY_REBALANCE_SPORTS
        if source_wallet.lower() == SWISSTONY_WALLET
        else FILTER_COPY_RN1_REBALANCE_SPORTS
    )
    value = _filter_copy_rebalance_section(wallet).get("allowed_sports", list(default))
    if not isinstance(value, list | tuple):
        return set(default)
    sports = {str(item).strip().lower() for item in value if str(item).strip()}
    return sports or set(default)


def _filter_copy_event_worst_case_loss(positions: Iterable[dict[str, Any]]) -> float:
    total_cost = 0.0
    payoff_by_asset: dict[str, float] = {}
    for position in positions:
        asset_id = str(position.get("asset_id") or "").strip()
        if not asset_id:
            continue
        total_cost += max(0.0, float(position.get("cost_basis_usdc") or 0))
        payoff_by_asset[asset_id] = payoff_by_asset.get(asset_id, 0.0) + max(0.0, float(position.get("quantity") or 0))
    if total_cost <= 0:
        return 0.0
    if len(payoff_by_asset) < 2:
        return round(total_cost, 6)
    return round(max(0.0, total_cost - min(payoff_by_asset.values())), 6)


def _filter_copy_sport_rule(
    source_wallet: str,
    metadata: dict[str, Any],
    wallet: dict[str, object],
) -> dict[str, Any] | None:
    if source_wallet.lower() != SWISSTONY_WALLET:
        return None
    rules = _wallet_profile_section(wallet, "filter_copy").get("sport_rules")
    if not isinstance(rules, dict):
        return None
    rule = rules.get(_event_sport_group(metadata))
    if not isinstance(rule, dict):
        return None
    if not _rule_bool(rule, "enabled", True):
        return None
    return rule


def _filter_copy_market_rule_block_reason(
    source_wallet: str,
    metadata: dict[str, Any],
    wallet: dict[str, object],
    source_position: dict[str, Any],
    event_book_role: dict[str, Any],
) -> str | None:
    rule = _filter_copy_sport_rule(source_wallet, metadata, wallet)
    if rule is None:
        return None
    allowed_bet_types = _rule_string_set(rule, "allowed_bet_types", FILTER_COPY_ALLOWED_BET_TYPES)
    if _event_bet_type(metadata) not in allowed_bet_types:
        return "filter_copy_market_rule_blocked"
    if int(source_position.get("buy_count") or 0) < _rule_int(rule, "min_buy_count", 1):
        return "filter_copy_market_rule_blocked"
    source_notional = float(source_position.get("net_notional_usdc") or source_position.get("buy_notional_usdc") or 0)
    if source_notional < _rule_float(rule, "min_source_notional_usdc", 0.0):
        return "filter_copy_market_rule_blocked"
    if _rule_bool(rule, "require_event_book_dominant", False) and event_book_role.get("role") != "dominant":
        return "filter_copy_market_rule_blocked"
    return None


def _filter_copy_sport_rule_buy_size(rule: dict[str, Any], source_price: float) -> float:
    price = float(source_price)
    min_price = _rule_float(rule, "min_price", 0.0)
    max_price = _rule_float(rule, "max_price", 0.0)
    if max_price > 0 and min_price <= price <= max_price:
        return _rule_float(rule, "buy_size_usdc", 0.0)
    extended_min = _rule_float(rule, "extended_min_price", 0.0)
    extended_max = _rule_float(rule, "extended_max_price", 0.0)
    if extended_max > 0 and extended_min <= price <= extended_max:
        return _rule_float(rule, "extended_buy_size_usdc", 0.0)
    return 0.0


def _rule_float(rule: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(rule.get(key, default))
    except (TypeError, ValueError):
        return default


def _rule_int(rule: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(rule.get(key, default))
    except (TypeError, ValueError):
        return default


def _rule_bool(rule: dict[str, Any], key: str, default: bool) -> bool:
    value = rule.get(key, default)
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


def _rule_string_set(rule: dict[str, Any], key: str, default: Iterable[str]) -> set[str]:
    value = rule.get(key, list(default))
    if not isinstance(value, list | tuple):
        value = list(default)
    return {str(item).strip().lower() for item in value if str(item).strip()} or {str(item).lower() for item in default}


def _filter_copy_market_block_reason(
    source_wallet: str,
    metadata: dict[str, Any],
    wallet: dict[str, object],
) -> str | None:
    text = _metadata_text(metadata)
    sport = _event_sport_group(metadata)
    bet_type = _event_bet_type(metadata)
    if sport not in _filter_copy_allowed_sports(source_wallet, wallet):
        return "filter_copy_market_blocked"
    if source_wallet.lower() == RN1_WALLET and sport == "esports" and bet_type not in {"moneyline_winlose", "map_or_game_winner"}:
        return "rn1_esports_map_winner_blocked"
    if bet_type not in _filter_copy_allowed_bet_types(wallet):
        return "filter_copy_market_blocked"
    patterns = _wallet_profile_list(
        wallet,
        "filter_copy",
        "blocked_title_patterns",
        [
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
        lower=True,
    )
    allowed_pattern_tokens = _filter_copy_allowed_pattern_tokens_for_bet_type(bet_type)
    if any(pattern in text and pattern not in allowed_pattern_tokens for pattern in patterns):
        return "filter_copy_market_blocked"
    return None


def _filter_copy_market_blocked_repair_candidate(
    source_wallet: str,
    metadata: dict[str, Any],
    wallet: dict[str, object],
) -> bool:
    clean_wallet = source_wallet.lower()
    if clean_wallet not in {RN1_WALLET, SWISSTONY_WALLET}:
        return False
    if _event_sport_group(metadata) not in _filter_copy_allowed_sports(source_wallet, wallet):
        return False
    bet_type = _event_bet_type(metadata)
    if clean_wallet == SWISSTONY_WALLET:
        return bet_type == "draw"
    return False


def _filter_copy_allowed_pattern_tokens_for_bet_type(bet_type: str) -> set[str]:
    if bet_type == "total_or_over_under":
        return {"o/u", "over/under", "total"}
    if bet_type == "spread_handicap":
        return {"spread", "handicap"}
    if bet_type == "both_teams_score":
        return {"both teams to score", "btts"}
    if bet_type == "map_or_game_winner":
        return {"map", "game"}
    return set()


def _rn1_filter_copy_is_main_winner_market(metadata: dict[str, Any]) -> bool:
    if _event_bet_type(metadata) != "moneyline_winlose":
        return False
    text = _metadata_text(metadata)
    blocked_fragments = (
        "end in a draw",
        " draw",
        "o/u",
        "over/under",
        " total",
        " spread",
        "handicap",
        "both teams to score",
        " btts ",
        " parlay",
    )
    return not any(fragment in f" {text} " for fragment in blocked_fragments)


def _event_book_position_with_metadata(position: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(position)
    for key in ("title", "outcome", "event_slug", "event_title", "market_slug", "sport_key", "bet_type"):
        value = metadata.get(key)
        if value not in (None, ""):
            enriched[key] = value
    return enriched


def _filter_copy_allowed_sports(source_wallet: str, wallet: dict[str, object]) -> set[str]:
    default = FILTER_COPY_SWISSTONY_SPORTS if source_wallet.lower() == SWISSTONY_WALLET else FILTER_COPY_RN1_SPORTS
    values = set(_wallet_profile_list(wallet, "filter_copy", "allowed_sports", list(default), lower=True))
    return values or set(default)


def _filter_copy_allowed_bet_types(wallet: dict[str, object]) -> set[str]:
    values = set(_wallet_profile_list(wallet, "filter_copy", "allowed_bet_types", list(FILTER_COPY_ALLOWED_BET_TYPES), lower=True))
    return values or set(FILTER_COPY_ALLOWED_BET_TYPES)


def _rn1_filter_copy_requires_event_book_dominance(source_wallet: str, metadata: dict[str, Any]) -> bool:
    if source_wallet.lower() != RN1_WALLET:
        return False
    sport = _event_sport_group(metadata)
    bet_type = _event_bet_type(metadata)
    return sport in RN1_FILTER_COPY_TENNIS_SPORTS or (sport == "esports" and bet_type == "map_or_game_winner")


def _rn1_filter_copy_event_book_min_dominance_share(
    source_wallet: str,
    metadata: dict[str, Any],
    wallet: dict[str, object],
    *,
    has_event_exposure: bool,
) -> float:
    default = _wallet_profile_float(
        wallet,
        "event_book",
        "min_dominance_share",
        RN1_EVENT_BOOK_MIN_DOMINANCE_SHARE,
    )
    if (
        source_wallet.lower() == RN1_WALLET
        and not has_event_exposure
        and _event_sport_group(metadata) in RN1_FILTER_COPY_TENNIS_SPORTS
    ):
        tennis_default = _wallet_profile_float(
            wallet,
            "event_book",
            "tennis_fresh_min_dominance_share",
            RN1_FILTER_COPY_TENNIS_FRESH_MIN_DOMINANCE_SHARE,
        )
        return max(default, tennis_default)
    if (
        source_wallet.lower() == RN1_WALLET
        and not has_event_exposure
        and _event_sport_group(metadata) == "esports"
        and _event_bet_type(metadata) == "map_or_game_winner"
    ):
        esports_default = _wallet_profile_float(
            wallet,
            "event_book",
            "esports_fresh_min_dominance_share",
            RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_SHARE,
        )
        return max(default, esports_default)
    return default


def _rn1_filter_copy_event_book_min_dominance_ratio(
    source_wallet: str,
    metadata: dict[str, Any],
    wallet: dict[str, object],
    *,
    has_event_exposure: bool,
) -> float:
    default = _wallet_profile_float(
        wallet,
        "event_book",
        "min_dominance_ratio",
        RN1_EVENT_BOOK_MIN_DOMINANCE_RATIO,
    )
    if (
        source_wallet.lower() == RN1_WALLET
        and not has_event_exposure
        and _event_sport_group(metadata) in RN1_FILTER_COPY_TENNIS_SPORTS
    ):
        tennis_default = _wallet_profile_float(
            wallet,
            "event_book",
            "tennis_fresh_min_dominance_ratio",
            RN1_FILTER_COPY_TENNIS_FRESH_MIN_DOMINANCE_RATIO,
        )
        return max(default, tennis_default)
    if (
        source_wallet.lower() == RN1_WALLET
        and not has_event_exposure
        and _event_sport_group(metadata) == "esports"
        and _event_bet_type(metadata) == "map_or_game_winner"
    ):
        esports_default = _wallet_profile_float(
            wallet,
            "event_book",
            "esports_fresh_min_dominance_ratio",
            RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_RATIO,
        )
        return max(default, esports_default)
    return default


def _rn1_filter_copy_source_book_repair_allowed(
    source_wallet: str,
    metadata: dict[str, Any],
    current_position: dict[str, Any],
    positive_positions: list[dict[str, Any]],
    *,
    has_event_exposure: bool,
) -> bool:
    if source_wallet.lower() != RN1_WALLET or not has_event_exposure:
        return False
    sport = _event_sport_group(metadata)
    if sport != "esports" and sport not in RN1_FILTER_COPY_TENNIS_SPORTS:
        return False
    current_asset = str(current_position.get("asset_id") or "")
    current_notional = _rn1_event_book_leg_source_notional(current_position)
    if not current_asset or current_notional <= 0:
        return False
    source_notionals = [_rn1_event_book_leg_source_notional(item) for item in positive_positions]
    total_notional = sum(source_notionals)
    if total_notional <= 0:
        return False
    if sport == "esports" and _event_bet_type(metadata) == "map_or_game_winner":
        return _rn1_event_book_leg_is_dominant(
            current_position,
            positive_positions,
            min_dominance_share=RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_SHARE,
            min_dominance_ratio=RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_RATIO,
        )
    dominant_notional = max(source_notionals)
    if current_notional >= dominant_notional:
        return True
    candidate_share = current_notional / total_notional
    candidate_to_dominant = current_notional / dominant_notional if dominant_notional > 0 else 0.0
    return (
        candidate_to_dominant >= FILTER_COPY_EVENT_BOOK_CO_DOMINANT_RATIO
        and candidate_share >= FILTER_COPY_EVENT_BOOK_CO_DOMINANT_SHARE
    )


def _rn1_filter_copy_tennis_block_reason(
    source_wallet: str,
    metadata: dict[str, Any],
    source_position: dict[str, Any],
    event_book_role: dict[str, Any],
) -> str | None:
    if source_wallet.lower() != RN1_WALLET or _event_sport_group(metadata) not in RN1_FILTER_COPY_TENNIS_SPORTS:
        return None
    if _event_bet_type(metadata) != "moneyline_winlose":
        return "filter_copy_market_blocked"
    if int(source_position.get("buy_count") or 0) < RN1_FILTER_COPY_TENNIS_MIN_BUY_COUNT:
        return "filter_copy_tennis_conviction_blocked"
    source_notional = float(source_position.get("net_notional_usdc") or source_position.get("buy_notional_usdc") or 0)
    if source_notional < RN1_FILTER_COPY_TENNIS_MIN_CUMULATIVE_SOURCE_USDC:
        return "filter_copy_tennis_conviction_blocked"
    candidate_to_dominant = _float_or_none(event_book_role.get("candidate_to_dominant"))
    if (
        int(event_book_role.get("rank") or 0) > 1
        and candidate_to_dominant is not None
        and candidate_to_dominant < 1 / RN1_FILTER_COPY_TENNIS_OPPOSITE_MAX_RATIO
    ):
        return "filter_copy_tennis_rank_blocked"
    return None


def _rn1_filter_copy_tennis_secondary_allowed(
    source_wallet: str,
    metadata: dict[str, Any],
    event_book_role: dict[str, Any],
) -> bool:
    if source_wallet.lower() != RN1_WALLET or _event_sport_group(metadata) not in RN1_FILTER_COPY_TENNIS_SPORTS:
        return False
    if int(event_book_role.get("rank") or 0) <= 1:
        return False
    candidate_to_dominant = _float_or_none(event_book_role.get("candidate_to_dominant"))
    return candidate_to_dominant is not None and candidate_to_dominant >= 1 / RN1_FILTER_COPY_TENNIS_OPPOSITE_MAX_RATIO


def _filter_copy_source_price_block_reason(
    source_wallet: str,
    source_price: float,
    wallet: dict[str, object],
    metadata: dict[str, Any] | None = None,
) -> str | None:
    min_price = _wallet_profile_float(wallet, "filter_copy", "min_source_price", FILTER_COPY_MIN_SOURCE_PRICE)
    max_price = _filter_copy_max_source_price(source_wallet, wallet)
    if source_wallet.lower() == RN1_WALLET and _event_sport_group(metadata or {}) in RN1_FILTER_COPY_TENNIS_SPORTS:
        max_price = RN1_FILTER_COPY_TENNIS_MAX_SOURCE_PRICE
    price = float(source_price)
    if price < min_price:
        return "filter_copy_price_blocked"
    rule = _filter_copy_sport_rule(source_wallet, metadata or {}, wallet)
    if rule is not None:
        return None if _filter_copy_sport_rule_buy_size(rule, price) > 0 else "filter_copy_price_blocked"
    if source_wallet.lower() == SWISSTONY_WALLET:
        return "filter_copy_price_blocked" if price >= max_price else None
    return "filter_copy_price_blocked" if price > max_price else None


def _filter_copy_event_book_price_block_reason(
    source_wallet: str,
    source_price: float,
    wallet: dict[str, object],
    metadata: dict[str, Any] | None = None,
    *,
    is_repair: bool,
    local: bool = False,
) -> str | None:
    price = float(source_price)
    min_price, max_price = _filter_copy_event_book_price_band(
        source_wallet,
        wallet,
        metadata or {},
        is_repair=is_repair,
    )
    if price < min_price:
        return "filter_copy_local_price_blocked" if local else "filter_copy_price_blocked"
    if max_price > 0 and price > max_price:
        return "filter_copy_local_price_blocked" if local else "filter_copy_price_blocked"
    return None


def _filter_copy_event_book_price_band(
    source_wallet: str,
    wallet: dict[str, object],
    metadata: dict[str, Any],
    *,
    is_repair: bool,
) -> tuple[float, float]:
    min_price = _wallet_profile_float(wallet, "filter_copy", "min_source_price", FILTER_COPY_MIN_SOURCE_PRICE)
    max_price = (
        _filter_copy_rebalance_float(wallet, "max_source_price", FILTER_COPY_REBALANCE_MAX_SOURCE_PRICE)
        if is_repair
        else _wallet_profile_float(wallet, "event_book", "max_avg_price", _filter_copy_max_source_price(source_wallet, wallet))
    )
    sport = _event_sport_group(metadata)
    if source_wallet.lower() == RN1_WALLET and sport in RN1_FILTER_COPY_TENNIS_SPORTS:
        return min_price, RN1_FILTER_COPY_TENNIS_MAX_SOURCE_PRICE
    if source_wallet.lower() == SWISSTONY_WALLET and not is_repair:
        max_price = min(max_price, _filter_copy_max_source_price(source_wallet, wallet))
    return min_price, max_price


def _filter_copy_local_price_block_reason(
    source_wallet: str,
    effective_entry_price: float,
    wallet: dict[str, object],
    metadata: dict[str, Any] | None = None,
) -> str | None:
    price = float(effective_entry_price)
    min_price = _wallet_profile_float(wallet, "filter_copy", "min_source_price", FILTER_COPY_MIN_SOURCE_PRICE)
    if price < min_price:
        return "filter_copy_local_price_blocked"
    rule = _filter_copy_sport_rule(source_wallet, metadata or {}, wallet)
    if rule is not None:
        return None if _filter_copy_sport_rule_buy_size(rule, price) > 0 else "filter_copy_local_price_blocked"
    max_price = _filter_copy_max_source_price(source_wallet, wallet)
    if source_wallet.lower() == RN1_WALLET and _event_sport_group(metadata or {}) in RN1_FILTER_COPY_TENNIS_SPORTS:
        max_price = RN1_FILTER_COPY_TENNIS_MAX_SOURCE_PRICE
    if max_price > 0 and price > max_price:
        return "filter_copy_local_price_blocked"
    return None


def _filter_copy_source_reference_price(source_position: dict[str, Any], *, fallback_price: float) -> float:
    avg_price = float(source_position.get("avg_buy_price") or 0)
    return avg_price if avg_price > 0 else float(fallback_price)


def _filter_copy_max_source_price(source_wallet: str, wallet: dict[str, object]) -> float:
    default = SWISSTONY_FILTER_COPY_MAX_SOURCE_PRICE if source_wallet.lower() == SWISSTONY_WALLET else RN1_FILTER_COPY_MAX_SOURCE_PRICE
    return _wallet_profile_float(wallet, "filter_copy", "max_source_price", default)


def _filter_copy_min_single_fill_usdc(source_wallet: str, wallet: dict[str, object]) -> float:
    default = SWISSTONY_FILTER_COPY_MIN_SINGLE_FILL_USDC if source_wallet.lower() == SWISSTONY_WALLET else RN1_FILTER_COPY_MIN_SINGLE_FILL_USDC
    return _wallet_profile_float(wallet, "filter_copy", "min_single_fill_usdc", default)


def _filter_copy_min_cumulative_source_usdc(
    source_wallet: str,
    wallet: dict[str, object],
    metadata: dict[str, Any] | None = None,
) -> float:
    default = (
        SWISSTONY_FILTER_COPY_MIN_CUMULATIVE_SOURCE_USDC
        if source_wallet.lower() == SWISSTONY_WALLET
        else RN1_FILTER_COPY_MIN_CUMULATIVE_SOURCE_USDC
    )
    value = _wallet_profile_float(wallet, "filter_copy", "min_cumulative_source_usdc", default)
    if source_wallet.lower() == RN1_WALLET:
        sport = _event_sport_group(metadata or {})
        if sport in RN1_FILTER_COPY_TENNIS_SPORTS:
            return RN1_FILTER_COPY_TENNIS_MIN_CUMULATIVE_SOURCE_USDC
        if sport == "soccer":
            return _wallet_profile_float(
                wallet,
                "event_book",
                "planner_rn1_soccer_min_event_source_usdc",
                RN1_FILTER_COPY_SOCCER_MIN_CUMULATIVE_SOURCE_USDC,
            )
        if sport == "mlb":
            return _wallet_profile_float(
                wallet,
                "event_book",
                "planner_rn1_mlb_min_event_source_usdc",
                RN1_FILTER_COPY_MLB_MIN_CUMULATIVE_SOURCE_USDC,
            )
        if float(value) == RN1_FILTER_COPY_MIN_CUMULATIVE_SOURCE_USDC and sport == "esports":
            return RN1_FILTER_COPY_ALT_MIN_CUMULATIVE_SOURCE_USDC
    return value


def _filter_copy_window_seconds(source_wallet: str, wallet: dict[str, object]) -> int:
    default = SWISSTONY_FILTER_COPY_WINDOW_SECONDS if source_wallet.lower() == SWISSTONY_WALLET else RN1_FILTER_COPY_WINDOW_SECONDS
    return _wallet_profile_int(wallet, "filter_copy", "accumulation_window_seconds", default)


def _filter_copy_daily_deployed_cap_usdc(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(wallet, "filter_copy", "daily_deployed_cap_usdc", FILTER_COPY_DAILY_DEPLOYED_CAP_USDC)


def _filter_copy_cap_credit_price(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(wallet, "filter_copy", "cap_credit_price", FILTER_COPY_CAP_CREDIT_PRICE)


def _filter_copy_rn1_repair_max_local_price(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "filter_copy",
        "rn1_repair_max_local_price",
        FILTER_COPY_RN1_REPAIR_MAX_LOCAL_PRICE,
    )


def _filter_copy_source_sell_exit_fraction(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(wallet, "filter_copy", "source_sell_exit_fraction", FILTER_COPY_SOURCE_SELL_EXIT_FRACTION)


def _filter_copy_event_book_min_asset_source_notional(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "filter_copy",
        "event_book_min_asset_source_notional_usdc",
        FILTER_COPY_EVENT_BOOK_MIN_ASSET_SOURCE_NOTIONAL_USDC,
    )


def _event_book_planner_enabled(wallet: dict[str, object]) -> bool:
    return _wallet_profile_bool(wallet, "event_book", "planner_enabled", False)


def _swisstony_event_book_fresh_quality_block_reason(
    *,
    event_positions: list[dict[str, Any]],
    metadata_by_asset: dict[str, dict[str, Any]],
    wallet: dict[str, object],
) -> str | None:
    total_source_notional = sum(float(item.get("net_notional_usdc") or 0) for item in event_positions)
    min_source_notional = _wallet_profile_float(
        wallet,
        "event_book",
        "planner_swisstony_fresh_min_event_source_usdc",
        40000.0,
    )
    if total_source_notional < min_source_notional:
        return "swisstony_event_book_fresh_quality_gate"

    strongest_leg_notional = max([float(item.get("net_notional_usdc") or 0) for item in event_positions] or [0.0])
    top_share = strongest_leg_notional / total_source_notional if total_source_notional > 0 else 0.0
    min_top_share = _wallet_profile_float(
        wallet,
        "event_book",
        "planner_swisstony_fresh_min_top_leg_share",
        0.55,
    )
    if top_share < min_top_share:
        return "swisstony_event_book_fresh_quality_gate"

    draw_notional = 0.0
    for item in event_positions:
        asset_id = str(item.get("asset_id") or "")
        if _event_bet_type(metadata_by_asset.get(asset_id, {})) == "draw":
            draw_notional += float(item.get("net_notional_usdc") or 0)
    draw_share = draw_notional / total_source_notional if total_source_notional > 0 else 0.0
    max_draw_share = _wallet_profile_float(
        wallet,
        "event_book",
        "planner_swisstony_fresh_max_draw_share",
        0.40,
    )
    if draw_share > max_draw_share:
        return "swisstony_event_book_fresh_quality_gate"
    return None


def _filter_copy_event_book_copy_scale(source_wallet: str, wallet: dict[str, object]) -> float:
    default = (
        SWISSTONY_SOURCE_FOLLOW_COPY_SCALE
        if source_wallet.lower() == SWISSTONY_WALLET
        else RN1_SOURCE_FOLLOW_COPY_SCALE
    )
    return _wallet_profile_float(wallet, "source_follow", "copy_scale", default)


def _filter_copy_event_book_max_event_exposure_usdc(wallet: dict[str, object]) -> float:
    event_follow_cap = _wallet_float(wallet, "event_follow_max_event_exposure_usdc", 0.0)
    repair_cap = _filter_copy_rebalance_float(
        wallet,
        "normal_event_cap_usdc",
        FILTER_COPY_REBALANCE_NORMAL_EVENT_CAP_USDC,
    ) + _filter_copy_rebalance_float(
        wallet,
        "extra_repair_event_cap_usdc",
        FILTER_COPY_REBALANCE_EXTRA_EVENT_CAP_USDC,
    )
    return max(event_follow_cap, repair_cap)


def _filter_copy_same_event_hedge_max_fraction(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "filter_copy",
        "same_event_hedge_max_fraction",
        FILTER_COPY_SAME_EVENT_HEDGE_MAX_FRACTION,
    )


def _filter_copy_scale_up_enabled(wallet: dict[str, object]) -> bool:
    return _wallet_profile_bool(wallet, "filter_copy", "scale_up_enabled", True)


def _filter_copy_scale_up_max_position_usdc(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "filter_copy",
        "scale_up_max_position_usdc",
        FILTER_COPY_SCALE_UP_MAX_POSITION_USDC,
    )


def _rn1_filter_copy_rebalance_max_order_usdc(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "event_book",
        "planner_rn1_max_rebalance_order_usdc",
        RN1_FILTER_COPY_REBALANCE_MAX_ORDER_USDC,
    )


def _filter_copy_rebalance_min_worst_case_improvement_fraction(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "event_book",
        "planner_rebalance_min_worst_case_improvement_fraction",
        RN1_FILTER_COPY_REBALANCE_MIN_WORST_CASE_IMPROVEMENT_FRACTION,
    )


def _filter_copy_min_top_up_usdc(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "filter_copy",
        "min_top_up_usdc",
        FILTER_COPY_MIN_TOP_UP_USDC,
    )


def _filter_copy_target_max_position_usdc(
    *,
    source_wallet: str,
    wallet: dict[str, object],
    metadata: dict[str, Any],
    base_notional: float,
) -> float:
    profile_cap = _filter_copy_scale_up_max_position_usdc(wallet)
    if source_wallet.lower() == RN1_WALLET:
        sport = _event_sport_group(metadata)
        if sport in RN1_FILTER_COPY_TENNIS_SPORTS:
            return 20.0
        return 20.0 if sport == "esports" else 40.0
    if source_wallet.lower() == SWISSTONY_WALLET and not _filter_copy_clean_soccer_main_winner(metadata):
        return min(profile_cap, base_notional) if profile_cap > 0 else base_notional
    return profile_cap


def _filter_copy_clean_soccer_main_winner(metadata: dict[str, Any]) -> bool:
    return _event_sport_group(metadata) == "soccer" and _event_bet_type(metadata) == "moneyline_winlose"


def _round_up_to_increment(value: float, increment: float) -> float:
    if value <= 0 or increment <= 0:
        return 0.0
    return round(math.ceil(value / increment) * increment, 6)


def _filter_copy_scale_up_increment_usdc(source_wallet: str, metadata: dict[str, Any], base_notional: float) -> float:
    if source_wallet.lower() != RN1_WALLET:
        return base_notional
    if _event_sport_group(metadata) in RN1_FILTER_COPY_TENNIS_SPORTS or _event_sport_group(metadata) == "esports":
        return min(5.0, base_notional) if base_notional > 0 else 5.0
    return base_notional


def _filter_copy_in_event_stop_loss_pct(wallet: dict[str, object]) -> float:
    return _wallet_profile_float(
        wallet,
        "filter_copy",
        "in_event_stop_loss_pct",
        FILTER_COPY_IN_EVENT_STOP_LOSS_PCT,
    )


def _filter_copy_bet_size_usdc(
    source_wallet: str,
    source_price: float,
    wallet: dict[str, object],
    metadata: dict[str, Any] | None = None,
) -> float:
    rule = _filter_copy_sport_rule(source_wallet, metadata or {}, wallet)
    if rule is not None:
        return _filter_copy_sport_rule_buy_size(rule, source_price)
    tiers = _wallet_profile_section(wallet, "filter_copy").get("tiers")
    notional = 0.0
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            try:
                min_price = float(tier.get("min_price", 0))
                max_price = float(tier.get("max_price", 0))
                tier_notional = float(tier.get("buy_size_usdc", 0))
            except (TypeError, ValueError):
                continue
            if min_price <= source_price < max_price and tier_notional > 0:
                notional = tier_notional
                break
    if notional <= 0:
        if 0.20 <= source_price < 0.35:
            notional = 12.0
        elif 0.35 <= source_price < 0.45:
            notional = 10.0
        elif 0.45 <= source_price < 0.55:
            notional = 8.0
        elif source_wallet.lower() == RN1_WALLET and 0.55 <= source_price <= RN1_FILTER_COPY_MAX_SOURCE_PRICE:
            notional = 5.0
    if source_wallet.lower() == RN1_WALLET:
        sport = _event_sport_group(metadata or {})
        if sport in RN1_FILTER_COPY_TENNIS_SPORTS:
            notional = min(notional, 10.0)
        elif sport == "esports":
            notional = min(notional, 5.0)
    return notional


def _pdt_day_start_utc() -> datetime:
    now_pdt = datetime.now(tz=PDT)
    return now_pdt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _sharp_simple_crypto_copy_enabled(source_wallet: str, wallet: dict[str, object], market_type: str) -> bool:
    wallet_name = str(wallet.get("name") or "").strip().lower()
    profile_market_types = _wallet_profile_list(wallet, "fixed_buy", "market_types", ["crypto"], lower=True)
    market_allowed = market_type in set(profile_market_types or ["crypto"])
    legacy_enabled = (
        market_type == "crypto"
        and source_wallet.lower() == SHARP_0X8A091_WALLET
        and wallet_name == "sharp_0x8a091"
        and not _weather_bracket_strategy_enabled(wallet)
        and not _repeat_buy_strategy_enabled(wallet)
        and not _event_follow_strategy_enabled(wallet)
    )
    profile_enabled = _wallet_profile_bool(wallet, "fixed_buy", "enabled", legacy_enabled)
    return (
        market_allowed
        and profile_enabled
        and not _weather_bracket_strategy_enabled(wallet)
        and not _repeat_buy_strategy_enabled(wallet)
        and not _event_follow_strategy_enabled(wallet)
    )


def _rn1_event_follow_market_allowed(metadata: dict[str, Any], wallet: dict[str, object]) -> bool:
    sport = _event_sport_group(metadata)
    bet_type = _event_bet_type(metadata)
    allowed_sports = set(
        _wallet_profile_list(wallet, "event_follow", "allowed_sports", RN1_ALLOWED_EVENT_SPORTS, lower=True)
        or RN1_ALLOWED_EVENT_SPORTS
    )
    allowed_bet_types = set(
        _wallet_profile_list(wallet, "event_follow", "allowed_bet_types", RN1_ALLOWED_EVENT_BET_TYPES, lower=True)
        or RN1_ALLOWED_EVENT_BET_TYPES
    )
    return sport in allowed_sports and bet_type in allowed_bet_types


def _swisstony_leg_target_notional(source_price: float, wallet: dict[str, object] | None = None) -> float:
    tiers = _wallet_profile_section(wallet, "tier_sizing").get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            try:
                min_price = float(tier.get("min_price", 0))
                max_price = float(tier.get("max_price", 0))
                notional = float(tier.get("buy_size_usdc", 0))
            except (TypeError, ValueError):
                continue
            if min_price <= source_price <= max_price and notional > 0:
                return notional
    if SWISSTONY_TIER_A_MIN_PRICE <= source_price <= SWISSTONY_TIER_A_MAX_PRICE:
        return SWISSTONY_TIER_A_NOTIONAL_USDC
    if SWISSTONY_TIER_A_MAX_PRICE < source_price <= SWISSTONY_TIER_B_MAX_PRICE:
        return SWISSTONY_TIER_B_NOTIONAL_USDC
    return 0.0


def _sports_win_market_title(title: str) -> bool:
    text = str(title or "").strip().lower()
    return text.startswith("will ") and " win on " in text and " end in a draw" not in text


def _sports_bracket_leg_type(leg: dict[str, Any]) -> str:
    metadata = {
        "title": leg.get("title"),
        "market_slug": leg.get("market_slug"),
        "event_slug": leg.get("event_slug"),
        "event_title": leg.get("event_title"),
        "outcome": leg.get("outcome"),
    }
    title = str(leg.get("title") or "")
    bet_type = _event_bet_type(metadata)
    if _sports_win_market_title(title):
        return "moneyline_win"
    if bet_type == "total_or_over_under":
        return "total_ladder"
    if bet_type == "spread_handicap":
        return "spread_ladder"
    if bet_type in {"both_teams_score", "draw", "moneyline_winlose", "map_or_game_winner"}:
        return bet_type
    return "other"


def _rn1_event_book_leg_in_conviction_band(
    leg: dict[str, Any],
    min_source_notional: float = RN1_CONVICTION_SOURCE_NOTIONAL_USDC,
    min_avg_price: float = RN1_ESPORTS_MIN_AVG_PRICE,
    max_avg_price: float = RN1_ESPORTS_MAX_AVG_PRICE,
) -> bool:
    source_notional = _rn1_event_book_leg_source_notional(leg)
    source_price = _rn1_event_book_leg_source_price(leg)
    return (
        source_notional >= min_source_notional
        and min_avg_price <= source_price <= max_avg_price
    )


def _rn1_event_book_group_key(leg: dict[str, Any]) -> tuple[str, str]:
    metadata = {
        "title": leg.get("title"),
        "market_slug": leg.get("market_slug"),
        "event_slug": leg.get("event_slug"),
        "event_title": leg.get("event_title"),
        "outcome": leg.get("outcome"),
    }
    bet_type = _event_bet_type(metadata)
    title = str(leg.get("title") or "").strip().lower()
    if bet_type == "moneyline_winlose":
        if title.startswith("will ") and " win on " in title:
            return ("event_result_moneyline", "")
        return ("moneyline_title", title)
    if bet_type == "total_or_over_under":
        return ("totals_ladder", "")
    if bet_type == "spread_handicap":
        return ("spread_ladder", "")
    if bet_type == "map_or_game_winner":
        return ("map_or_game_winner", title)
    return (_sports_bracket_leg_type(leg), title)


def _rn1_comparable_event_book_legs(current_leg: dict[str, Any], legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_key = _rn1_event_book_group_key(current_leg)
    return [leg for leg in legs if _rn1_event_book_group_key(leg) == current_key]


def _rn1_event_book_dominance_comparison_legs(
    metadata: dict[str, Any],
    current_leg: dict[str, Any],
    legs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _event_sport_group(metadata) == "esports" and _event_bet_type(metadata) == "map_or_game_winner":
        return legs
    return _rn1_comparable_event_book_legs(current_leg, legs)


def _rn1_event_book_leg_is_dominant(
    current_leg: dict[str, Any],
    comparable_legs: list[dict[str, Any]],
    *,
    min_dominance_share: float = RN1_EVENT_BOOK_MIN_DOMINANCE_SHARE,
    min_dominance_ratio: float = RN1_EVENT_BOOK_MIN_DOMINANCE_RATIO,
) -> bool:
    current_asset = str(current_leg.get("asset_id") or "")
    current_notional = _rn1_event_book_leg_source_notional(current_leg)
    total_notional = sum(_rn1_event_book_leg_source_notional(leg) for leg in comparable_legs)
    if current_notional <= 0 or total_notional <= 0:
        return False
    strongest_other = max(
        [
            _rn1_event_book_leg_source_notional(leg)
            for leg in comparable_legs
            if str(leg.get("asset_id") or "") != current_asset
        ]
        or [0.0]
    )
    if strongest_other <= 0:
        return True
    share = current_notional / total_notional
    ratio = current_notional / strongest_other
    return share >= float(min_dominance_share) or ratio >= float(min_dominance_ratio)


def _rn1_event_book_leg_source_notional(leg: dict[str, Any]) -> float:
    return float(leg.get("source_notional_usdc") or leg.get("net_notional_usdc") or leg.get("buy_notional_usdc") or 0)


def _rn1_event_book_leg_source_price(leg: dict[str, Any]) -> float:
    source_price = float(leg.get("source_avg_price") or leg.get("avg_buy_price") or 0)
    if source_price > 0:
        return source_price
    source_quantity = float(leg.get("source_quantity") or leg.get("buy_quantity") or 0)
    source_notional = _rn1_event_book_leg_source_notional(leg)
    return source_notional / source_quantity if source_quantity > 0 else 0.0


def _select_sports_bracket_pattern(legs: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    if len(legs) < 2:
        return None, []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for leg in legs:
        by_type.setdefault(str(leg.get("bracket_leg_type") or "other"), []).append(leg)
    for leg_type, pattern in (
        ("moneyline_win", SPORTS_DOUBLE_WIN_BRACKET_PATTERN),
        ("moneyline_winlose", SPORTS_TWO_OUTCOME_BRACKET_PATTERN),
        ("total_ladder", SPORTS_TOTAL_LADDER_BRACKET_PATTERN),
        ("spread_ladder", SPORTS_SPREAD_LADDER_BRACKET_PATTERN),
    ):
        selected = by_type.get(leg_type, [])
        if len(selected) >= 2:
            return pattern, selected
    map_winner_legs = by_type.get("map_or_game_winner", [])
    for selected in _same_title_leg_groups(map_winner_legs):
        if len(selected) >= 2:
            return SPORTS_TWO_OUTCOME_BRACKET_PATTERN, selected
    if len(legs) >= 3:
        return SPORTS_MULTI_LEG_BRACKET_PATTERN, legs
    return None, []


def _same_title_leg_groups(legs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for leg in legs:
        key = str(leg.get("title") or "").strip().lower()
        if not key:
            continue
        groups.setdefault(key, []).append(leg)
    return list(groups.values())


def _apply_two_outcome_hedge_targets(legs: list[dict[str, Any]]) -> None:
    if len(legs) != 2:
        return
    copied_legs = [leg for leg in legs if float(leg.get("copied_notional_usdc") or 0) > 0]
    if len(copied_legs) != 1:
        return
    anchor = copied_legs[0]
    anchor_notional = float(anchor.get("copied_notional_usdc") or 0)
    for leg in legs:
        if leg is anchor:
            continue
        price = float(leg.get("source_avg_price") or 0)
        if price <= 0 or price >= 1:
            continue
        hedge_target = round(anchor_notional * price / (1 - price), 6)
        leg["target_notional_usdc"] = max(float(leg.get("target_notional_usdc") or 0), hedge_target)


def _rn1_esports_repeat_buy_block_reason(
    trade: SourceTrade,
    metadata: dict[str, Any],
    signal: dict[str, Any],
    wallet: dict[str, object],
) -> str | None:
    if trade.source_wallet.lower() != RN1_WALLET or _event_sport_group(metadata) != "esports":
        return None
    allowed_bet_types = set(
        _wallet_profile_list(wallet, "esports_repeat_buy", "allowed_bet_types", RN1_ESPORTS_ALLOWED_BET_TYPES, lower=True)
    )
    if _event_bet_type(metadata) not in allowed_bet_types:
        return "rn1_esports_bet_type_blocked"
    min_buy_count = _wallet_profile_int(wallet, "esports_repeat_buy", "min_buy_count", RN1_ESPORTS_MIN_BUY_COUNT)
    if int(signal.get("buy_count") or 0) < min_buy_count:
        return "rn1_esports_waiting_for_buy_count"
    min_source_notional = _wallet_profile_float(
        wallet,
        "esports_repeat_buy",
        "min_source_notional_usdc",
        RN1_ESPORTS_MIN_SOURCE_NOTIONAL_USDC,
    )
    if float(signal.get("source_notional_usdc") or 0) < min_source_notional:
        return "rn1_esports_waiting_for_source_notional"
    avg_price = _signal_avg_price(signal)
    min_avg_price = _wallet_profile_float(wallet, "esports_repeat_buy", "min_avg_price", RN1_ESPORTS_MIN_AVG_PRICE)
    max_avg_price = _wallet_profile_float(wallet, "esports_repeat_buy", "max_avg_price", RN1_ESPORTS_MAX_AVG_PRICE)
    if avg_price < min_avg_price or avg_price > max_avg_price:
        return "rn1_esports_price_band_blocked"
    return None


def _rn1_high_conviction_filter_override(
    trade: SourceTrade,
    metadata: dict[str, Any],
    signal: dict[str, Any],
    wallet: dict[str, object],
) -> bool:
    if trade.source_wallet.lower() != RN1_WALLET:
        return False
    buy_count = int(signal.get("buy_count") or 0)
    source_notional = float(signal.get("source_notional_usdc") or 0)
    avg_price = _signal_avg_price(signal)
    if avg_price <= 0:
        return False
    sport = _event_sport_group(metadata)
    bet_type = _event_bet_type(metadata)
    min_buy_count = _wallet_profile_int(wallet, "high_conviction", "min_buy_count", 10)
    min_source_notional = _wallet_profile_float(
        wallet,
        "high_conviction",
        "min_source_notional_usdc",
        RN1_CONVICTION_SOURCE_NOTIONAL_USDC,
    )
    min_avg_price = _wallet_profile_float(wallet, "high_conviction", "min_avg_price", 0.40)
    max_avg_price = _wallet_profile_float(wallet, "high_conviction", "max_avg_price", 0.70)
    high_conviction = (
        buy_count >= min_buy_count
        and source_notional >= min_source_notional
        and min_avg_price <= avg_price <= max_avg_price
    )
    if bet_type in {"total_or_over_under", "spread_handicap"}:
        return high_conviction
    if sport in RN1_FILTER_COPY_TENNIS_SPORTS:
        return False
    if sport == "esports":
        esports_min_buy_count = _wallet_profile_int(wallet, "esports_repeat_buy", "min_buy_count", RN1_ESPORTS_MIN_BUY_COUNT)
        esports_bet_types = set(
            _wallet_profile_list(wallet, "esports_repeat_buy", "allowed_bet_types", RN1_ESPORTS_ALLOWED_BET_TYPES, lower=True)
        )
        return bet_type in esports_bet_types and buy_count >= esports_min_buy_count and high_conviction
    if bet_type in {"moneyline_winlose", "map_or_game_winner"} and sport in {"soccer", "mlb", "nba", "nhl"}:
        return high_conviction
    return False


def _event_sport_group(metadata: dict[str, Any]) -> str:
    sport = _normalized_sport_key(metadata.get("sport_key"))
    if sport:
        return sport
    series_sport = _sport_key_from_structured_slug(metadata.get("series_slug"))
    if series_sport:
        return series_sport
    text = _metadata_text(metadata)
    if any(token in text for token in ("counter-strike", "cs2", "league-of-legends", "dota", "valorant")):
        return "esports"
    if any(token in text for token in ("nba", "basketball")):
        return "nba"
    if any(token in text for token in ("mlb", "baseball")):
        return "mlb"
    if any(token in text for token in ("nfl", "american football")):
        return "nfl"
    if any(token in text for token in ("nhl", "hockey")):
        return "nhl"
    if "atp" in text:
        return "atp"
    if "wta" in text:
        return "wta"
    if "tennis" in text:
        return "tennis"
    if (
        _looks_like_soccer_market(text)
        or " fc " in f" {text} "
        or " win on " in text
    ):
        return "soccer"
    return "other"


def _normalized_sport_key(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"atp", "wta", "tennis", "mlb", "nba", "nfl", "nhl", "soccer", "esports"}:
        return normalized
    if normalized in {"football", "mls", "epl", "uefa", "ucl", "uel"}:
        return "soccer"
    return None


def _sport_key_from_structured_slug(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if not normalized:
        return None
    for prefix, sport in (
        ("mlb-", "mlb"),
        ("nba-", "nba"),
        ("nfl-", "nfl"),
        ("nhl-", "nhl"),
        ("wta-", "wta"),
        ("atp-", "atp"),
        ("mls-", "soccer"),
        ("epl-", "soccer"),
        ("uefa-", "soccer"),
        ("ucl-", "soccer"),
        ("uel-", "soccer"),
        ("champions-league-", "soccer"),
        ("premier-league-", "soccer"),
        ("la-liga-", "soccer"),
        ("laliga-", "soccer"),
        ("serie-a-", "soccer"),
        ("bundesliga-", "soccer"),
        ("counter-strike-", "esports"),
        ("cs2-", "esports"),
        ("dota-", "esports"),
        ("valorant-", "esports"),
        ("league-of-legends-", "esports"),
    ):
        if normalized.startswith(prefix):
            return sport
    return _normalized_sport_key(normalized)


def _looks_like_soccer_market(text: str) -> bool:
    if any(
        token in text
        for token in (
            "soccer",
            "football",
            "champions-league",
            "premier-league",
            "laliga",
            "serie-a",
            "bundesliga",
            "uefa",
            "ucl",
            "uel",
            "mls",
            "arsenal",
            "aston villa",
            "aston-villa",
            "braga",
            "crystal palace",
            "crystal-palace",
            "freiburg",
            "nottingham",
            "nottingham forest",
            "nottingham-forest",
            "rayo",
            "strasbourg",
            "vallecano",
        )
    ):
        return True
    if re.search(r"\b(fc|cf|sc|cd|rc|rcd|fk|bk|if|ogc|ssc)\b", text):
        return True
    return any(
        token in text
        for token in (
            "deportivo",
            "united",
            "athletic",
            "atletico",
            "city",
            "rovers",
            "wanderers",
            "futebol",
            "lecce",
            "lens",
            "nice",
            "zaragoza",
            "granada",
            "viking",
            "rosenborg",
        )
    )


def _event_bet_type(metadata: dict[str, Any]) -> str:
    bet_type = _normalized_bet_type(metadata.get("bet_type"))
    if bet_type:
        return bet_type
    sports_market_type = _bet_type_from_structured_market_type(metadata.get("sports_market_type"))
    if sports_market_type:
        return sports_market_type
    text = _metadata_text(metadata)
    if "both teams to score" in text or " btts " in f" {text} ":
        return "both_teams_score"
    if "end in a draw" in text or " draw" in text:
        return "draw"
    if "o/u" in text or "over/under" in text or "total" in text or " over " in f" {text} " or " under " in f" {text} ":
        return "total_or_over_under"
    if "spread" in text or "handicap" in text:
        return "spread_handicap"
    if ("map " in text or "game " in text) and ("winner" in text or " win" in text):
        return "map_or_game_winner"
    if " win on " in text or "winner" in text or " vs " in text or " vs. " in text:
        return "moneyline_winlose"
    return "other"


def _normalized_bet_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {
        "moneyline_winlose",
        "total_or_over_under",
        "spread_handicap",
        "both_teams_score",
        "draw",
        "map_or_game_winner",
    }:
        return normalized
    return None


def _bet_type_from_structured_market_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if not normalized:
        return None
    if normalized in {"moneyline", "winner", "match-winner", "game-winner"}:
        return "moneyline_winlose"
    if "spread" in normalized or "handicap" in normalized:
        return "spread_handicap"
    if normalized in {"total", "totals"} or "over-under" in normalized or "o-u" in normalized:
        return "total_or_over_under"
    if normalized in {"both-teams-to-score", "btts"}:
        return "both_teams_score"
    if normalized == "draw":
        return "draw"
    if "map" in normalized or "game" in normalized:
        return "map_or_game_winner"
    return None


def _metadata_text(metadata: dict[str, Any]) -> str:
    return " ".join(
        str(metadata.get(key) or "")
        for key in ("title", "market_slug", "event_slug", "event_title", "outcome")
    ).lower()
