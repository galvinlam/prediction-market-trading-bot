from pathlib import Path

import pytest

import polymarket_copy_trading.engine as engine_module
from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.store import Store


RN1 = "0x1111111111111111111111111111111111111111"
SWISSTONY = "0x2222222222222222222222222222222222222222"


@pytest.fixture(autouse=True)
def _use_legacy_repeat_buy_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "_filter_copy_enabled", lambda source_wallet, wallet: False)


def sports_buy(
    key: str,
    *,
    asset_id: str = "asset-team-a",
    notional: float = 20.0,
    price: float = 0.40,
    source_wallet: str = RN1,
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-04-27 21:20 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=source_wallet,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id="sports-market-1",
        outcome="Team A",
    )


def swisstony_buy(
    key: str,
    *,
    asset_id: str,
    notional: float,
    price: float,
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-05-01 15:41 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=SWISSTONY,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id="sports-market-1",
        outcome="Team B",
    )


def test_wallet_config_parses_repeat_buy_strategy_settings(tmp_path: Path) -> None:
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
    repeat_buy_strategy_enabled: true
    repeat_buy_size_usdc: 7.5
    repeat_buy_stop_loss_pct: 20
    reserved_cash_usdc: 50
""",
        encoding="utf-8",
    )

    config = load_config(path)
    wallet = config.wallets[0]

    assert wallet.repeat_buy_strategy_enabled is True
    assert wallet.repeat_buy_size_usdc == 7.5
    assert wallet.repeat_buy_stop_loss_pct == 20
    assert wallet.reserved_cash_usdc == 50


def test_wallet_config_parses_repeat_buy_signal_filters(tmp_path: Path) -> None:
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
    repeat_buy_strategy_enabled: true
    repeat_buy_min_source_notional_usdc: 100
    repeat_buy_min_buy_count: 3
    repeat_buy_min_avg_price: 0.05
    repeat_buy_max_avg_price: 0.75
    repeat_buy_max_total_exposure_usdc: 90
    repeat_buy_blocked_title_patterns:
      - "O/U"
      - "Counter-Strike"
    repeat_buy_allowed_sports: ["nba", "mlb", "atp"]
    repeat_buy_allowed_bet_types: ["moneyline_winlose"]
""",
        encoding="utf-8",
    )

    wallet = load_config(path).wallets[0]

    assert wallet.repeat_buy_min_source_notional_usdc == 100
    assert wallet.repeat_buy_min_buy_count == 3
    assert wallet.repeat_buy_min_avg_price == 0.05
    assert wallet.repeat_buy_max_avg_price == 0.75
    assert wallet.repeat_buy_max_total_exposure_usdc == 90
    assert wallet.repeat_buy_blocked_title_patterns == ("O/U", "Counter-Strike")
    assert wallet.repeat_buy_allowed_sports == ("nba", "mlb", "atp")
    assert wallet.repeat_buy_allowed_bet_types == ("moneyline_winlose",)


def test_wallet_config_parses_sports_trailing_stop_settings(tmp_path: Path) -> None:
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
    sports_trailing_stop_enabled: true
    sports_trailing_activation_pct: 35
    sports_trailing_stop_pct: 25
    sports_trailing_floor_delta: 0.03
""",
        encoding="utf-8",
    )

    wallet = load_config(path).wallets[0]

    assert wallet.sports_trailing_stop_enabled is True
    assert wallet.sports_trailing_activation_pct == 35
    assert wallet.sports_trailing_stop_pct == 25
    assert wallet.sports_trailing_floor_delta == 0.03


def test_repeat_buy_waits_for_second_buy_then_places_fixed_size_trade(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=8.0,
        repeat_buy_stop_loss_pct=0.0,
    )
    store.upsert_market_metadata(
        asset_id="asset-team-a",
        market_type="sports",
        title="Team A to win",
        outcome="Team A",
        market_slug="team-a-to-win",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    assert engine.process_trade(sports_buy("tx-1")) == "skipped"
    assert engine.process_trade(sports_buy("tx-2")) == "processed"
    assert engine.process_trade(sports_buy("tx-3")) == "skipped"

    signal = store.get_repeat_buy_signal(RN1, "asset-team-a")
    assert signal is not None
    assert signal["buy_count"] == 3
    assert signal["copied"] is True
    assert signal["copied_notional_usdc"] == 8.0
    position = store.list_positions()[0]
    assert position["cost_basis_usdc"] == 8.0


def test_rn1_repeat_buy_accumulates_to_source_scaled_target(tmp_path: Path) -> None:
    real_rn1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=real_rn1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=1000.0,
        repeat_buy_min_buy_count=2,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
        repeat_buy_max_total_exposure_usdc=100.0,
    )
    store.upsert_market_metadata(
        asset_id="asset-team-a",
        market_type="sports",
        title="Team A to win",
        outcome="Team A",
        market_slug="team-a-to-win",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    assert engine.process_trade(sports_buy("tx-1", notional=1000.0, source_wallet=real_rn1)) == "skipped"
    assert engine.process_trade(sports_buy("tx-2", notional=1000.0, source_wallet=real_rn1)) == "processed"
    assert engine.process_trade(sports_buy("tx-3", notional=4000.0, source_wallet=real_rn1)) == "processed"

    position = store.list_positions()[0]
    assert position["cost_basis_usdc"] == 3.0
    signal = store.get_repeat_buy_signal(real_rn1, "asset-team-a")
    assert signal is not None
    assert signal["copied_notional_usdc"] == 3.0


def test_rn1_repeat_buy_sizes_opposite_condition_buy_as_hedge(tmp_path: Path) -> None:
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
    )
    for asset_id, outcome in (("asset-home-yes", "Yes"), ("asset-home-no", "No")):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            condition_id="condition-home-win",
            title="Will Home FC win?",
            outcome=outcome,
            market_slug="home-fc-win",
        )
    prices = {"asset-home-yes": 0.55, "asset-home-no": 0.18}
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: prices[asset_id],
    )

    assert engine.process_trade(sports_buy("tx-1", asset_id="asset-home-yes", price=0.55, notional=50.0)) == "skipped"
    assert engine.process_trade(sports_buy("tx-2", asset_id="asset-home-yes", price=0.55, notional=50.0)) == "processed"
    assert engine.process_trade(sports_buy("tx-3", asset_id="asset-home-no", price=0.18, notional=50.0)) == "skipped"
    assert engine.process_trade(sports_buy("tx-4", asset_id="asset-home-no", price=0.18, notional=50.0)) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-home-yes"]["cost_basis_usdc"] == 5.0
    assert positions["asset-home-no"]["cost_basis_usdc"] == round(5.0 * 0.18 / (1 - 0.18), 6)


def test_repeat_buy_respects_configured_signal_quality_filters(tmp_path: Path) -> None:
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
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
        repeat_buy_max_total_exposure_usdc=75.0,
        repeat_buy_blocked_title_patterns=["O/U", "Counter-Strike"],
    )
    store.upsert_market_metadata(
        asset_id="tiny-source",
        market_type="sports",
        title="Team A to win",
        outcome="Team A",
    )
    store.upsert_market_metadata(
        asset_id="late-favorite",
        market_type="sports",
        title="Team B to win",
        outcome="Team B",
    )
    store.upsert_market_metadata(
        asset_id="total-market",
        market_type="sports",
        title="Team C vs Team D: O/U 221.5",
        outcome="Over",
    )
    store.upsert_market_metadata(
        asset_id="qualified",
        market_type="sports",
        title="Team E to win",
        outcome="Team E",
    )
    engine = CopyTradingEngine(
        config=_repeat_filter_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    for index in range(1, 4):
        assert engine.process_trade(sports_buy(f"tiny-{index}", asset_id="tiny-source", notional=20.0, price=0.40)) == "skipped"
    for index in range(1, 4):
        assert engine.process_trade(sports_buy(f"late-{index}", asset_id="late-favorite", notional=50.0, price=0.90)) == "skipped"
    for index in range(1, 4):
        assert engine.process_trade(sports_buy(f"total-{index}", asset_id="total-market", notional=50.0, price=0.40)) == "skipped"

    assert engine.process_trade(sports_buy("qualified-1", asset_id="qualified", notional=50.0, price=0.40)) == "skipped"
    assert engine.process_trade(sports_buy("qualified-2", asset_id="qualified", notional=50.0, price=0.40)) == "skipped"
    assert engine.process_trade(sports_buy("qualified-3", asset_id="qualified", notional=50.0, price=0.40)) == "processed"

    assert [position["asset_id"] for position in store.list_positions()] == ["qualified"]
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["repeat_buy_waiting_for_source_notional"] == 1
    assert summary["repeat_buy_price_band_blocked"] == 1
    assert summary["repeat_buy_market_filter_blocked"] == 3


def test_repeat_buy_blocks_when_event_follow_wallet_has_stronger_opposite_leg(tmp_path: Path) -> None:
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
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
    )
    store.upsert_wallet(
        name="swisstony",
        address=SWISSTONY,
        enabled=True,
        allowed_market_types=["sports"],
        event_follow_strategy_enabled=True,
        event_follow_min_event_source_notional_usdc=5000.0,
    )
    store.upsert_market_metadata(
        asset_id="team-a",
        market_type="sports",
        title="Team A vs Team B",
        event_slug="team-a-team-b-2026-05-01",
        outcome="Team A",
    )
    store.upsert_market_metadata(
        asset_id="team-b",
        market_type="sports",
        title="Team A vs Team B",
        event_slug="team-a-team-b-2026-05-01",
        outcome="Team B",
    )
    opposing_trade = swisstony_buy("swiss-1", asset_id="team-b", notional=444.0, price=0.46)
    store.record_event_follow_source_buy(
        source_wallet=SWISSTONY,
        event_slug="team-a-team-b-2026-05-01",
        event_title="Team A vs Team B",
        market_type="sports",
        trade=opposing_trade,
        market_slug="team-a-team-b",
        title="Team A vs Team B",
    )
    engine = CopyTradingEngine(
        config=_repeat_filter_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.48,
    )

    assert engine.process_trade(sports_buy("rn1-1", asset_id="team-a", notional=230.0, price=0.50)) == "skipped"
    assert engine.process_trade(sports_buy("rn1-2", asset_id="team-a", notional=5.0, price=0.48)) == "skipped"
    assert engine.process_trade(sports_buy("rn1-3", asset_id="team-a", notional=2.0, price=0.48)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["repeat_buy_conflicting_event_follow"] == 1


def test_rn1_repeat_buy_allows_soccer_football_but_blocks_tennis(tmp_path: Path) -> None:
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
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
        repeat_buy_max_total_exposure_usdc=75.0,
        repeat_buy_blocked_title_patterns=["atp-", "wta-", "tennis", "shymkent"],
        repeat_buy_allowed_sports=["nba", "mlb", "nhl", "soccer"],
        repeat_buy_allowed_bet_types=["moneyline_winlose", "map_or_game_winner"],
    )
    store.upsert_market_metadata(
        asset_id="soccer-football-club",
        market_type="sports",
        title="Will Club Nacional de Football win on 2026-05-01?",
        market_slug="lib-nacional-football-club-win-2026-05-01",
        event_slug="lib-nacional-football-club-2026-05-01",
        outcome="Yes",
    )
    store.upsert_market_metadata(
        asset_id="tennis-shymkent",
        market_type="sports",
        title="Shymkent 2: Antoine Ghibaudo vs Andrej Nedic",
        market_slug="atp-ghibaud-nedic-2026-05-01",
        event_slug="atp-ghibaud-nedic-2026-05-01",
        outcome="Andrej Nedic",
    )
    engine = CopyTradingEngine(
        config=_repeat_filter_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    for index in range(1, 4):
        result = engine.process_trade(
            sports_buy(f"soccer-{index}", asset_id="soccer-football-club", notional=50.0, price=0.40)
        )
    assert result == "processed"

    for index in range(1, 4):
        assert engine.process_trade(
            sports_buy(f"tennis-{index}", asset_id="tennis-shymkent", notional=50.0, price=0.40)
        ) == "skipped"

    assert [position["asset_id"] for position in store.list_positions()] == ["soccer-football-club"]
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["repeat_buy_market_filter_blocked"] == 3


def test_repeat_buy_blocks_worse_executable_price_than_source_signal(tmp_path: Path) -> None:
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
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
    )
    store.upsert_market_metadata(
        asset_id="runaway",
        market_type="sports",
        title="Team A to win",
        outcome="Team A",
    )
    engine = CopyTradingEngine(
        config=_repeat_filter_settings(
            tmp_path,
            slippage_pct=5,
            max_entry_price_source_premium=0.03,
            max_entry_price_source_multiple=1.10,
        ),
        store=store,
        buy_price_resolver=lambda asset_id: 0.47,
    )

    assert engine.process_trade(sports_buy("runaway-1", asset_id="runaway", notional=50.0, price=0.40)) == "skipped"
    assert engine.process_trade(sports_buy("runaway-2", asset_id="runaway", notional=50.0, price=0.40)) == "skipped"
    assert engine.process_trade(sports_buy("runaway-3", asset_id="runaway", notional=50.0, price=0.40)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["entry_price_drift_blocked"] == 1


def test_rn1_repeat_buy_allows_high_conviction_cs2_match_winner(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store.upsert_wallet(
        name="RN1",
        address=rn1_wallet,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
        repeat_buy_max_total_exposure_usdc=90.0,
        repeat_buy_blocked_title_patterns=["O/U", "spread", "handicap", "Abidjan 2:"],
        repeat_buy_allowed_sports=["nba", "mlb", "atp", "tennis", "nhl", "esports"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
    )
    asset_id = "cs2-match-furia"
    store.upsert_market_metadata(
        asset_id=asset_id,
        market_type="sports",
        title="Counter-Strike: FaZe vs FURIA (BO3) - BLAST Rivals Group B",
        market_slug="cs2-faze-furia-2026-04-30",
        event_slug="cs2-faze-furia-2026-04-30",
        outcome="FURIA",
    )
    engine = CopyTradingEngine(config=_rn1_esports_settings(tmp_path), store=store)

    result = "skipped"
    for index in range(1, 41):
        result = engine.process_trade(
            SourceTrade(
                idempotency_key=f"137:0xcs2-{index}:{index}:{rn1_wallet}",
                chain_id=137,
                exchange_contract="ctf_exchange",
                tx_hash=f"0xcs2-{index}",
                block_number=100 + index,
                block_timestamp="2026-04-30 13:31 PDT",
                log_index=index,
                source_wallet=rn1_wallet,
                side="buy",
                asset_id=asset_id,
                price=0.55,
                quantity=1000.0,
                notional_usdc=550.0,
            )
        )

    assert result == "processed"
    assert store.overview()["open_positions"] == 1
    assert store.get_repeat_buy_signal(rn1_wallet, asset_id)["buy_count"] == 40


def test_rn1_repeat_buy_blocks_low_conviction_cs2_and_pauses_abidjan_tennis(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store.upsert_wallet(
        name="RN1",
        address=rn1_wallet,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_blocked_title_patterns=["Abidjan 2:"],
        repeat_buy_allowed_sports=["esports", "tennis"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
    )
    config = _rn1_esports_settings(tmp_path)
    engine = CopyTradingEngine(config=config, store=store)
    store.upsert_market_metadata(
        asset_id="cs2-low",
        market_type="sports",
        title="Counter-Strike: P2N vs 3DMAX Academy (BO3) - Exort Series Contenders Stage",
        market_slug="cs2-p2n-3dmaxa-2026-04-30",
        event_slug="cs2-p2n-3dmaxa-2026-04-30",
        outcome="P2N",
    )
    assert engine.process_trade(
        SourceTrade(
            idempotency_key=f"137:0xcs2-low:1:{rn1_wallet}",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xcs2-low",
            block_number=200,
            block_timestamp="2026-04-30 09:39 PDT",
            log_index=1,
            source_wallet=rn1_wallet,
            side="buy",
            asset_id="cs2-low",
            price=0.43,
            quantity=400.0,
            notional_usdc=172.0,
        )
    ) == "skipped"
    assert store.list_trades()[0]["skip_reason"] == "rn1_esports_waiting_for_buy_count"

    store.upsert_market_metadata(
        asset_id="abidjan-tennis",
        market_type="sports",
        title="Abidjan 2: Hamish Stewart vs Blaise Bicknell",
        market_slug="atp-abidjan-2-stewart-bicknell",
        event_slug="atp-abidjan-2-stewart-bicknell",
        outcome="Hamish Stewart",
    )
    assert engine.process_trade(
        SourceTrade(
            idempotency_key=f"137:0xabidjan:1:{rn1_wallet}",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xabidjan",
            block_number=201,
            block_timestamp="2026-04-30 09:40 PDT",
            log_index=1,
            source_wallet=rn1_wallet,
            side="buy",
            asset_id="abidjan-tennis",
            price=0.40,
            quantity=100.0,
            notional_usdc=40.0,
        )
    ) == "skipped"
    assert store.list_trades()[0]["skip_reason"] == "rn1_tennis_paused"


def test_rn1_repeat_buy_blocks_high_conviction_cs2_map_winner(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store.upsert_wallet(
        name="RN1",
        address=rn1_wallet,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
        repeat_buy_max_total_exposure_usdc=90.0,
        repeat_buy_blocked_title_patterns=["O/U", "spread", "handicap", "Abidjan 2:"],
        repeat_buy_allowed_sports=["esports"],
        repeat_buy_allowed_bet_types=["moneyline_winlose", "map_or_game_winner"],
        event_follow_max_event_exposure_usdc=12.0,
        event_follow_max_total_exposure_usdc=90.0,
    )
    asset_id = "cs2-map-gamerlegion"
    store.upsert_market_metadata(
        asset_id=asset_id,
        market_type="sports",
        title="Counter-Strike: Astralis vs GamerLegion (BO3) - Map 2 Winner",
        market_slug="cs2-astralis-gamerlegion-2026-05-01-map-2",
        event_slug="cs2-astralis-gamerlegion-2026-05-01",
        outcome="GamerLegion",
    )
    engine = CopyTradingEngine(config=_rn1_esports_settings(tmp_path), store=store)

    result = "skipped"
    for index in range(1, 41):
        result = engine.process_trade(
            SourceTrade(
                idempotency_key=f"137:0xcs2-map-{index}:{index}:{rn1_wallet}",
                chain_id=137,
                exchange_contract="ctf_exchange",
                tx_hash=f"0xcs2-map-{index}",
                block_number=300 + index,
                block_timestamp="2026-05-01 13:31 PDT",
                log_index=index,
                source_wallet=rn1_wallet,
                side="buy",
                asset_id=asset_id,
                price=0.55,
                quantity=1000.0,
                notional_usdc=550.0,
            )
        )

    assert result == "skipped"
    assert store.list_positions() == []
    assert store.list_trades()[0]["skip_reason"] == "rn1_esports_bet_type_blocked"


def test_rn1_repeat_buy_blocks_correlated_cs2_map_winners_when_match_winner_exists(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store.upsert_wallet(
        name="RN1",
        address=rn1_wallet,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.75,
        repeat_buy_max_total_exposure_usdc=90.0,
        repeat_buy_blocked_title_patterns=["O/U", "spread", "handicap", "Abidjan 2:"],
        repeat_buy_allowed_sports=["esports"],
        repeat_buy_allowed_bet_types=["moneyline_winlose", "map_or_game_winner"],
        event_follow_max_event_exposure_usdc=12.0,
        event_follow_max_total_exposure_usdc=90.0,
    )
    event_slug = "cs2-astralis-gamerlegion-2026-05-01"
    match_title = "Counter-Strike: Astralis vs GamerLegion (BO3) - BLAST Rivals Playoffs"
    map_title = "Counter-Strike: Astralis vs GamerLegion (BO3) - Map 2 Winner"
    store.upsert_market_metadata(
        asset_id="cs2-match-gamerlegion",
        market_type="sports",
        title=match_title,
        market_slug=event_slug,
        event_slug=event_slug,
        outcome="GamerLegion",
    )
    store.upsert_market_metadata(
        asset_id="cs2-map-gamerlegion",
        market_type="sports",
        title=map_title,
        market_slug=f"{event_slug}-game2",
        event_slug=event_slug,
        outcome="GamerLegion",
    )
    store.upsert_market_metadata(
        asset_id="cs2-map-astralis",
        market_type="sports",
        title=map_title,
        market_slug=f"{event_slug}-game2",
        event_slug=event_slug,
        outcome="Astralis",
    )
    engine = CopyTradingEngine(config=_rn1_esports_settings(tmp_path), store=store)

    def buy(asset_id: str, outcome: str, price: float, index: int) -> SourceTrade:
        return SourceTrade(
            idempotency_key=f"137:0x{asset_id}-{index}:{index}:{rn1_wallet}",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash=f"0x{asset_id}-{index}",
            block_number=400 + index,
            block_timestamp="2026-05-01 13:31 PDT",
            log_index=index,
            source_wallet=rn1_wallet,
            side="buy",
            asset_id=asset_id,
            price=price,
            quantity=1000.0,
            notional_usdc=round(price * 1000.0, 6),
            outcome=outcome,
        )

    for index in range(1, 41):
        engine.process_trade(buy("cs2-match-gamerlegion", "GamerLegion", 0.55, index))

    positions = {row["asset_id"]: row for row in store.list_positions()}
    assert positions["cs2-match-gamerlegion"]["cost_basis_usdc"] == 11.0

    result = "skipped"
    for index in range(41, 81):
        result = engine.process_trade(buy("cs2-map-astralis", "Astralis", 0.55, index))

    positions = {row["asset_id"]: row for row in store.list_positions()}
    assert result == "skipped"
    assert set(positions) == {"cs2-match-gamerlegion"}
    assert store.list_trades()[0]["skip_reason"] == "rn1_esports_bet_type_blocked"


def test_rn1_repeat_buy_pauses_high_conviction_tennis_filter_override(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store.upsert_wallet(
        name="RN1",
        address=rn1_wallet,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.70,
        repeat_buy_max_total_exposure_usdc=90.0,
        repeat_buy_blocked_title_patterns=["tennis", "jiujiang"],
        repeat_buy_allowed_sports=["soccer", "mlb"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
    )
    asset_id = "rn1-tennis-conviction"
    store.upsert_market_metadata(
        asset_id=asset_id,
        market_type="sports",
        title="Jiujiang: Alex Bolt vs Adam Walton",
        market_slug="atp-jiujiang-bolt-walton-2026-05-01",
        event_slug="atp-jiujiang-bolt-walton-2026-05-01",
        outcome="Adam Walton",
    )
    engine = CopyTradingEngine(config=_settings(tmp_path), store=store)

    result = "skipped"
    for index in range(1, 11):
        result = engine.process_trade(
            SourceTrade(
                idempotency_key=f"137:0xtennis-{index}:{index}:{rn1_wallet}",
                chain_id=137,
                exchange_contract="ctf_exchange",
                tx_hash=f"0xtennis-{index}",
                block_number=500 + index,
                block_timestamp="2026-05-01 20:24 PDT",
                log_index=index,
                source_wallet=rn1_wallet,
                side="buy",
                asset_id=asset_id,
                price=0.55,
                quantity=600.0,
                notional_usdc=330.0,
            )
        )

    assert result == "skipped"
    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_tennis_paused"] == 10


def test_rn1_repeat_buy_allows_high_conviction_total_filter_override(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    store.upsert_wallet(
        name="RN1",
        address=rn1_wallet,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        repeat_buy_min_source_notional_usdc=100.0,
        repeat_buy_min_buy_count=3,
        repeat_buy_min_avg_price=0.05,
        repeat_buy_max_avg_price=0.70,
        repeat_buy_max_total_exposure_usdc=90.0,
        repeat_buy_blocked_title_patterns=["O/U", "total"],
        repeat_buy_allowed_sports=["soccer"],
        repeat_buy_allowed_bet_types=["moneyline_winlose"],
    )
    asset_id = "rn1-leeds-total"
    store.upsert_market_metadata(
        asset_id=asset_id,
        market_type="sports",
        title="Leeds United FC vs. Burnley FC: O/U 3.5",
        market_slug="leeds-burnley-2026-05-01-total-3pt5",
        event_slug="leeds-burnley-2026-05-01",
        outcome="Over",
    )
    engine = CopyTradingEngine(config=_settings(tmp_path), store=store)

    result = "skipped"
    for index in range(1, 11):
        result = engine.process_trade(
            SourceTrade(
                idempotency_key=f"137:0xtotal-{index}:{index}:{rn1_wallet}",
                chain_id=137,
                exchange_contract="ctf_exchange",
                tx_hash=f"0xtotal-{index}",
                block_number=600 + index,
                block_timestamp="2026-05-01 12:02 PDT",
                log_index=index,
                source_wallet=rn1_wallet,
                side="buy",
                asset_id=asset_id,
                price=0.47,
                quantity=700.0,
                notional_usdc=329.0,
            )
        )

    assert result == "processed"
    assert store.list_positions()[0]["asset_id"] == asset_id


def test_repeat_buy_wallet_stop_loss_closes_live_sports_drawdown(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=8.0,
        repeat_buy_stop_loss_pct=25.0,
    )
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.29)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )
    engine.process_trade(sports_buy("tx-1"))
    engine.process_trade(sports_buy("tx-2"))
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.29)

    assert engine.process_local_exits() == 1
    assert store.overview()["open_positions"] == 0
    assert [trade for trade in store.list_trades() if trade["paper_side"] == "sell"][-1]["close_reason"] == "stop_loss"


def test_sports_trailing_stop_exits_after_activated_winner_reverses(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=8.0,
        repeat_buy_stop_loss_pct=40.0,
        sports_trailing_stop_enabled=True,
        sports_trailing_activation_pct=35.0,
        sports_trailing_stop_pct=25.0,
        sports_trailing_floor_delta=0.03,
    )
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.40)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )
    engine.process_trade(sports_buy("tx-1"))
    engine.process_trade(sports_buy("tx-2"))

    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.56)
    assert engine.process_local_exits() == 0
    position = store.list_positions()[0]
    assert position["trailing_peak_price"] == 0.56
    assert position["trailing_activated"] is True

    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.45)
    assert engine.process_local_exits() == 0

    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.42)
    assert engine.process_local_exits() == 1
    assert store.overview()["open_positions"] == 0
    sell_trade = store.list_trades()[0]
    assert sell_trade["close_reason"] == "trailing_stop"


def test_sports_trailing_stop_does_not_turn_winner_into_loss_after_slippage(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="rn1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=5.0,
        repeat_buy_stop_loss_pct=0.0,
        sports_trailing_stop_enabled=True,
        sports_trailing_activation_pct=35.0,
        sports_trailing_stop_pct=25.0,
        sports_trailing_floor_delta=0.03,
    )
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.59)
    config_path = tmp_path / "config-trailing-profit-floor.yaml"
    config_path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "{RN1}"
    enabled: true
    allowed_market_types: ["sports"]
    repeat_buy_strategy_enabled: true
    repeat_buy_size_usdc: 5
    repeat_buy_stop_loss_pct: 0
    sports_trailing_stop_enabled: true
    sports_trailing_activation_pct: 35
    sports_trailing_stop_pct: 25
    sports_trailing_floor_delta: 0.03
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: 100
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
exits:
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    first = sports_buy("tx-1", price=0.59, notional=10)
    second = sports_buy("tx-2", price=0.59, notional=10)
    engine = CopyTradingEngine(config=config, store=store)
    assert engine.process_trade(first) == "skipped"
    assert engine.process_trade(second) == "processed"
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.94)
    assert engine.process_local_exits() == 0
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.61)

    assert CopyTradingEngine(config=config, store=store).process_local_exits() == 0
    assert len(store.list_positions()) == 1
    assert not any(trade["paper_side"] == "sell" for trade in store.list_trades())


def test_sports_trailing_stop_does_not_apply_to_weather(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports", "weather"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=8.0,
        repeat_buy_stop_loss_pct=0.0,
        sports_trailing_stop_enabled=True,
        sports_trailing_activation_pct=10.0,
        sports_trailing_stop_pct=10.0,
        sports_trailing_floor_delta=0.03,
    )
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="weather", current_price=0.40)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )
    engine.process_trade(sports_buy("tx-1"))
    engine.process_trade(sports_buy("tx-2"))

    store.upsert_market_metadata(asset_id="asset-team-a", market_type="weather", current_price=0.80)
    assert engine.process_local_exits() == 0
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="weather", current_price=0.42)
    assert engine.process_local_exits() == 0
    assert store.overview()["open_positions"] == 1


def test_repeat_buy_zero_wallet_stop_loss_suppresses_global_stop_loss(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=8.0,
        repeat_buy_stop_loss_pct=0.0,
    )
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.01)
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )
    engine.process_trade(sports_buy("tx-1"))
    engine.process_trade(sports_buy("tx-2"))
    store.upsert_market_metadata(asset_id="asset-team-a", market_type="sports", current_price=0.01)

    assert engine.process_local_exits() == 0
    assert store.overview()["open_positions"] == 1


def test_repeat_buy_can_use_its_own_reserved_cash(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address=RN1,
        enabled=True,
        allowed_market_types=["sports"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_size_usdc=3.0,
        repeat_buy_stop_loss_pct=0.0,
        reserved_cash_usdc=50.0,
    )
    store.upsert_market_metadata(
        asset_id="asset-team-a",
        market_type="sports",
        title="Team A to win",
        outcome="Team A",
        market_slug="team-a-to-win",
    )
    store.set_runtime_state("paper_cash_usdc", "51")
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    assert engine.process_trade(sports_buy("tx-1")) == "skipped"
    assert engine.process_trade(sports_buy("tx-2")) == "processed"

    assert store.list_positions()[0]["cost_basis_usdc"] == 3.0


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
    allowed_market_types: ["sports"]
    repeat_buy_strategy_enabled: true
    repeat_buy_size_usdc: 8
    repeat_buy_stop_loss_pct: 25
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


def _repeat_filter_settings(
    tmp_path: Path,
    *,
    slippage_pct: float = 0,
    max_entry_price_source_premium: float = 0.25,
    max_entry_price_source_multiple: float = 2.0,
):
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
    allowed_market_types: ["sports"]
    repeat_buy_strategy_enabled: true
    repeat_buy_size_usdc: 5
    repeat_buy_stop_loss_pct: 0
    repeat_buy_min_source_notional_usdc: 100
    repeat_buy_min_buy_count: 3
    repeat_buy_min_avg_price: 0.05
    repeat_buy_max_avg_price: 0.75
    repeat_buy_max_total_exposure_usdc: 75
    repeat_buy_blocked_title_patterns: ["O/U", "Counter-Strike"]
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: 100
  max_entry_price_source_premium: {max_entry_price_source_premium}
  max_entry_price_source_multiple: {max_entry_price_source_multiple}
paper:
  starting_cash_usdc: 100
  slippage_pct: {slippage_pct}
""",
        encoding="utf-8",
    )
    return load_config(path)


def _rn1_esports_settings(tmp_path: Path):
    rn1_wallet = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    path = tmp_path / "config-rn1-esports.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "{rn1_wallet}"
    enabled: true
    allowed_market_types: ["sports"]
    repeat_buy_strategy_enabled: true
    repeat_buy_size_usdc: 5
    repeat_buy_stop_loss_pct: 0
    repeat_buy_min_source_notional_usdc: 100
    repeat_buy_min_buy_count: 3
    repeat_buy_min_avg_price: 0.05
    repeat_buy_max_avg_price: 0.75
    repeat_buy_max_total_exposure_usdc: 90
    repeat_buy_blocked_title_patterns: ["O/U", "spread", "handicap", "Abidjan 2:"]
    repeat_buy_allowed_sports: ["nba", "mlb", "atp", "tennis", "nhl", "esports"]
    repeat_buy_allowed_bet_types: ["moneyline_winlose"]
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
