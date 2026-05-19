from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.store import Store
from polymarket_copy_trading.watcher import load_fixture_trades


SHARP = "0x8a091656e5f4c6bc4fdf37b2585be0235f68e317"


def test_fixture_pipeline_processes_configured_wallet_and_skips_duplicates(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
sizing:
  copy_scale: 0.25
  max_trade_usdc: 100
  max_position_usdc: 250
  min_trade_usdc: 5
paper:
  starting_cash_usdc: 1000
  slippage_pct: 5
""",
        encoding="utf-8",
    )
    fixture_path = tmp_path / "trades.json"
    fixture_path.write_text(
        """
[
  {
    "idempotency_key": "137:0xaaa:1:0x1111111111111111111111111111111111111111",
    "chain_id": 137,
    "exchange_contract": "ctf_exchange",
    "tx_hash": "0xaaa",
    "block_number": 100,
    "block_timestamp": "2026-04-26 16:45 PDT",
    "log_index": 1,
    "source_wallet": "0x1111111111111111111111111111111111111111",
    "side": "buy",
    "asset_id": "123",
    "price": 0.50,
    "quantity": 800,
    "notional_usdc": 400
  },
  {
    "idempotency_key": "137:0xbbb:1:0x2222222222222222222222222222222222222222",
    "chain_id": 137,
    "exchange_contract": "ctf_exchange",
    "tx_hash": "0xbbb",
    "block_number": 101,
    "block_timestamp": "2026-04-26 16:46 PDT",
    "log_index": 1,
    "source_wallet": "0x2222222222222222222222222222222222222222",
    "side": "buy",
    "asset_id": "456",
    "price": 0.25,
    "quantity": 400,
    "notional_usdc": 100
  }
]
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    engine = CopyTradingEngine(config=config, store=store)

    first = engine.process_trades(load_fixture_trades(fixture_path))
    second = engine.process_trades(load_fixture_trades(fixture_path))

    assert first["processed"] == 1
    assert first["ignored"] == 1
    assert second["duplicates"] == 1
    assert store.overview()["paper_cash_usdc"] == 900
    assert len(store.list_positions()) == 1


def test_sharp_crypto_copy_uses_fixed_five_dollar_buys_without_position_cap(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: Sharp_0x8a091
    address: "{SHARP}"
    allowed_market_types: ["crypto"]
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  copy_scale: 1
  max_trade_usdc: 100
  max_position_usdc: 3
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    store.upsert_market_metadata(asset_id="sharp-crypto-asset", market_type="crypto", current_price=0.50)
    engine = CopyTradingEngine(config=config, store=store)
    trades = [
        SourceTrade(
            idempotency_key=f"137:0xsharp{i}:1:{SHARP}",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash=f"0xsharp{i}",
            block_number=100 + i,
            block_timestamp=f"2026-05-02 09:0{i} PDT",
            log_index=1,
            source_wallet=SHARP,
            side="buy",
            asset_id="sharp-crypto-asset",
            price=0.50,
            quantity=200,
            notional_usdc=100,
            copy_trade_key=f"buy:sharp-crypto-asset:0.500000:100.{i:06d}",
        )
        for i in range(2)
    ]

    assert [engine.process_trade(trade) for trade in trades] == ["processed", "processed"]

    paper_buys = [trade for trade in store.list_trades() if trade["paper_side"] == "buy"]
    position = store.list_positions()[0]
    assert [trade["paper_notional_usdc"] for trade in paper_buys] == [5.0, 5.0]
    assert round(position["cost_basis_usdc"], 6) == 10.0


def test_sharp_crypto_copy_ignores_local_stop_loss(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: Sharp_0x8a091
    address: "{SHARP}"
    allowed_market_types: ["crypto"]
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 100
  max_position_usdc: 100
  min_trade_usdc: 1
exits:
  stop_loss_pct: 25
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = SourceTrade(
        idempotency_key=f"137:0xsharp-stop:1:{SHARP}",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xsharp-stop",
        block_number=100,
        block_timestamp="2026-05-02 09:00 PDT",
        log_index=1,
        source_wallet=SHARP,
        side="buy",
        asset_id="sharp-crypto-stop-asset",
        price=0.50,
        quantity=200,
        notional_usdc=100,
    )
    store.upsert_market_metadata(asset_id="sharp-crypto-stop-asset", market_type="crypto", current_price=0.50)
    engine = CopyTradingEngine(config=config, store=store)
    assert engine.process_trade(source_trade) == "processed"
    store.upsert_market_metadata(asset_id="sharp-crypto-stop-asset", market_type="crypto", current_price=0.20)

    assert CopyTradingEngine(config=config, store=store).process_local_exits() == 0
    assert len(store.list_positions()) == 1
    assert not any(trade["close_reason"] == "stop_loss" for trade in store.list_trades())


def test_engine_restart_does_not_reset_existing_paper_cash(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    first_engine = CopyTradingEngine(config=config, store=store)
    first_engine.process_trade(
        load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    )

    CopyTradingEngine(config=config, store=store)

    assert store.overview()["paper_cash_usdc"] == 990


def test_engine_restart_reconciles_stale_runtime_cash_from_ledger(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    engine = CopyTradingEngine(config=config, store=store)
    engine.process_trade(load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0])
    store.set_runtime_state("paper_cash_usdc", "995")

    CopyTradingEngine(config=config, store=store)

    assert store.overview()["paper_cash_usdc"] == 990


def test_engine_restart_hydrates_positions_before_processing_source_sell(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
  slippage_pct: 5
sizing:
  max_trade_usdc: 100
  max_position_usdc: 100
  min_trade_usdc: 5
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    first_engine = CopyTradingEngine(config=config, store=store)
    first_engine.process_trade(buy)
    sell = buy.__class__(
        **{
            **buy.__dict__,
            "idempotency_key": "137:0xsell:1:0x1111111111111111111111111111111111111111",
            "tx_hash": "0xsell",
            "side": "sell",
            "price": 0.7,
            "quantity": buy.quantity,
            "notional_usdc": buy.quantity * 0.7,
        }
    )

    result = CopyTradingEngine(config=config, store=store).process_trade(sell)
    paper_trades = store.list_trades()

    assert result == "processed"
    assert store.overview()["paper_cash_usdc"] == 1026.666667
    assert any(trade["paper_side"] == "sell" for trade in paper_trades)


def test_multiple_sources_same_trade_only_execute_first_and_record_all_sources(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
  - name: beta
    address: "0x2222222222222222222222222222222222222222"
paper:
  starting_cash_usdc: 1000
""",
        encoding="utf-8",
    )
    fixture_path = tmp_path / "same_trade.json"
    fixture_path.write_text(
        """
[
  {
    "idempotency_key": "137:0xaaa:1:0x1111111111111111111111111111111111111111",
    "chain_id": 137,
    "exchange_contract": "ctf_exchange",
    "tx_hash": "0xaaa",
    "block_number": 100,
    "block_timestamp": "2026-04-26 16:45 PDT",
    "log_index": 1,
    "source_wallet": "0x1111111111111111111111111111111111111111",
    "side": "buy",
    "asset_id": "123",
    "price": 0.5,
    "quantity": 800,
    "notional_usdc": 400
  },
  {
    "idempotency_key": "137:0xbbb:1:0x2222222222222222222222222222222222222222",
    "chain_id": 137,
    "exchange_contract": "ctf_exchange",
    "tx_hash": "0xbbb",
    "block_number": 101,
    "block_timestamp": "2026-04-26 16:46 PDT",
    "log_index": 1,
    "source_wallet": "0x2222222222222222222222222222222222222222",
    "side": "buy",
    "asset_id": "123",
    "price": 0.5,
    "quantity": 800,
    "notional_usdc": 400
  }
]
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)

    stats = CopyTradingEngine(config=config, store=store).process_trades(load_fixture_trades(fixture_path))
    trades = store.list_trades()

    assert stats["processed"] == 1
    assert stats["attributed"] == 1
    assert store.overview()["paper_cash_usdc"] == 990
    assert trades[0]["copied_from_count"] == 2
    assert trades[0]["copied_from_wallets"] == [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
    ]


def test_engine_uses_wallets_added_to_store_after_config_sync(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    store.upsert_wallet(name="beta", address="0x2222222222222222222222222222222222222222", enabled=True)
    trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    beta_trade = trade.__class__(
        **{
            **trade.__dict__,
            "idempotency_key": "137:0xbbb:1:0x2222222222222222222222222222222222222222",
            "tx_hash": "0xbbb",
            "source_wallet": "0x2222222222222222222222222222222222222222",
        }
    )

    stats = CopyTradingEngine(config=config, store=store).process_trades([beta_trade])

    assert stats["processed"] == 1


def test_engine_prices_paper_buy_from_local_market_quote_not_copied_trade_price(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]

    result = CopyTradingEngine(
        config=config,
        store=store,
        buy_price_resolver=lambda asset_id: 0.504,
    ).process_trade(source_trade)
    trade = store.list_trades()[0]
    position = store.list_positions()[0]

    assert result == "processed"
    assert trade["source_price"] == 0.5
    assert trade["fill_price"] == 0.5292
    assert position["avg_entry_price"] == 0.5292


def test_engine_skips_paper_buy_when_local_market_quote_is_unavailable(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]

    result = CopyTradingEngine(
        config=config,
        store=store,
        buy_price_resolver=lambda asset_id: None,
    ).process_trade(source_trade)
    trades = store.list_trades()

    assert result == "skipped"
    assert store.list_positions() == []
    assert trades[0]["skip_reason"] == "price_unavailable"


def test_engine_skips_buy_when_wallet_disallows_market_type(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["weather"]
market_filters:
  enabled_market_types: ["crypto", "weather"]
paper:
  starting_cash_usdc: 1000
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    store.upsert_market_metadata(asset_id="123", market_type="crypto")
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]

    result = CopyTradingEngine(config=config, store=store).process_trade(source_trade)
    trades = store.list_trades()

    assert result == "skipped"
    assert store.list_positions() == []
    assert trades[0]["skip_reason"] == "market_type_blocked"


def test_engine_hydrates_market_type_before_buy_gate(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["weather"]
market_filters:
  enabled_market_types: ["weather"]
paper:
  starting_cash_usdc: 1000
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]

    result = CopyTradingEngine(
        config=config,
        store=store,
        market_metadata_resolver=lambda asset_id: {
            "title": "Will the highest temperature in Miami be between 88-89F?",
            "outcome": "No",
            "market_type": "weather",
            "current_price": 0.72,
        },
    ).process_trade(source_trade)
    position = store.list_positions()[0]

    assert result == "processed"
    assert position["market_type"] == "weather"
    assert position["title"] == "Will the highest temperature in Miami be between 88-89F?"


def test_engine_skips_buy_after_market_close_time(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    store.upsert_market_metadata(
        asset_id=source_trade.asset_id,
        market_type="weather",
        market_close_time="2026-04-01 09:00 PDT",
    )

    result = CopyTradingEngine(config=config, store=store).process_trade(source_trade)
    trades = store.list_trades()

    assert result == "skipped"
    assert store.list_positions() == []
    assert trades[0]["skip_reason"] == "market_closed"


def test_engine_allows_in_play_sports_event_after_market_close_time(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    store.upsert_market_metadata(
        asset_id=source_trade.asset_id,
        market_type="sports",
        market_close_time="2026-04-01 09:00 PDT",
        event_slug="nba-lal-bos-2026-04-01",
        is_closed=False,
        resolution_price=None,
    )

    result = CopyTradingEngine(config=config, store=store).process_trade(source_trade)
    positions = store.list_positions()

    assert result == "processed"
    assert len(positions) == 1
    assert positions[0]["asset_id"] == source_trade.asset_id


def test_engine_skips_buy_when_market_has_resolution_price(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    store.upsert_market_metadata(
        asset_id=source_trade.asset_id,
        market_type="sports",
        is_closed=True,
        resolution_price=1.0,
    )

    result = CopyTradingEngine(config=config, store=store).process_trade(source_trade)
    trades = store.list_trades()

    assert result == "skipped"
    assert store.list_positions() == []
    assert trades[0]["skip_reason"] == "market_closed"


def test_source_sell_follows_same_fraction_of_source_inventory(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    sell = buy.__class__(
        **{
            **buy.__dict__,
            "idempotency_key": "137:0xsell:1:0x1111111111111111111111111111111111111111",
            "tx_hash": "0xsell",
            "block_number": buy.block_number + 1,
            "log_index": 0,
            "side": "sell",
            "price": 0.7,
            "quantity": buy.quantity * 0.25,
            "notional_usdc": buy.quantity * 0.25 * 0.7,
        }
    )

    result = CopyTradingEngine(config=config, store=store).process_trade(sell)
    position = store.list_positions()[0]
    sell_trade = [trade for trade in store.list_trades() if trade["paper_side"] == "sell"][0]

    assert result == "processed"
    assert round(position["quantity"], 6) == 15.0
    assert round(sell_trade["paper_quantity"], 6) == 5.0


def test_engine_records_no_position_skip_reason_for_unmatched_source_sell(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 1000
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = load_fixture_trades(Path(__file__).parent / "fixtures" / "single_buy.json")[0]
    sell = buy.__class__(
        **{
            **buy.__dict__,
            "idempotency_key": "137:0xsell:1:0x1111111111111111111111111111111111111111",
            "tx_hash": "0xsell",
            "side": "sell",
            "price": 0.7,
            "quantity": buy.quantity,
            "notional_usdc": buy.quantity * 0.7,
        }
    )

    result = CopyTradingEngine(config=config, store=store).process_trade(sell)
    trade = store.list_trades()[0]

    assert result == "skipped"
    assert trade["skip_reason"] == "no_position_to_sell"
