from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from polymarket_copy_trading.models import SourceTrade


def load_fixture_trades(path: str | Path) -> list[SourceTrade]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("fixture file must contain a list of source trades")
    return [_source_trade(item) for item in data]


def _source_trade(item: dict[str, Any]) -> SourceTrade:
    return SourceTrade(
        idempotency_key=str(item["idempotency_key"]),
        chain_id=int(item.get("chain_id", 137)),
        exchange_contract=str(item.get("exchange_contract", "ctf_exchange")),
        tx_hash=str(item["tx_hash"]),
        block_number=int(item["block_number"]),
        block_timestamp=str(item["block_timestamp"]),
        log_index=int(item["log_index"]),
        source_wallet=str(item["source_wallet"]).lower(),
        side=str(item["side"]).lower(),
        asset_id=str(item["asset_id"]),
        price=float(item["price"]),
        quantity=float(item["quantity"]),
        notional_usdc=float(item["notional_usdc"]),
        condition_id=item.get("condition_id"),
        market_id=item.get("market_id"),
        outcome=item.get("outcome"),
        raw_maker=item.get("raw_maker"),
        raw_taker=item.get("raw_taker"),
        raw_maker_asset_id=item.get("raw_maker_asset_id"),
        raw_taker_asset_id=item.get("raw_taker_asset_id"),
        raw_maker_amount_filled=item.get("raw_maker_amount_filled"),
        raw_taker_amount_filled=item.get("raw_taker_amount_filled"),
        copy_trade_key=item.get("copy_trade_key"),
    )
