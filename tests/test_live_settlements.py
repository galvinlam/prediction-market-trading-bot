from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.live_executor import LiveSettlementResult, redeem_planned_settlement_intents
from polymarket_copy_trading.price_monitor import PriceMonitor
from polymarket_copy_trading.store import Store


WALLET = "0x1111111111111111111111111111111111111111"


def test_live_mode_records_settlement_intent_without_paper_sell(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = _store_with_open_resolved_position(tmp_path, resolution_price=1.0)

    settlements = CopyTradingEngine(config=config, store=store).process_market_settlements()
    settlements_again = CopyTradingEngine(config=config, store=store).process_market_settlements()

    assert settlements == 1
    assert settlements_again == 0
    assert len(store.list_positions()) == 1
    assert not any(trade["paper_side"] == "sell" for trade in store.list_trades())
    intents = store.list_live_settlement_intents()
    assert len(intents) == 1
    assert intents[0]["source_wallet"] == WALLET
    assert intents[0]["asset_id"] == "settled-token"
    assert intents[0]["token_id"] == "settled-token"
    assert intents[0]["condition_id"] == "0xcondition"
    assert intents[0]["quantity"] == 20.0
    assert intents[0]["resolution_price"] == 1.0
    assert intents[0]["status"] == "planned"


def test_price_monitor_market_resolved_creates_live_settlement_intent(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = _store_with_open_resolved_position(tmp_path, resolution_price=None)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "market_resolved",
            "winning_asset_id": "settled-token",
            "assets_ids": ["settled-token", "loser-token"],
        }
    )

    assert stats == {"updated": 2, "exits": 0, "settlements": 1}
    assert store.list_positions()[0]["resolution_price"] == 1.0
    assert len(store.list_live_settlement_intents(status="planned")) == 1


def test_store_updates_live_settlement_intent_status(tmp_path: Path) -> None:
    store = _store_with_open_resolved_position(tmp_path, resolution_price=0.0)
    config = _live_config(tmp_path)
    assert CopyTradingEngine(config=config, store=store).process_market_settlements() == 1
    intent = store.list_live_settlement_intents()[0]

    redeemed = store.update_live_settlement_intent_status(
        intent["id"],
        status="redeemed",
        redemption_tx_hash="0xredeem",
        response={"transactionHash": "0xredeem"},
    )

    assert redeemed["status"] == "redeemed"
    assert redeemed["redemption_tx_hash"] == "0xredeem"
    assert redeemed["response_json"] == {"transactionHash": "0xredeem"}
    assert redeemed["error"] is None
    assert store.get_live_settlement_intent(intent["id"]) == redeemed
    assert store.list_live_settlement_intents(status="planned") == []


def test_redeem_planned_settlement_intents_updates_statuses(tmp_path: Path) -> None:
    store = _store_with_open_resolved_position(tmp_path, resolution_price=1.0)
    config = _live_config(tmp_path)
    assert CopyTradingEngine(config=config, store=store).process_market_settlements() == 1
    submitted: list[dict[str, object]] = []

    class FakeBroker:
        def redeem_settled_position(self, **kwargs):
            submitted.append(kwargs)
            return LiveSettlementResult(
                success=True,
                transaction_hash="0xsettled",
                status="redeemed",
                raw_response={"transactionHash": "0xsettled"},
                error=None,
            )

    stats = redeem_planned_settlement_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "redeemed": 1, "errors": 0}
    assert submitted == [
        {
            "condition_id": "0xcondition",
            "token_id": "settled-token",
            "resolution_price": 1.0,
            "size": 20.0,
        }
    ]
    intent = store.list_live_settlement_intents()[0]
    assert intent["status"] == "redeemed"
    assert intent["redemption_tx_hash"] == "0xsettled"


def test_redeem_planned_settlement_intents_keeps_failed_intent_retryable(tmp_path: Path) -> None:
    store = _store_with_open_resolved_position(tmp_path, resolution_price=1.0)
    config = _live_config(tmp_path)
    assert CopyTradingEngine(config=config, store=store).process_market_settlements() == 1

    class FakeBroker:
        def redeem_settled_position(self, **kwargs):
            return LiveSettlementResult(
                success=False,
                transaction_hash=None,
                status="error",
                raw_response={"error": "relayer unavailable"},
                error="relayer unavailable",
            )

    stats = redeem_planned_settlement_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "redeemed": 0, "errors": 1}
    intent = store.list_live_settlement_intents()[0]
    assert intent["status"] == "error"
    assert intent["error"] == "relayer unavailable"


def _live_config(tmp_path: Path):
    path = tmp_path / "live.yaml"
    path.write_text(
        f"""
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "{WALLET}"
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    return load_config(path)


def _store_with_open_resolved_position(tmp_path: Path, *, resolution_price: float | None) -> Store:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    with store._connect() as conn:
        conn.execute(
            """
            insert into wallets (address, name, enabled)
            values (?, 'alpha', 1)
            """,
            (WALLET,),
        )
        conn.execute(
            """
            insert into positions (asset_id, source_wallet, quantity, avg_entry_price, realized_pnl_usdc, status)
            values ('settled-token', ?, 20, 0.50, 0, 'open')
            """,
            (WALLET,),
        )
    store.upsert_market_metadata(
        asset_id="settled-token",
        condition_id="0xcondition",
        outcome="Yes",
        title="Settled market",
        current_price=resolution_price,
        price_source="resolution" if resolution_price is not None else None,
        is_closed=resolution_price is not None,
        resolution_price=resolution_price,
    )
    return store
