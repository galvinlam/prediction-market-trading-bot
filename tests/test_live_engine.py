from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.store import Store


def test_live_mode_records_order_intent_without_paper_fill(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    engine = CopyTradingEngine(config=config, store=store, buy_price_resolver=lambda asset_id: 0.51)
    trade = _source_buy()

    result = engine.process_trade(trade)

    assert result == "processed"
    assert store.list_trades()[0]["paper_side"] is None
    assert store.list_positions() == []
    intents = store.list_live_order_intents()
    assert len(intents) == 1
    assert intents[0]["source_idempotency_key"] == trade.idempotency_key
    assert intents[0]["asset_id"] == trade.asset_id
    assert intents[0]["side"] == "buy"
    assert intents[0]["price"] == 0.51
    assert intents[0]["notional_usdc"] == 10.0
    assert intents[0]["size"] == round(10.0 / 0.51, 6)
    assert intents[0]["status"] == "planned"


def test_live_mode_duplicate_source_trade_does_not_duplicate_order_intent(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    engine = CopyTradingEngine(config=config, store=store, buy_price_resolver=lambda asset_id: 0.50)
    trade = _source_buy()

    assert engine.process_trade(trade) == "processed"
    assert engine.process_trade(trade) == "duplicates"

    assert len(store.list_live_order_intents()) == 1


def test_live_mode_source_sell_records_sell_order_intent_without_paper_fill(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    store.insert_source_trade(_source_buy())
    _insert_live_position(store, quantity=20, avg_entry_price=0.50, current_price=0.60)
    engine = CopyTradingEngine(config=config, store=store)

    result = engine.process_trade(_source_sell(quantity=50, price=0.60))

    assert result == "processed"
    assert all(trade["paper_side"] is None for trade in store.list_trades())
    position = store.list_positions()[0]
    assert position["quantity"] == 20.0
    intents = store.list_live_order_intents()
    assert len(intents) == 1
    assert intents[0]["side"] == "sell"
    assert intents[0]["price"] == 0.60
    assert intents[0]["size"] == 10.0
    assert intents[0]["notional_usdc"] == 6.0
    assert intents[0]["status"] == "planned"


def test_live_mode_local_stop_loss_records_sell_order_intent_once(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    _insert_live_position(store, quantity=20, avg_entry_price=0.50, current_price=0.30)
    engine = CopyTradingEngine(config=config, store=store)

    exits = engine.process_local_exits()
    exits_again = engine.process_local_exits()

    assert exits == 1
    assert exits_again == 0
    assert all(trade["paper_side"] is None for trade in store.list_trades())
    assert len(store.list_positions()) == 1
    intents = store.list_live_order_intents()
    assert len(intents) == 1
    assert intents[0]["side"] == "sell"
    assert intents[0]["price"] == 0.30
    assert intents[0]["size"] == 20.0
    assert intents[0]["notional_usdc"] == 6.0
    assert intents[0]["status"] == "planned"


def test_live_mode_manual_sell_records_sell_order_intent(tmp_path: Path) -> None:
    config = _live_config(tmp_path)
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    _insert_live_position(store, quantity=12, avg_entry_price=0.40, current_price=0.55)
    engine = CopyTradingEngine(config=config, store=store)

    assert engine.process_manual_sell(asset_id="token-123", source_wallet="0x1111111111111111111111111111111111111111")

    assert all(trade["paper_side"] is None for trade in store.list_trades())
    intents = store.list_live_order_intents()
    assert len(intents) == 1
    assert intents[0]["side"] == "sell"
    assert intents[0]["price"] == 0.55
    assert intents[0]["size"] == 12.0
    assert intents[0]["notional_usdc"] == 6.6
    assert intents[0]["status"] == "planned"


def test_paper_mode_still_records_paper_fill(tmp_path: Path) -> None:
    config = _paper_config(tmp_path)
    store = Store(tmp_path / "paper.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    engine = CopyTradingEngine(config=config, store=store, buy_price_resolver=lambda asset_id: 0.50)

    result = engine.process_trade(_source_buy())

    assert result == "processed"
    assert store.list_live_order_intents() == []
    assert store.list_trades()[0]["paper_side"] == "buy"
    assert len(store.list_positions()) == 1


def test_paper_mode_records_live_shadow_audit_for_buy(tmp_path: Path) -> None:
    config = _paper_config(tmp_path, slippage_pct=5)
    store = Store(tmp_path / "paper.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    engine = CopyTradingEngine(config=config, store=store, buy_price_resolver=lambda asset_id: 0.50)

    result = engine.process_trade(_source_buy())

    assert result == "processed"
    assert store.list_live_order_intents() == []
    audit = store.list_live_shadow_audits()[0]
    assert audit["source_idempotency_key"] == _source_buy().idempotency_key
    assert audit["paper_trade_id"] > 0
    assert audit["asset_id"] == "token-123"
    assert audit["side"] == "buy"
    assert audit["paper_entry_price"] == 0.525
    assert audit["best_ask_at_decision"] == 0.50
    assert audit["order_price"] == 0.50
    assert audit["requested_notional_usdc"] == 10.0
    assert audit["requested_size"] == 20.0
    assert audit["would_fill_size"] is None
    assert audit["available_size_at_price"] is None
    assert audit["post_submit_book_price"] is None
    assert audit["decision_latency_ms"] is not None


def _paper_config(tmp_path: Path, *, slippage_pct: float = 0):
    path = tmp_path / "paper.yaml"
    path.write_text(_config_text("paper", slippage_pct=slippage_pct), encoding="utf-8")
    return load_config(path)


def _live_config(tmp_path: Path):
    path = tmp_path / "live.yaml"
    path.write_text(_config_text("live"), encoding="utf-8")
    return load_config(path)


def _config_text(mode: str, *, slippage_pct: float = 0) -> str:
    return f"""
mode:
  trading_mode: {mode}
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
sizing:
  copy_scale: 0.2
  max_trade_usdc: 10
  max_position_usdc: 25
  min_trade_usdc: 1
paper:
  starting_cash_usdc: 100
  slippage_pct: {slippage_pct}
"""


def _source_buy() -> SourceTrade:
    return SourceTrade(
        idempotency_key="137:0xaaa:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xaaa",
        block_number=100,
        block_timestamp="2026-05-02 14:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="token-123",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )


def _source_sell(*, quantity: float, price: float) -> SourceTrade:
    return SourceTrade(
        idempotency_key="137:0xbbb:2:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbbb",
        block_number=101,
        block_timestamp="2026-05-02 14:01 PDT",
        log_index=2,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="sell",
        asset_id="token-123",
        price=price,
        quantity=quantity,
        notional_usdc=round(quantity * price, 6),
    )


def _insert_live_position(
    store: Store,
    *,
    quantity: float,
    avg_entry_price: float,
    current_price: float,
) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            insert into positions (asset_id, source_wallet, quantity, avg_entry_price, realized_pnl_usdc, status)
            values ('token-123', '0x1111111111111111111111111111111111111111', ?, ?, 0, 'open')
            """,
            (quantity, avg_entry_price),
        )
    store.upsert_market_metadata(
        asset_id="token-123",
        current_price=current_price,
        price_source="test",
        neg_risk=False,
        market_type="other",
    )
