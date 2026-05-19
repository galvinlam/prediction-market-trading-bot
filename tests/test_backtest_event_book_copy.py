from datetime import datetime, timezone
from pathlib import Path

from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.wallet_profile import event_book_planner_default_overrides, wallet_profile_json_from_legacy_wallet
from scripts import backtest_event_book_copy as backtest
from scripts.backtest_event_book_copy import (
    activity_row_to_source_trade,
    fetch_onchain_source_trades,
    find_block_at_or_after,
    source_position_metrics,
)


class FakeRpc:
    def __init__(self, block_times: dict[int, int]) -> None:
        self.block_times = block_times
        self.log_calls: list[tuple[int, int, list[object] | None]] = []

    def block_number(self) -> int:
        return max(self.block_times)

    def call(self, method: str, params: list[object]) -> object:
        assert method == "eth_getBlockByNumber"
        block_number = int(str(params[0]), 16)
        return {"timestamp": hex(self.block_times[block_number])}

    def block_timestamp(self, block_number: int) -> str:
        timestamp = datetime.fromtimestamp(self.block_times[block_number], tz=timezone.utc)
        return timestamp.strftime("%Y-%m-%d %H:%M PDT")

    def logs(
        self,
        *,
        addresses: list[str],
        from_block: int,
        to_block: int,
        topics: list[object] | None = None,
    ) -> list[dict[str, object]]:
        self.log_calls.append((from_block, to_block, topics))
        return [
            {
                "transactionHash": "0xabc",
                "logIndex": "0x1",
                "blockNumber": hex(from_block),
                "address": addresses[0],
                "topics": topics or [],
                "data": "0x",
            }
        ]


def test_activity_row_to_source_trade_normalizes_public_data_api_trade() -> None:
    row = {
        "timestamp": 1778281359,
        "side": "BUY",
        "asset": "12345",
        "conditionId": "0xcondition",
        "price": 0.54,
        "size": 12.086955,
        "usdcSize": 6.526956,
        "transactionHash": "0xabc",
        "outcome": "Sabres",
    }

    trade = activity_row_to_source_trade(row, wallet="0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD", sequence=7)

    assert trade.idempotency_key == "137:0xabc:7:0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
    assert trade.block_timestamp.endswith(" PDT")
    assert trade.side == "buy"
    assert trade.asset_id == "12345"
    assert trade.price == 0.54
    assert trade.quantity == 12.086955
    assert trade.notional_usdc == 6.526956
    assert trade.condition_id == "0xcondition"
    assert trade.outcome == "Sabres"


def test_source_position_metrics_marks_open_inventory_to_current_price() -> None:
    trades = [
        SourceTrade(
            idempotency_key="buy",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xbuy",
            block_number=1,
            block_timestamp="2026-05-08 10:00 PDT",
            log_index=1,
            source_wallet="0xwallet",
            side="buy",
            asset_id="asset-a",
            price=0.50,
            quantity=200,
            notional_usdc=100,
        ),
        SourceTrade(
            idempotency_key="sell",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xsell",
            block_number=2,
            block_timestamp="2026-05-08 11:00 PDT",
            log_index=2,
            source_wallet="0xwallet",
            side="sell",
            asset_id="asset-a",
            price=0.80,
            quantity=50,
            notional_usdc=40,
        ),
    ]

    metrics = source_position_metrics(trades, mark_prices={"asset-a": 0.70})

    assert metrics["buy_notional_usdc"] == 100.0
    assert metrics["sell_notional_usdc"] == 40.0
    assert metrics["open_value_usdc"] == 105.0
    assert metrics["pnl_usdc"] == 45.0
    assert metrics["roi_pct"] == 45.0


def test_backtest_event_book_planner_flag_enables_profile_override() -> None:
    args = backtest.parse_args(["--event-book-planner"])
    profile = backtest.enable_event_book_planner_profile({"event_book": {"planner_max_event_budget_usdc": 10}})

    assert args.event_book_planner is True
    for key, value in event_book_planner_default_overrides().items():
        assert profile["event_book"][key] == value


def test_run_backtest_uses_replayed_source_positions_instead_of_live_snapshot(tmp_path, monkeypatch) -> None:
    snapshots: list[dict[str, object]] = []

    class NoLiveSnapshotClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def source_position_snapshot(self, wallet: str, asset_id: str) -> dict[str, object] | None:
            raise AssertionError("backtest must not call live source_position_snapshot")

    class InspectingEngine:
        def __init__(self, *, source_position_resolver, **kwargs: object) -> None:
            self.source_position_resolver = source_position_resolver

        def process_trades(self, trades: list[SourceTrade]) -> dict[str, int]:
            stats = {"processed": 0, "ignored": 0, "duplicates": 0, "skipped": 0, "attributed": 0}
            for trade in trades:
                result = self.process_trade(trade)
                stats[result] += 1
            return stats

        def process_trade(self, trade: SourceTrade) -> str:
            snapshots.append(self.source_position_resolver(trade.source_wallet, trade.asset_id) or {})
            return "processed"

    rows_by_wallet = {
        backtest.RN1: [
            {
                "timestamp": 1778281200,
                "side": "BUY",
                "asset": "asset-a",
                "price": 0.50,
                "size": 10,
                "usdcSize": 5,
                "transactionHash": "0xbuy1",
            },
            {
                "timestamp": 1778281260,
                "side": "BUY",
                "asset": "asset-a",
                "price": 0.70,
                "size": 10,
                "usdcSize": 7,
                "transactionHash": "0xbuy2",
            },
            {
                "timestamp": 1778281320,
                "side": "SELL",
                "asset": "asset-a",
                "price": 0.80,
                "size": 5,
                "usdcSize": 4,
                "transactionHash": "0xsell",
            },
        ],
        backtest.SWISSTONY: [],
    }

    monkeypatch.setattr(backtest, "ROOT", tmp_path)
    monkeypatch.setattr(backtest, "MarketDataClient", NoLiveSnapshotClient)
    monkeypatch.setattr(backtest, "CopyTradingEngine", InspectingEngine)
    monkeypatch.setattr(backtest, "clone_wallet_profiles", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backtest,
        "fetch_wallet_activity",
        lambda *, wallet, **kwargs: rows_by_wallet.get(wallet.lower(), []),
    )
    monkeypatch.setattr(
        backtest,
        "load_or_fetch_metadata",
        lambda **kwargs: {"asset-a": {"asset_id": "asset-a", "current_price": 0.60}},
    )

    args = backtest.parse_args(
        [
            "--config",
            str(Path("config.example.yaml").resolve()),
            "--source",
            "data-api",
            "--warmup-hours",
            "0",
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )

    backtest.run_backtest(args)

    assert [snapshot["net_notional_usdc"] for snapshot in snapshots] == [5.0, 12.0, 9.0]
    assert [snapshot["buy_notional_usdc"] for snapshot in snapshots] == [5.0, 12.0, 12.0]
    assert [snapshot["sell_notional_usdc"] for snapshot in snapshots] == [0.0, 0.0, 4.0]
    assert all(snapshot["source_position_snapshot_source"] == "historical_replay" for snapshot in snapshots)


def test_candidate_filter_uses_event_book_planner_fresh_price_band() -> None:
    class EmptyStore:
        def get_wallet(self, address: str) -> dict[str, object] | None:
            return None

    profile = wallet_profile_json_from_legacy_wallet({"name": "RN1", "address": backtest.RN1, "enabled": True})
    profile["filter_copy"]["max_source_price"] = 0.60
    profile["event_book"]["planner_fresh_max_price"] = 0.95
    wallet = {"profile_json": profile}
    trade = SourceTrade(
        idempotency_key="rn1-buy",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xrn1",
        block_number=1,
        block_timestamp="2026-05-18 12:00 PDT",
        log_index=1,
        source_wallet=backtest.RN1,
        side="buy",
        asset_id="asset-mlb",
        price=0.46,
        quantity=13043.478261,
        notional_usdc=6000.0,
        outcome="New York Yankees",
    )
    metadata = {
        "asset_id": "asset-mlb",
        "title": "New York Yankees vs. Baltimore Orioles",
        "outcome": "New York Yankees",
        "event_slug": "mlb-nyy-bal-2026-05-18",
        "sport_key": "mlb",
        "bet_type": "moneyline_winlose",
        "current_price": 0.84,
    }
    event_positions = [
        {
            "asset_id": "asset-mlb",
            "net_notional_usdc": 6000.0,
            "net_quantity": 13043.478261,
            "avg_buy_price": 0.46,
        }
    ]

    include, reason, target_notional = backtest.filtered_replay_candidate_decision(
        store=EmptyStore(),
        trade=trade,
        metadata=metadata,
        event_positions=event_positions,
        wallet_cache={backtest.RN1: wallet},
        selected_events=set(),
        selected_asset_targets={},
    )

    assert include is True
    assert reason == "rn1_mlb_moneyline_winlose"
    assert target_notional >= 1.0


def test_find_block_at_or_after_binary_searches_by_timestamp() -> None:
    rpc = FakeRpc({10: 1000, 11: 1010, 12: 1020, 13: 1030})
    target = datetime.fromtimestamp(1011, tz=timezone.utc)

    assert find_block_at_or_after(rpc, target, latest_block=13, earliest_block=10) == 12


def test_fetch_onchain_source_trades_queries_both_wallet_topic_positions(monkeypatch) -> None:
    rpc = FakeRpc({100: 1778281200, 101: 1778281202})
    decoded = SourceTrade(
        idempotency_key="137:0xabc:1:0xwallet",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xabc",
        block_number=100,
        block_timestamp="2026-05-08 16:20 PDT",
        log_index=1,
        source_wallet="0xwallet",
        side="buy",
        asset_id="asset-a",
        price=0.5,
        quantity=10,
        notional_usdc=5,
    )

    monkeypatch.setattr(backtest, "decode_order_filled_log", lambda *args, **kwargs: decoded)
    monkeypatch.setattr(backtest, "select_copyable_order_fills", lambda trades, *, exchange_addresses: trades)

    trades = fetch_onchain_source_trades(
        rpc=rpc,
        wallets=["0x000000000000000000000000000000000000abcd"],
        from_block=100,
        to_block=101,
        exchange_contracts=("ctf_exchange",),
        chunk_size=2,
    )

    assert trades == [decoded]
    assert len(rpc.log_calls) == 2
    assert rpc.log_calls[0][2][2] == ["0x000000000000000000000000000000000000000000000000000000000000abcd"]
    assert rpc.log_calls[1][2][3] == ["0x000000000000000000000000000000000000000000000000000000000000abcd"]
