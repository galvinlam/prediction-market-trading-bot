from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import PaperFill, SourceTrade
from polymarket_copy_trading.price_monitor import PriceMonitor
from polymarket_copy_trading.store import Store


WALLET = "0x1111111111111111111111111111111111111111"


def make_buy(asset_id: str, *, price: float, notional: float = 100.0) -> SourceTrade:
    return SourceTrade(
        idempotency_key=f"137:0xbuy-{asset_id}:1:{WALLET}",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=f"0xbuy-{asset_id}",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet=WALLET,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
    )


def write_config(path: Path) -> None:
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "{WALLET}"
    allowed_market_types: ["sports", "other"]
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
winner_capture:
  enabled: true
  entry_price_max: 0.35
  recover_stake_multiple: 2.0
  first_scale_multiple: 4.0
  first_scale_sell_pct: 35
  high_price_threshold: 0.50
  high_price_sell_pct: 50
  runner_pct: 15
  trailing_drawdown_pct: 30
  high_price_absolute_trail: 0.12
""",
        encoding="utf-8",
    )


def test_config_reads_winner_capture_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)

    config = load_config(config_path)

    assert config.winner_capture.enabled is True
    assert config.winner_capture.entry_price_max == 0.35
    assert config.winner_capture.recover_stake_multiple == 2.0
    assert config.winner_capture.runner_pct == 15


def test_winner_capture_recovers_stake_on_double(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = make_buy("cheap-winner", price=0.10)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_market_metadata(asset_id="cheap-winner", market_type="other", current_price=0.10)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "cheap-winner", "best_bid": "0.20"}]}
    )
    position = store.list_positions()[0]
    trades = store.list_trades()

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert position["quantity"] == 50
    assert position["winner_capture_stake_recovered"] is True
    assert any(trade["paper_side"] == "sell" and trade["close_reason"] == "winner_recover_stake" for trade in trades)


def test_winner_capture_scales_out_to_runner_on_large_spike(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = make_buy("parabolic-winner", price=0.05)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_market_metadata(asset_id="parabolic-winner", market_type="sports", current_price=0.05)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "parabolic-winner", "best_bid": "0.50"}]}
    )
    position = store.list_positions()[0]
    close_reasons = [trade["close_reason"] for trade in store.list_trades() if trade["paper_side"] == "sell"]

    assert stats == {"updated": 1, "exits": 3, "settlements": 0}
    assert round(position["quantity"], 6) == 30.0
    assert position["winner_capture_stake_recovered"] is True
    assert position["winner_capture_first_scale_done"] is True
    assert position["winner_capture_high_price_done"] is True
    assert set(close_reasons) >= {"winner_recover_stake", "winner_scale", "winner_high_price"}


def test_winner_capture_trails_remaining_runner_after_peak_reversal(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = make_buy("runner-reversal", price=0.05)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_market_metadata(asset_id="runner-reversal", market_type="other", current_price=0.05)
    PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "runner-reversal", "best_bid": "0.50"}]}
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "runner-reversal", "best_bid": "0.36"}]}
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "winner_trailing_stop" for trade in store.list_trades())


def test_sports_mid_price_winner_capture_recovers_half_stake(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = make_buy("mid-price-winner", price=0.55)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_market_metadata(asset_id="mid-price-winner", market_type="sports", current_price=0.55)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "mid-price-winner", "best_bid": "0.75"}]}
    )
    trades = store.list_trades()
    position = store.list_positions()[0]

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert position["winner_capture_stake_recovered"] is False
    assert any(trade["paper_side"] == "sell" and trade["close_reason"] == "sports_winner_recover_half_stake" for trade in trades)


def test_sports_mid_price_winner_capture_keeps_runner_after_high_price(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = make_buy("mid-price-parabolic", price=0.55)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_market_metadata(asset_id="mid-price-parabolic", market_type="sports", current_price=0.55)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "mid-price-parabolic", "best_bid": "0.92"}]}
    )
    position = store.list_positions()[0]
    close_reasons = [trade["close_reason"] for trade in store.list_trades() if trade["paper_side"] == "sell"]

    assert stats == {"updated": 1, "exits": 3, "settlements": 0}
    assert round(position["quantity"], 6) == round((10 / 0.55) * 0.15, 6)
    assert set(close_reasons) >= {
        "sports_winner_recover_half_stake",
        "sports_winner_recover_stake",
        "sports_winner_high_price",
    }


def test_live_sports_dead_cut_exits_before_near_zero_when_no_rally(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="alpha",
        address=WALLET,
        enabled=True,
        allowed_market_types=["sports"],
    )
    store.upsert_market_metadata(asset_id="dead-live-sport", market_type="sports", current_price=0.45)
    buy = make_buy("dead-live-sport", price=0.45)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.update_wallet(WALLET, event_follow_strategy_enabled=True, sports_trailing_stop_enabled=True)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "dead-live-sport", "best_bid": "0.08"}]}
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "sports_dead_cut" for trade in store.list_trades())


def test_live_sports_no_orderbook_loser_exits_after_close_time(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="alpha",
        address=WALLET,
        enabled=True,
        allowed_market_types=["sports"],
    )
    store.upsert_market_metadata(asset_id="settled-loser-sport", market_type="sports", current_price=0.45)
    buy = make_buy("settled-loser-sport", price=0.45)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.update_wallet(WALLET, event_follow_strategy_enabled=True)
    store.upsert_market_metadata(
        asset_id="settled-loser-sport",
        market_type="sports",
        event_slug="mlb-cle-oak-2026-05-02",
        current_price=0.001,
        price_source="clob_no_orderbook",
        market_close_time="2026-05-02 13:05 PDT",
        is_closed=False,
        resolution_price=None,
    )

    exits = CopyTradingEngine(config=config, store=store).process_local_exits()

    assert exits == 1
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "sports_event_lost" for trade in store.list_trades())


def test_live_sports_quoted_loser_exits_after_long_post_close_grace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="alpha",
        address=WALLET,
        enabled=True,
        allowed_market_types=["sports"],
    )
    store.upsert_market_metadata(asset_id="quoted-loser-sport", market_type="sports", current_price=0.45)
    buy = make_buy("quoted-loser-sport", price=0.45)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.update_wallet(WALLET, event_follow_strategy_enabled=True)
    store.upsert_market_metadata(
        asset_id="quoted-loser-sport",
        market_type="sports",
        event_slug="nba-phi-bos-2026-05-02",
        current_price=0.001,
        price_source="clob_sell",
        market_close_time="2026-05-02 13:05 PDT",
        is_closed=False,
        resolution_price=None,
    )

    exits = CopyTradingEngine(config=config, store=store).process_local_exits()

    assert exits == 1
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "sports_event_lost" for trade in store.list_trades())


def test_live_sports_dead_cut_waits_when_position_had_meaningful_rally(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="alpha",
        address=WALLET,
        enabled=True,
        allowed_market_types=["sports"],
    )
    store.upsert_market_metadata(asset_id="rallied-live-sport", market_type="sports", current_price=0.45)
    buy = make_buy("rallied-live-sport", price=0.45)
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.update_wallet(WALLET, event_follow_strategy_enabled=True, sports_trailing_stop_enabled=True)
    PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "rallied-live-sport", "best_bid": "0.55"}]}
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "rallied-live-sport", "best_bid": "0.08"}]}
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert len(store.list_positions()) == 1
    assert not any(trade["close_reason"] == "sports_dead_cut" for trade in store.list_trades())


def test_repeat_buy_stop_loss_pauses_when_opposite_condition_breaks_out(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=WALLET,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_stop_loss_pct=40.0,
    )
    for asset_id, outcome, entry_price, current_price in (
        ("deportivo-yes", "Yes", 0.58, 0.29),
        ("deportivo-no", "No", 0.17, 0.60),
    ):
        source = make_buy(asset_id, price=entry_price, notional=5.0)
        store.insert_source_trade(source)
        store.record_paper_fill(
            PaperFill(
                source_idempotency_key=source.idempotency_key,
                side="buy",
                asset_id=asset_id,
                source_wallet=WALLET,
                observed_price=entry_price,
                fill_price=entry_price,
                quantity=5.0 / entry_price,
                notional_usdc=5.0,
            ),
            cash_after_usdc=95.0,
            position_quantity=5.0 / entry_price,
            avg_entry_price=entry_price,
        )
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            condition_id="deportivo-win-condition",
            title="Will RC Deportivo La Coruna win on 2026-05-01?",
            outcome=outcome,
            market_slug="es2-dep-leg-2026-05-01-dep",
            event_slug="es2-dep-leg-2026-05-01",
            event_title="RC Deportivo La Coruna vs. CD Leganes",
            current_price=current_price,
        )

    exits = CopyTradingEngine(config=config, store=store).process_local_exits()
    yes_position = next(position for position in store.list_positions() if position["asset_id"] == "deportivo-yes")
    sell_reasons = [
        trade["close_reason"]
        for trade in store.list_trades()
        if trade["paper_side"] == "sell" and trade["asset_id"] == "deportivo-yes"
    ]

    assert exits > 0
    assert yes_position["status"] == "open"
    assert yes_position["quantity"] > 0
    assert "stop_loss" not in sell_reasons


def test_wallet_profile_can_disable_event_follow_local_stop_loss(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: swisstony
    address: "{WALLET}"
    allowed_market_types: ["sports"]
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
winner_capture:
  enabled: false
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="swisstony",
        address=WALLET,
        enabled=True,
        allowed_market_types=["sports"],
        event_follow_strategy_enabled=True,
        profile_json={
            "market_filters": {"allowed_market_types": ["sports"]},
            "event_follow": {"enabled": True},
            "risk": {"local_stop_loss_enabled": False},
        },
    )
    source = make_buy("profile-no-stop-loss", price=0.50, notional=5.0)
    store.insert_source_trade(source)
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key=source.idempotency_key,
            side="buy",
            asset_id=source.asset_id,
            source_wallet=WALLET,
            observed_price=0.50,
            fill_price=0.50,
            quantity=10.0,
            notional_usdc=5.0,
        ),
        cash_after_usdc=95.0,
        position_quantity=10.0,
        avg_entry_price=0.50,
    )
    store.upsert_market_metadata(
        asset_id=source.asset_id,
        market_type="sports",
        title="Will Arsenal FC win on 2026-05-01?",
        outcome="Yes",
        market_slug="arsenal-win-2026-05-01",
        event_slug="arsenal-win-2026-05-01",
        event_title="Arsenal FC",
        current_price=0.30,
    )

    exits = CopyTradingEngine(config=config, store=store).process_local_exits()

    assert exits == 0
    assert not any(trade["paper_side"] == "sell" and trade["close_reason"] == "stop_loss" for trade in store.list_trades())
