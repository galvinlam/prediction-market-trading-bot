from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable

from polymarket_copy_trading.polymarket_us_api import (
    POLYMARKET_US_API_URL,
    POLYMARKET_US_GATEWAY_URL,
    PolymarketUSClient,
    PolymarketUSCredentials,
)
from polymarket_copy_trading.store import Store


class LiveTradingConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class LivePolymarketCredentials:
    key_id: str = ""
    secret_key: str = ""
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    funder_address: str = ""

    def to_us_credentials(self) -> PolymarketUSCredentials:
        key_id = str(self.key_id or self.api_key or "").strip()
        secret_key = str(self.secret_key or self.api_secret or "").strip()
        if not key_id:
            raise LiveTradingConfigError("missing Polymarket US credential: POLYMARKET_US_KEY_ID")
        if not secret_key:
            raise LiveTradingConfigError("missing Polymarket US credential: POLYMARKET_US_SECRET_KEY")
        return PolymarketUSCredentials(key_id=key_id, secret_key=secret_key)


@dataclass(frozen=True)
class LiveLimitOrderRequest:
    market_slug: str
    outcome_side: str
    action: str
    price: float
    quantity: float
    order_type: str = "ORDER_TYPE_LIMIT"
    time_in_force: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    participate_dont_initiate: bool = False


@dataclass(frozen=True)
class LiveOrderPostResult:
    success: bool
    order_id: str | None
    status: str
    raw_response: Any | None
    error: str | None


@dataclass(frozen=True)
class LiveSettlementResult:
    success: bool
    transaction_hash: str | None
    status: str
    raw_response: Any | None
    error: str | None


OrderBuilder = Callable[[LiveLimitOrderRequest], Any]
SettlementExecutor = Callable[[dict[str, Any]], LiveSettlementResult]

class LivePolymarketBroker:
    def __init__(
        self,
        *,
        credentials: LivePolymarketCredentials,
        host: str = POLYMARKET_US_API_URL,
        gateway_url: str = POLYMARKET_US_GATEWAY_URL,
        chain_id: int = 137,
        signature_type: int = 2,
        client: Any | None = None,
        order_builder: OrderBuilder | None = None,
        settlement_executor: SettlementExecutor | None = None,
    ) -> None:
        self.credentials = credentials
        self.host = host.rstrip("/")
        self.gateway_url = gateway_url.rstrip("/")
        self.chain_id = chain_id
        self.signature_type = signature_type
        self._client = client
        self._order_builder = order_builder
        self._settlement_executor = settlement_executor

    @classmethod
    def from_env(cls) -> "LivePolymarketBroker":
        missing = [
            key
            for key in ("POLYMARKET_US_KEY_ID", "POLYMARKET_KEY_ID", "POLYMARKET_US_KEY")
            if not os.environ.get(key)
        ]
        missing_secret = [
            key
            for key in ("POLYMARKET_US_SECRET_KEY", "POLYMARKET_SECRET_KEY", "POLYMARKET_US_SECRET")
            if not os.environ.get(key)
        ]
        if len(missing) == 3:
            raise LiveTradingConfigError("missing live Polymarket credential: POLYMARKET_US_KEY_ID")
        if len(missing_secret) == 3:
            raise LiveTradingConfigError("missing live Polymarket credential: POLYMARKET_US_SECRET_KEY")
        key_id = _first_env("POLYMARKET_US_KEY_ID", "POLYMARKET_KEY_ID", "POLYMARKET_US_KEY") or ""
        secret_key = _first_env("POLYMARKET_US_SECRET_KEY", "POLYMARKET_SECRET_KEY", "POLYMARKET_US_SECRET") or ""
        return cls(
            credentials=LivePolymarketCredentials(
                key_id=str(key_id),
                secret_key=str(secret_key),
            ),
            host=os.environ.get("POLYMARKET_US_API_URL", POLYMARKET_US_API_URL),
            gateway_url=os.environ.get("POLYMARKET_US_GATEWAY_URL", POLYMARKET_US_GATEWAY_URL),
            chain_id=int(os.environ.get("POLYMARKET_CHAIN_ID", "137")),
            signature_type=int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "2")),
        )

    def client(self) -> Any:
        if self._client is None:
            self._client = PolymarketUSClient(
                credentials=self.credentials.to_us_credentials(),
                api_base_url=self.host,
                gateway_base_url=self.gateway_url,
            )
        return self._client

    def preflight(self) -> dict[str, Any]:
        checks: list[dict[str, str]] = [
            {
                "name": "polymarket_us_api_endpoint",
                "status": "ok" if self.host else "failed",
                "detail": self.host or "missing Polymarket US API endpoint",
            },
            {
                "name": "polymarket_us_gateway_endpoint",
                "status": "ok" if self.gateway_url else "failed",
                "detail": self.gateway_url or "missing Polymarket US gateway endpoint",
            },
            {
                "name": "polymarket_us_key_id",
                "status": "ok" if (self.credentials.key_id or self.credentials.api_key) else "failed",
                "detail": "configured" if (self.credentials.key_id or self.credentials.api_key) else "missing",
            },
            {
                "name": "polymarket_us_secret_key",
                "status": "ok" if (self.credentials.secret_key or self.credentials.api_secret) else "failed",
                "detail": "configured" if (self.credentials.secret_key or self.credentials.api_secret) else "missing",
            },
        ]
        try:
            client = self.client()
        except Exception as exc:
            checks.append({"name": "polymarket_us_client", "status": "failed", "detail": str(exc) or exc.__class__.__name__})
            return {"status": "failed", "checks": checks}

        for method_name in ("create_order", "get_order", "cancel_order", "get_account_balances"):
            checks.append(
                {
                    "name": f"polymarket_us_method_{method_name}",
                    "status": "ok" if callable(getattr(client, method_name, None)) else "failed",
                    "detail": "available" if callable(getattr(client, method_name, None)) else "missing",
                }
            )
        checks.append(
            {
                "name": "polymarket_us_settlement_redemption",
                "status": "skipped",
                "detail": "Polymarket US settlements are not redeemed through the legacy Polygon CTF relayer",
            }
        )
        failed = any(check["status"] == "failed" for check in checks)
        return {"status": "failed" if failed else "ok", "checks": checks}

    def create_and_post_limit_order(
        self,
        *,
        market_slug: str | None = None,
        outcome_side: str | None = None,
        action: str | None = None,
        side: str | None = None,
        price: float,
        size: float | None = None,
        quantity: float | None = None,
        order_type: str = "ORDER_TYPE_LIMIT",
        time_in_force: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        participate_dont_initiate: bool = False,
        **_: Any,
    ) -> LiveOrderPostResult:
        request = _validated_us_limit_order_request(
            market_slug=market_slug,
            outcome_side=outcome_side,
            action=action,
            side=side,
            price=price,
            size=size,
            quantity=quantity,
            order_type=order_type,
            time_in_force=time_in_force,
            participate_dont_initiate=participate_dont_initiate,
        )
        try:
            if self._order_builder is not None:
                response = self._order_builder(request)
            else:
                response = self.client().create_order(
                    market_slug=request.market_slug,
                    outcome_side=request.outcome_side,
                    action=request.action,
                    price=request.price,
                    quantity=request.quantity,
                    order_type=request.order_type,
                    time_in_force=request.time_in_force,
                    participate_dont_initiate=request.participate_dont_initiate,
                )
        except Exception as exc:
            return LiveOrderPostResult(
                success=False,
                order_id=None,
                status="exception",
                raw_response=None,
                error=str(exc) or exc.__class__.__name__,
            )
        return _normalize_order_post_response(response)

    def cancel_order(self, *, order_id: str | None = None, clob_order_id: str | None = None, market_slug: str | None = None) -> Any:
        clean_order_id = str(order_id or clob_order_id or "").strip()
        if not clean_order_id:
            raise ValueError("order_id is required")
        client = self.client()
        return client.cancel_order(order_id=clean_order_id, market_slug=market_slug)

    def get_order_status(self, *, order_id: str | None = None, clob_order_id: str | None = None) -> Any:
        clean_order_id = str(order_id or clob_order_id or "").strip()
        if not clean_order_id:
            raise ValueError("order_id is required")
        return self.client().get_order(order_id=clean_order_id)

    def get_tick_size(self, token_id: str) -> str | None:
        return None

    def redeem_settled_position(
        self,
        *,
        condition_id: str,
        token_id: str,
        resolution_price: float,
        size: float,
    ) -> LiveSettlementResult:
        request = _validated_settlement_request(
            condition_id=condition_id,
            token_id=token_id,
            resolution_price=resolution_price,
            size=size,
        )
        try:
            executor = self._settlement_executor or self._default_settlement_executor
            return executor(request)
        except Exception as exc:
            return LiveSettlementResult(
                success=False,
                transaction_hash=None,
                status="exception",
                raw_response=None,
                error=str(exc) or exc.__class__.__name__,
            )

    def _default_settlement_executor(self, request: dict[str, Any]) -> LiveSettlementResult:
        raise LiveTradingConfigError(
            "Polymarket US settlements are not redeemed through the legacy Polygon CTF relayer"
        )


def redeem_planned_settlement_intents(
    *,
    store: Store,
    broker: Any,
    limit: int = 50,
) -> dict[str, int]:
    intents = store.list_live_settlement_intents(status="planned", limit=limit)
    stats = {"planned": len(intents), "redeemed": 0, "errors": 0}
    for intent in intents:
        result = broker.redeem_settled_position(
            **(
                {
                    "condition_id": str(intent["condition_id"]),
                    "token_id": str(intent["token_id"]),
                    "resolution_price": float(intent["resolution_price"]),
                    "size": float(intent["quantity"]),
                }
                | _execution_context_kwargs(broker, "live_settlement_intent", intent)
            )
        )
        if result.success:
            store.update_live_settlement_intent_status(
                int(intent["id"]),
                status="redeemed",
                redemption_tx_hash=result.transaction_hash,
                response=result.raw_response,
            )
            stats["redeemed"] += 1
        else:
            store.update_live_settlement_intent_status(
                int(intent["id"]),
                status=result.status or "error",
                error=result.error,
                response=result.raw_response,
            )
            stats["errors"] += 1
    return stats


def post_planned_live_order_intents(
    *,
    store: Store,
    broker: Any,
    limit: int = 50,
    tick_size: str = "0.01",
) -> dict[str, int]:
    intents = store.list_live_order_intents(status="planned", limit=limit)
    stats = {"planned": len(intents), "posted": 0, "rejected": 0, "errors": 0}
    for intent in intents:
        metadata = store.get_market_metadata(str(intent["asset_id"]))
        if metadata is None:
            store.update_live_order_intent_status(
                int(intent["id"]),
                status="metadata_missing",
                error="market metadata is required for live order posting",
            )
            stats["errors"] += 1
            continue
        market_slug = str(metadata.get("market_slug") or "").strip()
        if not market_slug:
            store.update_live_order_intent_status(
                int(intent["id"]),
                status="metadata_missing",
                error="market metadata market_slug is required for Polymarket US live order posting",
            )
            stats["errors"] += 1
            continue
        outcome_side = _metadata_outcome_side(metadata)
        if outcome_side is None:
            store.update_live_order_intent_status(
                int(intent["id"]),
                status="metadata_missing",
                error="market metadata outcome_side is required for Polymarket US live order posting",
            )
            stats["errors"] += 1
            continue
        try:
            us_price = _us_yes_price(float(intent["price"]), outcome_side)
        except ValueError as exc:
            store.update_live_order_intent_status(
                int(intent["id"]),
                status="invalid_price",
                error=str(exc),
            )
            stats["errors"] += 1
            continue
        try:
            result = broker.create_and_post_limit_order(
                **(
                    {
                        "market_slug": market_slug,
                        "outcome_side": outcome_side,
                        "action": _order_action(str(intent["side"])),
                        "price": us_price,
                        "quantity": float(intent["size"]),
                        "order_type": "ORDER_TYPE_LIMIT",
                        "time_in_force": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                    }
                    | _execution_context_kwargs(broker, "live_order_intent", intent)
                )
            )
        except Exception as exc:
            result = LiveOrderPostResult(
                success=False,
                order_id=None,
                status="exception",
                raw_response=None,
                error=str(exc) or exc.__class__.__name__,
            )

        if result.success:
            store.update_live_order_intent_status(
                int(intent["id"]),
                status=result.status or "posted",
                clob_order_id=result.order_id,
                response=result.raw_response,
            )
            stats["posted"] += 1
            continue

        status = result.status or "error"
        store.update_live_order_intent_status(
            int(intent["id"]),
            status=status,
            error=result.error,
            response=result.raw_response,
        )
        if status == "rejected":
            stats["rejected"] += 1
        else:
            stats["errors"] += 1
    return stats


def reconcile_live_order_intents(
    *,
    store: Store,
    broker: Any,
    limit: int = 100,
    statuses: tuple[str, ...] = ("posted", "accepted", "open", "partially_filled", "partial", "pending"),
) -> dict[str, int]:
    intents = _live_order_intents_for_reconciliation(store=store, statuses=statuses, limit=limit)
    by_order_id = {str(intent["clob_order_id"]): intent for intent in intents}
    order_ids = list(by_order_id.keys())
    stats = {"open": len(order_ids), "updated": 0, "errors": 0}
    if not order_ids:
        return stats
    try:
        report = broker.reconcile_orders(order_ids)
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        for intent in intents:
            store.update_live_order_intent_status(int(intent["id"]), status=str(intent["status"]), error=error)
        stats["errors"] = len(intents)
        return stats

    for order_report in _reconciliation_orders(report):
        clob_order_id = str(_response_value(order_report, "clob_order_id", "order_id", "orderID", "id") or "").strip()
        intent = by_order_id.get(clob_order_id)
        if intent is None:
            continue
        error = _response_value(order_report, "error")
        raw_response = _response_value(order_report, "raw_response") or order_report
        if error is not None and str(error).strip():
            store.update_live_order_intent_status(
                int(intent["id"]),
                status=str(intent["status"]),
                error=str(error),
                response=raw_response,
            )
            stats["errors"] += 1
            continue
        status = str(_response_value(order_report, "status") or intent["status"]).strip().lower()
        store.update_live_order_intent_status(
            int(intent["id"]),
            status=status,
            clob_order_id=clob_order_id,
            response=raw_response,
        )
        stats["updated"] += 1
    return stats


def _live_order_intents_for_reconciliation(
    *,
    store: Store,
    statuses: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    intents: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    remaining = max(1, int(limit))
    for status in statuses:
        if remaining <= 0:
            break
        for intent in store.list_live_order_intents(status=status, limit=remaining):
            intent_id = int(intent["id"])
            clob_order_id = str(intent.get("clob_order_id") or "").strip()
            if intent_id in seen_ids or not clob_order_id:
                continue
            intents.append(intent)
            seen_ids.add(intent_id)
            remaining -= 1
            if remaining <= 0:
                break
    return intents


def _reconciliation_orders(report: Any) -> list[Any]:
    if isinstance(report, dict) and isinstance(report.get("orders"), list):
        return list(report["orders"])
    return []


def _validated_us_limit_order_request(
    *,
    market_slug: str | None,
    outcome_side: str | None,
    action: str | None,
    side: str | None,
    price: float,
    size: float | None,
    quantity: float | None,
    order_type: str = "ORDER_TYPE_LIMIT",
    time_in_force: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
    participate_dont_initiate: bool = False,
) -> LiveLimitOrderRequest:
    clean_market_slug = str(market_slug or "").strip()
    if not clean_market_slug:
        raise ValueError("market_slug is required")
    clean_outcome_side = _normalize_outcome_side(outcome_side)
    clean_action = _normalize_order_action(action or side)
    clean_price = float(price)
    if clean_price < 0.01 or clean_price > 0.99:
        raise ValueError("price must be between 0.01 and 0.99")
    if quantity is None and size is None:
        raise ValueError("quantity is required")
    clean_quantity = float(quantity if quantity is not None else size)
    if clean_quantity <= 0:
        raise ValueError("quantity must be positive")
    return LiveLimitOrderRequest(
        market_slug=clean_market_slug,
        outcome_side=clean_outcome_side,
        action=clean_action,
        price=clean_price,
        quantity=clean_quantity,
        order_type=_normalize_order_type(order_type),
        time_in_force=_normalize_time_in_force(time_in_force),
        participate_dont_initiate=bool(participate_dont_initiate),
    )


def _validated_settlement_request(
    *,
    condition_id: str,
    token_id: str,
    resolution_price: float,
    size: float,
) -> dict[str, Any]:
    clean_condition_id = str(condition_id).strip()
    if not clean_condition_id:
        raise ValueError("condition_id is required")
    clean_token_id = str(token_id).strip()
    if not clean_token_id:
        raise ValueError("token_id is required")
    clean_resolution_price = float(resolution_price)
    if clean_resolution_price not in {0.0, 1.0}:
        raise ValueError("resolution_price must be 0 or 1")
    clean_size = float(size)
    if clean_size <= 0:
        raise ValueError("size must be positive")
    return {
        "condition_id": clean_condition_id,
        "token_id": clean_token_id,
        "resolution_price": clean_resolution_price,
        "size": clean_size,
    }


def _normalize_outcome_side(value: str | None) -> str:
    clean = str(value or "").strip().upper()
    aliases = {
        "YES": "OUTCOME_SIDE_YES",
        "LONG": "OUTCOME_SIDE_YES",
        "BUY_LONG": "OUTCOME_SIDE_YES",
        "NO": "OUTCOME_SIDE_NO",
        "SHORT": "OUTCOME_SIDE_NO",
        "BUY_SHORT": "OUTCOME_SIDE_NO",
    }
    clean = aliases.get(clean, clean)
    if clean not in {"OUTCOME_SIDE_YES", "OUTCOME_SIDE_NO"}:
        raise ValueError("outcome_side must be OUTCOME_SIDE_YES or OUTCOME_SIDE_NO")
    return clean


def _normalize_order_action(value: str | None) -> str:
    clean = str(value or "").strip().upper()
    aliases = {"BUY": "ORDER_ACTION_BUY", "SELL": "ORDER_ACTION_SELL"}
    clean = aliases.get(clean, clean)
    if clean not in {"ORDER_ACTION_BUY", "ORDER_ACTION_SELL"}:
        raise ValueError("action must be ORDER_ACTION_BUY or ORDER_ACTION_SELL")
    return clean


def _normalize_order_type(value: str) -> str:
    clean = str(value or "").strip().upper()
    clean = {"LIMIT": "ORDER_TYPE_LIMIT", "MARKET": "ORDER_TYPE_MARKET"}.get(clean, clean)
    if clean not in {"ORDER_TYPE_LIMIT", "ORDER_TYPE_MARKET"}:
        raise ValueError("order_type must be ORDER_TYPE_LIMIT or ORDER_TYPE_MARKET")
    return clean


def _normalize_time_in_force(value: str) -> str:
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
    if clean not in {
        "TIME_IN_FORCE_DAY",
        "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "TIME_IN_FORCE_GOOD_TILL_DATE",
        "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "TIME_IN_FORCE_FILL_OR_KILL",
    }:
        raise ValueError("time_in_force is not a supported Polymarket US value")
    return clean


def _metadata_outcome_side(metadata: dict[str, Any]) -> str | None:
    direct = metadata.get("outcome_side")
    if direct:
        try:
            return _normalize_outcome_side(str(direct))
        except ValueError:
            return None
    outcome = str(metadata.get("outcome") or "").strip().lower()
    if outcome in {"yes", "long", "outcome_side_yes"}:
        return "OUTCOME_SIDE_YES"
    if outcome in {"no", "short", "outcome_side_no"}:
        return "OUTCOME_SIDE_NO"
    return None


def _order_action(side: str) -> str:
    return _normalize_order_action(side)


def _us_yes_price(source_price: float, outcome_side: str) -> float:
    price = float(source_price)
    if price <= 0 or price >= 1:
        raise ValueError("source price must be greater than 0 and less than 1")
    if _normalize_outcome_side(outcome_side) == "OUTCOME_SIDE_NO":
        price = 1.0 - price
    return round(price, 6)


def _normalize_order_post_response(response: Any) -> LiveOrderPostResult:
    order_id = _response_value(response, "orderID", "orderId", "order_id", "id")
    error = _response_value(response, "error", "errorMsg", "error_message", "message", "reason")
    success_value = _response_value(response, "success")
    status_value = _response_value(response, "status")

    success = _coerce_success(success_value, order_id=order_id, error=error)
    status = str(status_value).strip() if status_value is not None and str(status_value).strip() else ""
    if not status:
        status = "posted" if success else "rejected"

    return LiveOrderPostResult(
        success=success,
        order_id=str(order_id) if order_id is not None and str(order_id).strip() else None,
        status=status,
        raw_response=response,
        error=str(error) if error is not None and str(error).strip() else None,
    )


def _normalize_settlement_response(response: Any) -> LiveSettlementResult:
    tx_hash = _response_value(response, "transactionHash", "transaction_hash", "txHash", "tx_hash", "hash")
    error = _response_value(response, "error", "errorMsg", "error_message", "message", "reason")
    status_value = _response_value(response, "status", "state")
    success_value = _response_value(response, "success")
    success = _coerce_success(success_value, order_id=tx_hash, error=error)
    status = str(status_value).strip().lower() if status_value is not None and str(status_value).strip() else ""
    if not status:
        status = "redeemed" if success else "error"
    return LiveSettlementResult(
        success=success,
        transaction_hash=str(tx_hash) if tx_hash is not None and str(tx_hash).strip() else None,
        status=status,
        raw_response=response,
        error=str(error) if error is not None and str(error).strip() else None,
    )


def _resolve_tick_size(*, broker: Any, token_id: str, tick_size: str | None) -> str | None:
    clean_tick_size = str(tick_size or "").strip()
    if clean_tick_size and clean_tick_size.lower() != "auto":
        return clean_tick_size
    resolver = getattr(broker, "get_tick_size", None)
    if not callable(resolver):
        return None
    return _normalize_tick_size(resolver(token_id))


def _execution_context_kwargs(broker: Any, prefix: str, intent: dict[str, Any]) -> dict[str, str]:
    if not bool(getattr(broker, "supports_execution_context", False)):
        return {}
    intent_id = str(intent["id"])
    return {
        "idempotency_key": f"{prefix}:{intent_id}",
        "correlation_id": f"{prefix}:{intent_id}",
    }


def _normalize_tick_size(response: Any) -> str | None:
    value = _response_value(response, "tick_size", "tickSize", "minimum_tick_size", "minimumTickSize")
    if value is None and isinstance(response, str):
        value = response
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _response_value(response: Any, *keys: str) -> Any | None:
    if isinstance(response, dict):
        for key in keys:
            if key in response:
                return response[key]
        return None
    for key in keys:
        if hasattr(response, key):
            return getattr(response, key)
    return None


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def _coerce_success(success_value: Any | None, *, order_id: Any | None, error: Any | None) -> bool:
    if isinstance(success_value, bool):
        return success_value
    if isinstance(success_value, str):
        normalized = success_value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if success_value is not None:
        return bool(success_value)
    if error is not None and str(error).strip():
        return False
    return order_id is not None and str(order_id).strip() != ""
