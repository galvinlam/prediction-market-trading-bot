from pathlib import Path

from polymarket_copy_trading.live_executor import (
    LiveOrderPostResult,
    post_planned_live_order_intents,
    reconcile_live_order_intents,
)
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.service import main
from polymarket_copy_trading.store import Store


def make_source(key: str = "137:0xaaa:1:0x1111111111111111111111111111111111111111") -> SourceTrade:
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xaaa",
        block_number=100,
        block_timestamp="2026-05-02 09:15 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="token-123",
        price=0.50,
        quantity=800,
        notional_usdc=400,
        market_id="market-1",
        outcome="YES",
    )


def test_store_persists_live_order_intents_idempotently_and_updates_status(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)

    intent = store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
    )
    duplicate = store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.52,
        size=21.0,
        notional_usdc=11.0,
    )

    assert duplicate == intent
    assert len(store.list_live_order_intents()) == 1
    assert store.get_live_order_intent(intent["id"]) == intent
    assert store.get_live_order_intent_for_source(source.idempotency_key, side="buy") == intent
    assert intent["token_id"] == "token-123"
    assert store.get_live_order_intent(999999) is None

    accepted = store.update_live_order_intent_status(
        intent["id"],
        status="accepted",
        clob_order_id="0xclob",
        response={"orderID": "0xclob", "success": True},
    )

    assert accepted["status"] == "accepted"
    assert accepted["clob_order_id"] == "0xclob"
    assert accepted["response_json"] == {"orderID": "0xclob", "success": True}
    assert accepted["error"] is None
    assert accepted["created_at"].endswith(" PDT")
    assert accepted["updated_at"].endswith(" PDT")

    rejected_source = make_source("137:0xbbb:2:0x1111111111111111111111111111111111111111")
    store.insert_source_trade(rejected_source)
    rejected = store.create_live_order_intent(
        source_trade=rejected_source,
        side="sell",
        price=0.49,
        size=8.0,
        notional_usdc=3.92,
    )

    rejected = store.update_live_order_intent_status(
        rejected["id"],
        status="rejected",
        error="insufficient balance",
        response='{"success": false}',
    )

    intents = store.list_live_order_intents()
    assert [item["id"] for item in intents] == [rejected["id"], intent["id"]]
    assert [item["id"] for item in store.list_live_order_intents(status="accepted")] == [intent["id"]]
    assert store.list_live_order_intents(source_idempotency_key=rejected_source.idempotency_key) == [rejected]
    assert rejected["status"] == "rejected"
    assert rejected["error"] == "insufficient balance"
    assert rejected["response_json"] == {"success": False}
    assert rejected["source_wallet"] == "0x1111111111111111111111111111111111111111"
    assert rejected["asset_id"] == "token-123"


def test_post_planned_live_order_intents_posts_polymarket_us_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(
        asset_id=source.asset_id,
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
    )
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )
    submitted: list[dict[str, object]] = []

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            submitted.append(kwargs)
            return LiveOrderPostResult(
                success=True,
                order_id="order-us-1",
                status="posted",
                raw_response={"id": "order-us-1"},
                error=None,
            )

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "posted": 1, "rejected": 0, "errors": 0}
    assert submitted == [
        {
            "market_slug": "aec-mlb-team-a-team-b-2026-05-10",
            "outcome_side": "OUTCOME_SIDE_YES",
            "action": "ORDER_ACTION_BUY",
            "price": 0.51,
            "quantity": 19.607843,
            "order_type": "ORDER_TYPE_LIMIT",
            "time_in_force": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        }
    ]
    intent = store.list_live_order_intents()[0]
    assert intent["status"] == "posted"
    assert intent["clob_order_id"] == "order-us-1"
    assert intent["response_json"] == {"id": "order-us-1"}
    assert store.list_live_order_intents(status="planned") == []


def test_post_planned_live_order_intents_converts_no_price_to_yes_price(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(
        asset_id=source.asset_id,
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_NO",
    )
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )
    submitted: list[dict[str, object]] = []

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            submitted.append(kwargs)
            return LiveOrderPostResult(
                success=True,
                order_id="order-us-1",
                status="posted",
                raw_response={"id": "order-us-1"},
                error=None,
            )

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker(), tick_size="auto")

    assert stats == {"planned": 1, "posted": 1, "rejected": 0, "errors": 0}
    assert submitted[0]["outcome_side"] == "OUTCOME_SIDE_NO"
    assert submitted[0]["price"] == 0.49


def test_post_planned_live_order_intents_blocks_without_outcome_side(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(asset_id=source.asset_id, market_slug="aec-mlb-team-a-team-b-2026-05-10")
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            raise AssertionError("intent with unknown outcome_side should not post")

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker(), tick_size="auto")

    assert stats == {"planned": 1, "posted": 0, "rejected": 0, "errors": 1}
    intent = store.list_live_order_intents()[0]
    assert intent["status"] == "metadata_missing"
    assert intent["error"] == "market metadata outcome_side is required for Polymarket US live order posting"


def test_post_planned_live_order_intents_records_rejections_without_reposting(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(
        asset_id=source.asset_id,
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
    )
    store.create_live_order_intent(
        source_trade=source,
        side="sell",
        price=0.49,
        size=8.0,
        notional_usdc=3.92,
        status="planned",
    )
    attempts = 0

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            nonlocal attempts
            attempts += 1
            return LiveOrderPostResult(
                success=False,
                order_id=None,
                status="rejected",
                raw_response={"success": False, "error": "insufficient balance"},
                error="insufficient balance",
            )

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker())
    stats_again = post_planned_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "posted": 0, "rejected": 1, "errors": 0}
    assert stats_again == {"planned": 0, "posted": 0, "rejected": 0, "errors": 0}
    assert attempts == 1
    intent = store.list_live_order_intents()[0]
    assert intent["status"] == "rejected"
    assert intent["error"] == "insufficient balance"
    assert intent["response_json"] == {"success": False, "error": "insufficient balance"}


def test_post_planned_live_order_intents_blocks_without_market_metadata(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            raise AssertionError("intent with missing metadata should not post")

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "posted": 0, "rejected": 0, "errors": 1}
    intent = store.list_live_order_intents()[0]
    assert intent["status"] == "metadata_missing"
    assert intent["error"] == "market metadata is required for live order posting"


def test_post_planned_live_order_intents_blocks_without_market_slug(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(asset_id=source.asset_id, outcome_side="OUTCOME_SIDE_YES")
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            raise AssertionError("intent with unknown market_slug should not post")

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "posted": 0, "rejected": 0, "errors": 1}
    intent = store.list_live_order_intents()[0]
    assert intent["status"] == "metadata_missing"
    assert intent["error"] == "market metadata market_slug is required for Polymarket US live order posting"


def test_post_planned_live_order_intents_records_broker_exceptions(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(
        asset_id=source.asset_id,
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
    )
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )

    class FakeBroker:
        def create_and_post_limit_order(self, **kwargs):
            raise RuntimeError("polymarket us unavailable")

    stats = post_planned_live_order_intents(store=store, broker=FakeBroker())
    stats_again = post_planned_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"planned": 1, "posted": 0, "rejected": 0, "errors": 1}
    assert stats_again == {"planned": 0, "posted": 0, "rejected": 0, "errors": 0}
    intent = store.list_live_order_intents()[0]
    assert intent["status"] == "exception"
    assert intent["error"] == "polymarket us unavailable"


def test_reconcile_live_order_intents_updates_open_clob_statuses(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )
    intent = store.list_live_order_intents()[0]
    store.update_live_order_intent_status(
        intent["id"],
        status="accepted",
        clob_order_id="0xclob",
        response={"orderID": "0xclob", "status": "accepted"},
    )

    class FakeBroker:
        def reconcile_orders(self, order_ids):
            assert order_ids == ["0xclob"]
            return {
                "type": "order_reconciliation_report",
                "status": "ok",
                "orders": [
                    {
                        "clob_order_id": "0xclob",
                        "status": "filled",
                        "raw_response": {"id": "0xclob", "status": "filled", "filled_size": "19.607843"},
                        "error": None,
                    }
                ],
                "errors": 0,
            }

    stats = reconcile_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"open": 1, "updated": 1, "errors": 0}
    updated = store.get_live_order_intent(intent["id"])
    assert updated["status"] == "filled"
    assert updated["error"] is None
    assert updated["response_json"] == {"id": "0xclob", "status": "filled", "filled_size": "19.607843"}


def test_reconcile_live_order_intents_skips_intents_without_clob_order_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="accepted",
    )

    class FailBroker:
        def reconcile_orders(self, order_ids):
            raise AssertionError("intent without CLOB order id should not reconcile")

    stats = reconcile_live_order_intents(store=store, broker=FailBroker())

    assert stats == {"open": 0, "updated": 0, "errors": 0}


def test_reconcile_live_order_intents_keeps_retryable_status_on_gateway_error(tmp_path: Path) -> None:
    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )
    intent = store.list_live_order_intents()[0]
    store.update_live_order_intent_status(intent["id"], status="posted", clob_order_id="0xclob")

    class FakeBroker:
        def reconcile_orders(self, order_ids):
            return {
                "type": "order_reconciliation_report",
                "status": "partial",
                "orders": [
                    {
                        "clob_order_id": "0xclob",
                        "status": "unknown",
                        "raw_response": None,
                        "error": "gateway unavailable",
                    }
                ],
                "errors": 1,
            }

    stats = reconcile_live_order_intents(store=store, broker=FakeBroker())

    assert stats == {"open": 1, "updated": 0, "errors": 1}
    updated = store.get_live_order_intent(intent["id"])
    assert updated["status"] == "posted"
    assert updated["error"] == "gateway unavailable"


def test_run_live_orders_command_wires_dispatcher(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
app:
  live_database_url: sqlite:///{(tmp_path / "live.sqlite3").as_posix()}
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(Path(__file__).resolve().parents[1])

    called: dict[str, object] = {}

    class FakeBroker:
        @classmethod
        def from_env(cls):
            called["broker"] = "built"
            return cls()

    def fake_dispatch(*, store, broker, limit, tick_size):
        called["store_path"] = store.path
        called["broker_instance"] = broker
        called["limit"] = limit
        called["tick_size"] = tick_size
        return {"planned": 0, "posted": 0, "rejected": 0, "errors": 0}

    monkeypatch.setattr("polymarket_copy_trading.service.LivePolymarketBroker", FakeBroker)
    monkeypatch.setattr("polymarket_copy_trading.service.post_planned_live_order_intents", fake_dispatch)

    result = main(["run-live-orders", "--config", str(config_path), "--limit", "7", "--tick-size", "0.001"])

    assert result == 0
    assert called["broker"] == "built"
    assert isinstance(called["broker_instance"], FakeBroker)
    assert called["limit"] == 7
    assert called["tick_size"] == "0.001"
    assert called["store_path"] == tmp_path / "live.sqlite3"


def test_run_live_order_reconciliation_requires_live_mode(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  trading_mode: paper
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )

    class FailClient:
        def __init__(self, **kwargs):
            raise AssertionError("paper mode must not build execution client")

    monkeypatch.setattr("polymarket_copy_trading.service.ExecutionServiceClient", FailClient)

    assert (
        main(
            [
                "run-live-order-reconciliation",
                "--config",
                str(config_path),
                "--execution-service-url",
                "http://127.0.0.1:8791",
            ]
        )
        == 2
    )


def test_run_live_order_reconciliation_wires_gateway_client(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
app:
  live_database_url: sqlite:///{(tmp_path / "live.sqlite3").as_posix()}
""",
        encoding="utf-8",
    )
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, base_url: str, auth_secret: str | None):
            called["base_url"] = base_url
            called["auth_secret"] = auth_secret

    class FakeRemoteBroker:
        def __init__(self, *, client: FakeClient):
            called["client"] = client

    def fake_reconcile(*, store, broker, limit):
        called["store_path"] = store.path
        called["broker"] = broker
        called["limit"] = limit
        return {"open": 0, "updated": 0, "errors": 0}

    monkeypatch.setenv("EXECUTION_GATEWAY_AUTH_SECRET", "env-secret")
    monkeypatch.setattr("polymarket_copy_trading.service.ExecutionServiceClient", FakeClient)
    monkeypatch.setattr("polymarket_copy_trading.service.RemoteExecutionBroker", FakeRemoteBroker)
    monkeypatch.setattr("polymarket_copy_trading.service.reconcile_live_order_intents", fake_reconcile)

    result = main(
        [
            "run-live-order-reconciliation",
            "--config",
            str(config_path),
            "--limit",
            "11",
            "--execution-service-url",
            "http://127.0.0.1:8791",
        ]
    )

    assert result == 0
    assert called["base_url"] == "http://127.0.0.1:8791"
    assert called["auth_secret"] == "env-secret"
    assert isinstance(called["broker"], FakeRemoteBroker)
    assert called["limit"] == 11
    assert called["store_path"] == tmp_path / "live.sqlite3"
