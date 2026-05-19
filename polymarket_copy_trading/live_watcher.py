from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any, Callable

import requests
import websockets

from polymarket_copy_trading.config import AppSettings
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.store import Store


POLYGON_RPC_URL = "https://polygon.drpc.org"
POLYGON_WS_URL = "wss://polygon.drpc.org"
EXCHANGE_ADDRESSES = {
    "ctf_exchange": [
        "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
        "0xE111180000d2663C0091e4f400237545B87B996B",
    ],
    "neg_risk_ctf_exchange": [
        "0xC5d563A36AE78145C45a50134d48A1215220f80a",
        "0xe2222d279d744050d28e00520010520000310F59",
    ],
    "ctf_exchange_legacy": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "neg_risk_ctf_exchange_legacy": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "ctf_exchange_v2": "0xE111180000d2663C0091e4f400237545B87B996B",
    "neg_risk_ctf_exchange_v2": "0xe2222d279d744050d28e00520010520000310F59",
}
SCALE = 1_000_000
LEGACY_ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
V2_ORDER_FILLED_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
ORDER_FILLED_TOPIC = V2_ORDER_FILLED_TOPIC
ORDER_FILLED_TOPICS = [LEGACY_ORDER_FILLED_TOPIC, V2_ORDER_FILLED_TOPIC]
PDT = timezone(timedelta(hours=-7), "PDT")


class RpcError(RuntimeError):
    pass


class PolygonRpcClient:
    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self._request_id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        response = requests.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RpcError(str(payload["error"]))
        return payload["result"]

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block_timestamp(self, block_number: int) -> str:
        block = self.call("eth_getBlockByNumber", [hex(block_number), False])
        timestamp = int(block["timestamp"], 16)
        return datetime.fromtimestamp(timestamp, tz=PDT).strftime("%Y-%m-%d %H:%M PDT")

    def logs(
        self,
        *,
        addresses: list[str],
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "address": addresses,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }
        if topics is not None:
            params["topics"] = topics
        return self.call(
            "eth_getLogs",
            [params],
        )


class LivePaperWatcher:
    def __init__(
        self,
        *,
        config: AppSettings,
        store: Store,
        rpc_url: str | None = None,
        ws_url: str | None = None,
        buy_price_resolver: Callable[[str], float | None] | None = None,
        market_metadata_resolver: Callable[[str], dict[str, Any] | None] | None = None,
        source_position_resolver: Callable[[str, str], dict[str, Any] | None] | None = None,
        config_reloader: Callable[[], AppSettings] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.config_reloader = config_reloader
        self.buy_price_resolver = buy_price_resolver
        self.market_metadata_resolver = market_metadata_resolver
        self.source_position_resolver = source_position_resolver
        self.rpc = PolygonRpcClient(rpc_url or os.environ.get("POLYGON_RPC_URL") or POLYGON_RPC_URL)
        self.ws_url = ws_url or os.environ.get("POLYGON_WS_URL") or POLYGON_WS_URL
        self.engine = CopyTradingEngine(
            config=config,
            store=store,
            buy_price_resolver=buy_price_resolver,
            market_metadata_resolver=market_metadata_resolver,
            source_position_resolver=source_position_resolver,
        )
        self.addresses = _resolve_exchange_addresses(config.watcher.exchange_contracts)

    def run_forever(self, *, poll_seconds: float = 2.0) -> None:
        self.store.set_runtime_state("paper_watcher_status", "starting")
        asyncio.run(self._run_ws_forever(reconnect_seconds=poll_seconds))

    async def _run_ws_forever(self, *, reconnect_seconds: float) -> None:
        delay = max(0.5, reconnect_seconds)
        while True:
            try:
                await self._run_ws_session()
                delay = max(0.5, reconnect_seconds)
            except Exception as exc:
                self._record_ws_disconnect(exc)
                self._catch_up_with_http()
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.watcher.ws_reconnect_max_seconds)

    async def _run_ws_session(self) -> None:
        async with websockets.connect(
            self.ws_url,
            ping_interval=self.config.watcher.ws_ping_interval_seconds,
            ping_timeout=self.config.watcher.ws_ping_timeout_seconds,
            close_timeout=self.config.watcher.ws_close_timeout_seconds,
        ) as websocket:
            await websocket.send(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]})
            )
            ack = json.loads(await websocket.recv())
            if "error" in ack:
                raise RpcError(str(ack["error"]))
            self.store.set_runtime_state("paper_watcher_status", "running_ws")
            self.store.set_runtime_state("paper_watcher_last_error", "")
            while True:
                message = json.loads(await websocket.recv())
                params = message.get("params") or {}
                result = params.get("result") or {}
                block_hex = result.get("number")
                if block_hex:
                    self.process_to_block(int(block_hex, 16) - self.config.watcher.confirmations)

    def _record_ws_disconnect(self, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"
        self.store.set_runtime_state("paper_watcher_status", "ws_reconnecting")
        self.store.set_runtime_state("paper_watcher_last_error", error[:500])

    def _catch_up_with_http(self) -> None:
        try:
            target = self.rpc.block_number() - self.config.watcher.confirmations
            stats = self.process_to_block(target)
            self.store.set_runtime_state("paper_watcher_status", "ws_reconnecting_caught_up")
            self.store.set_runtime_state("paper_watcher_last_stats", json.dumps(stats))
        except Exception as exc:
            self.store.set_runtime_state("paper_watcher_status", "ws_reconnecting_catchup_failed")
            self.store.set_runtime_state("paper_watcher_last_error", f"{type(exc).__name__}: {exc}"[:500])

    def process_to_block(self, target_block: int) -> dict[str, int]:
        if target_block < 0:
            return {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        last = self._last_processed_block()
        from_block = last + 1 if last is not None else max(0, target_block - self.config.watcher.backfill_blocks)
        if from_block > target_block:
            return {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}

        stats = {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        for block_start in range(from_block, target_block + 1, 25):
            block_end = min(target_block, block_start + 24)
            stats = _merge_stats(stats, self.process_block_range(block_start, block_end))
            self.store.set_runtime_state("watcher_last_processed_block", str(block_end))
        return stats

    def process_block_range(self, from_block: int, to_block: int) -> dict[str, int]:
        self._refresh_config()
        tracked_wallets = {wallet["address"] for wallet in self.store.list_wallets() if wallet["enabled"]}
        if not tracked_wallets:
            return {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        stats = {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
        timestamps: dict[int, str] = {}
        candidates: list[SourceTrade] = []
        logs = self._tracked_order_filled_logs(from_block=from_block, to_block=to_block, tracked_wallets=tracked_wallets)
        for log in logs:
            block_number = int(log["blockNumber"], 16)
            if block_number not in timestamps:
                timestamps[block_number] = self.rpc.block_timestamp(block_number)
            trade = decode_order_filled_log(log, tracked_wallets=tracked_wallets, block_timestamp=timestamps[block_number])
            if trade is None:
                continue
            candidates.append(trade)
        selected = select_copyable_order_fills(candidates, exchange_addresses=set(self.addresses))
        self.store.set_runtime_state(
            "paper_watcher_last_scan",
            json.dumps(
                {
                    "from_block": from_block,
                    "to_block": to_block,
                    "tracked_wallets": len(tracked_wallets),
                    "raw_logs": len(logs),
                    "decoded_trades": len(candidates),
                    "selected_trades": len(selected),
                }
            ),
        )
        for trade in selected:
            result = self.engine.process_trade(trade)
            stats[result] += 1
        if sum(stats.values()):
            self.store.set_runtime_state("paper_watcher_last_stats", json.dumps(stats))
        return stats

    def _refresh_config(self) -> None:
        if self.config_reloader is None:
            return
        config = self.config_reloader()
        if config == self.config:
            return
        self.config = config
        self.engine = CopyTradingEngine(
            config=config,
            store=self.store,
            buy_price_resolver=self.buy_price_resolver,
            market_metadata_resolver=self.market_metadata_resolver,
        )
        self.addresses = _resolve_exchange_addresses(config.watcher.exchange_contracts)

    def _tracked_order_filled_logs(
        self,
        *,
        from_block: int,
        to_block: int,
        tracked_wallets: set[str],
    ) -> list[dict[str, Any]]:
        wallet_topics = [_address_topic(wallet) for wallet in sorted(tracked_wallets)]
        logs_by_key: dict[tuple[str, int, str], dict[str, Any]] = {}
        for topics in (
            [ORDER_FILLED_TOPICS, None, wallet_topics],
            [ORDER_FILLED_TOPICS, None, None, wallet_topics],
        ):
            for log in self.rpc.logs(
                addresses=self.addresses,
                from_block=from_block,
                to_block=to_block,
                topics=topics,
            ):
                key = (str(log["transactionHash"]).lower(), int(log["logIndex"], 16), str(log.get("address", "")).lower())
                logs_by_key[key] = log
        return [
            log
            for _, log in sorted(
                logs_by_key.items(),
                key=lambda item: (int(item[1]["blockNumber"], 16), int(item[1]["logIndex"], 16)),
            )
        ]

    def _last_processed_block(self) -> int | None:
        value = self.store.get_runtime_state("watcher_last_processed_block")
        return int(value) if value is not None else None


def decode_order_filled_log(
    log: dict[str, Any],
    *,
    tracked_wallets: set[str],
    block_timestamp: str = "",
) -> SourceTrade | None:
    topics = log.get("topics") or []
    data = str(log.get("data") or "0x")
    if len(topics) != 4 or not data.startswith("0x"):
        return None
    topic0 = str(topics[0]).lower()
    if topic0 == LEGACY_ORDER_FILLED_TOPIC:
        return _decode_legacy_order_filled_log(log, tracked_wallets=tracked_wallets, block_timestamp=block_timestamp)
    if topic0 != V2_ORDER_FILLED_TOPIC:
        return None

    maker = _topic_address(topics[2])
    taker = _topic_address(topics[3])
    tracked = {wallet.lower() for wallet in tracked_wallets}
    if maker not in tracked and taker not in tracked:
        return None

    words = _data_words(data)
    if len(words) < 7:
        return None

    maker_side = int(words[0], 16)
    token_id = int(words[1], 16)
    maker_amount = int(words[2], 16)
    taker_amount = int(words[3], 16)
    source_wallet = maker if maker in tracked else taker
    source_side = _relative_side(source_wallet=source_wallet, maker=maker, maker_side=maker_side)
    token_amount, collateral_amount = _amounts_for_maker_side(
        maker_side=maker_side,
        maker_amount=maker_amount,
        taker_amount=taker_amount,
    )
    quantity = token_amount / SCALE
    notional = collateral_amount / SCALE
    if quantity <= 0:
        return None
    price = round(notional / quantity, 6)

    tx_hash = str(log["transactionHash"])
    log_index = int(log["logIndex"], 16)
    return SourceTrade(
        idempotency_key=f"137:{tx_hash}:{log_index}:{source_wallet}",
        chain_id=137,
        exchange_contract=str(log.get("address", "")).lower(),
        tx_hash=tx_hash,
        block_number=int(log["blockNumber"], 16),
        block_timestamp=block_timestamp,
        log_index=log_index,
        source_wallet=source_wallet,
        side=source_side,
        asset_id=str(token_id),
        price=price,
        quantity=quantity,
        notional_usdc=notional,
        raw_maker=maker,
        raw_taker=taker,
        raw_maker_asset_id=str(token_id if maker_side == 1 else 0),
        raw_taker_asset_id=str(0 if maker_side == 1 else token_id),
        raw_maker_amount_filled=str(maker_amount),
        raw_taker_amount_filled=str(taker_amount),
        copy_trade_key=f"{source_side}:{token_id}:{price:.6f}:{notional:.6f}",
    )


def _decode_legacy_order_filled_log(
    log: dict[str, Any],
    *,
    tracked_wallets: set[str],
    block_timestamp: str,
) -> SourceTrade | None:
    topics = log.get("topics") or []
    maker = _topic_address(topics[2])
    taker = _topic_address(topics[3])
    tracked = {wallet.lower() for wallet in tracked_wallets}
    if maker not in tracked and taker not in tracked:
        return None

    words = _data_words(str(log.get("data") or "0x"))
    if len(words) < 5:
        return None

    maker_asset_id = int(words[0], 16)
    taker_asset_id = int(words[1], 16)
    maker_amount = int(words[2], 16)
    taker_amount = int(words[3], 16)
    source_wallet = maker if maker in tracked else taker
    amounts = _legacy_amounts_for_source(
        source_wallet=source_wallet,
        maker=maker,
        maker_asset_id=maker_asset_id,
        taker_asset_id=taker_asset_id,
        maker_amount=maker_amount,
        taker_amount=taker_amount,
    )
    if amounts is None:
        return None
    source_side, token_id, token_amount, collateral_amount = amounts
    quantity = token_amount / SCALE
    notional = collateral_amount / SCALE
    if quantity <= 0:
        return None
    price = round(notional / quantity, 6)

    tx_hash = str(log["transactionHash"])
    log_index = int(log["logIndex"], 16)
    return SourceTrade(
        idempotency_key=f"137:{tx_hash}:{log_index}:{source_wallet}",
        chain_id=137,
        exchange_contract=str(log.get("address", "")).lower(),
        tx_hash=tx_hash,
        block_number=int(log["blockNumber"], 16),
        block_timestamp=block_timestamp,
        log_index=log_index,
        source_wallet=source_wallet,
        side=source_side,
        asset_id=str(token_id),
        price=price,
        quantity=quantity,
        notional_usdc=notional,
        raw_maker=maker,
        raw_taker=taker,
        raw_maker_asset_id=str(maker_asset_id),
        raw_taker_asset_id=str(taker_asset_id),
        raw_maker_amount_filled=str(maker_amount),
        raw_taker_amount_filled=str(taker_amount),
        copy_trade_key=f"{source_side}:{token_id}:{price:.6f}:{notional:.6f}",
    )


def select_copyable_order_fills(trades: list[SourceTrade], *, exchange_addresses: set[str]) -> list[SourceTrade]:
    exchanges = {address.lower() for address in exchange_addresses}
    exchange_summary_keys = {
        (trade.tx_hash.lower(), trade.source_wallet.lower())
        for trade in trades
        if _is_exchange_summary_trade(trade, exchange_addresses=exchanges)
    }
    return [
        trade
        for trade in trades
        if (trade.tx_hash.lower(), trade.source_wallet.lower()) not in exchange_summary_keys
        or _is_exchange_summary_trade(trade, exchange_addresses=exchanges)
    ]


def _relative_side(*, source_wallet: str, maker: str, maker_side: int) -> str:
    if source_wallet == maker:
        return "buy" if maker_side == 0 else "sell"
    return "sell" if maker_side == 0 else "buy"


def _amounts_for_maker_side(*, maker_side: int, maker_amount: int, taker_amount: int) -> tuple[int, int]:
    if maker_side == 0:
        return taker_amount, maker_amount
    return maker_amount, taker_amount


def _legacy_amounts_for_source(
    *,
    source_wallet: str,
    maker: str,
    maker_asset_id: int,
    taker_asset_id: int,
    maker_amount: int,
    taker_amount: int,
) -> tuple[str, int, int, int] | None:
    source_is_maker = source_wallet == maker
    if maker_asset_id == 0 and taker_asset_id != 0:
        if source_is_maker:
            return "buy", taker_asset_id, taker_amount, maker_amount
        return "sell", taker_asset_id, taker_amount, maker_amount
    if taker_asset_id == 0 and maker_asset_id != 0:
        if source_is_maker:
            return "sell", maker_asset_id, maker_amount, taker_amount
        return "buy", maker_asset_id, maker_amount, taker_amount
    return None


def _is_exchange_summary_trade(trade: SourceTrade, *, exchange_addresses: set[str]) -> bool:
    return (
        (trade.raw_maker or "").lower() == trade.source_wallet.lower()
        and (trade.raw_taker or "").lower() in exchange_addresses
    )


def _topic_address(topic: str) -> str:
    value = topic[2:] if topic.startswith("0x") else topic
    return "0x" + value[-40:].lower()


def _address_topic(address: str) -> str:
    clean = address[2:] if address.startswith("0x") else address
    return "0x" + ("0" * 24) + clean.lower()


def _data_words(data: str) -> list[str]:
    body = data[2:]
    return [body[index : index + 64] for index in range(0, len(body), 64) if len(body[index : index + 64]) == 64]


def _merge_stats(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: left.get(key, 0) + right.get(key, 0) for key in set(left) | set(right)}


def _resolve_exchange_addresses(names: list[str]) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for name in names:
        values = EXCHANGE_ADDRESSES.get(name, name if str(name).startswith("0x") else None)
        if values is None:
            continue
        if isinstance(values, str):
            values = [values]
        for value in values:
            clean = value.lower()
            if clean not in seen:
                addresses.append(clean)
                seen.add(clean)
    return addresses
