from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polymarket_copy_trading.config import load_config  # noqa: E402
from polymarket_copy_trading import engine as engine_rules  # noqa: E402
from polymarket_copy_trading.engine import CopyTradingEngine  # noqa: E402
from polymarket_copy_trading.live_watcher import (  # noqa: E402
    EXCHANGE_ADDRESSES,
    ORDER_FILLED_TOPICS,
    PolygonRpcClient,
    decode_order_filled_log,
    select_copyable_order_fills,
)
from polymarket_copy_trading.market_data import MarketDataClient  # noqa: E402
from polymarket_copy_trading.models import SourceTrade  # noqa: E402
from polymarket_copy_trading.store import Store  # noqa: E402
from polymarket_copy_trading.wallet_profile import event_book_planner_default_overrides  # noqa: E402


PDT = ZoneInfo("America/Los_Angeles")
DATA_API_URL = "https://data-api.polymarket.com"
POLYGON_RPC_URL = "https://polygon.drpc.org"
RN1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
SWISSTONY = "0x204f72f35326db932158cba6adff0b9a1da95e14"
DEFAULT_WALLETS = {"RN1": RN1, "swisstony": SWISSTONY}
TRADE_TYPE = "TRADE"
CTF_EXCHANGE = "ctf_exchange"
RPC_RETRY_ATTEMPTS = 4


def activity_row_to_source_trade(row: dict[str, Any], *, wallet: str, sequence: int) -> SourceTrade:
    timestamp = _int(row.get("timestamp"), default=0)
    side = str(row.get("side") or "").strip().lower()
    if side not in {"buy", "sell"}:
        raise ValueError(f"unsupported activity side: {row.get('side')!r}")
    price = _float(row.get("price"))
    quantity = _float(row.get("size") or row.get("quantity"))
    notional = _float(row.get("usdcSize") or row.get("notional_usdc") or (price * quantity))
    tx_hash = str(row.get("transactionHash") or row.get("txHash") or f"synthetic-{sequence}").strip()
    clean_wallet = str(wallet).strip().lower()
    block_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(PDT)
    return SourceTrade(
        idempotency_key=f"137:{tx_hash}:{sequence}:{clean_wallet}",
        chain_id=137,
        exchange_contract=CTF_EXCHANGE,
        tx_hash=tx_hash,
        block_number=timestamp,
        block_timestamp=block_time.strftime("%Y-%m-%d %H:%M PDT"),
        log_index=sequence,
        source_wallet=clean_wallet,
        side=side,
        asset_id=str(row.get("asset") or row.get("asset_id") or row.get("token_id") or "").strip(),
        price=round(price, 8),
        quantity=round(quantity, 6),
        notional_usdc=round(notional, 6),
        condition_id=_string_or_none(row.get("conditionId") or row.get("condition_id")),
        market_id=_string_or_none(row.get("market") or row.get("marketId") or row.get("market_id")),
        outcome=_string_or_none(row.get("outcome")),
        copy_trade_key=f"{side}:{row.get('asset') or row.get('asset_id')}:{tx_hash}:{sequence}",
    )


def source_position_metrics(
    trades: list[SourceTrade],
    *,
    mark_prices: dict[str, float],
) -> dict[str, Any]:
    buy_notional = 0.0
    sell_notional = 0.0
    quantity_by_asset: dict[str, float] = defaultdict(float)
    for trade in trades:
        if trade.side == "buy":
            buy_notional += trade.notional_usdc
            quantity_by_asset[trade.asset_id] += trade.quantity
        elif trade.side == "sell":
            sell_notional += trade.notional_usdc
            quantity_by_asset[trade.asset_id] -= trade.quantity
    open_value = 0.0
    open_assets = 0
    for asset_id, quantity in quantity_by_asset.items():
        if quantity <= 0:
            continue
        open_assets += 1
        open_value += quantity * mark_prices.get(asset_id, 0.0)
    pnl = sell_notional + open_value - buy_notional
    return {
        "trades": len(trades),
        "buy_trades": sum(1 for trade in trades if trade.side == "buy"),
        "sell_trades": sum(1 for trade in trades if trade.side == "sell"),
        "open_assets": open_assets,
        "buy_notional_usdc": round(buy_notional, 6),
        "sell_notional_usdc": round(sell_notional, 6),
        "open_value_usdc": round(open_value, 6),
        "pnl_usdc": round(pnl, 6),
        "roi_pct": round((pnl / buy_notional) * 100, 6) if buy_notional else 0.0,
    }


class HistoricalReplaySourcePositionResolver:
    def __init__(self, trades: list[SourceTrade]) -> None:
        self._trades = list(trades)
        self._index_by_object = {id(trade): index for index, trade in enumerate(self._trades)}
        self._index_by_idempotency_key = {trade.idempotency_key: index for index, trade in enumerate(self._trades)}
        self._positions: dict[tuple[str, str], dict[str, float | int]] = {}
        self._current_index = -1

    def advance_to(self, trade: SourceTrade) -> None:
        target_index = self._index_by_object.get(id(trade))
        if target_index is None:
            target_index = self._index_by_idempotency_key.get(trade.idempotency_key)
        if target_index is None:
            return
        if target_index < self._current_index:
            self._positions = {}
            self._current_index = -1
        while self._current_index < target_index:
            self._current_index += 1
            self._apply(self._trades[self._current_index])

    def __call__(self, source_wallet: str, asset_id: str) -> dict[str, Any] | None:
        key = (str(source_wallet or "").lower(), str(asset_id or "").strip())
        position = self._positions.get(key)
        if position is None:
            return None
        return {
            "buy_count": int(position.get("buy_count") or 0),
            "buy_notional_usdc": round(float(position.get("buy_notional_usdc") or 0), 6),
            "buy_quantity": round(float(position.get("buy_quantity") or 0), 6),
            "sell_notional_usdc": round(float(position.get("sell_notional_usdc") or 0), 6),
            "sell_quantity": round(float(position.get("sell_quantity") or 0), 6),
            "net_quantity": round(float(position.get("net_quantity") or 0), 6),
            "net_notional_usdc": round(float(position.get("net_notional_usdc") or 0), 6),
            "avg_buy_price": round(float(position.get("avg_buy_price") or 0), 6),
            "source": "historical_replay",
            "source_position_snapshot_source": "historical_replay",
        }

    def _apply(self, trade: SourceTrade) -> None:
        key = (trade.source_wallet.lower(), str(trade.asset_id).strip())
        if not key[0] or not key[1]:
            return
        position = self._positions.setdefault(
            key,
            {
                "buy_count": 0,
                "buy_notional_usdc": 0.0,
                "buy_quantity": 0.0,
                "sell_notional_usdc": 0.0,
                "sell_quantity": 0.0,
                "net_quantity": 0.0,
                "net_notional_usdc": 0.0,
                "avg_buy_price": 0.0,
            },
        )
        side = str(trade.side or "").lower()
        if side == "buy":
            position["buy_count"] = int(position["buy_count"]) + 1
            position["buy_notional_usdc"] = float(position["buy_notional_usdc"]) + float(trade.notional_usdc or 0)
            position["buy_quantity"] = float(position["buy_quantity"]) + float(trade.quantity or 0)
        elif side == "sell":
            position["sell_notional_usdc"] = float(position["sell_notional_usdc"]) + float(trade.notional_usdc or 0)
            position["sell_quantity"] = float(position["sell_quantity"]) + float(trade.quantity or 0)
        else:
            return
        buy_quantity = float(position["buy_quantity"] or 0)
        buy_notional = float(position["buy_notional_usdc"] or 0)
        net_quantity = buy_quantity - float(position["sell_quantity"] or 0)
        avg_buy_price = buy_notional / buy_quantity if buy_quantity > 0 else 0.0
        position["avg_buy_price"] = avg_buy_price
        position["net_quantity"] = net_quantity
        position["net_notional_usdc"] = max(0.0, net_quantity) * avg_buy_price


class HistoricalReplayCopyTradingEngine:
    def __init__(self, *, config: Any, store: Store, source_trades: list[SourceTrade]) -> None:
        self._source_position_resolver = HistoricalReplaySourcePositionResolver(source_trades)
        self._engine = CopyTradingEngine(
            config=config,
            store=store,
            source_position_resolver=self._source_position_resolver,
        )

    def process_trades(self, trades: list[SourceTrade]) -> dict[str, int]:
        stats = {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        for trade in trades:
            self._source_position_resolver.advance_to(trade)
            result = self._engine.process_trade(trade)
            stats[result] += 1
        return stats


class PreloadedReplayCopyTradingEngine:
    def __init__(self, *, config: Any, store: Store) -> None:
        self._engine = CopyTradingEngine(config=config, store=store)

    def process_trades(self, trades: list[SourceTrade]) -> dict[str, int]:
        stats = {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        for trade in trades:
            if self._engine.store.has_source_trade_attribution(trade.idempotency_key):
                stats["duplicates"] += 1
                continue
            if not self._engine.store.is_wallet_enabled(trade.source_wallet):
                stats["ignored"] += 1
                continue
            if trade.side == "buy":
                result = self._engine._process_buy(trade)
            elif trade.side == "sell":
                if not self._engine.config.exits.mirror_source_sells:
                    result = self._engine._record_skip(trade, "source_sells_disabled")
                else:
                    result = self._engine._process_sell(trade, close_reason="source_sell")
            else:
                result = self._engine._record_skip(trade, "unsupported_side")
            stats[result] += 1
        return stats


@dataclass(frozen=True)
class CandidateSelection:
    trades: list[SourceTrade]
    reasons: dict[str, int]
    excluded_reasons: dict[str, int]


def run_backtest(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = ROOT / args.output_dir
    scratch_dir = ROOT / "data" / "backtests"
    output_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(PDT).strftime("%Y%m%d-%H%M-PDT")
    scratch_db = scratch_dir / f"event_book_backtest_{stamp}.sqlite3"

    config_path = ROOT / args.config
    config = load_config(config_path)
    config = replace(
        config,
        paper=replace(
            config.paper,
            starting_cash_usdc=float(args.starting_cash),
            slippage_pct=float(args.slippage_pct),
        ),
    )

    store = Store(scratch_db)
    store.initialize()
    clone_wallet_profiles(
        Path(args.wallet_db),
        store,
        DEFAULT_WALLETS.values(),
        event_book_planner=bool(args.event_book_planner),
    )

    session = requests.Session()
    end_utc = parse_backtest_time(args.end) if args.end else datetime.now(timezone.utc)
    analysis_start = parse_backtest_time(args.start) if args.start else end_utc - timedelta(hours=args.hours)
    replay_start = analysis_start - timedelta(hours=args.warmup_hours)
    analysis_hours = round((end_utc - analysis_start).total_seconds() / 3600, 6)
    activities_by_wallet: dict[str, list[dict[str, Any]]] = {}
    onchain_scan: dict[str, Any] | None = None
    analysis_start_block: int | None = None
    if args.source == "sqlite":
        source_trades = fetch_sqlite_source_trades(
            wallet_db=Path(args.wallet_db),
            wallets=list(DEFAULT_WALLETS.values()),
            since_utc=replay_start,
            until_utc=end_utc,
        )
    elif args.source == "onchain":
        rpc = PolygonRpcClient(args.rpc_url)
        latest_block = block_number_with_retries(rpc)
        scan_latest_block = max(0, latest_block - max(0, int(args.confirmations)))
        from_block = find_block_at_or_after(rpc, replay_start, latest_block=scan_latest_block)
        analysis_start_block = find_block_at_or_after(rpc, analysis_start, latest_block=scan_latest_block)
        end_candidate = find_block_at_or_after(rpc, end_utc, latest_block=scan_latest_block)
        end_candidate_time = block_timestamp_utc(rpc, end_candidate)
        to_block = end_candidate if end_candidate_time <= end_utc else max(0, end_candidate - 1)
        timestamp_resolver = interpolated_block_timestamp_resolver(
            from_block=from_block,
            to_block=to_block,
            from_time_utc=block_timestamp_utc(rpc, from_block),
            to_time_utc=block_timestamp_utc(rpc, to_block),
        )
        source_trades = fetch_onchain_source_trades(
            rpc=rpc,
            wallets=list(DEFAULT_WALLETS.values()),
            from_block=from_block,
            to_block=to_block,
            exchange_contracts=tuple(args.exchange_contracts),
            chunk_size=args.onchain_chunk_blocks,
            timestamp_resolver=timestamp_resolver,
        )
        onchain_scan = {
            "rpc_url": args.rpc_url,
            "from_block": from_block,
            "analysis_start_block": analysis_start_block,
            "to_block": to_block,
            "latest_block": latest_block,
            "scan_latest_block": scan_latest_block,
            "confirmations": int(args.confirmations),
            "exchange_contracts": list(args.exchange_contracts),
            "chunk_blocks": args.onchain_chunk_blocks,
            "timestamp_mode": "interpolated_from_endpoint_blocks",
        }
    else:
        source_trades = []
        sequence = 0
        for name, wallet in DEFAULT_WALLETS.items():
            rows = fetch_wallet_activity(
                session=session,
                wallet=wallet,
                since_utc=replay_start,
                limit=args.page_size,
                max_offset=args.max_offset,
                max_rows=args.max_trades_per_wallet,
            )
            activities_by_wallet[name] = rows
            for row in rows:
                sequence += 1
                try:
                    trade = activity_row_to_source_trade(row, wallet=wallet, sequence=sequence)
                except ValueError:
                    continue
                if not trade.asset_id or trade.price <= 0 or trade.quantity <= 0:
                    continue
                source_trades.append(trade)

    source_trades.sort(key=lambda trade: (trade.block_number, trade.log_index, trade.source_wallet, trade.asset_id))
    client = MarketDataClient(position_cache_ttl_seconds=300)
    if args.source == "sqlite":
        metadata_by_asset = load_sqlite_metadata(Path(args.wallet_db), source_trades)
    else:
        metadata_by_asset = load_or_fetch_metadata(
            client=client,
            wallet_db=Path(args.wallet_db),
            activity_rows=[row for rows in activities_by_wallet.values() for row in rows],
            trades=source_trades,
            max_gamma_requests=args.max_gamma_requests,
            metadata_workers=args.metadata_workers,
        )
    mark_prices = {
        asset_id: price
        for asset_id, metadata in metadata_by_asset.items()
        if (price := _optional_float(metadata.get("current_price"))) is not None
    }
    for trade in source_trades:
        metadata = metadata_by_asset.get(trade.asset_id) or fallback_metadata_from_activity(trade, {})
        replay_metadata = metadata_for_replay(metadata)
        store.upsert_market_metadata(asset_id=trade.asset_id, **replay_metadata)

    if args.source == "onchain" and analysis_start_block is not None:
        analysis_trades = [trade for trade in source_trades if trade.block_number >= analysis_start_block]
    else:
        analysis_trades = [trade for trade in source_trades if _trade_utc(trade) >= analysis_start]

    candidate_selection: CandidateSelection | None = None
    if args.candidate_filtered:
        preload_source_trades(store, source_trades)
        candidate_selection = select_filtered_replay_candidates(
            store=store,
            trades=source_trades,
            metadata_by_asset=metadata_by_asset,
            analysis_start=analysis_start,
            analysis_start_block=analysis_start_block if args.source == "onchain" else None,
        )
        engine = PreloadedReplayCopyTradingEngine(config=config, store=store)
        processed_trades = candidate_selection.trades
    else:
        engine = HistoricalReplayCopyTradingEngine(
            config=config,
            store=store,
            source_trades=source_trades,
        )
        processed_trades = source_trades
    stats = engine.process_trades(processed_trades)

    paper_metrics = paper_position_metrics(store)
    attribution = attribution_summary(store, processed_trades if args.candidate_filtered else None)
    event_coverage = event_book_coverage(store, analysis_trades if args.candidate_filtered else source_trades, metadata_by_asset)
    source_by_wallet = {
        name: source_position_metrics(
            [trade for trade in source_trades if trade.source_wallet.lower() == wallet.lower()],
            mark_prices=mark_prices,
        )
        for name, wallet in DEFAULT_WALLETS.items()
    }
    analysis_by_wallet = {
        name: source_position_metrics(
            [trade for trade in analysis_trades if trade.source_wallet.lower() == wallet.lower()],
            mark_prices=mark_prices,
        )
        for name, wallet in DEFAULT_WALLETS.items()
    }

    report = {
        "generated_at_pdt": datetime.now(PDT).strftime("%Y-%m-%d %H:%M PDT"),
        "input": {
            "source": args.source,
            "analysis_hours": analysis_hours,
            "warmup_hours": args.warmup_hours,
            "start_pdt": analysis_start.astimezone(PDT).strftime("%Y-%m-%d %H:%M PDT"),
            "end_pdt": end_utc.astimezone(PDT).strftime("%Y-%m-%d %H:%M PDT"),
            "starting_cash_usdc": args.starting_cash,
            "slippage_pct": args.slippage_pct,
            "max_trades_per_wallet": args.max_trades_per_wallet,
            "wallet_db": str(Path(args.wallet_db)),
            "scratch_db": str(scratch_db),
            "data_api_url": DATA_API_URL,
            "onchain_scan": onchain_scan,
            "candidate_filtered": bool(args.candidate_filtered),
            "processed_source_trades": len(processed_trades),
        },
        "fetch_counts": {
            name: sum(1 for trade in source_trades if trade.source_wallet.lower() == wallet.lower())
            for name, wallet in DEFAULT_WALLETS.items()
        },
        "analysis_counts": {
            name: sum(1 for trade in analysis_trades if trade.source_wallet.lower() == wallet.lower())
            for name, wallet in DEFAULT_WALLETS.items()
        },
        "candidate_filter": None
        if candidate_selection is None
        else {
            "candidate_trades": len(candidate_selection.trades),
            "reasons": candidate_selection.reasons,
            "excluded_reasons": candidate_selection.excluded_reasons,
        },
        "source_time_ranges": source_time_ranges(source_trades),
        "metadata": {
            "assets": len(metadata_by_asset),
            "marked_assets": len(mark_prices),
        },
        "engine_stats": stats,
        "source_metrics_replay_window": source_by_wallet,
        "source_metrics_analysis_window": analysis_by_wallet,
        "paper_metrics": paper_metrics,
        "paper_metrics_by_wallet": paper_position_metrics_by_wallet(store),
        "attribution": attribution,
        "event_book_coverage": event_coverage,
        "limitations": [
            "Source fills are replayed with source fill price plus configured slippage; historical order-book depth is not reconstructed.",
            "Current Gamma metadata is used for classification and mark prices, but replay clears closed/resolution flags to avoid false historical market_closed skips.",
            "On-chain per-fill timestamps are interpolated from scan endpoint blocks; execution order and analysis windows use exact block/log ordering.",
            "Source-position floors are reconstructed only from replayed source trades as of each processed trade.",
            "Source inventory before the replay window is unknown; use warmup_hours to reduce mid-position distortion.",
        ],
    }
    output_path = output_dir / f"event_book_backtest_{stamp}.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["input"]["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def fetch_wallet_activity(
    *,
    session: requests.Session,
    wallet: str,
    since_utc: datetime,
    limit: int,
    max_offset: int,
    max_rows: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset <= max_offset:
        response = session.get(
            f"{DATA_API_URL}/activity",
            params={"user": wallet, "limit": limit, "offset": offset, "type": TRADE_TYPE},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        page = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(page, list) or not page:
            break
        keep_fetching = False
        for row in page:
            if not isinstance(row, dict):
                continue
            timestamp = _int(row.get("timestamp"), default=0)
            row_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if row_time >= since_utc:
                rows.append(row)
                keep_fetching = True
                if len(rows) >= max_rows:
                    return rows
        if not keep_fetching:
            break
        if len(page) < limit:
            break
        offset += limit
    return rows


def preload_source_trades(store: Store, trades: list[SourceTrade]) -> int:
    if not trades:
        return 0
    rows = [
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
        )
        for trade in trades
    ]
    con = sqlite3.connect(store.path)
    try:
        cursor = con.executemany(
            """
            insert or ignore into source_trades (
              idempotency_key, copy_trade_key, chain_id, exchange_contract, tx_hash, block_number,
              block_timestamp, log_index, source_wallet, side, asset_id, condition_id,
              market_id, outcome, price, quantity, notional_usdc
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
        return max(0, int(cursor.rowcount or 0))
    finally:
        con.close()


def select_filtered_replay_candidates(
    *,
    store: Store,
    trades: list[SourceTrade],
    metadata_by_asset: dict[str, dict[str, Any]],
    analysis_start: datetime,
    analysis_start_block: int | None = None,
) -> CandidateSelection:
    candidates: list[SourceTrade] = []
    included_reasons: Counter[str] = Counter()
    excluded_reasons: Counter[str] = Counter()
    wallet_cache: dict[str, dict[str, Any]] = {}
    event_positions: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    selected_events: set[tuple[str, str]] = set()
    selected_asset_targets: dict[tuple[str, str, str], float] = {}
    for trade in trades:
        metadata = metadata_by_asset.get(trade.asset_id) or {}
        event_slug = str(metadata.get("event_slug") or "").strip()
        positions = update_replay_event_position(
            event_positions=event_positions,
            trade=trade,
            metadata=metadata,
        )
        if not _trade_in_analysis_window(trade, analysis_start=analysis_start, analysis_start_block=analysis_start_block):
            continue
        include, reason, target_notional = filtered_replay_candidate_decision(
            store=store,
            trade=trade,
            metadata=metadata,
            event_positions=positions,
            wallet_cache=wallet_cache,
            selected_events=selected_events,
            selected_asset_targets=selected_asset_targets,
        )
        if reason is None:
            continue
        if not include:
            excluded_reasons[reason] += 1
            continue
        candidates.append(trade)
        included_reasons[reason] += 1
        if event_slug:
            selected_events.add((trade.source_wallet.lower(), event_slug))
            selected_asset_targets[(trade.source_wallet.lower(), event_slug, trade.asset_id)] = max(
                target_notional,
                selected_asset_targets.get((trade.source_wallet.lower(), event_slug, trade.asset_id), 0.0),
            )
    return CandidateSelection(
        trades=candidates,
        reasons=dict(included_reasons.most_common()),
        excluded_reasons=dict(excluded_reasons.most_common()),
    )


def update_replay_event_position(
    *,
    event_positions: dict[tuple[str, str], dict[str, dict[str, Any]]],
    trade: SourceTrade,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    event_slug = str(metadata.get("event_slug") or "").strip()
    if not event_slug:
        return []
    by_asset = event_positions[(trade.source_wallet.lower(), event_slug)]
    item = by_asset.setdefault(
        trade.asset_id,
        {
            "asset_id": trade.asset_id,
            "buy_count": 0,
            "buy_notional_usdc": 0.0,
            "buy_quantity": 0.0,
            "sell_notional_usdc": 0.0,
            "sell_quantity": 0.0,
        },
    )
    if trade.side == "buy":
        item["buy_count"] += 1
        item["buy_notional_usdc"] += float(trade.notional_usdc or 0)
        item["buy_quantity"] += float(trade.quantity or 0)
    elif trade.side == "sell":
        item["sell_notional_usdc"] += float(trade.notional_usdc or 0)
        item["sell_quantity"] += float(trade.quantity or 0)
    positions: list[dict[str, Any]] = []
    for position in by_asset.values():
        buy_quantity = float(position.get("buy_quantity") or 0)
        buy_notional = float(position.get("buy_notional_usdc") or 0)
        net_quantity = buy_quantity - float(position.get("sell_quantity") or 0)
        avg_buy_price = buy_notional / buy_quantity if buy_quantity > 0 else 0.0
        if net_quantity <= 0:
            continue
        positions.append(
            {
                **position,
                "net_quantity": round(net_quantity, 6),
                "net_notional_usdc": round(max(0.0, net_quantity) * avg_buy_price, 6),
                "avg_buy_price": round(avg_buy_price, 6),
            }
        )
    return sorted(positions, key=lambda item: float(item.get("net_notional_usdc") or 0), reverse=True)


def filtered_replay_candidate_decision(
    *,
    store: Store,
    trade: SourceTrade,
    metadata: dict[str, Any],
    event_positions: list[dict[str, Any]],
    wallet_cache: dict[str, dict[str, Any]],
    selected_events: set[tuple[str, str]],
    selected_asset_targets: dict[tuple[str, str, str], float],
) -> tuple[bool, str | None, float]:
    if trade.side == "sell":
        return True, "sell", 0.0
    if trade.side != "buy":
        return False, None, 0.0
    wallet = wallet_cache.setdefault(trade.source_wallet.lower(), store.get_wallet(trade.source_wallet) or {})
    if not engine_rules._copy_buys_enabled(wallet):
        return False, "copy_buys_disabled", 0.0
    paused_reason = engine_rules._source_wallet_paused_sport_reason(trade.source_wallet, metadata, wallet)
    if paused_reason is not None:
        return False, paused_reason, 0.0
    sport = engine_rules._event_sport_group(metadata)
    bet_type = engine_rules._event_bet_type(metadata)
    if sport not in engine_rules._filter_copy_allowed_sports(trade.source_wallet, wallet):
        return False, None, 0.0
    if bet_type not in engine_rules._filter_copy_allowed_bet_types(wallet):
        if not (
            trade.source_wallet.lower() == SWISSTONY
            and bet_type == "draw"
            and str(metadata.get("event_slug") or "").strip()
        ):
            return False, None, 0.0
    if not str(metadata.get("event_slug") or "").strip():
        return False, None, 0.0
    event_key = (trade.source_wallet.lower(), str(metadata.get("event_slug") or "").strip())
    has_selected_event = event_key in selected_events
    if not has_selected_event:
        min_single_fill = engine_rules._filter_copy_min_single_fill_usdc(trade.source_wallet, wallet)
        if min_single_fill > 0 and float(trade.notional_usdc or 0) < min_single_fill:
            return False, "filter_copy_single_fill_too_small", 0.0
    source_notional = _replay_position_notional(event_positions, trade.asset_id)
    total_source_notional = sum(float(item.get("net_notional_usdc") or 0) for item in event_positions)
    min_source = engine_rules._filter_copy_min_cumulative_source_usdc(trade.source_wallet, wallet, metadata)
    if total_source_notional < min_source:
        return False, "event_book_waiting_for_source_position", 0.0
    if trade.source_wallet.lower() == RN1:
        min_asset_source = engine_rules._filter_copy_event_book_min_asset_source_notional(wallet)
        if not has_selected_event and min_asset_source > 0 and source_notional < min_asset_source:
            return False, "event_book_waiting_for_source_position", 0.0
        max_fresh_legs = engine_rules._wallet_profile_int(wallet, "event_book", "rn1_fresh_max_source_legs", 0)
        if not has_selected_event and max_fresh_legs > 0 and len(event_positions) > max_fresh_legs:
            return False, "rn1_event_book_too_complex", 0.0
        rn1_block = _rn1_candidate_block_reason(
            metadata=metadata,
            wallet=wallet,
            source_notional=source_notional,
            total_source_notional=total_source_notional,
            event_positions=event_positions,
            has_selected_event=has_selected_event,
        )
        if rn1_block is not None:
            return False, rn1_block, 0.0
    if trade.source_wallet.lower() == SWISSTONY and bet_type != "moneyline_winlose":
        return False, "filter_copy_market_blocked", 0.0
    price = _replay_candidate_price(metadata=metadata, trade=trade, event_positions=event_positions)
    fresh_min = engine_rules._wallet_profile_float(wallet, "event_book", "planner_fresh_min_price", 0.01)
    fresh_max = engine_rules._wallet_profile_float(wallet, "event_book", "planner_fresh_max_price", 0.95)
    rebalance_min = engine_rules._wallet_profile_float(wallet, "event_book", "planner_rebalance_min_price", 0.01)
    rebalance_max = engine_rules._wallet_profile_float(wallet, "event_book", "planner_rebalance_max_price", 0.98)
    if not has_selected_event and (price < fresh_min or price > fresh_max):
        return False, "event_book_fresh_price_blocked", 0.0
    if has_selected_event and (price < rebalance_min or price > rebalance_max):
        return False, "event_book_rebalance_price_blocked", 0.0
    min_order = max(engine_rules.POLYMARKET_MIN_BUY_NOTIONAL_USDC, 1.0)
    target_notional = _replay_candidate_target_notional(
        source_wallet=trade.source_wallet,
        wallet=wallet,
        metadata=metadata,
        source_notional=source_notional,
        total_source_notional=total_source_notional,
        min_source=min_source,
    )
    if target_notional < min_order:
        decision = "rebalance" if has_selected_event else "fresh_entry"
        return False, f"event_book_{decision}_below_min_order", target_notional
    existing_target = selected_asset_targets.get((trade.source_wallet.lower(), str(metadata.get("event_slug") or "").strip(), trade.asset_id), 0.0)
    if has_selected_event:
        target_delta = target_notional - existing_target
        if target_delta <= 0:
            return False, "event_book_target_met", target_notional
        if target_delta < min_order:
            return False, "event_book_rebalance_below_min_order", target_notional
    return True, f"{_wallet_name(trade.source_wallet).lower()}_{sport}_{bet_type}", target_notional


def _trade_in_analysis_window(
    trade: SourceTrade,
    *,
    analysis_start: datetime,
    analysis_start_block: int | None,
) -> bool:
    if analysis_start_block is not None:
        return trade.block_number >= analysis_start_block
    return _trade_utc(trade) >= analysis_start


def _replay_position_notional(event_positions: list[dict[str, Any]], asset_id: str) -> float:
    for item in event_positions:
        if str(item.get("asset_id") or "") == str(asset_id):
            return float(item.get("net_notional_usdc") or 0)
    return 0.0


def _rn1_candidate_block_reason(
    *,
    metadata: dict[str, Any],
    wallet: dict[str, Any],
    source_notional: float,
    total_source_notional: float,
    event_positions: list[dict[str, Any]],
    has_selected_event: bool,
) -> str | None:
    sport = engine_rules._event_sport_group(metadata)
    bet_type = engine_rules._event_bet_type(metadata)
    if bet_type == "map_or_game_winner" and sport != "esports":
        return "rn1_esports_map_not_extreme_dominant"
    if bet_type == "map_or_game_winner" and sport == "esports":
        min_share = engine_rules._wallet_profile_float(
            wallet,
            "event_book",
            "esports_fresh_min_dominance_share",
            engine_rules.RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_SHARE,
        )
        min_ratio = engine_rules._wallet_profile_float(
            wallet,
            "event_book",
            "esports_fresh_min_dominance_ratio",
            engine_rules.RN1_FILTER_COPY_ESPORTS_FRESH_MIN_DOMINANCE_RATIO,
        )
        return None if _dominant_enough(source_notional, total_source_notional, event_positions, min_share, min_ratio) else "rn1_esports_map_not_extreme_dominant"
    if not engine_rules._rn1_filter_copy_is_main_winner_market(metadata):
        return "filter_copy_market_blocked"
    if has_selected_event:
        return None
    min_share = engine_rules._rn1_filter_copy_event_book_min_dominance_share(
        RN1,
        metadata,
        wallet,
        has_event_exposure=False,
    )
    min_ratio = engine_rules._rn1_filter_copy_event_book_min_dominance_ratio(
        RN1,
        metadata,
        wallet,
        has_event_exposure=False,
    )
    return None if _dominant_enough(source_notional, total_source_notional, event_positions, min_share, min_ratio) else "rn1_event_book_not_dominant"


def _dominant_enough(
    source_notional: float,
    total_source_notional: float,
    event_positions: list[dict[str, Any]],
    min_share: float,
    min_ratio: float,
) -> bool:
    if source_notional <= 0 or total_source_notional <= 0:
        return False
    other = max(
        (float(item.get("net_notional_usdc") or 0) for item in event_positions if float(item.get("net_notional_usdc") or 0) != source_notional),
        default=0.0,
    )
    share = source_notional / total_source_notional
    ratio = source_notional / other if other > 0 else float("inf")
    return share >= min_share and ratio >= min_ratio


def _replay_candidate_price(
    *,
    metadata: dict[str, Any],
    trade: SourceTrade,
    event_positions: list[dict[str, Any]],
) -> float:
    current_price = _optional_float(metadata.get("current_price"))
    if current_price is not None and current_price > 0:
        return current_price
    for item in event_positions:
        if str(item.get("asset_id") or "") == trade.asset_id:
            avg_price = _optional_float(item.get("avg_buy_price"))
            if avg_price is not None and avg_price > 0:
                return avg_price
    return float(trade.price or 0)


def _replay_candidate_target_notional(
    *,
    source_wallet: str,
    wallet: dict[str, Any],
    metadata: dict[str, Any],
    source_notional: float,
    total_source_notional: float,
    min_source: float,
) -> float:
    if source_notional <= 0 or total_source_notional <= 0:
        return 0.0
    base_event_cap = engine_rules._wallet_profile_float(wallet, "event_book", "planner_base_event_budget_usdc", 5.0)
    max_event_cap = engine_rules._wallet_profile_float(wallet, "event_book", "planner_max_event_budget_usdc", 10.0)
    if source_wallet.lower() == RN1 and engine_rules._event_sport_group(metadata) in engine_rules.RN1_FILTER_COPY_TENNIS_SPORTS | {"esports"}:
        base_event_cap = engine_rules._wallet_profile_float(
            wallet,
            "event_book",
            "planner_rn1_tennis_esports_base_event_budget_usdc",
            min(base_event_cap, 5.0),
        )
        max_event_cap = engine_rules._wallet_profile_float(
            wallet,
            "event_book",
            "planner_rn1_tennis_esports_max_event_budget_usdc",
            min(max_event_cap, 10.0),
        )
    if source_wallet.lower() == SWISSTONY:
        base_event_cap = engine_rules._wallet_profile_float(wallet, "event_book", "planner_swisstony_base_event_budget_usdc", 3.0)
        max_event_cap = engine_rules._wallet_profile_float(wallet, "event_book", "planner_swisstony_max_event_budget_usdc", 5.0)
    conviction_floor = max(0.000001, float(min_source or 0))
    target_event = min(max_event_cap, base_event_cap * max(1.0, (total_source_notional / conviction_floor) ** 0.5))
    return round(target_event * (source_notional / total_source_notional), 6)


def fetch_sqlite_source_trades(
    *,
    wallet_db: Path,
    wallets: list[str],
    since_utc: datetime,
    until_utc: datetime,
) -> list[SourceTrade]:
    since_pdt = since_utc.astimezone(PDT).strftime("%Y-%m-%d %H:%M PDT")
    until_pdt = until_utc.astimezone(PDT).strftime("%Y-%m-%d %H:%M PDT")
    con = sqlite3.connect(wallet_db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            select
              idempotency_key, chain_id, exchange_contract, tx_hash, block_number, block_timestamp,
              log_index, source_wallet, side, asset_id, condition_id, market_id, outcome, price,
              quantity, notional_usdc, copy_trade_key
            from source_trades
            where lower(source_wallet) in ({})
              and exchange_contract <> 'local_exit'
              and block_timestamp >= ?
              and block_timestamp <= ?
            order by block_number, log_index, source_wallet, asset_id
            """.format(",".join("?" for _ in wallets)),
            (*[wallet.lower() for wallet in wallets], since_pdt, until_pdt),
        ).fetchall()
    finally:
        con.close()
    return [
        SourceTrade(
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
            price=float(row["price"]),
            quantity=float(row["quantity"]),
            notional_usdc=float(row["notional_usdc"]),
            condition_id=_string_or_none(row["condition_id"]),
            market_id=_string_or_none(row["market_id"]),
            outcome=_string_or_none(row["outcome"]),
            copy_trade_key=_string_or_none(row["copy_trade_key"]),
        )
        for row in rows
    ]


def load_sqlite_metadata(wallet_db: Path, trades: list[SourceTrade]) -> dict[str, dict[str, Any]]:
    asset_ids = sorted({trade.asset_id for trade in trades if trade.asset_id})
    if not asset_ids:
        return {}
    con = sqlite3.connect(wallet_db)
    con.row_factory = sqlite3.Row
    metadata: dict[str, dict[str, Any]] = {}
    try:
        for offset in range(0, len(asset_ids), 500):
            chunk = asset_ids[offset : offset + 500]
            rows = con.execute(
                "select * from market_metadata where asset_id in ({})".format(",".join("?" for _ in chunk)),
                tuple(chunk),
            ).fetchall()
            for row in rows:
                metadata[str(row["asset_id"])] = dict(row)
    finally:
        con.close()
    return metadata


def parse_backtest_time(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("time value is required")
    if text.endswith(" PDT"):
        parsed = datetime.strptime(text.removesuffix(" PDT"), "%Y-%m-%d %H:%M")
        return parsed.replace(tzinfo=PDT).astimezone(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PDT)
    return parsed.astimezone(timezone.utc)


def block_timestamp_utc(rpc: Any, block_number: int) -> datetime:
    block = rpc_call_with_retries(rpc, "eth_getBlockByNumber", [hex(int(block_number)), False])
    timestamp = int(block["timestamp"], 16)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def block_number_with_retries(rpc: Any) -> int:
    return int(rpc_call_with_retries(rpc, "eth_blockNumber", []), 16)


def block_timestamp_pdt(rpc: Any, block_number: int) -> str:
    return block_timestamp_utc(rpc, block_number).astimezone(PDT).strftime("%Y-%m-%d %H:%M PDT")


def interpolated_block_timestamp_resolver(
    *,
    from_block: int,
    to_block: int,
    from_time_utc: datetime,
    to_time_utc: datetime,
) -> Callable[[int], str]:
    clean_from_block = int(from_block)
    clean_to_block = max(clean_from_block, int(to_block))
    clean_from_time = from_time_utc.astimezone(timezone.utc)
    clean_to_time = to_time_utc.astimezone(timezone.utc)
    block_span = max(1, clean_to_block - clean_from_block)
    second_span = max(0.0, (clean_to_time - clean_from_time).total_seconds())

    def resolve(block_number: int) -> str:
        ratio = (int(block_number) - clean_from_block) / block_span
        timestamp = clean_from_time + timedelta(seconds=second_span * ratio)
        return timestamp.astimezone(PDT).strftime("%Y-%m-%d %H:%M PDT")

    return resolve


def rpc_call_with_retries(rpc: Any, method: str, params: list[Any]) -> Any:
    last_error: Exception | None = None
    for attempt in range(RPC_RETRY_ATTEMPTS):
        try:
            return rpc.call(method, params)
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= RPC_RETRY_ATTEMPTS:
                break
            time.sleep(min(0.5 * (2**attempt), 4.0))
    raise last_error or RuntimeError(f"RPC call failed: {method}")


def find_block_at_or_after(
    rpc: Any,
    target_utc: datetime,
    *,
    latest_block: int | None = None,
    earliest_block: int = 0,
) -> int:
    target = target_utc.astimezone(timezone.utc)
    latest = block_number_with_retries(rpc) if latest_block is None else int(latest_block)
    earliest = max(0, int(earliest_block))
    if latest <= earliest:
        return latest
    latest_time = block_timestamp_utc(rpc, latest)
    if latest_time <= target:
        return latest
    low = earliest
    high = latest
    while low < high:
        mid = (low + high) // 2
        if block_timestamp_utc(rpc, mid) < target:
            low = mid + 1
        else:
            high = mid
    return low


def fetch_onchain_source_trades(
    *,
    rpc: Any,
    wallets: list[str],
    from_block: int,
    to_block: int,
    exchange_contracts: tuple[str, ...],
    chunk_size: int,
    timestamp_resolver: Callable[[int], str] | None = None,
) -> list[SourceTrade]:
    if from_block > to_block:
        return []
    addresses = resolve_exchange_addresses(exchange_contracts)
    tracked_wallets = {wallet.lower() for wallet in wallets}
    if not addresses or not tracked_wallets:
        return []
    wallet_topics = [address_topic(wallet) for wallet in sorted(tracked_wallets)]
    logs_by_key: dict[tuple[str, int, str], dict[str, Any]] = {}
    clean_chunk_size = max(1, int(chunk_size))
    for block_start in range(int(from_block), int(to_block) + 1, clean_chunk_size):
        block_end = min(int(to_block), block_start + clean_chunk_size - 1)
        for topics in (
            [ORDER_FILLED_TOPICS, None, wallet_topics],
            [ORDER_FILLED_TOPICS, None, None, wallet_topics],
        ):
            for log in fetch_logs_with_split(
                rpc=rpc,
                addresses=addresses,
                from_block=block_start,
                to_block=block_end,
                topics=topics,
            ):
                key = (
                    str(log["transactionHash"]).lower(),
                    int(str(log["logIndex"]), 16),
                    str(log.get("address", "")).lower(),
                )
                logs_by_key[key] = log
    timestamps: dict[int, str] = {}
    candidates: list[SourceTrade] = []
    for _, log in sorted(
        logs_by_key.items(),
        key=lambda item: (int(str(item[1]["blockNumber"]), 16), int(str(item[1]["logIndex"]), 16)),
    ):
        block_number = int(str(log["blockNumber"]), 16)
        if block_number not in timestamps:
            timestamps[block_number] = (
                timestamp_resolver(block_number) if timestamp_resolver is not None else block_timestamp_pdt(rpc, block_number)
            )
        trade = decode_order_filled_log(log, tracked_wallets=tracked_wallets, block_timestamp=timestamps[block_number])
        if trade is not None:
            candidates.append(trade)
    return select_copyable_order_fills(candidates, exchange_addresses=set(addresses))


def fetch_logs_with_split(
    *,
    rpc: Any,
    addresses: list[str],
    from_block: int,
    to_block: int,
    topics: list[Any],
) -> list[dict[str, Any]]:
    try:
        return fetch_logs_with_retries(
            rpc=rpc,
            addresses=addresses,
            from_block=from_block,
            to_block=to_block,
            topics=topics,
        )
    except Exception:
        if from_block >= to_block:
            raise
        midpoint = (from_block + to_block) // 2
        return [
            *fetch_logs_with_split(
                rpc=rpc,
                addresses=addresses,
                from_block=from_block,
                to_block=midpoint,
                topics=topics,
            ),
            *fetch_logs_with_split(
                rpc=rpc,
                addresses=addresses,
                from_block=midpoint + 1,
                to_block=to_block,
                topics=topics,
            ),
        ]


def fetch_logs_with_retries(
    *,
    rpc: Any,
    addresses: list[str],
    from_block: int,
    to_block: int,
    topics: list[Any],
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(RPC_RETRY_ATTEMPTS):
        try:
            return rpc.logs(addresses=addresses, from_block=from_block, to_block=to_block, topics=topics)
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= RPC_RETRY_ATTEMPTS:
                break
            time.sleep(min(0.5 * (2**attempt), 4.0))
    raise last_error or RuntimeError("eth_getLogs failed")


def resolve_exchange_addresses(names: tuple[str, ...]) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for name in names:
        values = EXCHANGE_ADDRESSES.get(name, name if str(name).startswith("0x") else None)
        if values is None:
            continue
        if isinstance(values, str):
            values = [values]
        for value in values:
            clean = str(value).lower()
            if clean not in seen:
                addresses.append(clean)
                seen.add(clean)
    return addresses


def address_topic(address: str) -> str:
    clean = str(address).lower()
    if clean.startswith("0x"):
        clean = clean[2:]
    return "0x" + ("0" * 24) + clean


def load_or_fetch_metadata(
    *,
    client: MarketDataClient,
    wallet_db: Path,
    activity_rows: list[dict[str, Any]],
    trades: list[SourceTrade],
    max_gamma_requests: int,
    metadata_workers: int,
) -> dict[str, dict[str, Any]]:
    asset_ids = {trade.asset_id for trade in trades}
    metadata_by_asset = load_metadata_from_db(wallet_db, asset_ids)
    by_asset_activity: dict[str, dict[str, Any]] = {}
    for row in activity_rows:
        asset_id = str(row.get("asset") or row.get("asset_id") or "").strip()
        if asset_id and asset_id not in by_asset_activity:
            by_asset_activity[asset_id] = row
    missing: dict[str, SourceTrade] = {}
    for trade in trades:
        if trade.asset_id in metadata_by_asset:
            continue
        missing.setdefault(trade.asset_id, trade)

    fetch_assets = list(missing)[: max(0, int(max_gamma_requests))]
    fetched_metadata: dict[str, dict[str, Any] | None] = {}
    if fetch_assets:
        workers = max(1, int(metadata_workers))
        if workers == 1:
            fetched_metadata = {asset_id: client.market_metadata(asset_id) for asset_id in fetch_assets}
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                fetched_metadata = dict(zip(fetch_assets, executor.map(client.market_metadata, fetch_assets), strict=True))

    for asset_id, trade in missing.items():
        metadata_by_asset[asset_id] = fetched_metadata.get(asset_id) or fallback_metadata_from_activity(
            trade,
            by_asset_activity.get(asset_id, {}),
        )
    return metadata_by_asset


def load_metadata_from_db(path: Path, asset_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    clean_assets = [str(asset_id) for asset_id in asset_ids if str(asset_id)]
    if not clean_assets:
        return {}
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        rows = []
        for index in range(0, len(clean_assets), 500):
            chunk = clean_assets[index : index + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(con.execute(f"select * from market_metadata where asset_id in ({placeholders})", chunk).fetchall())
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {str(row["asset_id"]): dict(row) for row in rows}


def fallback_metadata_from_activity(trade: SourceTrade, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_id": trade.market_id,
        "condition_id": trade.condition_id,
        "outcome": trade.outcome,
        "title": _string_or_none(row.get("title")),
        "market_slug": _string_or_none(row.get("slug")),
        "market_url": None,
        "market_type": "other",
        "sport_key": None,
        "bet_type": None,
        "series_slug": None,
        "sports_market_type": None,
        "category_slug": None,
        "event_slug": _string_or_none(row.get("eventSlug")),
        "event_title": _string_or_none(row.get("title")),
        "current_price": _optional_float(row.get("price")),
        "price_source": "activity_fallback",
        "is_closed": False,
        "resolution_price": None,
    }


def metadata_for_replay(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
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
        "event_slug",
        "event_title",
        "neg_risk",
        "mergeable",
        "current_price",
        "price_source",
        "last_price_at",
    }
    replay = {key: metadata.get(key) for key in allowed_keys if key in metadata}
    replay["is_closed"] = False
    replay["resolution_price"] = None
    replay["market_close_time"] = None
    replay["market_close_time_kind"] = None
    return replay


def clone_wallet_profiles(
    source_db: Path,
    target_store: Store,
    wallets: Any,
    *,
    event_book_planner: bool = False,
) -> None:
    con = sqlite3.connect(source_db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select * from wallets where lower(address) in ({})".format(",".join("?" for _ in wallets)),
            tuple(str(wallet).lower() for wallet in wallets),
        ).fetchall()
    finally:
        con.close()
    for row in rows:
        profile_json = json.loads(row["profile_json"]) if row["profile_json"] else None
        if event_book_planner:
            profile_json = enable_event_book_planner_profile(profile_json)
        target_store.upsert_wallet(
            name=row["name"],
            address=row["address"],
            enabled=bool(row["enabled"]),
            strategy_label=row["strategy_label"],
            strategy_notes=row["strategy_notes"],
            allowed_market_types=_lines(row["allowed_market_types"]),
            bracket_strategy_enabled=bool(row["bracket_strategy_enabled"]),
            bracket_buy_size_usdc=float(row["bracket_buy_size_usdc"]),
            bracket_stop_loss_pct=float(row["bracket_stop_loss_pct"]),
            bracket_max_open_events=int(row["bracket_max_open_events"]),
            bracket_allowed_patterns=_lines(row["bracket_allowed_patterns"]),
            repeat_buy_strategy_enabled=bool(row["repeat_buy_strategy_enabled"]),
            repeat_buy_size_usdc=float(row["repeat_buy_size_usdc"]),
            repeat_buy_stop_loss_pct=float(row["repeat_buy_stop_loss_pct"]),
            repeat_buy_min_source_notional_usdc=float(row["repeat_buy_min_source_notional_usdc"]),
            repeat_buy_min_buy_count=int(row["repeat_buy_min_buy_count"]),
            repeat_buy_min_avg_price=float(row["repeat_buy_min_avg_price"]),
            repeat_buy_max_avg_price=float(row["repeat_buy_max_avg_price"]),
            repeat_buy_max_total_exposure_usdc=float(row["repeat_buy_max_total_exposure_usdc"]),
            repeat_buy_blocked_title_patterns=_lines(row["repeat_buy_blocked_title_patterns"]),
            repeat_buy_allowed_sports=_lines(row["repeat_buy_allowed_sports"]),
            repeat_buy_allowed_bet_types=_lines(row["repeat_buy_allowed_bet_types"]),
            event_follow_strategy_enabled=bool(row["event_follow_strategy_enabled"]),
            event_follow_buy_size_usdc=float(row["event_follow_buy_size_usdc"]),
            event_follow_max_event_exposure_usdc=float(row["event_follow_max_event_exposure_usdc"]),
            event_follow_max_total_exposure_usdc=float(row["event_follow_max_total_exposure_usdc"]),
            event_follow_min_source_trade_usdc=float(row["event_follow_min_source_trade_usdc"]),
            event_follow_min_event_source_notional_usdc=float(row["event_follow_min_event_source_notional_usdc"]),
            event_follow_min_event_buy_count=int(row["event_follow_min_event_buy_count"]),
            event_follow_min_avg_price=float(row["event_follow_min_avg_price"]),
            event_follow_max_avg_price=float(row["event_follow_max_avg_price"]),
            sports_trailing_stop_enabled=bool(row["sports_trailing_stop_enabled"]),
            sports_trailing_activation_pct=float(row["sports_trailing_activation_pct"]),
            sports_trailing_stop_pct=float(row["sports_trailing_stop_pct"]),
            sports_trailing_floor_delta=float(row["sports_trailing_floor_delta"]),
            reserved_cash_usdc=float(row["reserved_cash_usdc"]),
            profile_json=profile_json,
        )


def enable_event_book_planner_profile(profile_json: Any) -> dict[str, Any]:
    profile = profile_json if isinstance(profile_json, dict) else {}
    profile.setdefault("event_book", {}).update(event_book_planner_default_overrides())
    return profile


def paper_position_metrics(store: Store) -> dict[str, Any]:
    positions = store.list_positions()
    con = sqlite3.connect(store.path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("select * from paper_trades").fetchall()
    finally:
        con.close()
    buy_notional = sum(float(row["notional_usdc"] or 0) for row in rows if row["side"] == "buy")
    sell_notional = sum(float(row["notional_usdc"] or 0) for row in rows if row["side"] == "sell")
    realized = sum(float(row["realized_pnl_usdc"] or 0) for row in rows)
    open_cost = sum(float(position.get("cost_basis_usdc") or 0) for position in positions)
    open_value = sum(float(position.get("current_value_usdc") or 0) for position in positions)
    unrealized = open_value - open_cost
    pnl = realized + unrealized
    return {
        "paper_trades": len(rows),
        "paper_buys": sum(1 for row in rows if row["side"] == "buy"),
        "paper_sells": sum(1 for row in rows if row["side"] == "sell"),
        "open_positions": len(positions),
        "buy_notional_usdc": round(buy_notional, 6),
        "sell_notional_usdc": round(sell_notional, 6),
        "open_cost_usdc": round(open_cost, 6),
        "open_value_usdc": round(open_value, 6),
        "realized_pnl_usdc": round(realized, 6),
        "unrealized_pnl_usdc": round(unrealized, 6),
        "pnl_usdc": round(pnl, 6),
        "roi_pct": round((pnl / buy_notional) * 100, 6) if buy_notional else 0.0,
    }


def paper_position_metrics_by_wallet(store: Store) -> dict[str, dict[str, Any]]:
    positions = store.list_positions()
    rows_by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position in positions:
        rows_by_wallet[_wallet_name(str(position.get("source_wallet") or ""))].append(position)
    con = sqlite3.connect(store.path)
    con.row_factory = sqlite3.Row
    try:
        trade_rows = con.execute("select * from paper_trades").fetchall()
    finally:
        con.close()
    result: dict[str, dict[str, Any]] = {}
    for wallet in sorted({*_wallet_names_from_rows(trade_rows), *rows_by_wallet.keys()}):
        wallet_trade_rows = [row for row in trade_rows if _wallet_name(str(row["source_wallet"])) == wallet]
        wallet_positions = rows_by_wallet.get(wallet, [])
        buy_notional = sum(float(row["notional_usdc"] or 0) for row in wallet_trade_rows if row["side"] == "buy")
        realized = sum(float(row["realized_pnl_usdc"] or 0) for row in wallet_trade_rows)
        open_cost = sum(float(position.get("cost_basis_usdc") or 0) for position in wallet_positions)
        open_value = sum(float(position.get("current_value_usdc") or 0) for position in wallet_positions)
        pnl = realized + open_value - open_cost
        result[wallet] = {
            "paper_buys": sum(1 for row in wallet_trade_rows if row["side"] == "buy"),
            "open_positions": len(wallet_positions),
            "buy_notional_usdc": round(buy_notional, 6),
            "open_cost_usdc": round(open_cost, 6),
            "open_value_usdc": round(open_value, 6),
            "pnl_usdc": round(pnl, 6),
            "roi_pct": round((pnl / buy_notional) * 100, 6) if buy_notional else 0.0,
        }
    return result


def attribution_summary(store: Store, trades: list[SourceTrade] | None = None) -> dict[str, Any]:
    included_keys = {trade.idempotency_key for trade in trades} if trades is not None else None
    con = sqlite3.connect(store.path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            select
              st.idempotency_key,
              st.source_wallet,
              st.side,
              coalesce(sta.executed, 0) as executed,
              coalesce(sta.skip_reason, '') as skip_reason,
              st.notional_usdc
            from source_trades st
            left join source_trade_attributions sta on sta.source_idempotency_key = st.idempotency_key
            """
        ).fetchall()
    finally:
        con.close()
    by_wallet: dict[str, dict[str, Any]] = {}
    for row in rows:
        if included_keys is not None and str(row["idempotency_key"]) not in included_keys:
            continue
        wallet = _wallet_name(str(row["source_wallet"]))
        item = by_wallet.setdefault(
            wallet,
            {
                "source_trades": 0,
                "source_buy_notional_usdc": 0.0,
                "executed_buy_trades": 0,
                "executed_buy_source_notional_usdc": 0.0,
                "skipped_buy_trades": 0,
                "skip_reasons": Counter(),
                "skip_reason_source_notional_usdc": defaultdict(float),
            },
        )
        item["source_trades"] += 1
        if row["side"] != "buy":
            continue
        notional = float(row["notional_usdc"] or 0)
        item["source_buy_notional_usdc"] += notional
        if int(row["executed"] or 0):
            item["executed_buy_trades"] += 1
            item["executed_buy_source_notional_usdc"] += notional
        else:
            reason = str(row["skip_reason"] or "no_attribution")
            item["skipped_buy_trades"] += 1
            item["skip_reasons"][reason] += 1
            item["skip_reason_source_notional_usdc"][reason] += notional
    for item in by_wallet.values():
        source_notional = item["source_buy_notional_usdc"]
        executed_notional = item["executed_buy_source_notional_usdc"]
        item["source_buy_notional_usdc"] = round(source_notional, 6)
        item["executed_buy_source_notional_usdc"] = round(executed_notional, 6)
        item["participation_pct"] = round((executed_notional / source_notional) * 100, 6) if source_notional else 0.0
        item["skip_reasons"] = dict(item["skip_reasons"].most_common())
        item["skip_reason_source_notional_usdc"] = {
            key: round(value, 6)
            for key, value in sorted(
                item["skip_reason_source_notional_usdc"].items(),
                key=lambda pair: abs(pair[1]),
                reverse=True,
            )
        }
    return by_wallet


def event_book_coverage(
    store: Store,
    trades: list[SourceTrade],
    metadata_by_asset: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_event_assets: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for trade in trades:
        if trade.side != "buy":
            continue
        event_slug = str((metadata_by_asset.get(trade.asset_id) or {}).get("event_slug") or "").strip()
        if not event_slug:
            continue
        source_event_assets[(trade.source_wallet.lower(), event_slug)][trade.asset_id] += trade.notional_usdc
    positions = store.list_positions()
    copied_event_assets: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for position in positions:
        event_slug = str(position.get("event_slug") or "").strip()
        if not event_slug:
            continue
        key = (str(position.get("source_wallet") or "").lower(), event_slug)
        copied_event_assets[key][str(position.get("asset_id"))] += float(position.get("cost_basis_usdc") or 0)
    events: list[dict[str, Any]] = []
    for key, copied_assets in copied_event_assets.items():
        source_assets = source_event_assets.get(key, {})
        source_total = sum(source_assets.values())
        copied_total = sum(copied_assets.values())
        missed_assets = [
            {"asset_id": asset_id, "source_notional_usdc": round(notional, 6)}
            for asset_id, notional in sorted(source_assets.items(), key=lambda pair: pair[1], reverse=True)
            if asset_id not in copied_assets and notional >= 1000
        ][:5]
        events.append(
            {
                "wallet": _wallet_name(key[0]),
                "event_slug": key[1],
                "source_notional_usdc": round(source_total, 6),
                "copied_cost_usdc": round(copied_total, 6),
                "source_legs": len(source_assets),
                "copied_legs": len(copied_assets),
                "coverage_pct": round((copied_total / source_total) * 100, 6) if source_total else 0.0,
                "missed_conviction_assets": missed_assets,
            }
        )
    events.sort(key=lambda item: item["copied_cost_usdc"], reverse=True)
    return {
        "copied_events": len(events),
        "top_events": events[:25],
        "events_with_missed_conviction_assets": sum(1 for item in events if item["missed_conviction_assets"]),
    }


def _trade_utc(trade: SourceTrade) -> datetime:
    try:
        return parse_backtest_time(trade.block_timestamp)
    except (TypeError, ValueError):
        if trade.block_number > 1_000_000_000:
            return datetime.fromtimestamp(trade.block_number, tz=timezone.utc)
        return datetime.min.replace(tzinfo=timezone.utc)


def _wallet_name(wallet: str) -> str:
    clean = wallet.lower()
    if clean == RN1:
        return "RN1"
    if clean == SWISSTONY:
        return "swisstony"
    return clean


def _wallet_names_from_rows(rows: list[sqlite3.Row]) -> set[str]:
    return {_wallet_name(str(row["source_wallet"])) for row in rows}


def source_time_ranges(trades: list[SourceTrade]) -> dict[str, dict[str, Any]]:
    ranges: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[SourceTrade]] = defaultdict(list)
    for trade in trades:
        grouped[_wallet_name(trade.source_wallet)].append(trade)
    for wallet, wallet_trades in grouped.items():
        ordered = sorted(wallet_trades, key=lambda trade: trade.block_number)
        ranges[wallet] = {
            "trades": len(ordered),
            "start_pdt": ordered[0].block_timestamp,
            "end_pdt": ordered[-1].block_timestamp,
        }
    return ranges


def _lines(value: Any) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay public Polymarket wallet activity through the current event-book copy strategy.")
    parser.add_argument("--config", default="config.example.yaml")
    parser.add_argument("--wallet-db", default=str(ROOT / "data" / "polymarket-copy-trading.sqlite3"))
    parser.add_argument("--source", choices=("data-api", "onchain", "sqlite"), default="data-api")
    parser.add_argument("--start", help='Analysis start time, for example "2026-05-08 00:00 PDT" or ISO-8601.')
    parser.add_argument("--end", help='Analysis end time, for example "2026-05-08 16:00 PDT" or ISO-8601.')
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--warmup-hours", type=float, default=24.0)
    parser.add_argument("--starting-cash", type=float, default=100.0)
    parser.add_argument("--slippage-pct", type=float, default=5.0)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-offset", type=int, default=3000)
    parser.add_argument("--max-trades-per-wallet", type=int, default=1000)
    parser.add_argument("--max-gamma-requests", type=int, default=500)
    parser.add_argument("--metadata-workers", type=int, default=16)
    parser.add_argument("--rpc-url", default=POLYGON_RPC_URL)
    parser.add_argument("--exchange-contracts", nargs="+", default=["ctf_exchange", "neg_risk_ctf_exchange"])
    parser.add_argument("--onchain-chunk-blocks", type=int, default=500)
    parser.add_argument("--confirmations", type=int, default=5)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--event-book-planner", action="store_true", help="Enable the new event-level RN1/swisstony planner in cloned wallet profiles.")
    parser.add_argument(
        "--candidate-filtered",
        action="store_true",
        help="Preload the replay window for source-book context, then process only analysis-window candidate trades.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run_backtest(parse_args(argv))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
