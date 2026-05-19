from pathlib import Path

import pytest

from polymarket_copy_trading.config import WalletConfig
from polymarket_copy_trading.live_executor import LiveOrderPostResult, LivePolymarketBroker, LiveTradingConfigError
from polymarket_copy_trading.service import build_store, prepare_runtime_store
from polymarket_copy_trading.store import Store

from tests.test_store import make_fill, make_source


def test_live_store_imports_wallets_without_importing_paper_ledger(tmp_path: Path) -> None:
    paper_store = Store(tmp_path / "paper.sqlite3")
    paper_store.initialize()
    paper_store.sync_wallets(
        (
            WalletConfig(
                name="dashboard_wallet",
                address="0x1111111111111111111111111111111111111111",
                enabled=True,
                repeat_buy_strategy_enabled=True,
            ),
        )
    )
    paper_store.insert_source_trade(make_source())
    paper_store.record_paper_fill(
        make_fill(),
        cash_after_usdc=900,
        position_quantity=190.476190,
        avg_entry_price=0.525,
    )

    live_store = Store(tmp_path / "live.sqlite3")
    live_store.initialize()

    copied = live_store.import_wallets_if_empty(paper_store)

    assert copied is True
    assert live_store.list_wallets()[0]["name"] == "dashboard_wallet"
    assert live_store.list_wallets()[0]["repeat_buy_strategy_enabled"] is True
    assert live_store.list_trades() == []
    assert live_store.list_positions() == []


def test_live_store_does_not_overwrite_existing_wallets(tmp_path: Path) -> None:
    paper_store = Store(tmp_path / "paper.sqlite3")
    paper_store.initialize()
    paper_store.sync_wallets((WalletConfig(name="paper", address="0x1111111111111111111111111111111111111111"),))

    live_store = Store(tmp_path / "live.sqlite3")
    live_store.initialize()
    live_store.sync_wallets((WalletConfig(name="live", address="0x2222222222222222222222222222222222222222"),))

    copied = live_store.import_wallets_if_empty(paper_store)

    assert copied is False
    assert [wallet["name"] for wallet in live_store.list_wallets()] == ["live"]


def test_live_broker_fails_closed_without_required_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("POLYMARKET_US_KEY_ID", "POLYMARKET_KEY_ID", "POLYMARKET_US_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key in ("POLYMARKET_US_SECRET_KEY", "POLYMARKET_SECRET_KEY", "POLYMARKET_US_SECRET"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(LiveTradingConfigError, match="POLYMARKET_US_KEY_ID"):
        LivePolymarketBroker.from_env()


def test_live_broker_posts_limit_order_through_injected_us_client() -> None:
    posted: list[dict[str, object]] = []

    class FakeClient:
        def create_order(self, **kwargs: object) -> dict[str, object]:
            posted.append(kwargs)
            return {"id": "order-us-1"}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    result = broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
        action="ORDER_ACTION_BUY",
        price=0.45,
        quantity=10,
    )

    assert result == LiveOrderPostResult(
        success=True,
        order_id="order-us-1",
        status="posted",
        raw_response={"id": "order-us-1"},
        error=None,
    )
    assert posted == [
        {
            "market_slug": "aec-mlb-team-a-team-b-2026-05-10",
            "outcome_side": "OUTCOME_SIDE_YES",
            "action": "ORDER_ACTION_BUY",
            "price": 0.45,
            "quantity": 10.0,
            "order_type": "ORDER_TYPE_LIMIT",
            "time_in_force": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
            "participate_dont_initiate": False,
        }
    ]


def test_live_broker_posts_order_type_and_time_in_force() -> None:
    posted: list[dict[str, object]] = []

    class FakeClient:
        def create_order(self, **kwargs: object) -> dict[str, object]:
            posted.append(kwargs)
            return {"id": "order-us-1"}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    result = broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_NO",
        action="SELL",
        price=0.45,
        quantity=10,
        order_type="LIMIT",
        time_in_force="IOC",
    )

    assert result.success is True
    assert posted[0]["outcome_side"] == "OUTCOME_SIDE_NO"
    assert posted[0]["action"] == "ORDER_ACTION_SELL"
    assert posted[0]["order_type"] == "ORDER_TYPE_LIMIT"
    assert posted[0]["time_in_force"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"


def test_live_broker_cancel_order_uses_us_client() -> None:
    cancelled: list[str] = []

    class FakeClient:
        def cancel_order(self, *, order_id: str, market_slug: str | None = None) -> dict[str, object]:
            cancelled.append(order_id)
            return {"status": "cancelled", "id": order_id}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    response = broker.cancel_order(order_id="order-us-1")

    assert response == {"status": "cancelled", "id": "order-us-1"}
    assert cancelled == ["order-us-1"]


def test_live_broker_get_order_status_uses_injected_us_client() -> None:
    requested: list[str] = []

    class FakeClient:
        def get_order(self, *, order_id: str) -> dict[str, object]:
            requested.append(order_id)
            return {"id": order_id, "status": "filled"}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    response = broker.get_order_status(order_id="order-us-1")

    assert response == {"id": "order-us-1", "status": "filled"}
    assert requested == ["order-us-1"]


def test_live_broker_preflight_checks_us_client_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def create_order(self, **kwargs: object) -> dict[str, object]:
            return {"id": "order-us-1"}

        def get_order(self, *, order_id: str) -> dict[str, object]:
            return {"id": order_id}

        def cancel_order(self, *, order_id: str, market_slug: str | None = None) -> dict[str, object]:
            return {"canceled": order_id}

        def get_account_balances(self) -> dict[str, object]:
            return {"balances": []}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    report = broker.preflight()

    assert report["status"] == "ok"
    assert {check["name"]: check["status"] for check in report["checks"]} == {
        "polymarket_us_api_endpoint": "ok",
        "polymarket_us_gateway_endpoint": "ok",
        "polymarket_us_key_id": "ok",
        "polymarket_us_secret_key": "ok",
        "polymarket_us_method_create_order": "ok",
        "polymarket_us_method_get_order": "ok",
        "polymarket_us_method_cancel_order": "ok",
        "polymarket_us_method_get_account_balances": "ok",
        "polymarket_us_settlement_redemption": "skipped",
    }


def test_live_broker_env_uses_single_wallet_and_endpoint_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYMARKET_US_KEY_ID", "key-id")
    monkeypatch.setenv("POLYMARKET_US_SECRET_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("POLYMARKET_US_API_URL", "https://example-api")
    monkeypatch.setenv("POLYMARKET_US_GATEWAY_URL", "https://example-gateway")
    monkeypatch.setenv("POLYMARKET_CHAIN_ID", "80002")
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "1")

    broker = LivePolymarketBroker.from_env()

    assert broker.credentials.key_id == "key-id"
    assert broker.credentials.secret_key == "0x" + "1" * 64
    assert broker.host == "https://example-api"
    assert broker.gateway_url == "https://example-gateway"
    assert broker.chain_id == 80002
    assert broker.signature_type == 1


def test_live_broker_normalizes_rejected_limit_order_response() -> None:
    class FakeClient:
        def create_order(self, **kwargs: object) -> dict[str, object]:
            return {"success": False, "error": "insufficient balance", "status": "rejected"}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    result = broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_NO",
        action="ORDER_ACTION_SELL",
        price=0.45,
        quantity=10,
    )

    assert result.success is False
    assert result.order_id is None
    assert result.status == "rejected"
    assert result.raw_response == {"success": False, "error": "insufficient balance", "status": "rejected"}
    assert result.error == "insufficient balance"


def test_live_broker_normalizes_order_id_without_success_flag() -> None:
    class FakeClient:
        def create_order(self, **kwargs: object) -> dict[str, object]:
            return {"orderId": "def"}

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    result = broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
        action="ORDER_ACTION_BUY",
        price=0.45,
        quantity=10,
    )

    assert result.success is True
    assert result.order_id == "def"
    assert result.status == "posted"
    assert result.raw_response == {"orderId": "def"}
    assert result.error is None


def test_live_broker_normalizes_limit_order_post_exception() -> None:
    class FakeClient:
        def create_order(self, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("polymarket us unavailable")

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    result = broker.create_and_post_limit_order(
        market_slug="aec-mlb-team-a-team-b-2026-05-10",
        outcome_side="OUTCOME_SIDE_YES",
        action="ORDER_ACTION_BUY",
        price=0.45,
        quantity=10,
    )

    assert result.success is False
    assert result.order_id is None
    assert result.status == "exception"
    assert result.raw_response is None
    assert result.error == "polymarket us unavailable"


def test_live_broker_rejects_invalid_limit_order_before_posting() -> None:
    class FakeClient:
        def create_and_post_order(self, order: object, *, options: object) -> dict[str, object]:
            raise AssertionError("invalid order should not post")

    broker = LivePolymarketBroker(credentials=_fake_credentials(), client=FakeClient())

    with pytest.raises(ValueError, match="price"):
        broker.create_and_post_limit_order(
            market_slug="aec-mlb-team-a-team-b-2026-05-10",
            outcome_side="OUTCOME_SIDE_YES",
            action="ORDER_ACTION_BUY",
            price=1.0,
            quantity=10,
        )


def test_build_store_uses_live_database_url_for_live_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LIVE_DATABASE_URL", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  trading_mode: live
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
app:
  database_url: sqlite:///data/paper.sqlite3
  live_database_url: sqlite:///data/live.sqlite3
""",
        encoding="utf-8",
    )

    from polymarket_copy_trading.config import load_config

    store = build_store(load_config(config_path), project_root=tmp_path)

    assert store.path == tmp_path / "data" / "live.sqlite3"


def test_prepare_runtime_store_imports_paper_wallets_for_live_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LIVE_DATABASE_URL", raising=False)
    paper_store = Store(tmp_path / "data" / "paper.sqlite3")
    paper_store.initialize()
    paper_store.sync_wallets(
        (
            WalletConfig(
                name="paper_runtime_wallet",
                address="0x1111111111111111111111111111111111111111",
                enabled=True,
                event_follow_strategy_enabled=True,
            ),
        )
    )
    paper_store.insert_source_trade(make_source())
    paper_store.record_paper_fill(make_fill(), cash_after_usdc=900, position_quantity=1, avg_entry_price=0.5)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  trading_mode: live
wallets:
  - name: config_fallback
    address: "0x2222222222222222222222222222222222222222"
app:
  database_url: sqlite:///data/paper.sqlite3
  live_database_url: sqlite:///data/live.sqlite3
""",
        encoding="utf-8",
    )

    from polymarket_copy_trading.config import load_config

    config = load_config(config_path)
    live_store = build_store(config, project_root=tmp_path)
    live_store.initialize()

    prepare_runtime_store(config, live_store, project_root=tmp_path)

    assert [wallet["name"] for wallet in live_store.list_wallets()] == ["paper_runtime_wallet"]
    assert live_store.list_trades() == []


def _fake_credentials():
    from polymarket_copy_trading.live_executor import LivePolymarketCredentials

    return LivePolymarketCredentials(
        key_id="key",
        secret_key="0x" + "1" * 64,
        private_key="0x" + "1" * 64,
        api_key="key",
        api_secret="0x" + "1" * 64,
        api_passphrase="passphrase",
        funder_address="0x1111111111111111111111111111111111111111",
    )
