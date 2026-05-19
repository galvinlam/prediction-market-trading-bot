from dataclasses import replace
from pathlib import Path

import pytest

import polymarket_copy_trading.engine as engine_module
from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.store import Store


RN1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
GREERFEW = "0x64f6f18af2db92021efcd0894f9a94dfa0fc15a2"
SWISSTONY = "0x204f72f35326db932158cba6adff0b9a1da95e14"


@pytest.fixture(autouse=True)
def _use_legacy_event_follow_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "_filter_copy_enabled", lambda source_wallet, wallet: False)


def sports_buy(
    key: str,
    *,
    asset_id: str = "asset-event-a",
    price: float = 0.50,
    notional: float = 100.0,
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-04-28 15:00 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=RN1,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id="sports-market-1",
        outcome="Team A",
    )


def blocked_buy(key: str, *, asset_id: str, price: float = 0.30, notional: float = 100.0) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-04-28 15:00 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=RN1,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id="blocked-market",
        outcome="No",
    )


def greerfew_weather_buy(
    key: str,
    *,
    asset_id: str,
    price: float = 0.04,
    notional: float = 5.0,
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-04-29 21:32 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=GREERFEW,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id="weather-market-1",
        outcome="29C",
    )


def swisstony_buy(
    key: str,
    *,
    asset_id: str,
    price: float = 0.50,
    notional: float = 100.0,
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-04-30 14:30 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=SWISSTONY,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id="swisstony-market",
        outcome="No",
    )


def test_wallet_config_parses_event_follow_strategy_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "{RN1}"
    enabled: true
    allowed_market_types: ["sports", "other"]
    event_follow_strategy_enabled: true
    event_follow_buy_size_usdc: 2
    event_follow_max_event_exposure_usdc: 4
    event_follow_max_total_exposure_usdc: 50
    event_follow_min_source_trade_usdc: 20
    event_follow_min_event_source_notional_usdc: 250
    event_follow_min_event_buy_count: 3
    event_follow_min_avg_price: 0.20
    event_follow_max_avg_price: 0.80
""",
        encoding="utf-8",
    )

    config = load_config(path)
    wallet = config.wallets[0]

    assert wallet.event_follow_strategy_enabled is True
    assert wallet.event_follow_buy_size_usdc == 2
    assert wallet.event_follow_max_event_exposure_usdc == 4
    assert wallet.event_follow_max_total_exposure_usdc == 50
    assert wallet.event_follow_min_source_trade_usdc == 20
    assert wallet.event_follow_min_event_source_notional_usdc == 250
    assert wallet.event_follow_min_event_buy_count == 3
    assert wallet.event_follow_min_avg_price == 0.20
    assert wallet.event_follow_max_avg_price == 0.80


def test_event_follow_waits_for_repeated_event_signal_then_buys_fixed_size(tmp_path: Path) -> None:
    store = _store(tmp_path)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.30,
    )

    assert engine.process_trade(sports_buy("tx-1", asset_id="asset-event-a", price=0.30, notional=100)) == "skipped"
    assert engine.process_trade(sports_buy("tx-2", asset_id="asset-event-b", price=0.30, notional=100)) == "skipped"
    assert engine.process_trade(sports_buy("tx-3", asset_id="asset-event-a", price=0.30, notional=75)) == "processed"
    assert engine.process_trade(sports_buy("tx-4", asset_id="asset-event-b", price=0.30, notional=100)) == "processed"
    assert engine.process_trade(sports_buy("tx-5", asset_id="asset-event-a", price=0.30, notional=100)) == "skipped"

    signal = store.get_event_follow_signal(RN1, "nba-lal-bos-2026-04-29")
    assert signal is not None
    assert signal["buy_count"] == 5
    assert signal["source_notional_usdc"] == 475.0
    assert signal["source_avg_price"] == 0.3
    assert signal["copied_notional_usdc"] == 4.0
    positions = sorted(store.list_positions(), key=lambda row: row["asset_id"])
    assert [position["cost_basis_usdc"] for position in positions] == [2.0, 2.0]


def test_event_follow_ignores_small_and_out_of_band_source_buys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    assert engine.process_trade(sports_buy("tx-1", notional=10, price=0.50)) == "skipped"
    assert engine.process_trade(sports_buy("tx-2", asset_id="asset-event-b", notional=150, price=0.90)) == "skipped"
    assert engine.process_trade(sports_buy("tx-3", notional=150, price=0.90)) == "skipped"
    assert store.get_event_follow_signal(RN1, "nba-lal-bos-2026-04-29") is not None
    assert store.list_positions() == []


def test_event_follow_blocks_out_of_band_current_entry_price(tmp_path: Path) -> None:
    store = _store(tmp_path)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.90,
    )

    assert engine.process_trade(sports_buy("tx-1", asset_id="asset-event-a", price=0.30, notional=100)) == "skipped"
    assert engine.process_trade(sports_buy("tx-2", asset_id="asset-event-b", price=0.30, notional=100)) == "skipped"
    assert engine.process_trade(sports_buy("tx-3", asset_id="asset-event-a", price=0.30, notional=100)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["event_follow_entry_price_band_blocked"] == 1


def test_rn1_event_follow_allows_profile_sports_and_blocks_disallowed_bet_types(tmp_path: Path) -> None:
    store = _store(tmp_path)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.30,
    )

    skipped_assets = [
        "asset-soccer-moneyline",
        "asset-cs2-map",
        "asset-nba-total",
        "asset-wta-moneyline",
    ]

    for index, asset_id in enumerate(skipped_assets, start=1):
        assert engine.process_trade(blocked_buy(f"tx-{index}", asset_id=asset_id)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_market_filter_blocked"] == 2
    assert summary["rn1_tennis_paused"] == 1


def test_greerfew_weather_limit_copy_waits_when_executable_price_runs_away(tmp_path: Path) -> None:
    store = _greerfew_store(tmp_path)
    engine = CopyTradingEngine(
        config=_greerfew_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.29,
    )

    assert engine.process_trade(greerfew_weather_buy("tx-1", asset_id="asset-weather-a", notional=4)) == "skipped"
    assert engine.process_trade(greerfew_weather_buy("tx-2", asset_id="asset-weather-b", notional=6)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["greerfew_limit_price_blocked"] == 2


def test_greerfew_weather_limit_copy_blocks_large_relative_low_price_premium(tmp_path: Path) -> None:
    store = _greerfew_store(tmp_path)
    engine = CopyTradingEngine(
        config=_greerfew_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.019,
    )

    assert engine.process_trade(greerfew_weather_buy("tx-1", asset_id="asset-weather-a", price=0.01, notional=4)) == "skipped"
    assert engine.process_trade(greerfew_weather_buy("tx-2", asset_id="asset-weather-b", price=0.01, notional=6)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["greerfew_limit_price_blocked"] == 2


def test_greerfew_weather_copies_full_event_basket_proportionally(tmp_path: Path) -> None:
    store = _greerfew_store(tmp_path)
    engine = CopyTradingEngine(
        config=_greerfew_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.04,
    )

    assert engine.process_trade(greerfew_weather_buy("tx-1", asset_id="asset-weather-a", notional=4)) == "skipped"
    assert engine.process_trade(greerfew_weather_buy("tx-2", asset_id="asset-weather-b", notional=6)) == "processed"

    positions = sorted(store.list_positions(), key=lambda row: row["asset_id"])
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in positions] == [
        ("asset-weather-a", 1.0),
        ("asset-weather-b", 1.5),
    ]
    signal = store.get_event_follow_signal(GREERFEW, "weather-kuala-lumpur-2026-05-02")
    assert signal is not None
    assert signal["copied_notional_usdc"] == 2.5


def test_swisstony_event_follow_skips_legs_outside_copy_price_tiers(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    prices = {"asset-spread": 0.90, "asset-cheap-tail": 0.25}
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: prices[asset_id],
    )

    sequence = [
        ("asset-spread", 0.90),
        ("asset-spread", 0.90),
        ("asset-cheap-tail", 0.25),
        ("asset-cheap-tail", 0.25),
    ]

    for index, (asset_id, price) in enumerate(sequence, start=1):
        assert engine.process_trade(swisstony_buy(f"tx-{index}", asset_id=asset_id, price=price, notional=5000)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["swisstony_leg_tier_blocked"] == 1


def test_swisstony_event_follow_copies_ladder_legs_by_source_price_tier(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    prices = {
        "asset-soccer-no": 0.40,
        "asset-soccer-total": 0.70,
        "asset-spread": 0.90,
        "asset-cheap-tail": 0.25,
    }
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: prices[asset_id],
    )

    sequence = [
        ("asset-soccer-no", 0.40),
        ("asset-soccer-no", 0.40),
        ("asset-soccer-total", 0.70),
        ("asset-spread", 0.90),
    ]
    for index, (asset_id, price) in enumerate(sequence, start=1):
        assert engine.process_trade(swisstony_buy(f"tx-{index}", asset_id=asset_id, price=price, notional=5000)) in {
            "processed",
            "skipped",
        }

    positions = sorted(store.list_positions(), key=lambda row: row["asset_id"])
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in positions] == [
        ("asset-soccer-no", 3.0),
        ("asset-soccer-total", 2.0),
    ]
    signal = store.get_event_follow_signal(SWISSTONY, "swisstony-tiered-event")
    assert signal is not None
    assert signal["copied_notional_usdc"] == 5.0


def test_swisstony_event_follow_uses_profile_price_tiers(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    store.update_wallet(
        SWISSTONY,
        profile_json={
            "market_filters": {"allowed_market_types": ["sports"]},
            "event_follow": {
                "enabled": True,
                "buy_size_usdc": 2.0,
                "max_event_exposure_usdc": 15.0,
                "max_total_exposure_usdc": 50.0,
                "min_source_trade_usdc": 5000.0,
                "min_event_source_notional_usdc": 20000.0,
                "min_event_buy_count": 2,
                "min_avg_price": 0.30,
                "max_avg_price": 0.80,
            },
            "source_follow": {"enabled": False},
            "risk": {"reserved_cash_usdc": 10.0},
            "tier_sizing": {
                "tiers": [
                    {"min_price": 0.30, "max_price": 0.65, "buy_size_usdc": 4.0},
                    {"min_price": 0.65, "max_price": 0.80, "buy_size_usdc": 1.5},
                ]
            }
        },
    )
    _enable_swisstony_copy_buys(store, legacy_event_follow=True)
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-soccer-no", price=0.50, notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-soccer-no", price=0.50, notional=10000)) == "processed"

    positions = {position["asset_id"]: position["cost_basis_usdc"] for position in store.list_positions()}
    assert positions == {"asset-soccer-no": 4.0}


def test_swisstony_event_follow_accumulates_source_scaled_leg_exposure(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    store.update_wallet(
        SWISSTONY,
        event_follow_min_source_trade_usdc=0.0,
        event_follow_min_event_source_notional_usdc=1000.0,
        event_follow_min_event_buy_count=2,
        event_follow_max_event_exposure_usdc=75.0,
        event_follow_max_total_exposure_usdc=250.0,
    )
    _enable_swisstony_copy_buys(store, legacy_event_follow=True)
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-soccer-no", price=0.50, notional=1000.0)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-soccer-no", price=0.50, notional=1000.0)) == "processed"
    assert engine.process_trade(swisstony_buy("tx-3", asset_id="asset-soccer-no", price=0.50, notional=8000.0)) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-no"
    assert position["cost_basis_usdc"] == 5.0
    signal = store.get_event_follow_signal(SWISSTONY, "swisstony-tiered-event")
    assert signal is not None
    assert signal["copied_notional_usdc"] == 5.0


def test_event_follow_honors_wallet_sport_and_bet_type_filters(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    store.update_wallet(
        SWISSTONY,
        profile_json={
            "event_follow": {
                "allowed_sports": ["soccer", "atp", "wta", "nba", "nhl", "nfl", "esports"],
                "allowed_bet_types": ["moneyline_winlose", "total_or_over_under"],
            }
        },
    )
    _enable_swisstony_copy_buys(store)
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    blocked_assets = ["asset-btts", "asset-spread", "asset-baseball-total"]
    for index, asset_id in enumerate(blocked_assets, start=1):
        assert engine.process_trade(swisstony_buy(f"tx-{index}", asset_id=asset_id, price=0.50, notional=5000)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["event_follow_market_filter_blocked"] == 3


def test_swisstony_sports_bracket_copies_double_win_legs_as_group(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    for asset_id, title in (
        ("asset-brentford-no", "Will Brentford FC win on 2026-05-02?"),
        ("asset-west-ham-no", "Will West Ham United FC win on 2026-05-02?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            event_slug="epl-bre-wes-2026-05-02",
            event_title="Brentford FC vs. West Ham United FC",
            market_slug=f"epl-bre-wes-2026-05-02-{asset_id}",
            market_url=f"https://polymarket.com/event/epl-bre-wes-2026-05-02/{asset_id}",
        )
    prices = {"asset-brentford-no": 0.52, "asset-west-ham-no": 0.75}
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: prices[asset_id],
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-brentford-no", price=0.48, notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-west-ham-no", price=0.74, notional=10000)) == "processed"

    positions = sorted(store.list_positions(), key=lambda row: row["asset_id"])
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in positions] == [
        ("asset-brentford-no", 3.0),
        ("asset-west-ham-no", 2.0),
    ]
    brackets = store.list_sports_brackets()
    assert len(brackets) == 1
    assert brackets[0]["pattern"] == "sports_double_win_bracket"
    assert brackets[0]["copied_notional_usdc"] == 5.0
    assert len(brackets[0]["legs"]) == 2


def test_swisstony_auto_detects_total_ladder_bracket(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    for asset_id, title, outcome in (
        ("asset-total-35", "Brentford FC vs. West Ham United FC: O/U 3.5", "Under"),
        ("asset-total-45", "Brentford FC vs. West Ham United FC: O/U 4.5", "Under"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome=outcome,
            event_slug="epl-bre-wes-2026-05-02-more-markets",
            event_title="Brentford FC vs. West Ham United FC - More Markets",
            market_slug=f"epl-bre-wes-2026-05-02-{asset_id}",
        )
    prices = {"asset-total-35": 0.52, "asset-total-45": 0.72}
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: prices[asset_id],
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-total-35", price=0.50, notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-total-45", price=0.70, notional=10000)) == "processed"

    brackets = store.list_sports_brackets()
    assert len(brackets) == 1
    assert brackets[0]["pattern"] == "sports_total_ladder_bracket"
    assert brackets[0]["copied_notional_usdc"] == 5.0


def test_sports_bracket_scales_all_legs_when_cash_is_tight(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    store.update_wallet(
        SWISSTONY,
        event_follow_min_event_source_notional_usdc=20000.0,
        event_follow_min_event_buy_count=3,
        event_follow_max_event_exposure_usdc=8.0,
        event_follow_max_total_exposure_usdc=50.0,
    )
    _enable_swisstony_copy_buys(store)
    for asset_id, title, outcome in (
        ("asset-total-25-under", "Arsenal FC vs. Fulham FC: O/U 2.5", "Under"),
        ("asset-total-25-over", "Arsenal FC vs. Fulham FC: O/U 2.5", "Over"),
        ("asset-total-35-under", "Arsenal FC vs. Fulham FC: O/U 3.5", "Under"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome=outcome,
            event_slug="epl-ars-ful-2026-05-02-more-markets",
            event_title="Arsenal FC vs. Fulham FC - More Markets",
            market_slug=f"epl-ars-ful-2026-05-02-{asset_id}",
        )
    config = replace(_swisstony_settings(tmp_path), paper=replace(_swisstony_settings(tmp_path).paper, starting_cash_usdc=5.05))
    prices = {"asset-total-25-under": 0.48, "asset-total-25-over": 0.50, "asset-total-35-under": 0.70}
    engine = CopyTradingEngine(
        config=config,
        store=store,
        buy_price_resolver=lambda asset_id: prices[asset_id],
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-total-25-under", price=0.48, notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-total-25-over", price=0.50, notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-3", asset_id="asset-total-35-under", price=0.70, notional=10000)) == "processed"

    brackets = store.list_sports_brackets()
    assert len(brackets) == 1
    assert brackets[0]["pattern"] == "sports_total_ladder_bracket"
    assert len(brackets[0]["legs"]) == 3
    assert brackets[0]["copied_notional_usdc"] == 5.0
    assert all(leg["copied_notional_usdc"] >= 1.0 for leg in brackets[0]["legs"])
    assert {position["asset_id"] for position in store.list_positions()} == {
        "asset-total-25-under",
        "asset-total-25-over",
        "asset-total-35-under",
    }


def test_rn1_event_book_skips_balanced_two_sided_moneyline(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=3000.0,
        repeat_buy_min_buy_count=10,
        repeat_buy_min_avg_price=0.40,
        repeat_buy_max_avg_price=0.70,
        repeat_buy_allowed_sports=["mlb"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
        event_follow_buy_size_usdc=5.0,
        event_follow_max_event_exposure_usdc=15.0,
        event_follow_max_total_exposure_usdc=50.0,
        event_follow_min_source_trade_usdc=0.0,
        event_follow_min_event_source_notional_usdc=3000.0,
        event_follow_min_event_buy_count=10,
        event_follow_min_avg_price=0.40,
        event_follow_max_avg_price=0.70,
    )
    for asset_id, outcome in (
        ("asset-rangers", "Texas Rangers"),
        ("asset-tigers", "Detroit Tigers"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Texas Rangers vs. Detroit Tigers",
            outcome=outcome,
            event_slug="mlb-tex-det-2026-05-01",
            event_title="Texas Rangers vs. Detroit Tigers",
            market_slug=f"mlb-tex-det-2026-05-01-{asset_id}",
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.55,
    )

    result = "skipped"
    trade_index = 1
    for _ in range(9):
        result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-rangers", price=0.55, notional=330.0))
        trade_index += 1
        result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-tigers", price=0.55, notional=330.0))
        trade_index += 1
    result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-rangers", price=0.55, notional=330.0))
    trade_index += 1
    assert result == "skipped"
    result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-tigers", price=0.55, notional=330.0))

    assert result == "skipped"
    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_event_book_not_dominant"] == 2


def test_rn1_event_book_copies_only_dominant_moneyline_side(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=3000.0,
        repeat_buy_min_buy_count=10,
        repeat_buy_min_avg_price=0.40,
        repeat_buy_max_avg_price=0.70,
        repeat_buy_allowed_sports=["mlb"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
        event_follow_buy_size_usdc=5.0,
        event_follow_max_event_exposure_usdc=15.0,
        event_follow_max_total_exposure_usdc=50.0,
        event_follow_min_source_trade_usdc=0.0,
        event_follow_min_event_source_notional_usdc=3000.0,
        event_follow_min_event_buy_count=10,
        event_follow_min_avg_price=0.40,
        event_follow_max_avg_price=0.70,
    )
    for asset_id, outcome in (
        ("asset-rangers", "Texas Rangers"),
        ("asset-tigers", "Detroit Tigers"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Texas Rangers vs. Detroit Tigers",
            outcome=outcome,
            event_slug="mlb-tex-det-2026-05-01",
            event_title="Texas Rangers vs. Detroit Tigers",
            market_slug=f"mlb-tex-det-2026-05-01-{asset_id}",
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.55,
    )

    trade_index = 1
    for _ in range(3):
        assert engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-tigers", price=0.55, notional=330.0)) == "skipped"
        trade_index += 1
    result = "skipped"
    for _ in range(10):
        result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-rangers", price=0.55, notional=330.0))
        trade_index += 1

    assert result == "processed"
    positions = store.list_positions()
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in positions] == [("asset-rangers", 1.65)]


def test_rn1_source_follow_uses_profile_copy_scale_override(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=3000.0,
        repeat_buy_min_buy_count=10,
        repeat_buy_min_avg_price=0.40,
        repeat_buy_max_avg_price=0.70,
        repeat_buy_allowed_sports=["mlb"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
        profile_json={
            "market_filters": {"allowed_market_types": ["sports"]},
            "repeat_buy": {
                "enabled": True,
                "buy_size_usdc": 5.0,
                "stop_loss_pct": 0.0,
                "min_source_notional_usdc": 3000.0,
                "min_buy_count": 10,
                "min_avg_price": 0.40,
                "max_avg_price": 0.70,
                "max_total_exposure_usdc": 0.0,
                "allowed_sports": ["mlb"],
                "allowed_bet_types": ["moneyline_winlose"],
            },
            "source_follow": {"enabled": True, "copy_scale": 0.001, "max_asset_exposure_usdc": 25.0},
        },
    )
    for asset_id, outcome in (
        ("asset-rangers", "Texas Rangers"),
        ("asset-tigers", "Detroit Tigers"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Texas Rangers vs. Detroit Tigers",
            outcome=outcome,
            event_slug="mlb-tex-det-2026-05-01",
            event_title="Texas Rangers vs. Detroit Tigers",
            market_slug=f"mlb-tex-det-2026-05-01-{asset_id}",
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.55,
    )

    trade_index = 1
    for _ in range(3):
        assert engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-tigers", price=0.55, notional=330.0)) == "skipped"
        trade_index += 1
    result = "skipped"
    for _ in range(10):
        result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-rangers", price=0.55, notional=330.0))
        trade_index += 1

    assert result == "processed"
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in store.list_positions()] == [("asset-rangers", 3.3)]


def test_rn1_event_book_uses_wallet_configured_price_band(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=3000.0,
        repeat_buy_min_buy_count=10,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.80,
        repeat_buy_allowed_sports=["mlb"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
    )
    for asset_id, outcome in (
        ("asset-rangers", "Texas Rangers"),
        ("asset-tigers", "Detroit Tigers"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Texas Rangers vs. Detroit Tigers",
            outcome=outcome,
            event_slug="mlb-tex-det-2026-05-01",
            event_title="Texas Rangers vs. Detroit Tigers",
            market_slug=f"mlb-tex-det-2026-05-01-{asset_id}",
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.30,
    )

    trade_index = 1
    for _ in range(3):
        assert engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-tigers", price=0.30, notional=330.0)) == "skipped"
        trade_index += 1
    result = "skipped"
    for _ in range(10):
        result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-rangers", price=0.30, notional=330.0))
        trade_index += 1

    assert result == "processed"
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in store.list_positions()] == [("asset-rangers", 1.65)]


def test_rn1_event_follow_uses_profile_market_allow_list(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports", "other"],
        event_follow_strategy_enabled=True,
        event_follow_buy_size_usdc=2.0,
        event_follow_max_event_exposure_usdc=4.0,
        event_follow_max_total_exposure_usdc=50.0,
        event_follow_min_source_trade_usdc=0.0,
        event_follow_min_event_source_notional_usdc=0.0,
        event_follow_min_event_buy_count=1,
        event_follow_min_avg_price=0.20,
        event_follow_max_avg_price=0.80,
        repeat_buy_allowed_sports=["mlb"],
        profile_json={
            "market_filters": {"allowed_market_types": ["sports", "other"]},
            "event_follow": {
                "enabled": True,
                "buy_size_usdc": 2.0,
                "max_event_exposure_usdc": 4.0,
                "max_total_exposure_usdc": 50.0,
                "min_source_trade_usdc": 0.0,
                "min_event_source_notional_usdc": 0.0,
                "min_event_buy_count": 1,
                "min_avg_price": 0.20,
                "max_avg_price": 0.80,
                "allowed_sports": ["soccer"],
                "allowed_bet_types": ["moneyline_winlose"],
            },
        },
    )
    store.upsert_market_metadata(
        asset_id="asset-soccer-moneyline",
        market_type="sports",
        title="Will Nottingham Forest FC win on 2026-04-30?",
        outcome="No",
        market_slug="uel-not-ast4-2026-04-30-not",
        event_slug="uel-not-ast4-2026-04-30",
        event_title="Nottingham Forest FC vs Aston Villa",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    assert engine.process_trade(sports_buy("tx-1", asset_id="asset-soccer-moneyline", price=0.50, notional=100.0)) == "processed"
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in store.list_positions()] == [
        ("asset-soccer-moneyline", 2.0)
    ]


def test_rn1_repeat_buy_uses_profile_price_band(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=3000.0,
        repeat_buy_min_buy_count=10,
        repeat_buy_min_avg_price=0.40,
        repeat_buy_max_avg_price=0.70,
        repeat_buy_allowed_sports=["mlb"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
        profile_json={
            "market_filters": {"allowed_market_types": ["sports"]},
            "repeat_buy": {
                "enabled": True,
                "buy_size_usdc": 5.0,
                "stop_loss_pct": 0.0,
                "min_source_notional_usdc": 3000.0,
                "min_buy_count": 10,
                "min_avg_price": 0.05,
                "max_avg_price": 0.80,
                "max_total_exposure_usdc": 0.0,
                "allowed_sports": ["mlb"],
                "allowed_bet_types": ["moneyline_winlose"],
            },
            "source_follow": {"enabled": True, "copy_scale": 0.001, "max_asset_exposure_usdc": 25.0},
        },
    )
    for asset_id, outcome in (
        ("asset-rangers", "Texas Rangers"),
        ("asset-tigers", "Detroit Tigers"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Texas Rangers vs. Detroit Tigers",
            outcome=outcome,
            event_slug="mlb-tex-det-2026-05-01",
            event_title="Texas Rangers vs. Detroit Tigers",
            market_slug=f"mlb-tex-det-2026-05-01-{asset_id}",
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.30,
    )

    trade_index = 1
    for _ in range(3):
        assert engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-tigers", price=0.30, notional=330.0)) == "skipped"
        trade_index += 1
    result = "skipped"
    for _ in range(10):
        result = engine.process_trade(sports_buy(f"tx-{trade_index}", asset_id="asset-rangers", price=0.30, notional=330.0))
        trade_index += 1

    assert result == "processed"
    assert [(position["asset_id"], position["cost_basis_usdc"]) for position in store.list_positions()] == [("asset-rangers", 3.3)]


def test_swisstony_treats_soccer_more_markets_metadata_as_sports(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    store.upsert_market_metadata(
        asset_id="asset-soccer-more-total",
        market_type="other",
        title="RC Deportivo La Coruna vs. CD Leganes: O/U 3.5",
        outcome="Over",
        market_slug="es2-dep-leg-2026-05-01-total-3pt5",
        event_slug="es2-dep-leg-2026-05-01-more-markets",
        event_title="RC Deportivo La Coruna vs. CD Leganes - More Markets",
    )
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-soccer-more-total", notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-soccer-more-total", notional=10000)) == "processed"

    positions = store.list_positions()
    assert len(positions) == 1
    assert positions[0]["asset_id"] == "asset-soccer-more-total"
    assert positions[0]["cost_basis_usdc"] == 3.0


def test_swisstony_event_follow_sizes_opposite_condition_buy_as_hedge(tmp_path: Path) -> None:
    store = _swisstony_store(tmp_path)
    for asset_id, outcome in (("asset-soccer-no", "No"), ("asset-soccer-yes", "Yes")):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            condition_id="condition-arsenal-win",
            title="Will Arsenal FC win on 2026-04-29?",
            outcome=outcome,
            market_slug="ucl-atm1-ars-2026-04-29-ars",
            event_slug="swisstony-tiered-event",
            event_title="Atletico Madrid vs Arsenal",
        )
    engine = CopyTradingEngine(
        config=_swisstony_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.25 if asset_id == "asset-soccer-yes" else 0.40,
    )

    assert engine.process_trade(swisstony_buy("tx-1", asset_id="asset-soccer-no", price=0.40, notional=10000)) == "skipped"
    assert engine.process_trade(swisstony_buy("tx-2", asset_id="asset-soccer-no", price=0.40, notional=10000)) == "processed"
    assert engine.process_trade(swisstony_buy("tx-3", asset_id="asset-soccer-yes", price=0.25, notional=5000)) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-soccer-no"]["cost_basis_usdc"] == 3.0
    assert positions["asset-soccer-yes"]["cost_basis_usdc"] == round(3.0 * 0.25 / (1 - 0.25), 6)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports", "other"],
        event_follow_strategy_enabled=True,
        event_follow_buy_size_usdc=2.0,
        event_follow_max_event_exposure_usdc=4.0,
        event_follow_max_total_exposure_usdc=50.0,
        event_follow_min_source_trade_usdc=20.0,
        event_follow_min_event_source_notional_usdc=250.0,
        event_follow_min_event_buy_count=3,
        event_follow_min_avg_price=0.20,
        event_follow_max_avg_price=0.80,
        profile_json={
            "event_follow": {
                "enabled": True,
                "buy_size_usdc": 2.0,
                "max_event_exposure_usdc": 4.0,
                "max_total_exposure_usdc": 50.0,
                "min_source_trade_usdc": 20.0,
                "min_event_source_notional_usdc": 250.0,
                "min_event_buy_count": 3,
                "min_avg_price": 0.20,
                "max_avg_price": 0.80,
            },
            "source_follow": {"enabled": False},
        },
    )
    for asset_id, outcome in (("asset-event-a", "Lakers"), ("asset-event-b", "Celtics")):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Lakers vs. Celtics",
            outcome=outcome,
            market_slug="nba-lal-bos-2026-04-29",
            event_slug="nba-lal-bos-2026-04-29",
            event_title="Lakers vs. Celtics",
        )
    store.upsert_market_metadata(
        asset_id="asset-soccer-moneyline",
        market_type="other",
        title="Will Nottingham Forest FC win on 2026-04-30?",
        outcome="No",
        market_slug="uel-not-ast4-2026-04-30-not",
        event_slug="uel-not-ast4-2026-04-30",
        event_title="Nottingham Forest FC vs Aston Villa",
    )
    store.upsert_market_metadata(
        asset_id="asset-cs2-map",
        market_type="other",
        title="Counter-Strike: Natus Vincere vs FaZe - Map 2 Winner",
        outcome="Natus Vincere",
        market_slug="cs2-navi-faze-2026-04-29-game2",
        event_slug="cs2-navi-faze-2026-04-29",
        event_title="Counter-Strike: Natus Vincere vs FaZe",
    )
    store.upsert_market_metadata(
        asset_id="asset-nba-total",
        market_type="sports",
        title="Lakers vs. Celtics: O/U 221.5",
        outcome="Over",
        market_slug="nba-lal-bos-2026-04-29-total-221pt5",
        event_slug="nba-lal-bos-2026-04-29-more-markets",
        event_title="Lakers vs. Celtics",
    )
    store.upsert_market_metadata(
        asset_id="asset-wta-moneyline",
        market_type="sports",
        title="Madrid Open: Linda Noskova vs Coco Gauff",
        outcome="Coco Gauff",
        market_slug="wta-noskova-gauff-2026-04-27",
        event_slug="wta-noskova-gauff-2026-04-27",
        event_title="Madrid Open: Linda Noskova vs Coco Gauff",
    )
    return store


def _swisstony_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="swisstony",
        address=SWISSTONY,
        enabled=True,
        strategy_label="Custom",
        strategy_notes="Event-follow soccer edge: copy high-conviction soccer winner markets; avoid BTTS, draw, spread, tennis/baseball, and only take soccer totals at reduced size.",
        allowed_market_types=["sports"],
        event_follow_strategy_enabled=True,
        event_follow_buy_size_usdc=2.0,
        event_follow_max_event_exposure_usdc=15.0,
        event_follow_max_total_exposure_usdc=50.0,
        event_follow_min_source_trade_usdc=5000.0,
        event_follow_min_event_source_notional_usdc=20000.0,
        event_follow_min_event_buy_count=2,
        event_follow_min_avg_price=0.30,
        event_follow_max_avg_price=0.80,
        reserved_cash_usdc=10.0,
    )
    _enable_swisstony_copy_buys(store, legacy_event_follow=True)
    metadata = {
        "asset-soccer-no": {
            "title": "Will Arsenal FC win on 2026-04-29?",
            "outcome": "No",
            "event_slug": "swisstony-tiered-event",
            "market_slug": "ucl-atm1-ars-2026-04-29-ars",
            "event_title": "Atletico Madrid vs Arsenal",
            "market_type": "other",
        },
        "asset-soccer-total": {
            "title": "Rayo Vallecano de Madrid vs. RC Strasbourg Alsace: O/U 1.5",
            "outcome": "Over",
            "event_slug": "swisstony-tiered-event",
            "market_slug": "col-ray-str-2026-04-30-total-1pt5",
            "event_title": "Rayo Vallecano de Madrid vs. RC Strasbourg Alsace",
            "market_type": "sports",
        },
        "asset-btts": {
            "title": "Rayo Vallecano de Madrid vs. RC Strasbourg Alsace: Both Teams to Score",
            "outcome": "No",
            "event_slug": "col-ray-str-2026-04-30-more-markets",
            "market_slug": "col-ray-str-2026-04-30-btts",
            "event_title": "Rayo Vallecano de Madrid vs. RC Strasbourg Alsace",
            "market_type": "sports",
        },
        "asset-draw": {
            "title": "Will Shanghai Shenhua FC vs. Chengdu Rongcheng FC end in a draw?",
            "outcome": "Yes",
            "event_slug": "chi-sgr-ron-2026-05-01",
            "market_slug": "chi-sgr-ron-2026-05-01-draw",
            "event_title": "Shanghai Shenhua FC vs. Chengdu Rongcheng FC",
            "market_type": "sports",
        },
        "asset-spread": {
            "title": "Spread: Crystal Palace FC (-1.5)",
            "outcome": "Crystal Palace FC",
            "event_slug": "swisstony-tiered-event",
            "market_slug": "col-shd-cry-2026-04-30-spread-palace-1pt5",
            "event_title": "Crystal Palace FC vs Sheffield Wednesday",
            "market_type": "sports",
        },
        "asset-cheap-tail": {
            "title": "Will SC Braga win on 2026-04-30?",
            "outcome": "Yes",
            "event_slug": "swisstony-tiered-event",
            "market_slug": "uel-scb-scf-2026-04-30-scb",
            "event_title": "SC Braga vs SC Freiburg",
            "market_type": "sports",
        },
        "asset-tennis": {
            "title": "Madrid Open: Marta Kostyuk vs Anastasia Potapova",
            "outcome": "Anastasia Potapova",
            "event_slug": "wta-kostyuk-potapov-2026-04-30",
            "market_slug": "wta-kostyuk-potapov-2026-04-30",
            "event_title": "Madrid Open: Marta Kostyuk vs Anastasia Potapova",
            "market_type": "sports",
        },
        "asset-baseball-total": {
            "title": "Kansas City Royals vs. Athletics: O/U 9.5",
            "outcome": "Over",
            "event_slug": "mlb-kc-oak-2026-04-30",
            "market_slug": "mlb-kc-oak-2026-04-30-total-9pt5",
            "event_title": "Kansas City Royals vs. Athletics",
            "market_type": "sports",
        },
    }
    for asset_id, values in metadata.items():
        store.upsert_market_metadata(asset_id=asset_id, **values)
    return store


def _enable_swisstony_copy_buys(store: Store, *, legacy_event_follow: bool = False) -> None:
    profile = store.get_wallet(SWISSTONY)["profile_json"]
    profile.setdefault("strategy", {})["copy_buys_enabled"] = True
    if legacy_event_follow:
        profile.setdefault("filter_copy", {})["enabled"] = False
        profile.setdefault("event_follow", {})["allowed_sports"] = [
            "soccer",
            "other",
            "mlb",
            "nba",
            "nhl",
            "nfl",
            "esports",
        ]
        profile.setdefault("event_follow", {})["allowed_bet_types"] = [
            "moneyline_winlose",
            "total_or_over_under",
            "spread_handicap",
            "both_teams_score",
        ]
    store.update_wallet(SWISSTONY, profile_json=profile)


def _greerfew_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="greerfew",
        address=GREERFEW,
        enabled=True,
        strategy_label="Custom",
        strategy_notes="Weather limit-copy: wait for 2+ low-price event legs, then size the basket proportionally.",
        allowed_market_types=["weather"],
        event_follow_strategy_enabled=True,
        event_follow_buy_size_usdc=5.0,
        event_follow_max_event_exposure_usdc=5.0,
        event_follow_max_total_exposure_usdc=50.0,
        event_follow_min_source_trade_usdc=0.0,
        event_follow_min_event_source_notional_usdc=10.0,
        event_follow_min_event_buy_count=2,
        event_follow_min_avg_price=0.01,
        event_follow_max_avg_price=0.06,
    )
    for asset_id, outcome in (("asset-weather-a", "29C"), ("asset-weather-b", "30C")):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="weather",
            title="Kuala Lumpur high temperature on May 2",
            outcome=outcome,
            market_slug=f"weather-kuala-lumpur-2026-05-02-{outcome.lower()}",
            event_slug="weather-kuala-lumpur-2026-05-02",
            event_title="Kuala Lumpur high temperature on May 2",
        )
    return store


def _settings(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "{RN1}"
    enabled: true
    allowed_market_types: ["sports", "other"]
    event_follow_strategy_enabled: true
    event_follow_buy_size_usdc: 2
    event_follow_max_event_exposure_usdc: 4
    event_follow_max_total_exposure_usdc: 50
    event_follow_min_source_trade_usdc: 20
    event_follow_min_event_source_notional_usdc: 250
    event_follow_min_event_buy_count: 3
    event_follow_min_avg_price: 0.05
    event_follow_max_avg_price: 0.40
    profile_json:
      event_follow:
        enabled: true
        buy_size_usdc: 2
        max_event_exposure_usdc: 4
        max_total_exposure_usdc: 50
        min_source_trade_usdc: 20
        min_event_source_notional_usdc: 250
        min_event_buy_count: 3
        min_avg_price: 0.05
        max_avg_price: 0.40
      source_follow:
        enabled: false
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: 100
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
""",
        encoding="utf-8",
    )
    return load_config(path)


def _swisstony_settings(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: swisstony
    address: "{SWISSTONY}"
    enabled: true
    strategy_label: Custom
    strategy_notes: "Sports-only leg-tier event follow: Tier A 30-65c copies $3/leg, Tier B 65-80c copies $2/leg, skip outside the band."
    allowed_market_types: ["sports"]
    event_follow_strategy_enabled: true
    event_follow_buy_size_usdc: 2
    event_follow_max_event_exposure_usdc: 15
    event_follow_max_total_exposure_usdc: 50
    event_follow_min_source_trade_usdc: 5000
    event_follow_min_event_source_notional_usdc: 20000
    event_follow_min_event_buy_count: 2
    event_follow_min_avg_price: 0.30
    event_follow_max_avg_price: 0.80
    reserved_cash_usdc: 10
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: 100
paper:
  starting_cash_usdc: 500
  slippage_pct: 0
""",
        encoding="utf-8",
    )
    return load_config(path)


def _greerfew_settings(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: greerfew
    address: "{GREERFEW}"
    enabled: true
    strategy_label: Custom
    strategy_notes: "Weather limit-copy: wait for 2+ low-price event legs, then size the basket proportionally."
    allowed_market_types: ["weather"]
    event_follow_strategy_enabled: true
    event_follow_buy_size_usdc: 5
    event_follow_max_event_exposure_usdc: 5
    event_follow_max_total_exposure_usdc: 50
    event_follow_min_source_trade_usdc: 0
    event_follow_min_event_source_notional_usdc: 10
    event_follow_min_event_buy_count: 2
    event_follow_min_avg_price: 0.01
    event_follow_max_avg_price: 0.06
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: 100
paper:
  starting_cash_usdc: 500
  slippage_pct: 0
""",
        encoding="utf-8",
    )
    return load_config(path)
