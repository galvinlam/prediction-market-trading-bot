from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from polymarket_copy_trading.config import WalletConfig, default_wallet_profile_json
from polymarket_copy_trading.models import PaperFill, SourceTrade
from polymarket_copy_trading.store import Store


def make_source(key: str = "137:0xaaa:1:0x1111111111111111111111111111111111111111") -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xaaa",
        block_number=100,
        block_timestamp="2026-04-26 16:30 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="123",
        price=0.50,
        quantity=800,
        notional_usdc=400,
        market_id="market-1",
        outcome="YES",
    )


def make_fill() -> PaperFill:
    return PaperFill(
        source_idempotency_key="137:0xaaa:1:0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="123",
        source_wallet="0x1111111111111111111111111111111111111111",
        observed_price=0.50,
        fill_price=0.525,
        quantity=190.476190,
        notional_usdc=100,
    )


def make_sell_source() -> SourceTrade:
    return SourceTrade(
        idempotency_key="137:0xbbb:2:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbbb",
        block_number=101,
        block_timestamp="2026-04-27 09:15 PDT",
        log_index=2,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="sell",
        asset_id="123",
        price=0.60,
        quantity=190.476190,
        notional_usdc=114.285714,
        market_id="market-1",
        outcome="YES",
    )


def make_sell_fill() -> PaperFill:
    return PaperFill(
        source_idempotency_key="137:0xbbb:2:0x1111111111111111111111111111111111111111",
        side="sell",
        asset_id="123",
        source_wallet="0x1111111111111111111111111111111111111111",
        observed_price=0.60,
        fill_price=0.60,
        quantity=190.476190,
        notional_usdc=114.285714,
        realized_pnl_usdc=14.285714,
        close_reason="source_sell",
    )


def test_source_inventory_quantity_before_uses_chain_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    wallet = "0x1111111111111111111111111111111111111111"
    store.upsert_wallet(name="source", address=wallet, enabled=True)
    assert store.insert_source_trade(
        replace(
            make_source("buy-1"),
            source_wallet=wallet,
            asset_id="asset",
            block_number=10,
            log_index=1,
            quantity=100.0,
            notional_usdc=50.0,
        )
    )
    sell = replace(
        make_sell_source(),
        idempotency_key="sell-1",
        source_wallet=wallet,
        asset_id="asset",
        block_number=11,
        log_index=1,
        quantity=10.0,
        notional_usdc=5.0,
    )
    assert store.insert_source_trade(sell)
    assert store.insert_source_trade(
        replace(
            make_source("buy-2"),
            source_wallet=wallet,
            asset_id="asset",
            block_number=12,
            log_index=1,
            quantity=900.0,
            notional_usdc=450.0,
        )
    )

    assert store.source_inventory_quantity_before(sell) == 100.0


def test_store_initializes_schema_and_syncs_wallets(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.sync_wallets((WalletConfig(name="alpha", address="0x1111111111111111111111111111111111111111"),))

    wallets = store.list_wallets()
    assert wallets == [
        {
            "name": "alpha",
            "address": "0x1111111111111111111111111111111111111111",
            "enabled": True,
            "strategy_label": "Standard",
            "strategy_notes": "",
            "allowed_market_types": ["crypto", "weather", "sports", "other"],
            "bracket_strategy_enabled": False,
            "bracket_buy_size_usdc": 10.0,
            "bracket_stop_loss_pct": 0.0,
            "bracket_max_open_events": 0,
            "bracket_allowed_patterns": ["exact_or_binary", "range", "above_or_higher", "below_or_lower"],
            "repeat_buy_strategy_enabled": False,
            "repeat_buy_size_usdc": 5.0,
            "repeat_buy_stop_loss_pct": 0.0,
            "repeat_buy_min_source_notional_usdc": 0.0,
            "repeat_buy_min_buy_count": 2,
            "repeat_buy_min_avg_price": 0.01,
            "repeat_buy_max_avg_price": 1.0,
            "repeat_buy_max_total_exposure_usdc": 0.0,
            "repeat_buy_blocked_title_patterns": [],
            "repeat_buy_allowed_sports": [],
            "repeat_buy_allowed_bet_types": [],
            "event_follow_strategy_enabled": False,
            "event_follow_buy_size_usdc": 2.0,
            "event_follow_max_event_exposure_usdc": 4.0,
            "event_follow_max_total_exposure_usdc": 50.0,
            "event_follow_min_source_trade_usdc": 20.0,
            "event_follow_min_event_source_notional_usdc": 250.0,
            "event_follow_min_event_buy_count": 3,
            "event_follow_min_avg_price": 0.2,
            "event_follow_max_avg_price": 0.8,
            "sports_trailing_stop_enabled": False,
            "sports_trailing_activation_pct": 35.0,
            "sports_trailing_stop_pct": 25.0,
            "sports_trailing_floor_delta": 0.03,
            "reserved_cash_usdc": 0.0,
            "profile_json": default_wallet_profile_json(),
        }
    ]


def test_store_saves_wallet_allowed_market_types(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["crypto", "weather"],
    )

    wallet = store.get_wallet("0x1111111111111111111111111111111111111111")

    assert wallet is not None
    assert wallet["allowed_market_types"] == ["crypto", "weather"]


def test_store_saves_wallet_strategy_notes(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="greerfew",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        strategy_label="Custom",
        strategy_notes="Weather event-follow only: repeated low-price entries with small fixed copy size.",
    )

    wallet = store.get_wallet("0x1111111111111111111111111111111111111111")

    assert wallet is not None
    assert wallet["strategy_label"] == "Custom"
    assert wallet["strategy_notes"] == "Weather event-follow only: repeated low-price entries with small fixed copy size."


def test_store_persists_wallet_profile_json(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="profile-wallet",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        profile_json={
            "source_follow": {"copy_scale": 0.002, "max_asset_exposure_usdc": 12},
            "event_book": {"min_dominance_ratio": 1.4},
        },
    )
    store.update_wallet(
        "0x1111111111111111111111111111111111111111",
        profile_json='{"fixed_buy":{"buy_size_usdc":4}}',
    )

    wallet = store.get_wallet("0x1111111111111111111111111111111111111111")

    assert wallet is not None
    expected_profile = default_wallet_profile_json()
    expected_profile["fixed_buy"]["buy_size_usdc"] = 4.0
    assert wallet["profile_json"] == expected_profile


def test_store_applies_wallet_profile_json_strategy_overrides(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="rn1",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        profile_json={
            "market_filters": {"allowed_market_types": ["sports", "other"]},
            "repeat_buy": {
                "enabled": True,
                "buy_size_usdc": 7,
                "min_source_notional_usdc": 1000,
                "min_buy_count": 4,
                "min_avg_price": 0.05,
                "max_avg_price": 0.8,
                "allowed_sports": ["MLB", "NBA"],
            },
            "event_follow": {
                "enabled": True,
                "max_total_exposure_usdc": 350,
                "min_source_trade_usdc": 0,
            },
            "risk": {"reserved_cash_usdc": 40},
        },
    )

    wallet = store.get_wallet("0x1111111111111111111111111111111111111111")

    assert wallet is not None
    assert wallet["allowed_market_types"] == ["sports", "other"]
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 7
    assert wallet["repeat_buy_min_source_notional_usdc"] == 1000
    assert wallet["repeat_buy_min_buy_count"] == 4
    assert wallet["repeat_buy_min_avg_price"] == 0.05
    assert wallet["repeat_buy_max_avg_price"] == 0.8
    assert wallet["repeat_buy_allowed_sports"] == ["mlb", "nba"]
    assert wallet["event_follow_strategy_enabled"] is True
    assert wallet["event_follow_max_total_exposure_usdc"] == 350
    assert wallet["event_follow_min_source_trade_usdc"] == 0
    assert wallet["reserved_cash_usdc"] == 40


def test_store_backfills_profile_json_from_legacy_wallet_fields_when_omitted(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="legacy",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        strategy_label="Custom",
        allowed_market_types=["sports"],
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=12,
        bracket_allowed_patterns=["range"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=8,
        repeat_buy_min_source_notional_usdc=3000,
        repeat_buy_allowed_sports=["MLB"],
        event_follow_strategy_enabled=True,
        event_follow_buy_size_usdc=3,
        event_follow_min_source_trade_usdc=0,
        sports_trailing_stop_enabled=True,
        sports_trailing_stop_pct=20,
        reserved_cash_usdc=30,
    )

    profile = store.get_wallet("0x1111111111111111111111111111111111111111")["profile_json"]

    assert profile["market_filters"]["allowed_market_types"] == ["sports"]
    assert profile["weather_bracket"]["enabled"] is True
    assert profile["weather_bracket"]["buy_size_usdc"] == 12.0
    assert profile["weather_bracket"]["allowed_patterns"] == ["range"]
    assert profile["repeat_buy"]["enabled"] is True
    assert profile["repeat_buy"]["buy_size_usdc"] == 8.0
    assert profile["repeat_buy"]["min_source_notional_usdc"] == 3000.0
    assert profile["repeat_buy"]["allowed_sports"] == ["mlb"]
    assert profile["event_follow"]["enabled"] is True
    assert profile["event_follow"]["buy_size_usdc"] == 3.0
    assert profile["event_follow"]["min_source_trade_usdc"] == 0.0
    assert profile["sports_trailing"]["enabled"] is True
    assert profile["sports_trailing"]["stop_pct"] == 20.0
    assert profile["risk"]["reserved_cash_usdc"] == 30.0
    assert profile["strategy"]["custom"] is True


def test_store_persists_profile_json_overrides_into_legacy_columns(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="canonical",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["crypto"],
        repeat_buy_strategy_enabled=False,
        repeat_buy_size_usdc=5,
        profile_json={
            "market_filters": {"allowed_market_types": ["sports"]},
            "repeat_buy": {"enabled": True, "buy_size_usdc": 9},
        },
    )

    wallet = store.get_wallet("0x1111111111111111111111111111111111111111")
    with store._connect() as conn:
        row = conn.execute(
            "select allowed_market_types, repeat_buy_strategy_enabled, repeat_buy_size_usdc from wallets where address = ?",
            ("0x1111111111111111111111111111111111111111",),
        ).fetchone()

    assert wallet["allowed_market_types"] == ["sports"]
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 9.0
    assert row["allowed_market_types"] == "sports"
    assert row["repeat_buy_strategy_enabled"] == 1
    assert row["repeat_buy_size_usdc"] == 9.0


def test_store_update_wallet_legacy_fields_refresh_profile_json_when_profile_omitted(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="legacy-update",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        profile_json={"source_follow": {"copy_scale": 0.002}},
    )

    store.update_wallet(
        "0x1111111111111111111111111111111111111111",
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=6,
        repeat_buy_allowed_sports=["MLB"],
    )

    profile = store.get_wallet("0x1111111111111111111111111111111111111111")["profile_json"]

    assert profile["repeat_buy"]["enabled"] is True
    assert profile["repeat_buy"]["buy_size_usdc"] == 6.0
    assert profile["repeat_buy"]["allowed_sports"] == ["mlb"]
    assert profile["source_follow"]["copy_scale"] == 0.002


def test_store_preserves_zero_wallet_event_follow_source_trade_minimum(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.upsert_wallet(
        name="greerfew",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        event_follow_min_source_trade_usdc=0.0,
        event_follow_min_event_source_notional_usdc=5.0,
    )

    wallet = store.get_wallet("0x1111111111111111111111111111111111111111")

    assert wallet is not None
    assert wallet["event_follow_min_source_trade_usdc"] == 0.0
    assert wallet["event_follow_min_event_source_notional_usdc"] == 5.0


def test_store_seeds_config_wallets_only_when_empty(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    config_wallet = WalletConfig(name="config", address="0x1111111111111111111111111111111111111111")
    dashboard_wallet = WalletConfig(name="dashboard", address="0x2222222222222222222222222222222222222222")

    assert store.seed_wallets_if_empty((config_wallet,)) is True
    store.upsert_wallet(name=dashboard_wallet.name, address=dashboard_wallet.address, enabled=True)

    assert store.seed_wallets_if_empty((WalletConfig(name="placeholder", address="0x3333333333333333333333333333333333333333"),)) is False
    assert [wallet["address"] for wallet in store.list_wallets()] == [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
    ]


def test_store_sync_wallets_preserves_known_wallet_defaults_with_dataclass_default_profile(tmp_path: Path) -> None:
    rn1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    store.sync_wallets((WalletConfig(name="RN1", address=rn1),))

    profile = store.get_wallet(rn1)["profile_json"]
    assert profile["source_follow"]["enabled"] is True
    assert profile["binary_hedge"]["enabled"] is True
    assert "soccer" in profile["event_follow"]["allowed_sports"]


def test_store_inserts_source_trades_idempotently(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    assert store.insert_source_trade(make_source()) is True
    assert store.insert_source_trade(make_source()) is False
    assert len(store.list_trades()) == 1


def test_store_lists_open_and_recent_price_monitor_assets_without_grouping_full_history(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    open_trade = replace(
        make_source("137:0xopen:1:0x1111111111111111111111111111111111111111"),
        asset_id="open-asset",
        block_number=100,
    )
    recent_trade = replace(
        make_source("137:0xrecent:1:0x1111111111111111111111111111111111111111"),
        asset_id="recent-asset",
        block_number=300,
    )
    older_trade = replace(
        make_source("137:0xolder:1:0x1111111111111111111111111111111111111111"),
        asset_id="older-asset",
        block_number=200,
    )
    duplicate_recent = replace(
        make_source("137:0xrecent2:1:0x1111111111111111111111111111111111111111"),
        asset_id="recent-asset",
        block_number=301,
    )
    for trade in (open_trade, recent_trade, older_trade, duplicate_recent):
        store.insert_source_trade(trade)
    store.record_paper_fill(
        replace(make_fill(), source_idempotency_key=open_trade.idempotency_key, asset_id="open-asset"),
        cash_after_usdc=900,
        position_quantity=10,
        avg_entry_price=0.5,
    )

    assets = store.list_price_monitor_asset_ids(recent_trade_limit=2)

    assert assets == ["open-asset", "recent-asset", "older-asset"]


def test_store_prunes_only_old_closed_unreferenced_source_history(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 5, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    prunable = replace(
        make_source("137:0xprune:1:0x1111111111111111111111111111111111111111"),
        asset_id="old-closed",
        block_number=10,
        block_timestamp="2026-05-01 09:00 PDT",
    )
    open_market = replace(
        make_source("137:0xopenmarket:1:0x1111111111111111111111111111111111111111"),
        asset_id="old-open",
        block_number=11,
        block_timestamp="2026-05-01 09:05 PDT",
    )
    paper_linked = replace(
        make_source("137:0xpaper:1:0x1111111111111111111111111111111111111111"),
        asset_id="old-paper",
        block_number=12,
        block_timestamp="2026-05-01 09:10 PDT",
    )
    recent = replace(
        make_source("137:0xrecent:1:0x1111111111111111111111111111111111111111"),
        asset_id="recent-closed",
        block_number=13,
        block_timestamp="2026-05-04 09:00 PDT",
    )
    for trade in (prunable, open_market, paper_linked, recent):
        store.insert_source_trade(trade)
        store.record_copy_attribution(trade, executed=False, paper_trade_id=None, skip_reason="test_skip")
    store.upsert_market_metadata(
        asset_id="old-closed",
        is_closed=True,
        market_close_time="2026-05-01 09:30 PDT",
    )
    store.upsert_market_metadata(
        asset_id="old-open",
        is_closed=False,
        market_close_time="2026-05-10 09:30 PDT",
    )
    store.upsert_market_metadata(
        asset_id="old-paper",
        is_closed=True,
        market_close_time="2026-05-01 09:30 PDT",
    )
    store.upsert_market_metadata(
        asset_id="recent-closed",
        is_closed=True,
        market_close_time="2026-05-04 09:30 PDT",
    )
    store.record_paper_fill(
        replace(make_fill(), source_idempotency_key=paper_linked.idempotency_key, asset_id="old-paper"),
        cash_after_usdc=900,
        position_quantity=5,
        avg_entry_price=0.5,
    )

    dry_run = store.prune_old_source_history(retention_hours=72, now=now)

    assert dry_run["applied"] is False
    assert dry_run["candidates"]["source_trades"] == 1
    assert dry_run["candidates"]["source_trade_attributions"] == 1

    applied = store.prune_old_source_history(retention_hours=72, apply=True, now=now)

    assert applied["deleted_source_trades"] == 1
    assert applied["deleted_source_trade_attributions"] == 1
    with store._connect() as conn:
        rows = conn.execute("select idempotency_key from source_trades order by block_number").fetchall()
        attribution_rows = conn.execute("select source_idempotency_key from source_trade_attributions").fetchall()
    assert [row["idempotency_key"] for row in rows] == [
        open_market.idempotency_key,
        paper_linked.idempotency_key,
        recent.idempotency_key,
    ]
    assert {row["source_idempotency_key"] for row in attribution_rows} == {
        open_market.idempotency_key,
        paper_linked.idempotency_key,
        recent.idempotency_key,
    }


def test_store_records_paper_fill_position_and_overview(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())

    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=190.476190, avg_entry_price=0.525)

    overview = store.overview()
    holdings = store.list_positions()
    trades = store.list_trades()

    assert overview["paper_cash_usdc"] == 900
    assert overview["open_positions"] == 1
    assert holdings[0]["asset_id"] == "123"
    assert holdings[0]["quantity"] == 190.476190
    assert trades[0]["paper_side"] == "buy"
    assert trades[0]["source_time"] == "2026-04-26 16:30 PDT"
    assert trades[0]["paper_time"].endswith(" PDT")


def test_store_adds_entry_basis_to_sell_trade_rows(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=190.476190, avg_entry_price=0.525)
    store.insert_source_trade(make_sell_source())
    store.record_paper_fill(make_sell_fill(), cash_after_usdc=1014.285714, position_quantity=0, avg_entry_price=0)

    sell_trade = store.list_trades()[0]

    assert sell_trade["paper_side"] == "sell"
    assert sell_trade["source_price"] == 0.6
    assert sell_trade["source_notional_usdc"] == 114.285714
    assert sell_trade["fill_price"] == 0.6
    assert sell_trade["paper_notional_usdc"] == 114.285714
    assert sell_trade["entry_price"] == 0.525
    assert sell_trade["entry_notional_usdc"] == 100
    assert sell_trade["realized_pnl_usdc"] == 14.285714


def test_store_labels_trade_sources_with_wallet_names(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(
        (
            WalletConfig(name="alpha", address="0x1111111111111111111111111111111111111111"),
            WalletConfig(name="beta", address="0x2222222222222222222222222222222222222222"),
        )
    )
    alpha = make_source()
    beta = SourceTrade(
        **{
            **alpha.__dict__,
            "idempotency_key": "137:0xbbb:1:0x2222222222222222222222222222222222222222",
            "tx_hash": "0xbbb",
            "source_wallet": "0x2222222222222222222222222222222222222222",
            "copy_trade_key": alpha.normalized_copy_trade_key,
        }
    )
    store.insert_source_trade(alpha)
    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=190.476190, avg_entry_price=0.525)
    store.record_copy_attribution(alpha, executed=True, paper_trade_id=1)
    store.insert_source_trade(beta)
    store.record_copy_attribution(beta, executed=False, paper_trade_id=None)

    trade = store.list_trades()[0]
    holding = store.list_positions()[0]

    assert trade["source_wallet_name"] == "alpha"
    assert trade["copied_from_wallet_names"] == ["alpha", "beta"]
    assert holding["source_wallet_name"] == "alpha"


def test_store_enriches_positions_with_current_price_and_unrealized_pnl(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=100, avg_entry_price=0.50)
    store.upsert_market_metadata(
        asset_id="123",
        current_price=0.65,
        price_source="clob_sell",
        title="Example market",
        outcome="Yes",
        market_url="https://polymarket.com/event/example-market",
        last_price_at="2026-04-27 08:05 PDT",
        market_close_time="2026-04-29 05:00 PDT",
    )

    holding = store.list_positions()[0]
    pnl = store.pnl_summary()

    assert holding["title"] == "Example market"
    assert holding["current_price"] == 0.65
    assert holding["current_value_usdc"] == 65
    assert holding["unrealized_pnl_usdc"] == 15
    assert holding["market_url"] == "https://polymarket.com/event/example-market"
    assert holding["buy_time"].endswith(" PDT")
    assert holding["market_close_time"] == "2026-04-29 05:00 PDT"
    assert holding["buy_tx_hash"] == "0xaaa"
    assert pnl["portfolio_value_usdc"] == 965
    assert pnl["unrealized_pnl_usdc"] == 15
    assert pnl["pnl"]["lifetime"] == 15


def test_pnl_summary_can_use_starting_cash_baseline_for_total_return(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=100, avg_entry_price=0.50)
    store.upsert_market_metadata(asset_id="123", current_price=0.65)

    pnl = store.pnl_summary(starting_cash_usdc=1000)

    assert pnl["portfolio_value_usdc"] == 965
    assert pnl["pnl"]["lifetime"] == -35
    assert pnl["pnl"]["day"] == -35
    assert pnl["starting_cash_usdc"] == 1000
    assert pnl["series_by_range"]["day"][0]["value"] == 1000
    assert pnl["series_by_range"]["day"][-1]["label"] == "Mark"
    assert pnl["series_by_range"]["day"][-1]["value"] == 965


def test_pnl_summary_uses_ledger_cash_when_runtime_cash_is_stale(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=950, position_quantity=100, avg_entry_price=0.50)
    store.upsert_market_metadata(asset_id="123", current_price=0.65)

    pnl = store.pnl_summary(starting_cash_usdc=1000)

    assert pnl["cash_usdc"] == 900
    assert pnl["portfolio_value_usdc"] == 965
    assert pnl["realized_pnl_usdc"] == 0
    assert pnl["unrealized_pnl_usdc"] == 15
    assert pnl["pnl"]["lifetime"] == -35


def test_store_lists_closed_positions_with_exit_price_and_realized_pnl(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=190.476190, avg_entry_price=0.525)
    store.insert_source_trade(make_sell_source())
    store.record_paper_fill(make_sell_fill(), cash_after_usdc=1014.285714, position_quantity=0, avg_entry_price=0)
    store.upsert_market_metadata(
        asset_id="123",
        current_price=0.62,
        price_source="clob_sell",
        title="Closed market",
        outcome="Yes",
        market_url="https://polymarket.com/event/closed-market",
        last_price_at="2026-04-27 09:20 PDT",
    )

    closed = store.list_closed_positions()

    assert closed == [
        {
            "asset_id": "123",
            "source_wallet": "0x1111111111111111111111111111111111111111",
            "source_wallet_name": None,
            "quantity": 0,
            "avg_entry_price": 0,
            "realized_pnl_usdc": 14.285714,
            "status": "closed",
            "updated_at": closed[0]["updated_at"],
            "buy_time": closed[0]["buy_time"],
            "close_time": closed[0]["close_time"],
            "buy_tx_hash": "0xaaa",
            "sell_tx_hash": "0xbbb",
            "market_id": None,
            "condition_id": None,
            "outcome": "Yes",
            "title": "Closed market",
            "market_slug": None,
            "market_url": "https://polymarket.com/event/closed-market",
            "current_price": 0.62,
            "price_source": "clob_sell",
            "last_price_at": "2026-04-27 09:20 PDT",
            "market_type": None,
            "event_slug": None,
            "event_title": None,
            "market_close_time": None,
            "market_close_time_kind": None,
            "is_closed": None,
            "resolution_price": None,
            "entry_price": 0.525,
            "exit_price": 0.6,
            "closed_quantity": 190.47619,
            "closed_notional_usdc": 114.285714,
            "close_reason": "source_sell",
        }
    ]


def test_store_closed_position_exit_price_is_weighted_average_for_scaled_exits(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key="buy",
            side="buy",
            asset_id="123",
            source_wallet="0x1111111111111111111111111111111111111111",
            observed_price=0.20,
            fill_price=0.20,
            quantity=10,
            notional_usdc=2,
        ),
        cash_after_usdc=998,
        position_quantity=10,
        avg_entry_price=0.20,
    )
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key="sell-1",
            side="sell",
            asset_id="123",
            source_wallet="0x1111111111111111111111111111111111111111",
            observed_price=0.50,
            fill_price=0.50,
            quantity=4,
            notional_usdc=2,
            realized_pnl_usdc=1.2,
            close_reason="winner_recover_stake",
        ),
        cash_after_usdc=1000,
        position_quantity=6,
        avg_entry_price=0.20,
    )
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key="sell-2",
            side="sell",
            asset_id="123",
            source_wallet="0x1111111111111111111111111111111111111111",
            observed_price=0.10,
            fill_price=0.10,
            quantity=6,
            notional_usdc=0.6,
            realized_pnl_usdc=-0.6,
            close_reason="winner_trailing_stop",
        ),
        cash_after_usdc=1000.6,
        position_quantity=0,
        avg_entry_price=0,
    )

    closed = store.list_closed_positions()

    assert closed[0]["entry_price"] == 0.2
    assert closed[0]["exit_price"] == 0.26
    assert closed[0]["closed_quantity"] == 10
    assert closed[0]["closed_notional_usdc"] == 2.6
    assert closed[0]["realized_pnl_usdc"] == 0.6
    assert closed[0]["close_reason"] == "winner_trailing_stop"


def test_store_lists_closed_positions_from_trade_ledger_after_position_summary_cleanup(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=190.476190, avg_entry_price=0.525)
    store.insert_source_trade(make_sell_source())
    store.record_paper_fill(make_sell_fill(), cash_after_usdc=1014.285714, position_quantity=0, avg_entry_price=0)
    store.upsert_market_metadata(
        asset_id="123",
        current_price=0.62,
        price_source="clob_sell",
        title="Closed market",
        outcome="Yes",
        market_url="https://polymarket.com/event/closed-market",
        last_price_at="2026-04-27 09:20 PDT",
    )
    with store._connect() as conn:
        conn.execute("delete from positions where asset_id = ? and source_wallet = ?", ("123", make_source().source_wallet))

    closed = store.list_closed_positions()

    assert len(closed) == 1
    assert closed[0]["asset_id"] == "123"
    assert closed[0]["source_wallet"] == "0x1111111111111111111111111111111111111111"
    assert closed[0]["realized_pnl_usdc"] == 14.285714
    assert closed[0]["entry_price"] == 0.525
    assert closed[0]["exit_price"] == 0.6
    assert closed[0]["buy_tx_hash"] == "0xaaa"
    assert closed[0]["sell_tx_hash"] == "0xbbb"
    assert closed[0]["buy_time"].endswith(" PDT")
    assert closed[0]["close_time"].endswith(" PDT")
    assert closed[0]["closed_quantity"] == 190.47619
    assert closed[0]["close_reason"] == "source_sell"


def test_store_sports_bracket_legs_keep_entry_and_txn_after_close(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(name="swisstony", address="0x1111111111111111111111111111111111111111", enabled=True)
    store.upsert_market_metadata(
        asset_id="asset-san-diego-no",
        market_type="sports",
        title="Will San Diego FC win on 2026-05-02?",
        outcome="No",
        event_slug="mls-san-diego-fc-vs-la-galaxy-2026-05-02",
        event_title="San Diego FC vs LA Galaxy",
        market_slug="will-san-diego-fc-win-on-2026-05-02",
        market_close_time="2026-05-02 15:42 PDT",
        current_price=0.65,
    )
    store.record_sports_bracket_candidate(
        source_wallet="0x1111111111111111111111111111111111111111",
        event_slug="mls-san-diego-fc-vs-la-galaxy-2026-05-02",
        event_title="San Diego FC vs LA Galaxy",
        pattern="sports_double_win_bracket",
        legs=[
            {
                "asset_id": "asset-san-diego-no",
                "outcome": "No",
                "market_slug": "will-san-diego-fc-win-on-2026-05-02",
                "title": "Will San Diego FC win on 2026-05-02?",
                "source_quantity": 100,
                "source_notional_usdc": 62,
                "target_notional_usdc": 5,
                "copied_notional_usdc": 5,
            }
        ],
    )
    store.insert_source_trade(
        SourceTrade(
            idempotency_key="137:0xbuy-san-diego:1:0x1111111111111111111111111111111111111111",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xbuy-san-diego",
            block_number=100,
            block_timestamp="2026-05-02 12:00 PDT",
            log_index=1,
            source_wallet="0x1111111111111111111111111111111111111111",
            side="buy",
            asset_id="asset-san-diego-no",
            price=0.62,
            quantity=100,
            notional_usdc=62,
            outcome="No",
        )
    )
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key="137:0xbuy-san-diego:1:0x1111111111111111111111111111111111111111",
            side="buy",
            asset_id="asset-san-diego-no",
            source_wallet="0x1111111111111111111111111111111111111111",
            observed_price=0.62,
            fill_price=0.65,
            quantity=7.692307,
            notional_usdc=5,
        ),
        cash_after_usdc=995,
        position_quantity=7.692307,
        avg_entry_price=0.65,
    )
    store.insert_source_trade(
        SourceTrade(
            idempotency_key="137:0xsell-san-diego:2:0x1111111111111111111111111111111111111111",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xsell-san-diego",
            block_number=101,
            block_timestamp="2026-05-02 15:43 PDT",
            log_index=2,
            source_wallet="0x1111111111111111111111111111111111111111",
            side="sell",
            asset_id="asset-san-diego-no",
            price=0.80,
            quantity=7.692307,
            notional_usdc=6.153846,
            outcome="No",
        )
    )
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key="137:0xsell-san-diego:2:0x1111111111111111111111111111111111111111",
            side="sell",
            asset_id="asset-san-diego-no",
            source_wallet="0x1111111111111111111111111111111111111111",
            observed_price=0.80,
            fill_price=0.80,
            quantity=7.692307,
            notional_usdc=6.153846,
            realized_pnl_usdc=1.153846,
        ),
        cash_after_usdc=1001.153846,
        position_quantity=0,
        avg_entry_price=0,
    )

    leg = store.list_sports_brackets()[0]["legs"][0]

    assert leg["avg_entry_price"] == 0.65
    assert leg["buy_time"].endswith(" PDT")
    assert leg["market_close_time"] == "2026-05-02 15:42 PDT"
    assert leg["buy_tx_hash"] == "0xbuy-san-diego"


def test_store_sports_brackets_hide_uncopied_source_only_legs(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(name="swisstony", address="0x1111111111111111111111111111111111111111", enabled=True)
    store.record_sports_bracket_candidate(
        source_wallet="0x1111111111111111111111111111111111111111",
        event_slug="epl-ars-ful-2026-05-02-more-markets",
        event_title="Arsenal FC vs. Fulham FC",
        pattern="sports_total_ladder_bracket",
        legs=[
            {
                "asset_id": "arsenal-over-25",
                "outcome": "Over",
                "market_slug": "arsenal-over-25",
                "title": "Arsenal FC vs. Fulham FC: O/U 2.5",
                "source_quantity": 100,
                "source_notional_usdc": 50,
                "target_notional_usdc": 2,
                "copied_notional_usdc": 2,
            },
            {
                "asset_id": "arsenal-under-35",
                "outcome": "Under",
                "market_slug": "arsenal-under-35",
                "title": "Arsenal FC vs. Fulham FC: O/U 3.5",
                "source_quantity": 50,
                "source_notional_usdc": 35,
                "target_notional_usdc": 2,
                "copied_notional_usdc": 0,
            },
        ],
    )
    store.insert_source_trade(
        SourceTrade(
            idempotency_key="137:0xbuy-arsenal:1:0x1111111111111111111111111111111111111111",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xbuy-arsenal",
            block_number=100,
            block_timestamp="2026-05-02 08:08 PDT",
            log_index=1,
            source_wallet="0x1111111111111111111111111111111111111111",
            side="buy",
            asset_id="arsenal-over-25",
            price=0.50,
            quantity=4,
            notional_usdc=2,
            outcome="Over",
        )
    )
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key="137:0xbuy-arsenal:1:0x1111111111111111111111111111111111111111",
            side="buy",
            asset_id="arsenal-over-25",
            source_wallet="0x1111111111111111111111111111111111111111",
            observed_price=0.50,
            fill_price=0.525,
            quantity=3.809524,
            notional_usdc=2,
        ),
        cash_after_usdc=998,
        position_quantity=3.809524,
        avg_entry_price=0.525,
    )

    legs = store.list_sports_brackets()[0]["legs"]

    assert [leg["asset_id"] for leg in legs] == ["arsenal-over-25"]
