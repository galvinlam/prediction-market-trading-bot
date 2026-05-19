from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import threading
import time

from polymarket_copy_trading.execution_service import (
    ExecutionReceiptStore,
    ExecutionServiceClient,
    RemoteExecutionBroker,
    create_execution_app,
)
from polymarket_copy_trading.live_executor import LiveOrderPostResult, LiveSettlementResult
from polymarket_copy_trading.service import main
from polymarket_copy_trading.store import Store

from tests.test_live_order_intents import make_source
from tests.test_live_settlements import _live_config, _store_with_open_resolved_position


def test_execution_service_posts_signed_place_order_and_returns_report(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = _place_order_command()

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["type"] == "execution_report"
    assert payload["command_id"] == "cmd-1"
    assert payload["correlation_id"] == "corr-1"
    assert payload["status"] == "accepted"
    assert payload["order_id"] == "0xorder"
    assert payload["clob_order_id"] == "0xorder"
    assert payload["duplicate_replayed"] is False
    assert broker.orders == [
        {
            "market_slug": "aec-mlb-team-a-team-b-2026-05-10",
            "outcome_side": "OUTCOME_SIDE_YES",
            "action": "ORDER_ACTION_BUY",
            "price": 0.42,
            "quantity": 12.5,
        }
    ]


def test_execution_service_blocks_mutating_commands_when_execution_disabled(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
        execution_enabled=False,
    )
    command = _place_order_command()

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 403
    assert response.get_json() == {"error": "execution_disabled"}
    assert broker.orders == []


def test_execution_service_allows_reconciliation_when_execution_disabled(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
        execution_enabled=False,
    )
    payload = {"schema_version": 1, "order_ids": ["0xorder"]}

    response = app.test_client().post(
        "/v1/execution/reconcile/orders",
        data=_signed_body(payload, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(payload, "secret")},
    )

    assert response.status_code == 200
    assert response.get_json()["orders"] == [
        {
            "order_id": "0xorder",
            "clob_order_id": "0xorder",
            "status": "filled",
            "raw_response": {"id": "0xorder", "status": "filled"},
            "error": None,
        }
    ]
    assert broker.status_requests == ["0xorder"]


def test_execution_service_preflight_reports_gateway_and_broker_checks(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
        execution_enabled=False,
    )
    payload = {"schema_version": 1}

    response = app.test_client().post(
        "/v1/execution/preflight",
        data=_signed_body(payload, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(payload, "secret")},
    )

    assert response.status_code == 200
    report = response.get_json()
    assert report["type"] == "preflight_report"
    assert report["status"] == "ok"
    assert report["execution_enabled"] is False
    assert report["checks"] == [{"name": "fake_broker", "status": "ok", "detail": "ready"}]


def test_execution_service_replays_duplicate_idempotency_key_without_reposting(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    client = app.test_client()
    command = _place_order_command()

    first = client.post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )
    second = client.post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(broker.orders) == 1
    replayed = second.get_json()
    assert replayed["status"] == "accepted"
    assert replayed["clob_order_id"] == "0xorder"
    assert replayed["duplicate_replayed"] is True


def test_execution_service_replays_retry_with_fresh_command_envelope(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    client = app.test_client()
    original = _place_order_command()
    retry = _place_order_command()
    retry["command_id"] = "cmd-retry"
    retry["correlation_id"] = "corr-retry"
    retry["created_at"] = datetime.now(timezone.utc).isoformat()
    retry["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()

    assert client.post(
        "/v1/execution/commands",
        data=_signed_body(original, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(original, "secret")},
    ).status_code == 200
    response = client.post(
        "/v1/execution/commands",
        data=_signed_body(retry, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(retry, "secret")},
    )

    assert response.status_code == 200
    assert len(broker.orders) == 1
    assert response.get_json()["duplicate_replayed"] is True


def test_execution_service_does_not_double_execute_concurrent_duplicate_commands(tmp_path: Path) -> None:
    broker = SlowFakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = _place_order_command()
    barrier = threading.Barrier(2)
    responses: list[tuple[int, dict[str, object]]] = []

    def post_command() -> None:
        barrier.wait(timeout=5)
        response = app.test_client().post(
            "/v1/execution/commands",
            data=_signed_body(command, "secret"),
            content_type="application/json",
            headers={"X-Execution-Signature": _signature(command, "secret")},
        )
        responses.append((response.status_code, response.get_json()))

    threads = [threading.Thread(target=post_command) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(responses) == 2
    assert sorted(status for status, _ in responses) == [200, 200]
    assert len(broker.orders) == 1
    assert sorted(bool(payload["duplicate_replayed"]) for _, payload in responses) == [False, True]


def test_execution_service_rejects_idempotency_payload_mismatch(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    client = app.test_client()
    original = _place_order_command()
    changed = _place_order_command()
    changed["payload"]["price"] = 0.43

    assert client.post(
        "/v1/execution/commands",
        data=_signed_body(original, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(original, "secret")},
    ).status_code == 200
    response = client.post(
        "/v1/execution/commands",
        data=_signed_body(changed, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(changed, "secret")},
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "idempotency_key_payload_mismatch"
    assert len(broker.orders) == 1


def test_execution_service_rejects_bad_signature_before_broker_execution(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(_place_order_command(), "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": "bad"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_signature"
    assert broker.orders == []


def test_execution_service_rejects_expired_command_before_broker_execution(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = _place_order_command()
    command["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "command_expired"
    assert broker.orders == []


def test_execution_service_redeems_settlement_command(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = {
        **_base_command(command_id="cmd-settle", command_type="redeem_settlement", idempotency_key="idem-settle"),
        "payload": {
            "condition_id": "0x" + "a" * 64,
            "token_id": "token-1",
            "resolution_price": 1.0,
            "size": 12.5,
        },
    }

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "settlement_confirmed"
    assert payload["transaction_hash"] == "0xsettled"
    assert broker.settlements == [
        {
            "condition_id": "0x" + "a" * 64,
            "token_id": "token-1",
            "resolution_price": 1.0,
            "size": 12.5,
        }
    ]


def test_execution_service_cancels_order_command(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = {
        **_base_command(command_id="cmd-cancel", command_type="cancel_order", idempotency_key="idem-cancel"),
        "payload": {"order_id": "0xorder"},
    }

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "cancelled"
    assert payload["order_id"] == "0xorder"
    assert payload["clob_order_id"] == "0xorder"
    assert broker.cancelled == ["0xorder"]


def test_execution_service_normalizes_sdk_cancel_response(tmp_path: Path) -> None:
    broker = FakeBroker()
    broker.cancel_response = {"canceled": "0xorder"}
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = {
        **_base_command(command_id="cmd-cancel", command_type="cancel_order", idempotency_key="idem-cancel"),
        "payload": {"order_id": "0xorder"},
    }

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "cancelled"
    assert payload["order_id"] == "0xorder"
    assert payload["clob_order_id"] == "0xorder"
    assert payload["raw_response"] == {"canceled": "0xorder"}


def test_execution_service_gets_order_status_command(tmp_path: Path) -> None:
    broker = FakeBroker()
    app = create_execution_app(
        broker=broker,
        auth_secret="secret",
        receipt_store=ExecutionReceiptStore(tmp_path / "receipts.sqlite3"),
    )
    command = {
        **_base_command(command_id="cmd-status", command_type="get_order_status", idempotency_key="idem-status"),
        "payload": {"order_id": "0xorder"},
    }

    response = app.test_client().post(
        "/v1/execution/commands",
        data=_signed_body(command, "secret"),
        content_type="application/json",
        headers={"X-Execution-Signature": _signature(command, "secret")},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "filled"
    assert payload["order_id"] == "0xorder"
    assert payload["clob_order_id"] == "0xorder"
    assert payload["raw_response"] == {"id": "0xorder", "status": "filled"}
    assert broker.status_requests == ["0xorder"]


def test_execution_service_client_signs_and_posts_command() -> None:
    command = _place_order_command()
    session = FakeSession()
    client = ExecutionServiceClient(
        base_url="http://gateway.local",
        auth_secret="secret",
        session=session,
    )

    report = client.execute(command)

    assert report == {"type": "execution_report", "status": "accepted"}
    assert session.url == "http://gateway.local/v1/execution/commands"
    assert session.timeout == 10.0
    assert session.headers["Content-Type"] == "application/json"
    assert session.headers["X-Execution-Signature"] == _signature(command, "secret")
    assert session.data == _canonical_bytes(command)


def test_execution_service_client_calls_preflight() -> None:
    session = FakeSession({"type": "preflight_report", "status": "ok"})
    client = ExecutionServiceClient(base_url="http://gateway.local/", auth_secret="secret", session=session)

    report = client.preflight()

    assert report == {"type": "preflight_report", "status": "ok"}
    assert session.url == "http://gateway.local/v1/execution/preflight"
    assert session.headers["X-Execution-Signature"] == _signature({"schema_version": 1}, "secret")


def test_execution_service_client_calls_order_reconciliation() -> None:
    session = FakeSession({"type": "order_reconciliation_report", "orders": []})
    client = ExecutionServiceClient(base_url="http://gateway.local", auth_secret="secret", session=session)

    report = client.reconcile_orders(["0xorder"])

    assert report == {"type": "order_reconciliation_report", "orders": []}
    assert session.url == "http://gateway.local/v1/execution/reconcile/orders"
    assert json.loads((session.data or b"{}").decode("utf-8")) == {"schema_version": 1, "order_ids": ["0xorder"]}


def test_remote_execution_broker_maps_place_order_report_to_live_result() -> None:
    client = FakeExecutionClient(
        {
            "status": "accepted",
            "order_id": "order-remote",
            "raw_response": {"id": "order-remote"},
            "error": None,
        }
    )
    broker = RemoteExecutionBroker(client=client, wallet_id="wallet-main", command_ttl_seconds=30)

    result = broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
        action="ORDER_ACTION_BUY",
        price=0.42,
        quantity=12.5,
    )

    assert result == LiveOrderPostResult(
        success=True,
        order_id="order-remote",
        status="accepted",
        raw_response={"id": "order-remote"},
        error=None,
    )
    command = client.commands[0]
    assert command["command_type"] == "place_order"
    assert command["wallet_id"] == "wallet-main"
    assert command["payload"] == {
        "market_slug": "aec-mlb-team-a-team-b-2026-05-10",
        "outcome_side": "OUTCOME_SIDE_YES",
        "action": "ORDER_ACTION_BUY",
        "price": 0.42,
        "quantity": 12.5,
    }
    assert str(command["idempotency_key"]).startswith("place_order:")


def test_remote_execution_broker_sends_order_type_when_provided() -> None:
    client = FakeExecutionClient(
        {
            "status": "accepted",
            "order_id": "order-remote",
            "raw_response": {"id": "order-remote"},
            "error": None,
        }
    )
    broker = RemoteExecutionBroker(client=client)

    broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_NO",
        action="ORDER_ACTION_SELL",
        price=0.55,
        quantity=8,
        order_type="FAK",
    )

    assert client.commands[0]["payload"]["order_type"] == "FAK"


def test_remote_execution_broker_exposes_order_reconciliation() -> None:
    client = FakeExecutionClient({"type": "order_reconciliation_report", "orders": []})
    broker = RemoteExecutionBroker(client=client)

    report = broker.reconcile_orders(["0xorder"])

    assert report == {"type": "order_reconciliation_report", "orders": []}
    assert client.reconcile_order_ids == ["0xorder"]


def test_live_order_dispatch_passes_intent_context_to_gateway_capable_broker(tmp_path: Path) -> None:
    from polymarket_copy_trading.live_executor import post_planned_live_order_intents

    store = Store(tmp_path / "live.sqlite3")
    store.initialize()
    source = make_source()
    store.insert_source_trade(source)
    store.upsert_market_metadata(
        asset_id=source.asset_id,
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
    )
    intent = store.create_live_order_intent(
        source_trade=source,
        side="buy",
        price=0.51,
        size=19.607843,
        notional_usdc=10.0,
        status="planned",
    )
    captured: dict[str, object] = {}

    class ContextBroker:
        supports_execution_context = True

        def create_and_post_limit_order(self, **kwargs):
            captured.update(kwargs)
            return LiveOrderPostResult(
                success=True,
                order_id="order-us-1",
                status="accepted",
                raw_response={"id": "order-us-1"},
                error=None,
            )

    stats = post_planned_live_order_intents(store=store, broker=ContextBroker(), tick_size="0.001")

    assert stats == {"planned": 1, "posted": 1, "rejected": 0, "errors": 0}
    assert captured["idempotency_key"] == f"live_order_intent:{intent['id']}"
    assert captured["correlation_id"] == f"live_order_intent:{intent['id']}"


def test_live_settlement_dispatch_passes_intent_context_to_gateway_capable_broker(tmp_path: Path) -> None:
    from polymarket_copy_trading.engine import CopyTradingEngine
    from polymarket_copy_trading.live_executor import redeem_planned_settlement_intents

    store = _store_with_open_resolved_position(tmp_path, resolution_price=1.0)
    config = _live_config(tmp_path)
    assert CopyTradingEngine(config=config, store=store).process_market_settlements() == 1
    intent = store.list_live_settlement_intents()[0]
    captured: dict[str, object] = {}

    class ContextBroker:
        supports_execution_context = True

        def redeem_settled_position(self, **kwargs):
            captured.update(kwargs)
            return LiveSettlementResult(
                success=True,
                transaction_hash="0xsettled",
                status="settlement_confirmed",
                raw_response={"transactionHash": "0xsettled"},
                error=None,
            )

    stats = redeem_planned_settlement_intents(store=store, broker=ContextBroker())

    assert stats == {"planned": 1, "redeemed": 1, "errors": 0}
    assert captured["idempotency_key"] == f"live_settlement_intent:{intent['id']}"
    assert captured["correlation_id"] == f"live_settlement_intent:{intent['id']}"


def test_run_execution_service_command_wires_gateway(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )
    called: dict[str, object] = {}

    class FakeBroker:
        @classmethod
        def from_env(cls):
            called["broker"] = "built"
            return cls()

    class FakeApp:
        def run(self, *, host: str, port: int) -> None:
            called["host"] = host
            called["port"] = port

    def fake_create_execution_app(*, broker, auth_secret, receipt_store, execution_enabled):
        called["broker_instance"] = broker
        called["auth_secret"] = auth_secret
        called["receipt_store_path"] = receipt_store.path
        called["execution_enabled"] = execution_enabled
        return FakeApp()

    monkeypatch.setenv("EXECUTION_GATEWAY_AUTH_SECRET", "env-secret")
    monkeypatch.setenv("EXECUTION_GATEWAY_EXECUTION_ENABLED", "true")
    monkeypatch.setattr("polymarket_copy_trading.service.LivePolymarketBroker", FakeBroker)
    monkeypatch.setattr("polymarket_copy_trading.service.create_execution_app", fake_create_execution_app)

    result = main(
        [
            "run-execution-service",
            "--config",
            str(config_path),
            "--host",
            "127.0.0.1",
            "--port",
            "8791",
            "--receipt-db",
            str(tmp_path / "gateway.sqlite3"),
        ]
    )

    assert result == 0
    assert called["broker"] == "built"
    assert isinstance(called["broker_instance"], FakeBroker)
    assert called["auth_secret"] == "env-secret"
    assert called["receipt_store_path"] == tmp_path / "gateway.sqlite3"
    assert called["execution_enabled"] is True
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 8791


def test_run_execution_service_requires_auth_secret_before_broker(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )

    class FailBroker:
        @classmethod
        def from_env(cls):
            raise AssertionError("gateway without auth secret must not build broker")

    monkeypatch.delenv("EXECUTION_GATEWAY_AUTH_SECRET", raising=False)
    monkeypatch.setattr("polymarket_copy_trading.service.LivePolymarketBroker", FailBroker)

    assert main(["run-execution-service", "--config", str(config_path)]) == 2


def test_derive_polymarket_api_key_command_is_deprecated_for_us(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )
    class FakeBroker:
        @classmethod
        def derive_api_credentials_from_env(cls, *, nonce):
            raise AssertionError("Polymarket US credentials must not be derived through CLOB")

    monkeypatch.setattr("polymarket_copy_trading.service.LivePolymarketBroker", FakeBroker)

    result = main(["derive-polymarket-api-key", "--config", str(config_path), "--nonce", "9"])

    assert result == 2
    assert "deprecated for Polymarket US" in capsys.readouterr().out


def test_derive_polymarket_api_key_command_is_disabled_in_paper_mode(monkeypatch, tmp_path: Path) -> None:
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

    class FailBroker:
        @classmethod
        def derive_api_credentials_from_env(cls, *, nonce):
            raise AssertionError("paper mode must not derive live API credentials")

    monkeypatch.setattr("polymarket_copy_trading.service.LivePolymarketBroker", FailBroker)

    assert main(["derive-polymarket-api-key", "--config", str(config_path)]) == 2


def test_run_live_orders_can_dispatch_through_execution_service(monkeypatch, tmp_path: Path) -> None:
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
            called["remote_client"] = client

    def fake_dispatch(*, store, broker, limit, tick_size):
        called["broker"] = broker
        called["limit"] = limit
        called["tick_size"] = tick_size
        return {"planned": 0, "posted": 0, "rejected": 0, "errors": 0}

    monkeypatch.setenv("EXECUTION_GATEWAY_AUTH_SECRET", "env-secret")
    monkeypatch.setattr("polymarket_copy_trading.service.ExecutionServiceClient", FakeClient)
    monkeypatch.setattr("polymarket_copy_trading.service.RemoteExecutionBroker", FakeRemoteBroker)
    monkeypatch.setattr("polymarket_copy_trading.service.post_planned_live_order_intents", fake_dispatch)

    result = main(
        [
            "run-live-orders",
            "--config",
            str(config_path),
            "--limit",
            "3",
            "--tick-size",
            "0.001",
            "--execution-service-url",
            "http://127.0.0.1:8791",
        ]
    )

    assert result == 0
    assert called["base_url"] == "http://127.0.0.1:8791"
    assert called["auth_secret"] == "env-secret"
    assert isinstance(called["broker"], FakeRemoteBroker)
    assert called["limit"] == 3
    assert called["tick_size"] == "0.001"


def test_run_live_settlements_can_dispatch_through_execution_service(monkeypatch, tmp_path: Path) -> None:
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
            called["remote_client"] = client

    def fake_redeem(*, store, broker, limit):
        called["broker"] = broker
        called["limit"] = limit
        return {"planned": 0, "redeemed": 0, "errors": 0}

    monkeypatch.setenv("EXECUTION_GATEWAY_AUTH_SECRET", "env-secret")
    monkeypatch.setattr("polymarket_copy_trading.service.ExecutionServiceClient", FakeClient)
    monkeypatch.setattr("polymarket_copy_trading.service.RemoteExecutionBroker", FakeRemoteBroker)
    monkeypatch.setattr("polymarket_copy_trading.service.redeem_planned_settlement_intents", fake_redeem)

    result = main(
        [
            "run-live-settlements",
            "--config",
            str(config_path),
            "--limit",
            "4",
            "--execution-service-url",
            "http://127.0.0.1:8791",
        ]
    )

    assert result == 0
    assert called["base_url"] == "http://127.0.0.1:8791"
    assert called["auth_secret"] == "env-secret"
    assert isinstance(called["broker"], FakeRemoteBroker)
    assert called["limit"] == 4


def test_execution_gateway_commands_are_disabled_in_paper_mode(monkeypatch, tmp_path: Path) -> None:
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

    class FailBroker:
        @classmethod
        def from_env(cls):
            raise AssertionError("paper mode must not build live broker")

    monkeypatch.setattr("polymarket_copy_trading.service.LivePolymarketBroker", FailBroker)

    assert main(["run-execution-service", "--config", str(config_path)]) == 2
    assert (
        main(
            [
                "run-live-orders",
                "--config",
                str(config_path),
                "--execution-service-url",
                "http://127.0.0.1:8791",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "run-live-settlements",
                "--config",
                str(config_path),
                "--execution-service-url",
                "http://127.0.0.1:8791",
            ]
        )
        == 2
    )


def _base_command(
    *,
    command_id: str = "cmd-1",
    command_type: str = "place_order",
    idempotency_key: str = "idem-1",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command_id": command_id,
        "command_type": command_type,
        "idempotency_key": idempotency_key,
        "correlation_id": "corr-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "wallet_id": "wallet-1",
        "payload": {},
    }


def _place_order_command() -> dict[str, object]:
    return {
        **_base_command(),
        "payload": {
            "market_slug": "aec-mlb-team-a-team-b-2026-05-10",
            "outcome_side": "OUTCOME_SIDE_YES",
            "action": "ORDER_ACTION_BUY",
            "price": 0.42,
            "quantity": 12.5,
        },
    }


def _canonical_bytes(command: dict[str, object]) -> bytes:
    return json.dumps(command, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _signed_body(command: dict[str, object], secret: str) -> bytes:
    return _canonical_bytes(command)


def _signature(command: dict[str, object], secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _canonical_bytes(command), hashlib.sha256).hexdigest()


class FakeBroker:
    def __init__(self) -> None:
        self.orders: list[dict[str, object]] = []
        self.settlements: list[dict[str, object]] = []
        self.cancelled: list[str] = []
        self.status_requests: list[str] = []
        self.cancel_response: dict[str, object] | None = None

    def preflight(self) -> dict[str, object]:
        return {"status": "ok", "checks": [{"name": "fake_broker", "status": "ok", "detail": "ready"}]}

    def create_and_post_limit_order(self, **kwargs: object) -> LiveOrderPostResult:
        self.orders.append(kwargs)
        return LiveOrderPostResult(
            success=True,
            order_id="0xorder",
            status="accepted",
            raw_response={"orderID": "0xorder", "success": True, "status": "accepted"},
            error=None,
        )

    def redeem_settled_position(self, **kwargs: object) -> LiveSettlementResult:
        self.settlements.append(kwargs)
        return LiveSettlementResult(
            success=True,
            transaction_hash="0xsettled",
            status="settlement_confirmed",
            raw_response={"transactionHash": "0xsettled", "success": True},
            error=None,
        )

    def cancel_order(self, *, order_id: str, market_slug: str | None = None):
        self.cancelled.append(order_id)
        return self.cancel_response or {"status": "cancelled", "order_id": order_id}

    def get_order_status(self, *, order_id: str):
        self.status_requests.append(order_id)
        return {"id": order_id, "status": "filled"}


class SlowFakeBroker(FakeBroker):
    def create_and_post_limit_order(self, **kwargs: object) -> LiveOrderPostResult:
        time.sleep(0.1)
        return super().create_and_post_limit_order(**kwargs)


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or {"type": "execution_report", "status": "accepted"}
        self.url: str | None = None
        self.data: bytes | None = None
        self.headers: dict[str, str] = {}
        self.timeout: float | None = None

    def post(self, url: str, *, data: bytes, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.url = url
        self.data = data
        self.headers = headers
        self.timeout = timeout
        return FakeResponse(self.payload)


class FakeExecutionClient:
    def __init__(self, report: dict[str, object]) -> None:
        self.report = report
        self.commands: list[dict[str, object]] = []
        self.reconcile_order_ids: list[str] = []

    def execute(self, command: dict[str, object]) -> dict[str, object]:
        self.commands.append(command)
        return self.report

    def reconcile_orders(self, order_ids: list[str]) -> dict[str, object]:
        self.reconcile_order_ids = order_ids
        return self.report
