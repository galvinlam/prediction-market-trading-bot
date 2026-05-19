from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.live_watcher import (
    LEGACY_ORDER_FILLED_TOPIC,
    V2_ORDER_FILLED_TOPIC,
    ORDER_FILLED_TOPIC,
    LivePaperWatcher,
    decode_order_filled_log,
    select_copyable_order_fills,
)
from polymarket_copy_trading.store import Store


TRACKED_MAKER = "0x1111111111111111111111111111111111111111"
TRACKED_TAKER = "0x2222222222222222222222222222222222222222"


def topic_address(address: str) -> str:
    return "0x" + ("0" * 24) + address[2:]


def word(value: int) -> str:
    return f"{value:064x}"


def make_log(*, maker: str, taker: str, side: int, token_id: int, maker_amount: int, taker_amount: int) -> dict:
    data_words = [
        side,
        token_id,
        maker_amount,
        taker_amount,
        0,
        0x1234,
        0x5678,
    ]
    return {
        "address": "0xE111180000d2663C0091e4f400237545B87B996B",
        "blockNumber": "0x64",
        "transactionHash": "0xabc",
        "logIndex": "0x1",
        "topics": [
            ORDER_FILLED_TOPIC,
            "0x" + "aa" * 32,
            topic_address(maker),
            topic_address(taker),
        ],
        "data": "0x" + "".join(word(value) for value in data_words),
    }


def make_legacy_log(
    *,
    maker: str,
    taker: str,
    maker_asset_id: int,
    taker_asset_id: int,
    maker_amount: int,
    taker_amount: int,
    tx_hash: str = "0xabc",
    log_index: int = 1,
    address: str = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
) -> dict:
    data_words = [
        maker_asset_id,
        taker_asset_id,
        maker_amount,
        taker_amount,
        0,
    ]
    return {
        "address": address,
        "blockNumber": "0x64",
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "topics": [
            LEGACY_ORDER_FILLED_TOPIC,
            "0x" + "aa" * 32,
            topic_address(maker),
            topic_address(taker),
        ],
        "data": "0x" + "".join(word(value) for value in data_words),
    }


def test_v2_order_filled_topic_matches_deployed_contract_event() -> None:
    assert V2_ORDER_FILLED_TOPIC == "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"


def test_decode_order_filled_for_tracked_maker_buy() -> None:
    log = make_log(
        maker=TRACKED_MAKER,
        taker=TRACKED_TAKER,
        side=0,
        token_id=123,
        maker_amount=50_000_000,
        taker_amount=100_000_000,
    )

    trade = decode_order_filled_log(log, tracked_wallets={TRACKED_MAKER}, block_timestamp="2026-04-26 17:00 PDT")

    assert trade is not None
    assert trade.source_wallet == TRACKED_MAKER
    assert trade.side == "buy"
    assert trade.asset_id == "123"
    assert trade.notional_usdc == 50
    assert trade.quantity == 100
    assert trade.price == 0.5


def test_decode_order_filled_for_tracked_taker_is_opposite_side() -> None:
    log = make_log(
        maker=TRACKED_MAKER,
        taker=TRACKED_TAKER,
        side=1,
        token_id=123,
        maker_amount=100_000_000,
        taker_amount=70_000_000,
    )

    trade = decode_order_filled_log(log, tracked_wallets={TRACKED_TAKER}, block_timestamp="2026-04-26 17:00 PDT")

    assert trade is not None
    assert trade.source_wallet == TRACKED_TAKER
    assert trade.side == "buy"
    assert trade.notional_usdc == 70
    assert trade.quantity == 100
    assert trade.price == 0.7


def test_decode_order_filled_ignores_untracked_wallets() -> None:
    log = make_log(
        maker=TRACKED_MAKER,
        taker=TRACKED_TAKER,
        side=0,
        token_id=123,
        maker_amount=50_000_000,
        taker_amount=100_000_000,
    )

    assert decode_order_filled_log(log, tracked_wallets={"0x3333333333333333333333333333333333333333"}) is None


def test_decode_order_filled_ignores_non_orderfilled_topic() -> None:
    log = make_log(
        maker=TRACKED_MAKER,
        taker=TRACKED_TAKER,
        side=0,
        token_id=123,
        maker_amount=50_000_000,
        taker_amount=100_000_000,
    )
    log["topics"][0] = "0x" + "00" * 32

    assert decode_order_filled_log(log, tracked_wallets={TRACKED_MAKER}) is None


def test_decode_legacy_order_filled_for_tracked_maker_buy() -> None:
    log = make_legacy_log(
        maker=TRACKED_MAKER,
        taker=TRACKED_TAKER,
        maker_asset_id=0,
        taker_asset_id=123,
        maker_amount=50_000_000,
        taker_amount=100_000_000,
    )

    trade = decode_order_filled_log(log, tracked_wallets={TRACKED_MAKER}, block_timestamp="2026-04-27 07:37 PDT")

    assert trade is not None
    assert trade.source_wallet == TRACKED_MAKER
    assert trade.side == "buy"
    assert trade.asset_id == "123"
    assert trade.notional_usdc == 50
    assert trade.quantity == 100
    assert trade.price == 0.5


def test_decode_legacy_order_filled_for_tracked_taker_buy() -> None:
    log = make_legacy_log(
        maker=TRACKED_MAKER,
        taker=TRACKED_TAKER,
        maker_asset_id=123,
        taker_asset_id=0,
        maker_amount=100_000_000,
        taker_amount=70_000_000,
    )

    trade = decode_order_filled_log(log, tracked_wallets={TRACKED_TAKER}, block_timestamp="2026-04-27 07:37 PDT")

    assert trade is not None
    assert trade.source_wallet == TRACKED_TAKER
    assert trade.side == "buy"
    assert trade.asset_id == "123"
    assert trade.notional_usdc == 70
    assert trade.quantity == 100
    assert trade.price == 0.7


def test_exchange_summary_suppresses_internal_match_legs() -> None:
    exchange = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
    internal_leg = decode_order_filled_log(
        make_legacy_log(
            maker=TRACKED_MAKER,
            taker=TRACKED_TAKER,
            maker_asset_id=123,
            taker_asset_id=0,
            maker_amount=100_000_000,
            taker_amount=99_000_000,
            tx_hash="0xabc",
            log_index=1,
            address=exchange,
        ),
        tracked_wallets={TRACKED_TAKER},
    )
    summary = decode_order_filled_log(
        make_legacy_log(
            maker=TRACKED_TAKER,
            taker=exchange,
            maker_asset_id=0,
            taker_asset_id=456,
            maker_amount=5_000_000,
            taker_amount=50_000_000,
            tx_hash="0xabc",
            log_index=2,
            address=exchange,
        ),
        tracked_wallets={TRACKED_TAKER},
    )

    assert internal_leg is not None
    assert summary is not None
    selected = select_copyable_order_fills([internal_leg, summary], exchange_addresses={exchange})

    assert selected == [summary]


class FakeRpc:
    def block_number(self) -> int:
        return 105

    def logs(self, **kwargs) -> list:
        return []


def test_ws_disconnect_records_reconnect_and_http_catchup(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
watcher:
  confirmations: 1
  backfill_blocks: 2
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    config = load_config(config_path)
    watcher = LivePaperWatcher(config=config, store=store, rpc_url="http://unused", ws_url="ws://unused")
    watcher.rpc = FakeRpc()

    watcher._record_ws_disconnect(RuntimeError("closed"))
    assert store.get_runtime_state("paper_watcher_status") == "ws_reconnecting"
    assert "closed" in (store.get_runtime_state("paper_watcher_last_error") or "")

    watcher._catch_up_with_http()

    assert store.get_runtime_state("paper_watcher_status") == "ws_reconnecting_caught_up"
    assert store.get_runtime_state("watcher_last_processed_block") == "104"


def test_live_watcher_wires_market_metadata_resolver_into_engine(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
watcher:
  confirmations: 1
  backfill_blocks: 2
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    config = load_config(config_path)
    def resolver(_asset_id: str) -> dict[str, str]:
        return {"market_type": "weather"}

    watcher = LivePaperWatcher(
        config=config,
        store=store,
        rpc_url="http://unused",
        ws_url="ws://unused",
        market_metadata_resolver=resolver,
    )

    assert watcher.engine.market_metadata_resolver is resolver
