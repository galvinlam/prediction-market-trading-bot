from __future__ import annotations

from dataclasses import dataclass
import base64
import binascii
import json
import os
import time
from typing import Any

import requests
from cryptography.hazmat.primitives.asymmetric import ed25519


POLYMARKET_US_API_URL = "https://api.polymarket.us"
POLYMARKET_US_GATEWAY_URL = "https://gateway.polymarket.us"


class PolymarketUSConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolymarketUSCredentials:
    key_id: str
    secret_key: str

    @classmethod
    def from_env(cls) -> "PolymarketUSCredentials":
        key_id = _first_env("POLYMARKET_US_KEY_ID", "POLYMARKET_KEY_ID", "POLYMARKET_US_KEY")
        secret_key = _first_env("POLYMARKET_US_SECRET_KEY", "POLYMARKET_SECRET_KEY", "POLYMARKET_US_SECRET")
        if not key_id:
            raise PolymarketUSConfigError("missing Polymarket US credential: POLYMARKET_US_KEY_ID")
        if not secret_key:
            raise PolymarketUSConfigError("missing Polymarket US credential: POLYMARKET_US_SECRET_KEY")
        return cls(key_id=key_id, secret_key=secret_key)


class PolymarketUSClient:
    def __init__(
        self,
        *,
        credentials: PolymarketUSCredentials,
        api_base_url: str | None = None,
        gateway_base_url: str | None = None,
        session: Any | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.credentials = credentials
        self.api_base_url = (api_base_url or os.environ.get("POLYMARKET_US_API_URL") or POLYMARKET_US_API_URL).rstrip(
            "/"
        )
        self.gateway_base_url = (
            gateway_base_url or os.environ.get("POLYMARKET_US_GATEWAY_URL") or POLYMARKET_US_GATEWAY_URL
        ).rstrip("/")
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self._private_key = ed25519.Ed25519PrivateKey.from_private_bytes(_secret_key_bytes(credentials.secret_key))

    @classmethod
    def from_env(cls, *, session: Any | None = None, timeout: float = 15.0) -> "PolymarketUSClient":
        return cls(credentials=PolymarketUSCredentials.from_env(), session=session, timeout=timeout)

    def auth_headers(self, method: str, path: str, *, timestamp_ms: int | None = None) -> dict[str, str]:
        clean_method = str(method).strip().upper()
        clean_path = _normalize_path(path)
        timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        message = f"{timestamp}{clean_method}{clean_path}".encode("utf-8")
        signature = base64.b64encode(self._private_key.sign(message)).decode("ascii")
        return {
            "X-PM-Access-Key": self.credentials.key_id,
            "X-PM-Timestamp": timestamp,
            "X-PM-Signature": signature,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        clean_method = str(method).strip().upper()
        clean_path = _normalize_path(path)
        headers = self.auth_headers(clean_method, clean_path) if authenticated else {"Content-Type": "application/json"}
        kwargs: dict[str, Any] = {"headers": headers, "timeout": self.timeout}
        if params:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["data"] = _canonical_json(json_body)
        response = self.session.request(clean_method, f"{self.api_base_url}{clean_path}", **kwargs)
        response.raise_for_status()
        return _response_json(response)

    def gateway_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_method = str(method).strip().upper()
        clean_path = _normalize_path(path)
        response = self.session.request(
            clean_method,
            f"{self.gateway_base_url}{clean_path}",
            params=params or None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return _response_json(response)

    def create_order(
        self,
        *,
        market_slug: str,
        outcome_side: str,
        action: str,
        price: float,
        quantity: float,
        order_type: str = "ORDER_TYPE_LIMIT",
        time_in_force: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        participate_dont_initiate: bool = False,
        manual_order_indicator: str = "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        synchronous_execution: bool | None = None,
        max_block_time: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "marketSlug": str(market_slug).strip(),
            "type": _normalize_order_type(order_type),
            "price": {"value": _price_value(price), "currency": "USD"},
            "quantity": float(quantity),
            "tif": _normalize_time_in_force(time_in_force),
            "outcomeSide": _normalize_outcome_side(outcome_side),
            "action": _normalize_action(action),
            "manualOrderIndicator": _normalize_manual_order_indicator(manual_order_indicator),
            "participateDontInitiate": bool(participate_dont_initiate),
        }
        if synchronous_execution is not None:
            payload["synchronousExecution"] = bool(synchronous_execution)
        if max_block_time is not None:
            payload["maxBlockTime"] = str(int(max_block_time))
        return self.request("POST", "/v1/orders", json_body=payload)

    def cancel_order(self, *, order_id: str, market_slug: str | None = None) -> dict[str, Any]:
        clean_order_id = str(order_id).strip()
        if not clean_order_id:
            raise ValueError("order_id is required")
        body: dict[str, Any] = {}
        if market_slug:
            body["marketSlug"] = str(market_slug).strip()
        return self.request("POST", f"/v1/order/{clean_order_id}/cancel", json_body=body)

    def get_order(self, *, order_id: str) -> dict[str, Any]:
        clean_order_id = str(order_id).strip()
        if not clean_order_id:
            raise ValueError("order_id is required")
        return self.request("GET", f"/v1/order/{clean_order_id}")

    def get_account_balances(self) -> dict[str, Any]:
        return self.request("GET", "/v1/account/balances")

    def get_positions(self, *, market_slug: str | None = None, limit: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if market_slug:
            params["market"] = market_slug
        if limit is not None:
            params["limit"] = int(limit)
        return self.request("GET", "/v1/portfolio/positions", params=params or None)

    def get_market_by_slug(self, market_slug: str) -> dict[str, Any]:
        clean_slug = str(market_slug).strip()
        if not clean_slug:
            raise ValueError("market_slug is required")
        return self.gateway_request("GET", f"/v1/market/slug/{clean_slug}")

    def get_market_bbo(self, market_slug: str) -> dict[str, Any]:
        clean_slug = str(market_slug).strip()
        if not clean_slug:
            raise ValueError("market_slug is required")
        return self.gateway_request("GET", f"/v1/markets/{clean_slug}/bbo")

    def get_market_book(self, market_slug: str) -> dict[str, Any]:
        clean_slug = str(market_slug).strip()
        if not clean_slug:
            raise ValueError("market_slug is required")
        return self.gateway_request("GET", f"/v1/markets/{clean_slug}/book")


def _secret_key_bytes(secret_key: str) -> bytes:
    clean = str(secret_key or "").strip()
    if not clean:
        raise PolymarketUSConfigError("Polymarket US secret key is empty")
    hex_text = clean[2:] if clean.lower().startswith("0x") else clean
    try:
        if len(hex_text) >= 64 and all(char in "0123456789abcdefABCDEF" for char in hex_text):
            decoded = bytes.fromhex(hex_text)
        else:
            decoded = base64.b64decode(clean, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PolymarketUSConfigError("Polymarket US secret key must be base64 or hex encoded") from exc
    if len(decoded) < 32:
        raise PolymarketUSConfigError("Polymarket US secret key must decode to at least 32 bytes")
    return decoded[:32]


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _response_json(response: Any) -> dict[str, Any]:
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def _normalize_path(path: str) -> str:
    clean = str(path).strip()
    if not clean:
        raise ValueError("path is required")
    return clean if clean.startswith("/") else f"/{clean}"


def _normalize_order_type(value: str) -> str:
    clean = str(value or "").strip().upper()
    aliases = {"LIMIT": "ORDER_TYPE_LIMIT", "MARKET": "ORDER_TYPE_MARKET"}
    clean = aliases.get(clean, clean)
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
    valid = {
        "TIME_IN_FORCE_DAY",
        "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "TIME_IN_FORCE_GOOD_TILL_DATE",
        "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "TIME_IN_FORCE_FILL_OR_KILL",
    }
    if clean not in valid:
        raise ValueError("time_in_force is not a supported Polymarket US value")
    return clean


def _normalize_outcome_side(value: str) -> str:
    clean = str(value or "").strip().upper()
    aliases = {"YES": "OUTCOME_SIDE_YES", "LONG": "OUTCOME_SIDE_YES", "NO": "OUTCOME_SIDE_NO", "SHORT": "OUTCOME_SIDE_NO"}
    clean = aliases.get(clean, clean)
    if clean not in {"OUTCOME_SIDE_YES", "OUTCOME_SIDE_NO"}:
        raise ValueError("outcome_side must be OUTCOME_SIDE_YES or OUTCOME_SIDE_NO")
    return clean


def _normalize_action(value: str) -> str:
    clean = str(value or "").strip().upper()
    aliases = {"BUY": "ORDER_ACTION_BUY", "SELL": "ORDER_ACTION_SELL"}
    clean = aliases.get(clean, clean)
    if clean not in {"ORDER_ACTION_BUY", "ORDER_ACTION_SELL"}:
        raise ValueError("action must be ORDER_ACTION_BUY or ORDER_ACTION_SELL")
    return clean


def _normalize_manual_order_indicator(value: str) -> str:
    clean = str(value or "").strip().upper()
    aliases = {"AUTO": "MANUAL_ORDER_INDICATOR_AUTOMATIC", "AUTOMATIC": "MANUAL_ORDER_INDICATOR_AUTOMATIC", "MANUAL": "MANUAL_ORDER_INDICATOR_MANUAL"}
    clean = aliases.get(clean, clean)
    if clean not in {"MANUAL_ORDER_INDICATOR_MANUAL", "MANUAL_ORDER_INDICATOR_AUTOMATIC"}:
        raise ValueError("manual_order_indicator is not a supported Polymarket US value")
    return clean


def _price_value(value: float) -> str:
    price = float(value)
    if price < 0.01 or price > 0.99:
        raise ValueError("price must be between 0.01 and 0.99 for Polymarket US")
    return f"{price:.6f}".rstrip("0").rstrip(".")


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return str(value)
    return None
