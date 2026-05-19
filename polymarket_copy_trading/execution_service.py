from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any
from uuid import uuid4

import requests
from flask import Flask, jsonify, request

from polymarket_copy_trading.live_executor import LiveOrderPostResult, LivePolymarketBroker, LiveSettlementResult


SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_COMMAND_TYPES = {"place_order", "cancel_order", "redeem_settlement", "get_order_status"}
MUTATING_COMMAND_TYPES = {"place_order", "cancel_order", "redeem_settlement"}


class ExecutionReceiptStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists execution_receipts (
                    idempotency_key text primary key,
                    payload_hash text not null,
                    report_json text not null,
                    created_at text not null
                )
                """
            )

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_hash, report_json from execution_receipts where idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "payload_hash": str(row["payload_hash"]),
            "report": json.loads(str(row["report_json"])),
        }

    def record(self, *, idempotency_key: str, payload_hash: str, report: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into execution_receipts (idempotency_key, payload_hash, report_json, created_at)
                values (?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    payload_hash,
                    json.dumps(report, separators=(",", ":"), sort_keys=True),
                    _utc_now_iso(),
                ),
            )

    def execute_once(self, *, idempotency_key: str, payload_hash: str, executor: Any) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select payload_hash, report_json from execution_receipts where idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if str(row["payload_hash"]) != payload_hash:
                    conn.commit()
                    return {"error": "idempotency_key_payload_mismatch", "_http_status": 409}
                report = json.loads(str(row["report_json"]))
                report["duplicate_replayed"] = True
                conn.commit()
                return report
            report = executor()
            conn.execute(
                """
                insert into execution_receipts (idempotency_key, payload_hash, report_json, created_at)
                values (?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    payload_hash,
                    json.dumps(report, separators=(",", ":"), sort_keys=True),
                    _utc_now_iso(),
                ),
            )
            conn.commit()
            return report

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn


class InMemoryExecutionReceiptStore:
    def __init__(self) -> None:
        self._receipts: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        receipt = self._receipts.get(idempotency_key)
        if receipt is None:
            return None
        return {"payload_hash": receipt["payload_hash"], "report": dict(receipt["report"])}

    def record(self, *, idempotency_key: str, payload_hash: str, report: dict[str, Any]) -> None:
        self._receipts[idempotency_key] = {"payload_hash": payload_hash, "report": dict(report)}

    def execute_once(self, *, idempotency_key: str, payload_hash: str, executor: Any) -> dict[str, Any]:
        with self._lock:
            existing = self.get(idempotency_key)
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    return {"error": "idempotency_key_payload_mismatch", "_http_status": 409}
                report = dict(existing["report"])
                report["duplicate_replayed"] = True
                return report
            report = executor()
            self.record(idempotency_key=idempotency_key, payload_hash=payload_hash, report=report)
            return report


class ExecutionServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth_secret: str | None = None,
        timeout: float = 10.0,
        session: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_secret = auth_secret
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/v1/execution/commands", command)

    def preflight(self) -> dict[str, Any]:
        return self._post_json("/v1/execution/preflight", {"schema_version": SUPPORTED_SCHEMA_VERSION})

    def reconcile_orders(self, order_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        return self._post_json(
            "/v1/execution/reconcile/orders",
            {"schema_version": SUPPORTED_SCHEMA_VERSION, "order_ids": [str(order_id) for order_id in order_ids]},
        )

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = _canonical_json_bytes(payload)
        headers = {"Content-Type": "application/json"}
        if self.auth_secret:
            headers["X-Execution-Signature"] = _hmac_signature(body, self.auth_secret)
        response = self.session.post(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class RemoteExecutionBroker:
    supports_execution_context = True

    def __init__(
        self,
        *,
        client: ExecutionServiceClient,
        wallet_id: str = "default",
        command_ttl_seconds: int = 60,
    ) -> None:
        self.client = client
        self.wallet_id = wallet_id
        self.command_ttl_seconds = int(command_ttl_seconds)

    def create_and_post_limit_order(
        self,
        *,
        market_slug: str,
        outcome_side: str,
        action: str,
        price: float,
        quantity: float,
        order_type: str | None = None,
        time_in_force: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> LiveOrderPostResult:
        payload = {
            "market_slug": str(market_slug),
            "outcome_side": str(outcome_side),
            "action": str(action),
            "price": float(price),
            "quantity": float(quantity),
        }
        if order_type:
            payload["order_type"] = str(order_type).strip().upper()
        if time_in_force:
            payload["time_in_force"] = str(time_in_force).strip().upper()
        report = self.client.execute(
            self._command(
                "place_order",
                payload,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
        return LiveOrderPostResult(
            success=_report_success(report),
            order_id=_first_report_value(report, "order_id", "clob_order_id"),
            status=str(report.get("status") or "error"),
            raw_response=report.get("raw_response"),
            error=_report_value(report, "error"),
        )

    def cancel_order(
        self,
        *,
        order_id: str | None = None,
        clob_order_id: str | None = None,
        market_slug: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        payload = {"order_id": str(order_id or clob_order_id)}
        if market_slug:
            payload["market_slug"] = str(market_slug)
        return self.client.execute(
            self._command("cancel_order", payload, idempotency_key=idempotency_key, correlation_id=correlation_id)
        )

    def get_order_status(
        self,
        *,
        order_id: str | None = None,
        clob_order_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        payload = {"order_id": str(order_id or clob_order_id)}
        return self.client.execute(
            self._command("get_order_status", payload, idempotency_key=idempotency_key, correlation_id=correlation_id)
        )

    def reconcile_orders(self, order_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        return self.client.reconcile_orders([str(order_id) for order_id in order_ids])

    def redeem_settled_position(
        self,
        *,
        condition_id: str,
        token_id: str,
        resolution_price: float,
        size: float,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> LiveSettlementResult:
        payload = {
            "condition_id": str(condition_id),
            "token_id": str(token_id),
            "resolution_price": float(resolution_price),
            "size": float(size),
        }
        report = self.client.execute(
            self._command(
                "redeem_settlement",
                payload,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
        return LiveSettlementResult(
            success=_report_success(report),
            transaction_hash=_report_value(report, "transaction_hash"),
            status=str(report.get("status") or "error"),
            raw_response=report.get("raw_response"),
            error=_report_value(report, "error"),
        )

    def _command(
        self,
        command_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.command_ttl_seconds)
        clean_idempotency_key = (
            str(idempotency_key).strip()
            if idempotency_key
            else f"{command_type}:{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"
        )
        clean_correlation_id = str(correlation_id).strip() if correlation_id else f"corr_{uuid4().hex}"
        return {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "command_id": f"cmd_{uuid4().hex}",
            "command_type": command_type,
            "idempotency_key": clean_idempotency_key,
            "correlation_id": clean_correlation_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "wallet_id": self.wallet_id,
            "payload": payload,
        }


def create_execution_app(
    *,
    broker: Any | None = None,
    auth_secret: str | None = None,
    receipt_store: Any | None = None,
    execution_enabled: bool = True,
) -> Flask:
    app = Flask(__name__)
    command_broker = broker or LivePolymarketBroker.from_env()
    receipts = receipt_store or InMemoryExecutionReceiptStore()

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "polymarket-execution-gateway",
                "execution_enabled": bool(execution_enabled),
            }
        )

    @app.post("/v1/execution/preflight")
    def preflight():
        parsed = _authenticated_json_request(auth_secret)
        if isinstance(parsed, tuple):
            return parsed
        if parsed.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            return jsonify({"error": "unsupported_schema_version"}), 400
        return jsonify(_preflight_report(command_broker, execution_enabled=execution_enabled))

    @app.post("/v1/execution/reconcile/orders")
    def reconcile_orders():
        parsed = _authenticated_json_request(auth_secret)
        if isinstance(parsed, tuple):
            return parsed
        if parsed.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            return jsonify({"error": "unsupported_schema_version"}), 400
        order_ids = parsed.get("order_ids")
        validation_error = _validate_order_ids(order_ids)
        if validation_error:
            return jsonify({"error": validation_error}), 400
        return jsonify(_reconcile_order_report(command_broker, [str(order_id).strip() for order_id in order_ids]))

    @app.post("/v1/execution/commands")
    def execute_command():
        command = _authenticated_json_request(auth_secret)
        if isinstance(command, tuple):
            return command

        validation_error = _validate_command(command)
        if validation_error:
            return jsonify({"error": validation_error}), 400
        if not bool(execution_enabled) and str(command["command_type"]) in MUTATING_COMMAND_TYPES:
            return jsonify({"error": "execution_disabled"}), 403

        idempotency_key = str(command["idempotency_key"])
        payload_hash = _payload_hash(command)
        execute_once = getattr(receipts, "execute_once", None)
        if callable(execute_once):
            report = execute_once(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                executor=lambda: _dispatch_command(command_broker, command),
            )
            status = report.pop("_http_status", None)
            if status is not None:
                return jsonify(report), int(status)
            return jsonify(report)

        report = _dispatch_with_legacy_receipt_store(
            receipts=receipts,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            command_broker=command_broker,
            command=command,
        )
        status = report.pop("_http_status", None)
        if status is not None:
            return jsonify(report), int(status)
        return jsonify(report)

    return app


def _dispatch_with_legacy_receipt_store(
    *,
    receipts: Any,
    idempotency_key: str,
    payload_hash: str,
    command_broker: Any,
    command: dict[str, Any],
) -> dict[str, Any]:
    existing = receipts.get(idempotency_key)
    if existing is not None:
        if existing["payload_hash"] != payload_hash:
            return {"error": "idempotency_key_payload_mismatch", "_http_status": 409}
        report = dict(existing["report"])
        report["duplicate_replayed"] = True
        return report
    report = _dispatch_command(command_broker, command)
    receipts.record(idempotency_key=idempotency_key, payload_hash=payload_hash, report=report)
    return report


def _authenticated_json_request(auth_secret: str | None) -> dict[str, Any] | tuple[Any, int]:
    raw_body = request.get_data() or b""
    if auth_secret and not _valid_signature(raw_body, auth_secret, request.headers.get("X-Execution-Signature")):
        return jsonify({"error": "invalid_signature"}), 401

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"error": "invalid_json"}), 400
    if not isinstance(payload, dict):
        return jsonify({"error": "request_must_be_object"}), 400
    return payload


def _validate_command(command: dict[str, Any]) -> str | None:
    if command.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return "unsupported_schema_version"
    for key in ("command_id", "command_type", "idempotency_key", "correlation_id", "expires_at", "payload"):
        if key not in command or command[key] in (None, ""):
            return f"missing_{key}"
    if command["command_type"] not in SUPPORTED_COMMAND_TYPES:
        return "unsupported_command_type"
    if not isinstance(command["payload"], dict):
        return "payload_must_be_object"
    try:
        expires_at = _parse_datetime(str(command["expires_at"]))
    except ValueError:
        return "invalid_expires_at"
    if expires_at <= datetime.now(timezone.utc):
        return "command_expired"
    payload_error = _validate_payload(str(command["command_type"]), command["payload"])
    if payload_error:
        return payload_error
    return None


def _validate_payload(command_type: str, payload: dict[str, Any]) -> str | None:
    required_by_type = {
        "place_order": ("market_slug", "outcome_side", "action", "price", "quantity"),
        "cancel_order": ("order_id",),
        "redeem_settlement": ("condition_id", "token_id", "resolution_price", "size"),
        "get_order_status": ("order_id",),
    }
    payload = _normalized_command_payload(command_type, payload)
    for key in required_by_type[command_type]:
        if key not in payload or payload[key] in (None, ""):
            return f"missing_payload_{key}"
    if command_type == "place_order":
        if _normalize_outcome_side(payload["outcome_side"]) is None:
            return "invalid_payload_outcome_side"
        if _normalize_action(payload["action"]) is None:
            return "invalid_payload_action"
        price = _float_payload(payload["price"])
        if price is None or price < 0.01 or price > 0.99:
            return "invalid_payload_price"
        quantity = _float_payload(payload["quantity"])
        if quantity is None or quantity <= 0:
            return "invalid_payload_quantity"
        if payload.get("order_type") is not None and _normalize_order_type(payload["order_type"]) is None:
            return "invalid_payload_order_type"
        if payload.get("time_in_force") is not None and _normalize_time_in_force(payload["time_in_force"]) is None:
            return "invalid_payload_time_in_force"
    if command_type == "redeem_settlement":
        resolution_price = _float_payload(payload["resolution_price"])
        if resolution_price is None or resolution_price not in {0.0, 1.0}:
            return "invalid_payload_resolution_price"
        size = _float_payload(payload["size"])
        if size is None or size <= 0:
            return "invalid_payload_size"
    return None


def _validate_order_ids(order_ids: Any) -> str | None:
    if not isinstance(order_ids, list):
        return "order_ids_must_be_list"
    if not order_ids:
        return "order_ids_required"
    if len(order_ids) > 100:
        return "too_many_order_ids"
    for order_id in order_ids:
        if not str(order_id).strip():
            return "invalid_order_id"
    return None


def _preflight_report(broker: Any, *, execution_enabled: bool) -> dict[str, Any]:
    method = getattr(broker, "preflight", None)
    if callable(method):
        try:
            broker_report = method()
        except Exception as exc:
            broker_report = {
                "status": "failed",
                "checks": [
                    {
                        "name": "broker_preflight",
                        "status": "failed",
                        "detail": str(exc) or exc.__class__.__name__,
                    }
                ],
            }
    else:
        broker_report = {
            "status": "ok",
            "checks": [{"name": "broker_preflight", "status": "skipped", "detail": "broker has no preflight method"}],
        }
    broker_dict = broker_report if isinstance(broker_report, dict) else {}
    checks = broker_dict.get("checks")
    clean_checks = checks if isinstance(checks, list) else []
    failed = any(str(check.get("status") or "").lower() == "failed" for check in clean_checks if isinstance(check, dict))
    status = "failed" if failed else str(broker_dict.get("status") or "ok")
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "type": "preflight_report",
        "status": status,
        "execution_enabled": bool(execution_enabled),
        "checks": clean_checks,
    }


def _reconcile_order_report(broker: Any, order_ids: list[str]) -> dict[str, Any]:
    orders = []
    for order_id in order_ids:
        orders.append(_order_status_result(broker, order_id))
    errors = sum(1 for order in orders if order.get("error"))
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "type": "order_reconciliation_report",
        "status": "ok" if errors == 0 else "partial",
        "orders": orders,
        "errors": errors,
    }


def _order_status_result(broker: Any, order_id: str) -> dict[str, Any]:
    method = getattr(broker, "get_order_status", None)
    if not callable(method):
        return {
            "order_id": order_id,
            "clob_order_id": order_id,
            "status": "unknown",
            "raw_response": None,
            "error": "broker does not support get_order_status",
        }
    try:
        response = method(order_id=order_id)
    except Exception as exc:
        return {
            "order_id": order_id,
            "clob_order_id": order_id,
            "status": "unknown",
            "raw_response": None,
            "error": str(exc) or exc.__class__.__name__,
        }
    resolved_order_id = _response_value(response, "order_id", "clob_order_id", "orderID", "orderId", "id") or order_id
    return {
        "order_id": resolved_order_id,
        "clob_order_id": resolved_order_id,
        "status": _response_value(response, "status") or "unknown",
        "raw_response": response,
        "error": _response_value(response, "error"),
    }


def _dispatch_command(broker: Any, command: dict[str, Any]) -> dict[str, Any]:
    command_type = str(command["command_type"])
    payload = _normalized_command_payload(command_type, command["payload"])
    if command_type == "place_order":
        kwargs = {
            "market_slug": str(payload["market_slug"]),
            "outcome_side": str(payload["outcome_side"]),
            "action": str(payload["action"]),
            "price": float(payload["price"]),
            "quantity": float(payload["quantity"]),
        }
        if payload.get("order_type") is not None:
            kwargs["order_type"] = str(payload["order_type"]).strip().upper()
        if payload.get("time_in_force") is not None:
            kwargs["time_in_force"] = str(payload["time_in_force"]).strip().upper()
        result = broker.create_and_post_limit_order(**kwargs)
        return _order_report(command, result)
    if command_type == "redeem_settlement":
        result = broker.redeem_settled_position(
            condition_id=str(payload["condition_id"]),
            token_id=str(payload["token_id"]),
            resolution_price=float(payload["resolution_price"]),
            size=float(payload["size"]),
        )
        return _settlement_report(command, result)
    if command_type == "cancel_order":
        return _generic_broker_report(
            command,
            method_name="cancel_order",
            kwargs={"order_id": str(payload["order_id"]), "market_slug": payload.get("market_slug")},
            broker=broker,
        )
    if command_type == "get_order_status":
        return _generic_broker_report(
            command,
            method_name="get_order_status",
            kwargs={"order_id": str(payload["order_id"])},
            broker=broker,
        )
    raise ValueError(f"unsupported command type: {command_type}")


def _order_report(command: dict[str, Any], result: LiveOrderPostResult) -> dict[str, Any]:
    status = result.status or ("accepted" if result.success else "rejected")
    return _base_report(command) | {
        "status": status,
        "order_id": result.order_id,
        "clob_order_id": result.order_id,
        "transaction_hash": None,
        "raw_response": result.raw_response,
        "error": result.error,
    }


def _settlement_report(command: dict[str, Any], result: LiveSettlementResult) -> dict[str, Any]:
    status = result.status or ("settlement_confirmed" if result.success else "failed_retryable")
    return _base_report(command) | {
        "status": status,
        "order_id": None,
        "clob_order_id": None,
        "transaction_hash": result.transaction_hash,
        "raw_response": result.raw_response,
        "error": result.error,
    }


def _generic_broker_report(
    command: dict[str, Any],
    *,
    method_name: str,
    kwargs: dict[str, Any],
    broker: Any,
) -> dict[str, Any]:
    method = getattr(broker, method_name, None)
    if not callable(method):
        return _base_report(command) | {
            "status": "failed_terminal",
            "order_id": kwargs.get("order_id"),
            "clob_order_id": kwargs.get("order_id"),
            "transaction_hash": None,
            "raw_response": None,
            "error": f"broker does not support {method_name}",
        }
    try:
        response = method(**kwargs)
    except Exception as exc:
        return _base_report(command) | {
            "status": "failed_retryable",
            "order_id": kwargs.get("order_id"),
            "clob_order_id": kwargs.get("order_id"),
            "transaction_hash": None,
            "raw_response": None,
            "error": str(exc) or exc.__class__.__name__,
        }
    status = _response_value(response, "status") or "accepted"
    order_id = _response_value(response, "order_id", "clob_order_id", "orderID", "orderId", "id") or kwargs.get("order_id")
    if method_name == "cancel_order":
        cancelled_order_id = _response_value(response, "canceled", "cancelled")
        if cancelled_order_id is not None:
            status = "cancelled"
            order_id = cancelled_order_id
    return _base_report(command) | {
        "status": status,
        "order_id": order_id,
        "clob_order_id": order_id,
        "transaction_hash": _response_value(response, "transaction_hash", "transactionHash"),
        "raw_response": response,
        "error": _response_value(response, "error"),
    }


def _base_report(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "type": "execution_report",
        "report_id": f"rpt_{uuid4().hex}",
        "command_id": str(command["command_id"]),
        "command_type": str(command["command_type"]),
        "idempotency_key": str(command["idempotency_key"]),
        "correlation_id": str(command["correlation_id"]),
        "created_at": _utc_now_iso(),
        "duplicate_replayed": False,
    }


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _payload_hash(command: dict[str, Any]) -> str:
    fingerprint = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "command_type": str(command["command_type"]),
        "wallet_id": str(command.get("wallet_id") or ""),
        "payload": _normalized_payload_for_hash(str(command["command_type"]), command["payload"]),
    }
    return hashlib.sha256(_canonical_json_bytes(fingerprint)).hexdigest()


def _normalized_payload_for_hash(command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalized_command_payload(command_type, payload)
    if command_type == "place_order":
        return {
            "market_slug": str(payload["market_slug"]),
            "outcome_side": str(payload["outcome_side"]),
            "action": str(payload["action"]),
            "price": float(payload["price"]),
            "quantity": float(payload["quantity"]),
            "order_type": str(payload.get("order_type") or "ORDER_TYPE_LIMIT").strip().upper(),
            "time_in_force": str(payload.get("time_in_force") or "TIME_IN_FORCE_GOOD_TILL_CANCEL").strip().upper(),
        }
    if command_type == "redeem_settlement":
        return {
            "condition_id": str(payload["condition_id"]),
            "token_id": str(payload["token_id"]),
            "resolution_price": float(payload["resolution_price"]),
            "size": float(payload["size"]),
        }
    if command_type in {"cancel_order", "get_order_status"}:
        normalized = {"order_id": str(payload["order_id"])}
        if command_type == "cancel_order" and payload.get("market_slug"):
            normalized["market_slug"] = str(payload["market_slug"])
        return normalized
    return dict(payload)


def _normalized_command_payload(command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if command_type == "place_order":
        if "market_slug" not in normalized and "marketSlug" in normalized:
            normalized["market_slug"] = normalized["marketSlug"]
        if "outcome_side" not in normalized and "outcomeSide" in normalized:
            normalized["outcome_side"] = normalized["outcomeSide"]
        if "action" not in normalized and "side" in normalized:
            side = str(normalized["side"]).strip().lower()
            if side in {"buy", "sell"}:
                normalized["action"] = f"ORDER_ACTION_{side.upper()}"
        if "quantity" not in normalized and "size" in normalized:
            normalized["quantity"] = normalized["size"]
        if "order_type" not in normalized and "type" in normalized:
            normalized["order_type"] = normalized["type"]
        if "time_in_force" not in normalized and "tif" in normalized:
            normalized["time_in_force"] = normalized["tif"]
    if command_type in {"cancel_order", "get_order_status"}:
        if "order_id" not in normalized and "clob_order_id" in normalized:
            normalized["order_id"] = normalized["clob_order_id"]
        if "market_slug" not in normalized and "marketSlug" in normalized:
            normalized["market_slug"] = normalized["marketSlug"]
    return normalized


def _normalize_outcome_side(value: Any) -> str | None:
    clean = str(value or "").strip().upper()
    aliases = {"YES": "OUTCOME_SIDE_YES", "LONG": "OUTCOME_SIDE_YES", "NO": "OUTCOME_SIDE_NO", "SHORT": "OUTCOME_SIDE_NO"}
    clean = aliases.get(clean, clean)
    return clean if clean in {"OUTCOME_SIDE_YES", "OUTCOME_SIDE_NO"} else None


def _normalize_action(value: Any) -> str | None:
    clean = str(value or "").strip().upper()
    aliases = {"BUY": "ORDER_ACTION_BUY", "SELL": "ORDER_ACTION_SELL"}
    clean = aliases.get(clean, clean)
    return clean if clean in {"ORDER_ACTION_BUY", "ORDER_ACTION_SELL"} else None


def _normalize_order_type(value: Any) -> str | None:
    clean = str(value or "").strip().upper()
    clean = {"LIMIT": "ORDER_TYPE_LIMIT", "MARKET": "ORDER_TYPE_MARKET"}.get(clean, clean)
    return clean if clean in {"ORDER_TYPE_LIMIT", "ORDER_TYPE_MARKET"} else None


def _normalize_time_in_force(value: Any) -> str | None:
    clean = str(value or "").strip().upper()
    aliases = {
        "DAY": "TIME_IN_FORCE_DAY",
        "GTC": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "GTD": "TIME_IN_FORCE_GOOD_TILL_DATE",
        "IOC": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "FAK": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "FOK": "TIME_IN_FORCE_FILL_OR_KILL",
    }
    clean = aliases.get(clean, clean)
    valid = {
        "TIME_IN_FORCE_DAY",
        "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "TIME_IN_FORCE_GOOD_TILL_DATE",
        "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "TIME_IN_FORCE_FILL_OR_KILL",
    }
    return clean if clean in valid else None


def _hmac_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _valid_signature(body: bytes, secret: str, provided_signature: str | None) -> bool:
    if not provided_signature:
        return False
    expected = _hmac_signature(body, secret)
    return hmac.compare_digest(expected, provided_signature)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response_value(response: Any, *keys: str) -> Any | None:
    if isinstance(response, dict):
        for key in keys:
            if key in response:
                return response[key]
    for key in keys:
        if hasattr(response, key):
            return getattr(response, key)
    return None


def _float_payload(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _report_success(report: dict[str, Any]) -> bool:
    if report.get("error"):
        return False
    status = str(report.get("status") or "").lower()
    return status not in {"rejected", "expired", "failed_retryable", "failed_terminal", "exception", "error"}


def _report_value(report: dict[str, Any], key: str) -> str | None:
    value = report.get(key)
    if value is None or str(value).strip() == "":
        return None
    return str(value)


def _first_report_value(report: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _report_value(report, key)
        if value:
            return value
    return None
