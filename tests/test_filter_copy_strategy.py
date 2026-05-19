from pathlib import Path

import pytest

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.paper import PaperExecutionError
from polymarket_copy_trading.store import Store
from polymarket_copy_trading.wallet_profile import event_book_planner_default_overrides


RN1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
SWISSTONY = "0x204f72f35326db932158cba6adff0b9a1da95e14"


def source_trade(
    key: str,
    *,
    wallet: str = RN1,
    asset_id: str = "asset-nba-main",
    price: float = 0.50,
    notional: float = 3000.0,
    side: str = "buy",
    block_number: int = 100,
    block_timestamp: str = "2026-05-03 12:00 PDT",
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=key,
        block_number=block_number,
        block_timestamp=block_timestamp,
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=wallet,
        side=side,
        asset_id=asset_id,
        price=price,
        quantity=notional / price,
        notional_usdc=notional,
        market_id=f"market-{asset_id}",
        outcome="Yes",
    )


def test_execute_buy_blocks_polymarket_sub_minimum_notional(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)
    trade = source_trade("tx-1", asset_id="asset-nba-main", price=0.40, notional=3000.0)

    with pytest.raises(PaperExecutionError, match="buy_below_min_notional"):
        engine._execute_buy(trade, notional_usdc=0.999999, observed_price=0.40)

    assert store.paper_trade_count() == 0
    assert store.list_positions() == []


def test_rn1_filter_copy_pauses_dominant_tennis_event_book_leg(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="wta-keys-stearns-2026-05-11",
        event_title="Madison Keys vs Peyton Stearns",
        markets=[
            ("asset-tennis-dominant", "Internazionali BNL d'Italia: Madison Keys vs Peyton Stearns", "Madison Keys"),
            ("asset-tennis-hedge", "Internazionali BNL d'Italia: Madison Keys vs Peyton Stearns", "Peyton Stearns"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-dominant", count=19, price=0.40, notional=200.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-hedge", count=5, price=0.60, notional=200.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-tennis-dominant", price=0.40, notional=200.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_tennis_paused"] == 1


def test_rn1_filter_copy_blocks_barely_dominant_two_sided_tennis_fresh_entry(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    _upsert_same_event_markets(
        store,
        event_slug="atp-darderi-zverev-2026-05-12",
        event_title="Luciano Darderi vs Alexander Zverev",
        markets=[
            ("asset-zverev", "Internazionali BNL d'Italia: Luciano Darderi vs Alexander Zverev", "Alexander Zverev"),
            ("asset-darderi", "Internazionali BNL d'Italia: Luciano Darderi vs Alexander Zverev", "Luciano Darderi"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-zverev", count=19, price=0.52, notional=140.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-darderi", count=20, price=0.37, notional=78.5)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.379)

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-zverev", price=0.364, notional=140.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_event_book_not_dominant"] == 1


def test_rn1_filter_copy_blocks_dominant_esports_map_leg(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="cs2-furia-spirit-map1-2026-05-11",
        event_title="FURIA vs Spirit",
        markets=[
            ("asset-cs2-map-dominant", "Counter-Strike: FURIA vs Spirit - Map 1 Winner", "FURIA"),
            ("asset-cs2-map-hedge", "Counter-Strike: FURIA vs Spirit - Map 1 Winner", "Spirit"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-cs2-map-dominant", count=9, price=0.35, notional=500.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-cs2-map-hedge", count=2, price=0.65, notional=500.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.35)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-cs2-map-dominant", price=0.35, notional=500.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_rn1_filter_copy_blocks_barely_dominant_two_sided_esports_map_fresh_entry(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="cs2-navi-vitality-map2-2026-05-12",
        event_title="NAVI vs Vitality",
        markets=[
            ("asset-cs2-map-navi", "Counter-Strike: NAVI vs Vitality - Map 2 Winner", "NAVI"),
            ("asset-cs2-map-vitality", "Counter-Strike: NAVI vs Vitality - Map 2 Winner", "Vitality"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-cs2-map-navi", count=9, price=0.40, notional=500.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-cs2-map-vitality", count=10, price=0.55, notional=280.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-cs2-map-navi", price=0.40, notional=500.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_filter_copy_event_book_rounds_proportional_hedge_to_minimum_buy(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="soccer-yunnan-yukun-2026-05-06",
        event_title="Yunnan Yukun FC vs Zhejiang Zhiye FC",
        markets=[
            ("asset-yunnan-yes", "Will Yunnan Yukun FC win on 2026-05-06?", "Yes"),
            ("asset-yunnan-no", "Will Yunnan Yukun FC win on 2026-05-06?", "No"),
        ],
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.54 if asset_id == "asset-yunnan-yes" else 0.38,
    )

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-yunnan-yes", price=0.54, notional=10000.0)) == "processed"
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-yunnan-no", price=0.38, notional=1000.0)) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-yunnan-yes"]["cost_basis_usdc"] == 5.0
    assert positions["asset-yunnan-no"]["cost_basis_usdc"] == 1.0


def test_rn1_filter_copy_blocks_derivative_repair_after_dominant_event_leg(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="epl-tottenham-leeds-2026-05-11",
        event_title="Tottenham Hotspur FC vs Leeds United FC",
        markets=[
            ("asset-spurs-no", "Will Tottenham Hotspur FC win on 2026-05-11?", "No"),
            ("asset-spurs-draw", "Will Tottenham Hotspur FC vs. Leeds United FC end in a draw?", "No"),
            ("asset-spurs-total", "Tottenham Hotspur FC vs. Leeds United FC: O/U 2.5", "Over"),
        ],
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: {
            "asset-spurs-no": 0.40,
            "asset-spurs-draw": 0.34,
            "asset-spurs-total": 0.38,
        }[asset_id],
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-spurs-draw", price=0.34, notional=5000.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-spurs-no", price=0.40, notional=20000.0, block_number=101)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-3", asset_id="asset-spurs-draw", price=0.34, notional=5000.0, block_number=102)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-4", asset_id="asset-spurs-total", price=0.38, notional=3000.0, block_number=103)
    ) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-spurs-no"}
    assert positions["asset-spurs-no"]["cost_basis_usdc"] == 10.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 3


def test_rn1_filter_copy_allows_high_drift_event_book_repair_when_risk_reducing(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-nyy-bal-2026-05-11",
        event_title="New York Yankees vs Baltimore Orioles",
        markets=[
            ("asset-yankees", "New York Yankees vs. Baltimore Orioles", "New York Yankees"),
            ("asset-orioles", "New York Yankees vs. Baltimore Orioles", "Baltimore Orioles"),
        ],
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.55 if asset_id == "asset-yankees" else 0.90,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-yankees", price=0.55, notional=20000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-orioles", price=0.40, notional=20000.0, block_number=101)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-yankees"]["cost_basis_usdc"] == 10.0
    assert positions["asset-orioles"]["cost_basis_usdc"] == 3.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert "filter_copy_local_price_blocked" not in summary
    assert "entry_price_drift_blocked" not in summary


def test_rn1_filter_copy_blocks_near_one_event_book_repair_even_when_risk_reducing(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-nyy-bal-2026-05-11",
        event_title="New York Yankees vs Baltimore Orioles",
        markets=[
            ("asset-yankees", "New York Yankees vs. Baltimore Orioles", "New York Yankees"),
            ("asset-orioles", "New York Yankees vs. Baltimore Orioles", "Baltimore Orioles"),
        ],
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.55 if asset_id == "asset-yankees" else 0.99,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-yankees", price=0.55, notional=20000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-orioles", price=0.40, notional=20000.0, block_number=101)
    ) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-yankees"}
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_local_price_blocked"] == 1


def test_rn1_filter_copy_allows_esports_source_book_repair_when_worst_case_check_rejects(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="cs2-parivision-g2-2026-05-12",
        event_title="Counter-Strike: PARIVISION vs G2",
        markets=[
            ("asset-parivision", "Counter-Strike: PARIVISION vs G2 (BO3) - PGL Astana Group Stage", "PARIVISION"),
            ("asset-g2", "Counter-Strike: PARIVISION vs G2 (BO3) - PGL Astana Group Stage", "G2"),
        ],
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-parivision", price=0.50, notional=20000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-g2", price=0.50, notional=20000.0, block_number=101)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-3", asset_id="asset-g2", price=0.50, notional=10000.0, block_number=102)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-parivision"]["cost_basis_usdc"] == 10.0
    assert positions["asset-g2"]["cost_basis_usdc"] == 15.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert "filter_copy_repair_not_risk_reducing" not in summary


def test_rn1_filter_copy_blocks_co_dominant_tennis_repair_under_strict_rules(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    _upsert_same_event_markets(
        store,
        event_slug="atp-khachanov-prizmic-2026-05-12",
        event_title="Karen Khachanov vs Dino Prizmic",
        markets=[
            ("asset-prizmic", "Internazionali BNL d'Italia: Karen Khachanov vs Dino Prizmic", "Dino Prizmic"),
            ("asset-khachanov", "Internazionali BNL d'Italia: Karen Khachanov vs Dino Prizmic", "Karen Khachanov"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-prizmic", count=19, price=0.40, notional=150.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-khachanov", count=19, price=0.70, notional=50.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-prizmic" else 0.70,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-prizmic", price=0.40, notional=1100.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-khachanov", price=0.70, notional=1100.0, block_number=101)
    ) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-prizmic"}
    assert positions["asset-prizmic"]["cost_basis_usdc"] == 1.975
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_tennis_conviction_blocked"] == 1
    assert summary["rn1_event_book_not_dominant"] == 1


def test_rn1_filter_copy_accepts_main_sports_while_blocking_maps_and_tennis(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.574 if asset_id == "asset-nba-main" else 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-nba-main", price=0.574)) == "processed"
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-nba-expensive", price=0.575)) == "processed"
    assert engine.process_trade(source_trade("tx-3", asset_id="asset-nba-total", price=0.40)) == "skipped"
    assert engine.process_trade(source_trade("tx-4", asset_id="asset-soccer-draw", price=0.40)) == "skipped"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-main", count=19, price=0.40, notional=75.0)
    assert engine.process_trade(source_trade("tx-5", asset_id="asset-wta-main", price=0.40, notional=75.0)) == "skipped"
    assert engine.process_trade(source_trade("tx-6", asset_id="asset-soccer-main", price=0.19)) == "skipped"
    assert engine.process_trade(source_trade("tx-7", asset_id="asset-cs2-main", price=0.40, notional=5000.0)) == "processed"
    assert engine.process_trade(source_trade("tx-8", asset_id="asset-cs2-map", price=0.40, notional=5000.0)) == "skipped"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-atp-main", count=19, price=0.40, notional=75.0)
    assert engine.process_trade(source_trade("tx-9", asset_id="asset-atp-main", price=0.40, notional=75.0)) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {
        "asset-nba-main",
        "asset-nba-expensive",
        "asset-cs2-main",
    }
    assert positions["asset-nba-main"]["cost_basis_usdc"] == 1.5
    assert positions["asset-nba-expensive"]["cost_basis_usdc"] == 1.5
    assert positions["asset-cs2-main"]["cost_basis_usdc"] == 2.5
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_price_blocked"] == 1
    assert summary["filter_copy_market_blocked"] == 3
    assert summary["rn1_tennis_paused"] == 2


def test_rn1_filter_copy_tennis_requires_conviction_before_rank_rules(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-atp-main", price=0.40, notional=1500.0)) == "skipped"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-main", count=19, price=0.40, notional=50.0)
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-tennis-main", price=0.40, notional=50.0)) == "skipped"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-main", count=18, price=0.46, notional=100.0)
    assert engine.process_trade(source_trade("tx-3", asset_id="asset-wta-main", price=0.46, notional=100.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_tennis_conviction_blocked"] == 3


def test_rn1_filter_copy_disabled_does_not_use_tennis_event_book_reopen(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    wallet = store.get_wallet(RN1)
    profile = wallet["profile_json"]
    profile["filter_copy"]["enabled"] = False
    profile["repeat_buy"]["enabled"] = True
    profile["repeat_buy"]["min_buy_count"] = 2
    profile["repeat_buy"]["min_source_notional_usdc"] = 1.0
    store.update_wallet(RN1, profile_json=profile)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-main", count=1, price=0.40, notional=100.0)
    assert engine.process_trade(source_trade("tx-1", asset_id="asset-wta-main", price=0.40, notional=100.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["repeat_buy_waiting_for_second_buy"] == 1


def test_filter_copy_uses_structured_sport_and_bet_type_before_text_fallback(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    store.upsert_market_metadata(
        asset_id="asset-structured-mlb",
        market_type="sports",
        sport_key="mlb",
        bet_type="moneyline_winlose",
        title="Participant A / Participant B",
        market_slug="daily-match-market",
        event_slug="daily-match-event",
        event_title="Participant A / Participant B",
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-structured-mlb", price=0.40, notional=5000.0)) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-structured-mlb"


def test_rn1_filter_copy_blocks_structured_counter_strike_map_when_not_event_extreme(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    store.upsert_market_metadata(
        asset_id="asset-cs2-structured-match",
        market_type="sports",
        sport_key="esports",
        bet_type="moneyline_winlose",
        title="Counter-Strike: Eternal Fire vs Johnny Speeds",
        outcome="Eternal Fire",
        market_slug="cs2-ef-js-match",
        event_slug="cs2-ef-js",
        event_title="Counter-Strike: Eternal Fire vs Johnny Speeds",
    )
    store.upsert_market_metadata(
        asset_id="asset-cs2-structured-map",
        market_type="sports",
        sport_key="esports",
        bet_type="map_or_game_winner",
        title="Counter-Strike: Eternal Fire vs Johnny Speeds - Map 2 Winner",
        outcome="Eternal Fire",
        market_slug="cs2-ef-js-map-2",
        event_slug="cs2-ef-js",
        event_title="Counter-Strike: Eternal Fire vs Johnny Speeds",
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-cs2-structured-match", price=0.40, notional=5000.0)) == "processed"
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-cs2-structured-map", price=0.40, notional=5000.0)) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-cs2-structured-match"}
    assert positions["asset-cs2-structured-match"]["cost_basis_usdc"] == 2.5
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_rn1_filter_copy_wta_requires_conviction_before_rank_rules(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    for asset_id, player in (
        ("asset-wta-rank-one", "Player A"),
        ("asset-wta-rank-two", "Player B"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=f"WTA: {player} vs Player C",
            outcome=player,
            event_slug="wta-player-a-player-b-2026-05-03",
            event_title="WTA Player A vs Player B",
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-rank-one", count=18, price=0.40, notional=350.0)
    assert engine.process_trade(source_trade("tx-1", asset_id="asset-wta-rank-one", price=0.40, notional=350.0)) == "skipped"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-rank-two", count=19, price=0.40, notional=50.0)
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-wta-rank-two", price=0.40, notional=100.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_tennis_conviction_blocked"] == 2


def test_rn1_filter_copy_allows_strict_dominant_tennis_event_book_leg(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1, enable_rn1_planner=True)
    _unpause_rn1_tennis(store)
    _upsert_same_event_markets(
        store,
        event_slug="atp-dominant-tennis-2026-05-08",
        event_title="Holger Rune vs Casper Ruud",
        markets=[
            ("asset-tennis-opposite", "ATP: Holger Rune vs Casper Ruud", "Casper Ruud"),
            ("asset-tennis-candidate", "ATP: Holger Rune vs Casper Ruud", "Holger Rune"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-candidate", count=19, price=0.40, notional=75.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-opposite", count=5, price=0.40, notional=100.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-tennis-candidate", price=0.40, notional=75.0)) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-tennis-candidate"}
    assert positions["asset-tennis-candidate"]["cost_basis_usdc"] == 5.0


def test_rn1_filter_copy_tennis_blocks_secondary_when_event_book_not_dominant(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    _upsert_same_event_markets(
        store,
        event_slug="wta-keys-stearns-2026-05-08",
        event_title="Madison Keys vs Peyton Stearns",
        markets=[
            ("asset-tennis-opposite", "Internazionali BNL d'Italia: Madison Keys vs Peyton Stearns", "Peyton Stearns"),
            ("asset-tennis-candidate", "Internazionali BNL d'Italia: Madison Keys vs Peyton Stearns", "Madison Keys"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-opposite", count=20, price=0.57, notional=175.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-candidate", count=19, price=0.32, notional=100.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.32)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-tennis-candidate", price=0.32, notional=100.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_event_book_not_dominant"] == 1


def test_rn1_filter_copy_tennis_blocks_secondary_when_opposite_is_materially_larger(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    _upsert_same_event_markets(
        store,
        event_slug="wta-gibson-shnaider-2026-05-08",
        event_title="Talia Gibson vs Diana Shnaider",
        markets=[
            ("asset-tennis-opposite", "Internazionali BNL d'Italia: Talia Gibson vs Diana Shnaider", "Diana Shnaider"),
            ("asset-tennis-candidate", "Internazionali BNL d'Italia: Talia Gibson vs Diana Shnaider", "Talia Gibson"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-opposite", count=20, price=0.70, notional=300.0)
    _seed_source_buys(store, wallet=RN1, asset_id="asset-tennis-candidate", count=19, price=0.25, notional=80.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.25)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-tennis-candidate", price=0.25, notional=80.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_tennis_rank_blocked"] == 1


def test_filter_copy_event_book_allows_close_rank_one_flip_against_open_opposite_position(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    for asset_id, player in (
        ("asset-soccer-opposite-one", "Player A"),
        ("asset-soccer-opposite-flip", "Player B"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Will Inter Miami CF win on 2026-05-03?",
            outcome=player,
            event_slug="mls-inter-miami-opposite-flip-2026-05-03",
            event_title="Inter Miami CF vs Atlanta United FC",
            condition_id="condition-opposite-flip",
        )
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-soccer-opposite-one", price=0.40, notional=10000.0)) == "processed"
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-soccer-opposite-flip", price=0.40, notional=10600.0)) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-soccer-opposite-one", "asset-soccer-opposite-flip"}
    assert positions["asset-soccer-opposite-one"]["cost_basis_usdc"] == 5.0
    assert positions["asset-soccer-opposite-flip"]["cost_basis_usdc"] == 3.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert "filter_copy_opposite_rank_flip_blocked" not in summary


def test_rn1_filter_copy_wta_allows_dominant_leg_and_blocks_weak_secondary(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    for asset_id, player in (
        ("asset-wta-rank-one", "Player A"),
        ("asset-wta-rank-two", "Player B"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=f"WTA: {player} vs Player C",
            outcome=player,
            event_slug="wta-player-a-player-b-2026-05-03",
            event_title="WTA Player A vs Player B",
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-rank-one", count=19, price=0.40, notional=350.0)
    assert engine.process_trade(source_trade("tx-1", asset_id="asset-wta-rank-one", price=0.40, notional=350.0)) == "processed"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-rank-two", count=19, price=0.40, notional=100.0)
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-wta-rank-two", price=0.40, notional=100.0)) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-wta-rank-one"}
    assert positions["asset-wta-rank-one"]["cost_basis_usdc"] == 3.5
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_tennis_rank_blocked"] == 1


def test_rn1_filter_copy_wta_repair_lane_can_follow_event_book(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    for asset_id, player in (
        ("asset-wta-repair-initial", "Player A"),
        ("asset-wta-repair-rank-one", "Player B"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=f"WTA: {player} vs Player C",
            outcome=player,
            event_slug="wta-player-a-player-b-repair-2026-05-05",
            event_title="WTA Player A vs Player B",
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.75 if asset_id == "asset-wta-repair-rank-one" else 0.40,
    )

    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-repair-initial", count=19, price=0.40, notional=600.0)
    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-wta-repair-initial", price=0.40, notional=600.0, block_number=100)
    ) == "processed"
    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-repair-rank-one", count=19, price=0.75, notional=1000.0)
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-wta-repair-rank-one", price=0.75, notional=1000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-wta-repair-initial"]["cost_basis_usdc"] == 6.0
    assert positions["asset-wta-repair-rank-one"]["cost_basis_usdc"] == 1.714286


def test_swisstony_filter_copy_accepts_event_book_sports_and_waits_for_conviction(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.50)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.539, notional=3000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.540, notional=3000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-3", wallet=SWISSTONY, asset_id="asset-nba-main", price=0.40, notional=1500.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-4", wallet=SWISSTONY, asset_id="asset-soccer-btts", price=0.40, notional=1500.0)
    ) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-soccer-main", "asset-soccer-main-2"}
    assert positions["asset-soccer-main"]["cost_basis_usdc"] == 3.0
    assert positions["asset-soccer-main-2"]["cost_basis_usdc"] == 3.0


def test_swisstony_probe_profile_records_source_flow_without_copying_buys(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY, enable_swisstony_copy=False)
    profile = store.get_wallet(SWISSTONY)["profile_json"]
    profile.setdefault("strategy", {})["copy_buys_enabled"] = False
    store.update_wallet(SWISSTONY, profile_json=profile)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "skipped"

    assert store.list_positions() == []
    assert store.source_position_summary(source_wallet=SWISSTONY, asset_id="asset-soccer-main")["buy_count"] == 1
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["copy_buys_disabled"] == 1


def test_swisstony_filter_copy_uses_cumulative_conviction_instead_of_single_fill_size(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=1000.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=1000.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-3", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=1000.0)
    ) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 3.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_waiting_for_source_position"] == 2


def test_swisstony_filter_copy_blocks_mlb_moneyline_event_book(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-diamondbacks-cubs-2026-05-05",
        event_title="MLB: Arizona Diamondbacks vs Chicago Cubs",
        markets=[
            ("asset-swisstony-mlb-rank-one", "MLB: Arizona Diamondbacks vs Chicago Cubs", "Chicago Cubs"),
            ("asset-swisstony-mlb-secondary", "MLB: Arizona Diamondbacks vs Chicago Cubs", "Arizona Diamondbacks"),
        ],
    )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-mlb-rank-one", count=9, price=0.70, notional=300.0)
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-mlb-secondary", count=2, price=0.30, notional=250.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.70,
    )

    assert engine.process_trade(
        source_trade("tx-10", wallet=SWISSTONY, asset_id="asset-swisstony-mlb-rank-one", price=0.70, notional=300.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_swisstony_filter_copy_allows_tiny_trigger_after_cumulative_conviction(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _upsert_same_event_markets(
        store,
        event_slug="epl-tiny-trigger-2026-05-05",
        event_title="Chelsea FC vs Arsenal FC",
        markets=[
            ("asset-swisstony-soccer-rank-one", "Will Chelsea FC win on 2026-05-05?", "Yes"),
            ("asset-swisstony-soccer-secondary", "Will Arsenal FC win on 2026-05-05?", "Yes"),
        ],
    )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-soccer-rank-one", count=9, price=0.40, notional=400.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    assert engine.process_trade(
        source_trade("tx-10", wallet=SWISSTONY, asset_id="asset-swisstony-soccer-rank-one", price=0.40, notional=25.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert round(positions["asset-swisstony-soccer-rank-one"]["cost_basis_usdc"], 3) == 3.625


def test_swisstony_filter_copy_applies_soccer_local_price_band(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _upsert_same_event_markets(
        store,
        event_slug="epl-local-price-2026-05-05",
        event_title="Chelsea FC vs Arsenal FC",
        markets=[
            ("asset-swisstony-soccer-rank-one", "Will Chelsea FC win on 2026-05-05?", "Yes"),
            ("asset-swisstony-soccer-secondary", "Will Arsenal FC win on 2026-05-05?", "Yes"),
        ],
    )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-soccer-rank-one", count=9, price=0.50, notional=400.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.70)

    assert engine.process_trade(
        source_trade("tx-10", wallet=SWISSTONY, asset_id="asset-swisstony-soccer-rank-one", price=0.50, notional=400.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_local_price_blocked"] == 1


def test_swisstony_filter_copy_blocks_wta_initial_entries(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    store.upsert_market_metadata(
        asset_id="asset-swisstony-wta-rank-one",
        market_type="sports",
        title="WTA: Player A vs Player B",
        outcome="Player A",
        event_slug="wta-player-a-player-b-2026-05-05",
        event_title="WTA Player A vs Player B",
    )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-wta-rank-one", count=10, price=0.70, notional=400.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.70)

    assert engine.process_trade(
        source_trade("tx-11", wallet=SWISSTONY, asset_id="asset-swisstony-wta-rank-one", price=0.70, notional=400.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_swisstony_filter_copy_blocks_secondary_tennis_event_book_leg(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _upsert_same_event_markets(
        store,
        event_slug="wta-player-a-player-b-secondary-2026-05-05",
        event_title="WTA Player A vs Player B",
        markets=[
            ("asset-swisstony-wta-secondary", "WTA: Player A vs Player B", "Player A"),
            ("asset-swisstony-wta-dominant", "WTA: Player A vs Player B", "Player B"),
        ],
    )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-wta-secondary", count=9, price=0.70, notional=350.0)
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-wta-dominant", count=10, price=0.45, notional=700.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.45 if asset_id == "asset-swisstony-wta-dominant" else 0.70,
    )

    assert engine.process_trade(
        source_trade("tx-10", wallet=SWISSTONY, asset_id="asset-swisstony-wta-secondary", price=0.70, notional=350.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_swisstony_filter_copy_blocks_atp_wta_initial_lanes(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title, outcome in (
        ("asset-swisstony-wta-too-cheap", "WTA: Player C vs Player D", "Player C"),
        ("asset-swisstony-wta-normal", "WTA: Player E vs Player F", "Player E"),
        ("asset-swisstony-atp-normal", "ATP: Player G vs Player H", "Player G"),
        ("asset-swisstony-atp-high", "ATP: Player I vs Player J", "Player I"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome=outcome,
            event_slug=f"{asset_id}-event",
            event_title=title,
        )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-wta-too-cheap", count=9, price=0.40, notional=400.0)
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-wta-normal", count=9, price=0.70, notional=400.0)
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-atp-normal", count=9, price=0.50, notional=400.0)
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-atp-high", count=9, price=0.70, notional=400.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: {
            "asset-swisstony-wta-too-cheap": 0.40,
            "asset-swisstony-wta-normal": 0.70,
            "asset-swisstony-atp-normal": 0.50,
            "asset-swisstony-atp-high": 0.70,
        }[asset_id],
    )

    assert engine.process_trade(
        source_trade("tx-10", wallet=SWISSTONY, asset_id="asset-swisstony-wta-too-cheap", price=0.40, notional=400.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-11", wallet=SWISSTONY, asset_id="asset-swisstony-wta-normal", price=0.70, notional=400.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-12", wallet=SWISSTONY, asset_id="asset-swisstony-atp-normal", price=0.50, notional=400.0)
    ) == "skipped"
    assert engine.process_trade(
        source_trade("tx-13", wallet=SWISSTONY, asset_id="asset-swisstony-atp-high", price=0.70, notional=400.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 4


def test_swisstony_filter_copy_blocks_nhl_initial_entries(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    store.upsert_market_metadata(
        asset_id="asset-swisstony-nhl-rank-one",
        market_type="sports",
        title="NHL: Edmonton Oilers vs Dallas Stars",
        outcome="Edmonton Oilers",
        event_slug="nhl-oilers-stars-2026-05-05",
        event_title="NHL Edmonton Oilers vs Dallas Stars",
    )
    _seed_source_buys(store, wallet=SWISSTONY, asset_id="asset-swisstony-nhl-rank-one", count=9, price=0.70, notional=400.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.70)

    assert engine.process_trade(
        source_trade("tx-10", wallet=SWISSTONY, asset_id="asset-swisstony-nhl-rank-one", price=0.70, notional=400.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_filter_copy_uses_cumulative_avg_when_late_fill_crosses_conviction(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.42)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-nba-main", price=0.40, notional=2900.0)) == "skipped"
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-nba-main", price=0.90, notional=100.0)) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-nba-main"
    assert position["cost_basis_usdc"] == 1.5
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_waiting_for_source_position"] == 1
    assert "filter_copy_price_blocked" not in summary


def test_filter_copy_still_blocks_conviction_when_executable_price_runs_too_far(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.90)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-nba-main", price=0.40, notional=2900.0)) == "skipped"
    assert engine.process_trade(source_trade("tx-2", asset_id="asset-nba-main", price=0.90, notional=100.0)) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_waiting_for_source_position"] == 1
    assert summary["filter_copy_local_price_blocked"] == 1


def test_filter_copy_uses_persisted_source_position_size_to_accumulate_conviction(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    settings = _settings(tmp_path, RN1)
    prior = source_trade("tx-1", asset_id="asset-mlb-main", price=0.40, notional=4500.0, block_number=99)
    assert store.insert_source_trade(prior) is True
    engine = CopyTradingEngine(config=settings, store=store, buy_price_resolver=lambda asset_id: 0.40)

    result = engine.process_trade(source_trade("tx-2", asset_id="asset-mlb-main", price=0.40, notional=500.0))

    assert result == "processed"
    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-mlb-main"
    assert position["cost_basis_usdc"] == 2.5


def test_filter_copy_uses_full_source_position_not_recent_window_for_conviction(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    prior = source_trade(
        "tx-1",
        asset_id="asset-mlb-main",
        price=0.40,
        notional=4500.0,
        block_number=99,
        block_timestamp="2026-05-03 11:58 PDT",
    )
    assert store.insert_source_trade(prior) is True
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    result = engine.process_trade(
        source_trade(
            "tx-2",
            asset_id="asset-mlb-main",
            price=0.40,
            notional=500.0,
            block_number=100,
            block_timestamp="2026-05-03 12:00 PDT",
        )
    )

    assert result == "processed"
    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-mlb-main"
    assert position["cost_basis_usdc"] == 2.5


def test_swisstony_filter_copy_sizes_first_entry_to_source_scale(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=12000.0)
    ) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 5.0


def test_filter_copy_enforces_local_price_band_for_clean_soccer(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.90)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.46, notional=3000.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_local_price_blocked"] == 1


def test_rn1_filter_copy_uses_source_scale_event_book_sizing(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-soccer-main", price=0.40, notional=21172.0)
    ) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 10.586


def test_filter_copy_skips_small_incremental_event_book_top_ups(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=1500.0, block_number=101)
    ) == "skipped"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 3.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_top_up_below_min"] == 1


def test_rn1_filter_copy_caps_main_winner_at_event_book_cap(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-soccer-main", price=0.40, notional=100000.0)
    ) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 50.0


def test_filter_copy_uses_wallet_cap_not_global_sizing_cap(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1, max_position_usdc=3),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-soccer-main", price=0.40, notional=100000.0)
    ) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 50.0


def test_rn1_filter_copy_uses_event_book_cap_for_tennis_and_esports(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _unpause_rn1_tennis(store)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    _seed_source_buys(store, wallet=RN1, asset_id="asset-wta-main", count=19, price=0.40, notional=5000.0)
    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-wta-main", price=0.40, notional=5000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-cs2-main", price=0.40, notional=100000.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-wta-main", "asset-cs2-main"}
    assert positions["asset-wta-main"]["cost_basis_usdc"] == 50.0
    assert positions["asset-cs2-main"]["cost_basis_usdc"] == 50.0


def test_filter_copy_cumulative_source_size_is_net_of_prior_source_sells(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    prior_buy = source_trade("tx-1", asset_id="asset-mlb-main", price=0.40, notional=3000.0, block_number=98)
    prior_sell = source_trade(
        "tx-2",
        asset_id="asset-mlb-main",
        price=0.40,
        notional=3000.0,
        side="sell",
        block_number=99,
    )
    assert store.insert_source_trade(prior_buy) is True
    assert store.insert_source_trade(prior_sell) is True
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    result = engine.process_trade(source_trade("tx-3", asset_id="asset-mlb-main", price=0.40, notional=500.0, block_number=100))

    assert result == "skipped"
    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_waiting_for_source_position"] == 1


def test_filter_copy_reconciles_missed_dominant_event_leg_from_later_same_event_fill(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
            market_close_time="2026-05-04 07:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    assert store.insert_source_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=5000.0, block_number=99)
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-soccer-main" else 0.46,
    )

    result = engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.46, notional=500.0, block_number=100)
    )

    assert result == "processed"
    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-soccer-main"}
    assert positions["asset-soccer-main"]["cost_basis_usdc"] == 5.0


def test_filter_copy_reconcile_sizes_missed_leg_to_conviction_target(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
            market_close_time="2026-05-04 07:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    assert store.insert_source_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=12000.0, block_number=99)
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-soccer-main" else 0.46,
    )

    result = engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.46, notional=500.0, block_number=100)
    )

    assert result == "processed"
    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 5.0


def test_filter_copy_does_not_scale_into_same_open_asset(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.39, notional=200.0)
    ) == "skipped"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 3.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_scale_target_met"] == 1


def test_swisstony_filter_copy_scales_same_asset_to_source_book_size(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.39, notional=3000.0)
    ) == "skipped"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 3.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_top_up_below_min"] == 1


def test_swisstony_filter_copy_large_source_add_scales_to_source_book_target(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.39, notional=15000.0)
    ) == "skipped"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-soccer-main"
    assert position["cost_basis_usdc"] == 3.0


def test_filter_copy_allows_both_source_wallets_to_copy_same_asset(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    store.sync_wallets(_settings(tmp_path, SWISSTONY).wallets)
    _enable_copy_buys(store, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.35)

    assert engine.process_trade(source_trade("tx-1", wallet=RN1, asset_id="asset-soccer-main", price=0.35, notional=10000.0)) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.35, notional=3000.0)
    ) == "processed"

    positions = sorted(store.list_positions(), key=lambda row: row["source_wallet"])
    assert [(position["source_wallet"], position["asset_id"], position["cost_basis_usdc"]) for position in positions] == [
        (RN1, "asset-soccer-main", 5.0),
        (SWISSTONY, "asset-soccer-main", 3.0),
    ]


def test_filter_copy_enforces_daily_deployed_cap_per_wallet(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    settings = _settings(tmp_path, RN1)
    engine = CopyTradingEngine(config=settings, store=store, buy_price_resolver=lambda asset_id: 0.30)

    for index in range(1, 7):
        assert engine.process_trade(
            source_trade(f"tx-{index}", asset_id=f"asset-nba-main-{index}", price=0.30, notional=30000.0)
        ) == "processed"
    assert engine.process_trade(source_trade("tx-7", asset_id="asset-nba-main-7", price=0.30, notional=30000.0)) == "skipped"

    assert round(sum(position["cost_basis_usdc"] for position in store.list_positions()), 6) == 90.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_daily_cap"] == 1


def test_filter_copy_daily_deployed_cap_reuses_closed_capacity(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    settings = _settings(tmp_path, RN1)
    engine = CopyTradingEngine(config=settings, store=store, buy_price_resolver=lambda asset_id: 0.30)

    for index in range(1, 7):
        asset_id = f"asset-nba-main-{index}"
        assert engine.process_trade(
            source_trade(f"tx-{index}", asset_id=asset_id, price=0.30, notional=30000.0)
        ) == "processed"
        assert engine.process_trade(
            source_trade(
                f"sell-{index}",
                asset_id=asset_id,
                price=0.30,
                notional=30000.0,
                side="sell",
                block_number=200 + index,
            )
        ) == "processed"

    assert store.open_cost_basis_for_wallet(RN1) == 0.0
    assert engine.process_trade(source_trade("tx-7", asset_id="asset-nba-main-7", price=0.30, notional=30000.0)) == "processed"

    positions = store.list_positions()
    assert len(positions) == 1
    assert positions[0]["asset_id"] == "asset-nba-main-7"
    assert positions[0]["cost_basis_usdc"] == 15.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert "filter_copy_daily_cap" not in summary


def test_filter_copy_daily_deployed_cap_credits_near_resolved_winners(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    settings = _settings(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=settings, store=store, buy_price_resolver=lambda asset_id: 0.30)

    for index in range(1, 7):
        asset_id = f"asset-nba-main-{index}"
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title=f"Will Soccer Team {index} win on 2026-05-11?",
            outcome="Yes",
            event_slug=f"soccer-team-{index}-2026-05-11",
            event_title=f"Soccer Team {index}",
        )
        _seed_source_buys(store, wallet=SWISSTONY, asset_id=asset_id, count=9, price=0.30, notional=3000.0)
        assert engine.process_trade(
            source_trade(f"tx-{index}", wallet=SWISSTONY, asset_id=asset_id, price=0.30, notional=30000.0)
        ) == "processed"
        store.upsert_market_metadata(
            asset_id=asset_id,
            current_price=0.999,
            price_source="clob_ws_price_change",
            is_closed=False,
            resolution_price=None,
        )

    store.upsert_market_metadata(
        asset_id="asset-swisstony-fresh-soccer",
        market_type="sports",
        sport_key="soccer",
        bet_type="moneyline_winlose",
        title="Will Fresh FC win on 2026-05-11?",
        outcome="No",
        event_slug="fresh-fc-2026-05-11",
        event_title="Fresh FC",
    )
    _seed_source_buys(
        store,
        wallet=SWISSTONY,
        asset_id="asset-swisstony-fresh-soccer",
        count=9,
        price=0.30,
        notional=3000.0,
    )

    assert engine.process_trade(
        source_trade("tx-7", wallet=SWISSTONY, asset_id="asset-swisstony-fresh-soccer", price=0.30, notional=30000.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-swisstony-fresh-soccer"]["cost_basis_usdc"] == 5.0
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert "filter_copy_daily_cap" not in summary


def test_rn1_filter_copy_rebalance_allows_high_price_rank_one_repair_over_gross_event_cap(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    for asset_id, outcome in (
        ("asset-nba-repair-initial", "Cavaliers"),
        ("asset-nba-repair-rank-one", "Pistons"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Cavaliers vs. Pistons",
            outcome=outcome,
            event_slug="nba-cle-det-repair-2026-05-05",
            event_title="Cavaliers vs. Pistons",
            market_close_time="2099-05-05 16:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.75 if asset_id == "asset-nba-repair-rank-one" else 0.40,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-nba-repair-initial", price=0.40, notional=12000.0, block_number=99)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-nba-repair-rank-one", price=0.75, notional=15000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-nba-repair-initial"]["cost_basis_usdc"] == 6.0
    assert positions["asset-nba-repair-rank-one"]["cost_basis_usdc"] == 3.0


def test_rn1_filter_copy_rebalance_uses_source_position_snapshot_floor_for_repair_sizing(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    for asset_id, outcome in (
        ("asset-nba-repair-initial", "Cavaliers"),
        ("asset-nba-repair-rank-one", "Pistons"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Cavaliers vs. Pistons",
            outcome=outcome,
            event_slug="nba-cle-det-repair-2026-05-05",
            event_title="Cavaliers vs. Pistons",
            market_close_time="2099-05-05 16:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )

    snapshots = {
        (RN1, "asset-nba-repair-rank-one"): {
            "net_notional_usdc": 15000.0,
            "avg_buy_price": 0.75,
            "source": "data_api_positions",
        },
    }
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.75 if asset_id == "asset-nba-repair-rank-one" else 0.40,
        source_position_resolver=lambda wallet, asset_id: snapshots.get((wallet, asset_id)),
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-nba-repair-initial", price=0.40, notional=12000.0, block_number=99)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-nba-repair-rank-one", price=0.75, notional=500.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-nba-repair-initial"]["cost_basis_usdc"] == 6.0
    assert positions["asset-nba-repair-rank-one"]["cost_basis_usdc"] == 3.0


def test_filter_copy_high_price_event_book_entry_uses_source_scale_without_existing_same_event_position(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    store.upsert_market_metadata(
        asset_id="asset-nba-repair-rank-one",
        market_type="sports",
        title="Cavaliers vs. Pistons",
        outcome="Pistons",
        event_slug="nba-cle-det-repair-2026-05-05",
        event_title="Cavaliers vs. Pistons",
        market_close_time="2099-05-05 16:00 PDT",
        market_close_time_kind="event_start",
        is_closed=False,
        resolution_price=None,
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.75)

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-nba-repair-rank-one", price=0.75, notional=15000.0)
    ) == "processed"

    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-nba-repair-rank-one"
    assert position["cost_basis_usdc"] == 7.5


def test_swisstony_filter_copy_rebalance_allows_high_price_dominant_soccer_repair(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, outcome in (
        ("asset-soccer-repair-initial", "No"),
        ("asset-soccer-repair-rank-one", "Yes"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Will Arsenal FC win on 2026-05-05?",
            outcome=outcome,
            event_slug="ucl-ars-atm-repair-2026-05-05",
            event_title="Arsenal FC vs Club Atletico de Madrid",
            market_close_time="2099-05-05 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.82 if asset_id == "asset-soccer-repair-rank-one" else 0.40,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-repair-initial", price=0.40, notional=3000.0, block_number=99)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-repair-rank-one", price=0.82, notional=6000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-soccer-repair-initial"]["cost_basis_usdc"] == 3.0
    assert positions["asset-soccer-repair-rank-one"]["cost_basis_usdc"] == 4.666667


def test_swisstony_filter_copy_targets_event_book_source_scale(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    event_slug = "epl-source-book-2026-05-08"
    for asset_id, outcome in (
        ("asset-book-yes", "Yes"),
        ("asset-book-no", "No"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title="Will Arsenal FC win on 2026-05-08?",
            outcome=outcome,
            event_slug=event_slug,
            event_title="Arsenal FC vs Chelsea FC",
            market_close_time="2099-05-08 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-book-yes" else 0.78,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-book-yes", price=0.40, notional=30000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-book-no", price=0.78, notional=15000.0, block_number=101)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-book-yes"]["cost_basis_usdc"] == 5.0
    assert positions["asset-book-no"]["cost_basis_usdc"] == 2.333333


def test_event_book_planner_integration_copies_scaled_event_book_shape(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _enable_event_book_planner(store, SWISSTONY)
    event_slug = "epl-planner-shape-2026-05-12"
    for asset_id, outcome in (
        ("asset-planner-yes", "Yes"),
        ("asset-planner-no", "No"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title="Will Arsenal FC win on 2026-05-12?",
            outcome=outcome,
            event_slug=event_slug,
            event_title="Arsenal FC vs Chelsea FC",
            market_close_time="2099-05-12 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    assert store.insert_source_trade(
        source_trade("tx-seed-1", wallet=SWISSTONY, asset_id="asset-planner-yes", price=0.55, notional=30000.0, block_number=90)
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-planner-no" else 0.55,
    )

    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-planner-no", price=0.40, notional=60000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert round(positions["asset-planner-no"]["cost_basis_usdc"], 3) == 3.333
    assert round(positions["asset-planner-yes"]["cost_basis_usdc"], 3) == 1.667


def test_rn1_event_book_planner_fresh_entry_only_copies_dominant_main_winner(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _enable_event_book_planner(store, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-planner-main-winner-2026-05-13",
        event_title="Tampa Bay Rays vs Toronto Blue Jays",
        markets=[
            ("asset-planner-bluejays", "Tampa Bay Rays vs. Toronto Blue Jays", "Toronto Blue Jays"),
            ("asset-planner-rays", "Tampa Bay Rays vs. Toronto Blue Jays", "Tampa Bay Rays"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-planner-rays", count=1, price=0.40, notional=4000.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.46 if asset_id == "asset-planner-bluejays" else 0.40,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-planner-bluejays", price=0.46, notional=9000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-planner-bluejays"}
    assert round(positions["asset-planner-bluejays"]["cost_basis_usdc"], 3) == 6.708


def test_rn1_event_book_planner_allows_large_executable_price_drift_after_shape_decision(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _enable_event_book_planner(store, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-planner-price-drift-2026-05-13",
        event_title="Tampa Bay Rays vs Toronto Blue Jays",
        markets=[
            ("asset-planner-drift-bluejays", "Tampa Bay Rays vs. Toronto Blue Jays", "Toronto Blue Jays"),
            ("asset-planner-drift-rays", "Tampa Bay Rays vs. Toronto Blue Jays", "Tampa Bay Rays"),
        ],
    )
    _seed_source_buys(store, wallet=RN1, asset_id="asset-planner-drift-rays", count=1, price=0.40, notional=4000.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.84 if asset_id == "asset-planner-drift-bluejays" else 0.40,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-planner-drift-bluejays", price=0.46, notional=9000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-planner-drift-bluejays"}
    assert round(positions["asset-planner-drift-bluejays"]["cost_basis_usdc"], 3) == 6.708


def test_rn1_event_book_planner_blocks_derivative_rebalance(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _enable_event_book_planner(store, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-planner-derivative-2026-05-13",
        event_title="Chicago Cubs vs Atlanta Braves",
        markets=[
            ("asset-planner-cubs", "Chicago Cubs vs. Atlanta Braves", "Chicago Cubs"),
            ("asset-planner-total", "Chicago Cubs vs. Atlanta Braves: O/U 5.5", "Over"),
        ],
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.50 if asset_id == "asset-planner-cubs" else 0.42,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-planner-cubs", price=0.50, notional=12000.0, block_number=100)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-planner-total", price=0.42, notional=6000.0, block_number=101)
    ) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-planner-cubs"}
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_rn1_event_book_planner_blocks_fresh_books_with_more_than_three_source_legs(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    _enable_event_book_planner(store, RN1)
    _upsert_same_event_markets(
        store,
        event_slug="mlb-planner-complex-book-2026-05-13",
        event_title="Tampa Bay Rays vs Toronto Blue Jays",
        markets=[
            ("asset-complex-rays", "Tampa Bay Rays vs. Toronto Blue Jays", "Tampa Bay Rays"),
            ("asset-complex-bluejays", "Tampa Bay Rays vs. Toronto Blue Jays", "Toronto Blue Jays"),
            ("asset-complex-total-over", "Tampa Bay Rays vs. Toronto Blue Jays: O/U 7.5", "Over"),
            ("asset-complex-total-under", "Tampa Bay Rays vs. Toronto Blue Jays: O/U 7.5", "Under"),
        ],
    )
    for asset_id in (
        "asset-complex-rays",
        "asset-complex-bluejays",
        "asset-complex-total-over",
        "asset-complex-total-under",
    ):
        _seed_source_buys(store, wallet=RN1, asset_id=asset_id, count=1, price=0.40, notional=4000.0)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-complex-rays", price=0.40, notional=4000.0, block_number=100)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["rn1_event_book_too_complex"] == 1


def test_event_book_planner_integration_uses_reserve_for_high_price_rebalance(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _enable_event_book_planner(store, SWISSTONY)
    event_slug = "epl-planner-rebalance-2026-05-12"
    for asset_id, outcome in (
        ("asset-planner-anchor", "No"),
        ("asset-planner-hedge", "Yes"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title="Will Arsenal FC win on 2026-05-12?",
            outcome=outcome,
            event_slug=event_slug,
            event_title="Arsenal FC vs Chelsea FC",
            market_close_time="2099-05-12 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-planner-anchor" else 0.90,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-planner-anchor", price=0.40, notional=50000.0, block_number=99)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-planner-hedge", price=0.90, notional=10000.0, block_number=100)
    ) == "skipped"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-planner-anchor"]["cost_basis_usdc"] == 5.0
    assert "asset-planner-hedge" not in positions


def test_event_book_planner_integration_swisstony_blocks_weak_fresh_event(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    _enable_event_book_planner(store, SWISSTONY)
    event_slug = "epl-planner-quality-2026-05-12"
    for asset_id, outcome in (
        ("asset-quality-yes", "Yes"),
        ("asset-quality-no", "No"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title="Will Arsenal FC win on 2026-05-12?",
            outcome=outcome,
            event_slug=event_slug,
            event_title="Arsenal FC vs Chelsea FC",
            market_close_time="2099-05-12 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
    )
    assert store.insert_source_trade(
        source_trade("tx-quality-90", wallet=SWISSTONY, asset_id="asset-quality-yes", price=0.55, notional=30000.0, block_number=90)
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-quality-no" else 0.55,
    )

    assert engine.process_trade(
        source_trade("tx-quality-100", wallet=SWISSTONY, asset_id="asset-quality-no", price=0.40, notional=9000.0, block_number=100)
    ) == "skipped"
    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["swisstony_event_book_fresh_quality_gate"] == 1

    assert engine.process_trade(
        source_trade("tx-quality-101", wallet=SWISSTONY, asset_id="asset-quality-no", price=0.40, notional=2000.0, block_number=101)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert round(positions["asset-quality-yes"]["cost_basis_usdc"], 3) == 3.659
    assert round(positions["asset-quality-no"]["cost_basis_usdc"], 3) == 1.341


def test_filter_copy_event_book_prioritizes_underweight_companion_legs_when_cash_limited(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    event_slug = "epl-limited-source-book-2026-05-12"
    for asset_id, outcome in (
        ("asset-limited-no", "No"),
        ("asset-limited-yes", "Yes"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title="Will Arsenal FC win on 2026-05-12?",
            outcome=outcome,
            event_slug=event_slug,
            event_title="Arsenal FC vs Chelsea FC",
            market_close_time="2099-05-12 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    assert store.insert_source_trade(
        source_trade("tx-seed-1", wallet=SWISSTONY, asset_id="asset-limited-yes", price=0.55, notional=30000.0, block_number=90)
    )
    store.set_runtime_state("paper_cash_usdc", "40")
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-limited-no" else 0.55,
    )

    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-limited-no", price=0.40, notional=60000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-limited-yes"]["cost_basis_usdc"] == 5.0
    assert positions["asset-limited-no"]["cost_basis_usdc"] == 4.666667


def test_swisstony_filter_copy_allows_draw_no_as_event_book_repair_leg(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    event_slug = "epl-ars-che-repair-2026-05-12"
    markets = (
        ("asset-main-no", "Will Arsenal FC win on 2026-05-12?", "No", "moneyline_winlose"),
        ("asset-draw-no", "Will Arsenal FC vs. Chelsea FC end in a draw?", "No", "draw"),
    )
    for asset_id, title, outcome, bet_type in markets:
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type=bet_type,
            title=title,
            outcome=outcome,
            event_slug=event_slug,
            event_title="Arsenal FC vs Chelsea FC",
            market_close_time="2099-05-12 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-main-no" else 0.75,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-main-no", price=0.40, notional=30000.0, block_number=99)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-draw-no", price=0.75, notional=10000.0, block_number=100)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-main-no", "asset-draw-no"}
    assert positions["asset-main-no"]["cost_basis_usdc"] == 5.0
    assert positions["asset-draw-no"]["cost_basis_usdc"] == 1.75


def test_filter_copy_event_book_repair_bypasses_opposite_rank_flip_when_source_book_changes(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    event_slug = "epl-source-book-flip-2026-05-08"
    for asset_id, outcome in (
        ("asset-flip-yes", "Yes"),
        ("asset-flip-no", "No"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            sport_key="soccer",
            bet_type="moneyline_winlose",
            title="Will Chelsea FC win on 2026-05-08?",
            outcome=outcome,
            event_slug=event_slug,
            event_title="Chelsea FC vs Arsenal FC",
            market_close_time="2099-05-08 12:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-flip-yes" else 0.79,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-flip-yes", price=0.40, notional=30000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-flip-no", price=0.79, notional=31000.0, block_number=101)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-flip-yes"]["cost_basis_usdc"] == 5.0
    assert positions["asset-flip-no"]["cost_basis_usdc"] == 3.557377
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert "filter_copy_opposite_rank_flip_blocked" not in summary


def test_swisstony_filter_copy_blocks_structured_totals_after_moneyline_only_policy(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    store.upsert_market_metadata(
        asset_id="asset-total-over",
        market_type="sports",
        sport_key="soccer",
        bet_type="total_or_over_under",
        title="Arsenal FC vs. Chelsea FC: Over/Under 2.5 goals",
        outcome="Over",
        event_slug="epl-total-book-2026-05-08",
        event_title="Arsenal FC vs Chelsea FC",
        market_close_time="2099-05-08 12:00 PDT",
        market_close_time_kind="event_start",
        is_closed=False,
        resolution_price=None,
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.42)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-total-over", price=0.42, notional=5000.0)
    ) == "skipped"

    assert store.list_positions() == []
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_market_blocked"] == 1


def test_filter_copy_mirrors_partial_source_sell_for_event_book_position(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.50)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.50, notional=10000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.50, notional=1000.0, side="sell", block_number=101)
    ) == "processed"

    position = store.list_positions()[0]
    assert round(position["quantity"], 6) == 9.0
    sells = [trade for trade in store.list_trades() if trade["paper_side"] == "sell"]
    assert len(sells) == 1
    assert round(sells[0]["paper_notional_usdc"], 6) == 0.5


def test_filter_copy_sizes_same_event_hedge_by_source_exposure_ratio(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
            market_close_time="2099-05-04 07:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-soccer-main" else 0.46,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=10000.0)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.46, notional=1500.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-soccer-main"]["cost_basis_usdc"] == 5.0
    assert positions["asset-soccer-main-2"]["cost_basis_usdc"] == 1.0


def test_filter_copy_allows_fresh_in_play_conviction_entry(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    store.upsert_market_metadata(
        asset_id="asset-soccer-main",
        market_type="sports",
        title="Will Chelsea FC win on 2026-05-04?",
        outcome="No",
        event_slug="epl-che-not-2026-05-04",
        event_title="Chelsea FC vs Nottingham Forest FC",
        market_close_time="2020-05-04 07:00 PDT",
        market_close_time_kind="event_start",
        is_closed=False,
        resolution_price=None,
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-soccer-main"]["cost_basis_usdc"] == 3.0


def test_filter_copy_reconciles_secondary_source_event_book_leg_with_missed_dominant_copy(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
            market_close_time="2020-05-04 07:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    assert store.insert_source_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=10000.0)
    )
    engine = CopyTradingEngine(config=_settings(tmp_path, SWISSTONY), store=store, buy_price_resolver=lambda asset_id: 0.46)

    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.46, notional=3000.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-soccer-main", "asset-soccer-main-2"}
    assert positions["asset-soccer-main"]["cost_basis_usdc"] == 5.0
    assert positions["asset-soccer-main-2"]["cost_basis_usdc"] == 1.615385


def test_filter_copy_reconcile_does_not_execute_previously_skipped_source_fill(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
        )
    observed_prices = {"asset-soccer-main": 0.90, "asset-soccer-main-2": 0.40}
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: observed_prices[asset_id],
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=3000.0)
    ) == "skipped"
    observed_prices["asset-soccer-main"] = 0.40
    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.40, notional=3000.0, block_number=101)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert set(positions) == {"asset-soccer-main-2"}
    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["filter_copy_local_price_blocked"] == 1


def test_filter_copy_sizes_late_in_play_same_event_hedges_by_profile_fraction(tmp_path: Path) -> None:
    store = _store(tmp_path, SWISSTONY)
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
            market_close_time="2099-05-04 07:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, SWISSTONY),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40 if asset_id == "asset-soccer-main" else 0.46,
    )

    assert engine.process_trade(
        source_trade("tx-1", wallet=SWISSTONY, asset_id="asset-soccer-main", price=0.40, notional=10000.0)
    ) == "processed"
    for asset_id, title in (
        ("asset-soccer-main", "Will Chelsea FC win on 2026-05-04?"),
        ("asset-soccer-main-2", "Will Nottingham Forest FC win on 2026-05-04?"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome="No",
            event_slug="epl-che-not-2026-05-04",
            event_title="Chelsea FC vs Nottingham Forest FC",
            market_close_time="2020-05-04 07:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )

    assert engine.process_trade(
        source_trade("tx-2", wallet=SWISSTONY, asset_id="asset-soccer-main-2", price=0.46, notional=3000.0)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-soccer-main"]["cost_basis_usdc"] == 5.0
    assert positions["asset-soccer-main-2"]["cost_basis_usdc"] == 1.615385


def test_rn1_filter_copy_scales_same_event_hedge_after_source_conviction_builds(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    for asset_id, outcome in (
        ("asset-yunnan-yes", "Yes"),
        ("asset-yunnan-no", "No"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Will Yunnan Yukun FC win on 2026-05-06?",
            outcome=outcome,
            event_slug="chi-yun-zhe-2026-05-06",
            event_title="Yunnan Yukun FC vs Zhejiang Zhiye FC",
            market_close_time="2099-05-06 05:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1),
        store=store,
        buy_price_resolver=lambda asset_id: 0.53 if asset_id == "asset-yunnan-yes" else 0.39,
    )

    assert engine.process_trade(
        source_trade("tx-1", asset_id="asset-yunnan-yes", price=0.54, notional=10000.0, block_number=100)
    ) == "processed"
    for asset_id, outcome in (
        ("asset-yunnan-yes", "Yes"),
        ("asset-yunnan-no", "No"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title="Will Yunnan Yukun FC win on 2026-05-06?",
            outcome=outcome,
            event_slug="chi-yun-zhe-2026-05-06",
            event_title="Yunnan Yukun FC vs Zhejiang Zhiye FC",
            market_close_time="2020-05-06 05:00 PDT",
            market_close_time_kind="event_start",
            is_closed=False,
            resolution_price=None,
    )
    assert engine.process_trade(
        source_trade("tx-2", asset_id="asset-yunnan-no", price=0.34, notional=1200.0, block_number=101)
    ) == "processed"
    assert engine.process_trade(
        source_trade("tx-3", asset_id="asset-yunnan-no", price=0.38, notional=4400.0, block_number=102)
    ) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-yunnan-yes"]["cost_basis_usdc"] == 5.0
    assert round(positions["asset-yunnan-no"]["cost_basis_usdc"], 2) == 2.8


def test_filter_copy_holds_sports_winner_to_source_sell_or_settlement(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.36)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-soccer-main", price=0.36, notional=10000.0)) == "processed"
    store.upsert_market_metadata(
        asset_id="asset-soccer-main",
        market_type="sports",
        current_price=0.998,
        price_source="clob_ws_price_change",
        is_closed=False,
        resolution_price=None,
    )

    exits = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store).process_local_exits()

    assert exits == 0
    assert len(store.list_positions()) == 1
    assert not [trade for trade in store.list_trades() if trade["paper_side"] == "sell"]


def test_filter_copy_in_event_stop_loss_waits_before_event_start(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1, filter_copy_stop_loss_pct=35.0)
    engine = CopyTradingEngine(
        config=_settings(tmp_path, RN1, filter_copy_stop_loss_pct=35.0),
        store=store,
        buy_price_resolver=lambda asset_id: 0.40,
    )

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-soccer-main", price=0.40, notional=10000.0)) == "processed"
    store.upsert_market_metadata(
        asset_id="asset-soccer-main",
        market_type="sports",
        current_price=0.20,
        price_source="clob_ws_price_change",
        market_close_time="2099-05-03 12:00 PDT",
        market_close_time_kind="event_start",
        is_closed=False,
        resolution_price=None,
    )

    exits = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store).process_local_exits()

    assert exits == 0
    assert len(store.list_positions()) == 1


def test_filter_copy_holds_through_live_event_drawdown(tmp_path: Path) -> None:
    store = _store(tmp_path, RN1)
    engine = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store, buy_price_resolver=lambda asset_id: 0.40)

    assert engine.process_trade(source_trade("tx-1", asset_id="asset-soccer-main", price=0.40, notional=10000.0)) == "processed"
    store.upsert_market_metadata(
        asset_id="asset-soccer-main",
        market_type="sports",
        current_price=0.25,
        price_source="clob_ws_price_change",
        market_close_time="2020-05-03 12:00 PDT",
        market_close_time_kind="event_start",
        is_closed=False,
        resolution_price=None,
    )

    exits = CopyTradingEngine(config=_settings(tmp_path, RN1), store=store).process_local_exits()

    assert exits == 0
    assert len(store.list_positions()) == 1
    assert not [trade for trade in store.list_trades() if trade["paper_side"] == "sell"]


def _store(
    tmp_path: Path,
    wallet: str,
    *,
    filter_copy_stop_loss_pct: float | None = None,
    enable_rn1_planner: bool = False,
    enable_swisstony_copy: bool = True,
) -> Store:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(_settings(tmp_path, wallet, filter_copy_stop_loss_pct=filter_copy_stop_loss_pct).wallets)
    if wallet.lower() == RN1.lower() and not enable_rn1_planner:
        profile = store.get_wallet(wallet)["profile_json"]
        profile.setdefault("event_book", {})["planner_enabled"] = False
        store.update_wallet(wallet, profile_json=profile)
    if wallet.lower() == SWISSTONY.lower():
        profile = store.get_wallet(wallet)["profile_json"]
        profile.setdefault("event_book", {})["planner_enabled"] = False
        store.update_wallet(wallet, profile_json=profile)
    if enable_swisstony_copy and wallet.lower() == SWISSTONY.lower():
        _enable_copy_buys(store, wallet)
    metadata = {
        "asset-nba-main": ("sports", "Will Detroit Pistons win on 2026-05-03?", "Detroit Pistons", "NBA"),
        "asset-nba-expensive": ("sports", "Will Orlando Magic win on 2026-05-03?", "Orlando Magic", "NBA"),
        "asset-nba-total": ("sports", "Detroit Pistons vs. Orlando Magic: O/U 218.5", "Over", "NBA"),
        "asset-soccer-draw": ("sports", "Will San Diego FC vs. LA Galaxy end in a draw?", "Yes", "MLS"),
        "asset-tennis-main": ("sports", "Madrid Open: Yuan Yue vs Anna Blinkova", "Yuan Yue", "Tennis"),
        "asset-wta-main": ("sports", "WTA: Yuan Yue vs Anna Blinkova", "Yuan Yue", "WTA Tennis"),
        "asset-atp-main": ("sports", "ATP: Holger Rune vs Casper Ruud", "Holger Rune", "ATP Tennis"),
        "asset-cs2-main": ("sports", "CS2: G2 vs FaZe", "G2", "CS2"),
        "asset-cs2-map": ("sports", "CS2: G2 vs FaZe map 1 winner", "G2", "CS2"),
        "asset-soccer-main": ("sports", "Will San Diego FC win on 2026-05-03?", "No", "MLS"),
        "asset-soccer-main-2": ("sports", "Will Arsenal FC win on 2026-05-03?", "Yes", "UCL"),
        "asset-soccer-btts": ("sports", "Arsenal FC vs. PSG: Both Teams to Score", "No", "UCL"),
        "asset-mlb-main": ("sports", "Will Texas Rangers win on 2026-05-03?", "Yes", "MLB"),
    }
    for index in range(1, 18):
        metadata[f"asset-nba-main-{index}"] = (
            "sports",
            f"Will NBA Team {index} win on 2026-05-03?",
            "Yes",
            "NBA",
        )
    for asset_id, (market_type, title, outcome, event_title) in metadata.items():
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type=market_type,
            title=title,
            outcome=outcome,
            market_slug=f"{asset_id}-slug",
            event_slug=f"{asset_id}-event",
            event_title=event_title,
        )
    return store


def _enable_copy_buys(store: Store, wallet: str) -> None:
    profile = store.get_wallet(wallet)["profile_json"]
    profile.setdefault("strategy", {})["copy_buys_enabled"] = True
    profile.setdefault("event_book", {})["planner_enabled"] = False
    store.update_wallet(wallet, profile_json=profile)


def _unpause_rn1_tennis(store: Store) -> None:
    profile = store.get_wallet(RN1)["profile_json"]
    filter_copy = profile.setdefault("filter_copy", {})
    allowed = set(filter_copy.get("allowed_sports") or [])
    allowed.update({"atp", "wta", "tennis"})
    filter_copy["allowed_sports"] = sorted(allowed)
    filter_copy["paused_sports"] = []
    store.update_wallet(RN1, profile_json=profile)


def _enable_event_book_planner(store: Store, wallet: str) -> None:
    profile = store.get_wallet(wallet)["profile_json"]
    profile["event_book"].update(event_book_planner_default_overrides(wallet))
    store.update_wallet(wallet, profile_json=profile)


def _upsert_same_event_markets(
    store: Store,
    *,
    event_slug: str,
    event_title: str,
    markets: list[tuple[str, str, str]],
) -> None:
    for asset_id, title, outcome in markets:
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="sports",
            title=title,
            outcome=outcome,
            event_slug=event_slug,
            event_title=event_title,
        )


def _seed_source_buys(
    store: Store,
    *,
    wallet: str,
    asset_id: str,
    count: int,
    price: float,
    notional: float,
    start_block: int = 80,
) -> None:
    for index in range(1, count + 1):
        assert store.insert_source_trade(
            source_trade(
                f"seed-{asset_id}-{index}",
                wallet=wallet,
                asset_id=asset_id,
                price=price,
                notional=notional,
                block_number=start_block + index,
            )
        )


def _settings(
    tmp_path: Path,
    wallet: str,
    *,
    filter_copy_stop_loss_pct: float | None = None,
    max_position_usdc: float = 100,
):
    name = "RN1" if wallet == RN1 else "swisstony"
    path = tmp_path / f"config-{name}.yaml"
    profile_json = ""
    if filter_copy_stop_loss_pct is not None:
        profile_json = f"""
    profile_json:
      filter_copy:
        in_event_stop_loss_pct: {filter_copy_stop_loss_pct}
"""
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: {name}
    address: "{wallet}"
    enabled: true
    allowed_market_types: ["sports", "other"]
{profile_json.rstrip()}
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: {max_position_usdc}
paper:
  starting_cash_usdc: 500
  slippage_pct: 0
exits:
  mirror_source_sells: true
""",
        encoding="utf-8",
    )
    return load_config(path)
