from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric import ed25519

from polymarket_copy_trading.polymarket_us_api import PolymarketUSClient, PolymarketUSCredentials


def test_polymarket_us_client_signs_timestamp_method_and_path() -> None:
    seed = bytes(range(32))
    client = PolymarketUSClient(
        credentials=PolymarketUSCredentials(key_id="key-1", secret_key=base64.b64encode(seed).decode("ascii")),
        session=FakeSession({"ok": True}),
    )

    headers = client.auth_headers("GET", "/v1/account/balances", timestamp_ms=1_777_777_777_000)

    assert headers["X-PM-Access-Key"] == "key-1"
    assert headers["X-PM-Timestamp"] == "1777777777000"
    public_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key()
    public_key.verify(
        base64.b64decode(headers["X-PM-Signature"]),
        b"1777777777000GET/v1/account/balances",
    )


def test_polymarket_us_client_posts_create_order_shape() -> None:
    session = FakeSession({"id": "order-1"})
    client = PolymarketUSClient(
        credentials=PolymarketUSCredentials(
            key_id="key-1",
            secret_key=base64.b64encode(bytes(range(32))).decode("ascii"),
        ),
        session=session,
    )

    response = client.create_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="NO",
        action="BUY",
        price=0.42,
        quantity=12.5,
    )

    assert response == {"id": "order-1"}
    assert session.method == "POST"
    assert session.url == "https://api.polymarket.us/v1/orders"
    assert session.headers["X-PM-Access-Key"] == "key-1"
    assert json.loads(session.data.decode("utf-8")) == {
        "action": "ORDER_ACTION_BUY",
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        "marketSlug": "aec-mlb-team-a-team-b-2026-05-10",
        "outcomeSide": "OUTCOME_SIDE_NO",
        "participateDontInitiate": False,
        "price": {"currency": "USD", "value": "0.42"},
        "quantity": 12.5,
        "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "type": "ORDER_TYPE_LIMIT",
    }


def test_polymarket_us_client_uses_gateway_for_market_reads() -> None:
    session = FakeSession({"market": {"slug": "abc"}})
    client = PolymarketUSClient(
        credentials=PolymarketUSCredentials(
            key_id="key-1",
            secret_key=base64.b64encode(bytes(range(32))).decode("ascii"),
        ),
        session=session,
    )

    assert client.get_market_by_slug("abc") == {"market": {"slug": "abc"}}
    assert session.method == "GET"
    assert session.url == "https://gateway.polymarket.us/v1/market/slug/abc"
    assert "X-PM-Access-Key" not in session.headers


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.method = ""
        self.url = ""
        self.headers: dict[str, str] = {}
        self.data = b""

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.method = method
        self.url = url
        self.headers = dict(kwargs.get("headers") or {})
        self.data = kwargs.get("data") or b""
        return FakeResponse(self.payload)
