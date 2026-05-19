from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.price_monitor import PriceMonitor, _classify_market
from polymarket_copy_trading.store import Store


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_price_monitor_classifies_carolina_hurricanes_as_sports() -> None:
    assert _classify_market({"question": "Hurricanes vs. Flyers", "slug": "nhl-car-phi-2026-05-07"}) == "sports"


def test_price_monitor_classifies_structured_sports_without_keyword_text() -> None:
    assert (
        _classify_market(
            {
                "question": "Participant A / Participant B",
                "slug": "daily-match-market",
                "sportsMarketType": "moneyline",
                "seriesSlug": "nhl-2026",
                "events": [{"slug": "daily-match-event", "seriesSlug": "nhl-2026"}],
            }
        )
        == "sports"
    )


def test_price_monitor_event_fallback_preserves_structured_classification(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/events"
        assert params == {"slug": "daily-match-event", "limit": 1}
        return FakeResponse(
            [
                {
                    "slug": "daily-match-event",
                    "title": "Participant A / Participant B",
                    "sportsMarketType": "moneyline",
                    "seriesSlug": "nhl-2026",
                    "markets": [
                        {
                            "id": "market-structured",
                            "conditionId": "0xstructured",
                            "question": "Participant A / Participant B",
                            "slug": "daily-match-market",
                            "outcomes": '["Home", "Away"]',
                            "outcomePrices": '["0.62", "0.38"]',
                            "clobTokenIds": '["asset-home", "asset-away"]',
                        }
                    ],
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    metadata = PriceMonitor(config=load_config(config_path), store=store).get_event_market_metadata(
        "asset-away", event_slug="daily-match-event"
    )

    assert metadata["market_type"] == "sports"
    assert metadata["sport_key"] == "nhl"
    assert metadata["bet_type"] == "moneyline_winlose"
    assert metadata["series_slug"] == "nhl-2026"
    assert metadata["sports_market_type"] == "moneyline"


def test_price_monitor_updates_open_asset_marks_and_market_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.set_runtime_state("paper_cash_usdc", "90")
    with store._connect() as conn:
        conn.execute(
            """
            insert into positions (asset_id, source_wallet, quantity, avg_entry_price, realized_pnl_usdc, status)
            values ('123', '0x1111111111111111111111111111111111111111', 10, 0.4, 0, 'open')
            """
        )

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/price"):
            return FakeResponse({"price": "0.55"})
        if url.endswith("/markets"):
            return FakeResponse(
                [
                    {
                        "id": "market-1",
                        "conditionId": "0xabc",
                        "question": "Example market?",
                        "slug": "example-market",
                        "endDate": "2026-04-29T12:00:00Z",
                        "events": [{"slug": "example-event"}],
                        "outcomes": '["Yes", "No"]',
                        "clobTokenIds": '["123", "456"]',
                    }
                ]
            )
        raise AssertionError(url)

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    stats = PriceMonitor(config=load_config(config_path), store=store).refresh_once()
    holding = store.list_positions()[0]

    assert stats == {"priced": 1, "metadata": 1, "errors": 0, "exits": 0, "settlements": 0, "open_assets": 1}
    assert holding["current_price"] == 0.55
    assert holding["title"] == "Example market?"
    assert holding["outcome"] == "Yes"
    assert holding["market_url"] == "https://polymarket.com/event/example-event/example-market"
    assert holding["market_close_time"] == "2026-04-29 05:00 PDT"


def test_price_monitor_resolves_settled_sports_market_from_event_slug_fallback(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    with store._connect() as conn:
        conn.execute(
            """
            insert into positions (asset_id, source_wallet, quantity, avg_entry_price, realized_pnl_usdc, status)
            values ('asset-athletics', '0x1111111111111111111111111111111111111111', 10, 0.45, 0, 'open')
            """
        )
    store.upsert_market_metadata(
        asset_id="asset-athletics",
        market_type="sports",
        event_slug="mlb-cle-oak-2026-05-02",
        current_price=0.001,
        price_source="clob_no_orderbook",
    )

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/price") or url.endswith("/midpoint"):
            return FakeResponse({}, status_code=404)
        if url.endswith("/markets"):
            assert params == {"clob_token_ids": "asset-athletics", "limit": 1}
            return FakeResponse([])
        if url.endswith("/events"):
            assert params == {"slug": "mlb-cle-oak-2026-05-02", "limit": 1}
            return FakeResponse(
                [
                    {
                        "slug": "mlb-cle-oak-2026-05-02",
                        "title": "Cleveland Guardians vs. Athletics",
                        "closedTime": "2026-05-03T00:57:02Z",
                        "markets": [
                            {
                                "id": "2107002",
                                "conditionId": "0xmlb",
                                "question": "Cleveland Guardians vs. Athletics",
                                "slug": "mlb-cle-oak-2026-05-02",
                                "closed": True,
                                "closedTime": "2026-05-03 00:57:00+00",
                                "gameStartTime": "2026-05-02 20:05:00+00",
                                "endDate": "2026-05-09T20:05:00Z",
                                "outcomes": '["Cleveland Guardians", "Athletics"]',
                                "outcomePrices": '["1", "0"]',
                                "clobTokenIds": '["asset-guardians", "asset-athletics"]',
                            }
                        ],
                    }
                ]
            )
        raise AssertionError(url)

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    stats = PriceMonitor(config=load_config(config_path), store=store).refresh_once()

    assert stats["metadata"] == 1
    assert stats["settlements"] == 1
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "market_settlement" for trade in store.list_trades())


def test_price_monitor_uses_fast_polling_only_when_positions_are_open(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
price_monitor:
  poll_interval_seconds: 20
  idle_poll_interval_seconds: 240
""",
        encoding="utf-8",
    )
    monitor = PriceMonitor(config=load_config(config_path), store=Store(tmp_path / "app.sqlite3"))

    assert monitor.next_poll_seconds({"open_assets": 1}) == 20
    assert monitor.next_poll_seconds({"open_assets": 0}) == 240
    assert monitor.next_poll_seconds({"open_assets": 1}, override_seconds=9) == 9


def test_event_follow_sports_position_honors_configured_stop_loss(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: swisstony
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports"]
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 40
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = SourceTrade(
        idempotency_key="137:0xbuy-event-follow-sport:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-event-follow-sport",
        block_number=100,
        block_timestamp="2026-05-01 21:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="event-follow-sports-stop-loss",
        price=0.45,
        quantity=20,
        notional_usdc=9,
    )
    store.insert_source_trade(source_trade)
    engine = CopyTradingEngine(config=config, store=store)
    fill = engine.broker.buy(source_trade, notional_usdc=3)
    store.record_paper_fill(fill, cash_after_usdc=97, position_quantity=fill.quantity, avg_entry_price=0.45)
    store.upsert_market_metadata(
        asset_id="event-follow-sports-stop-loss",
        market_type="sports",
        title="Cleveland Guardians vs. Athletics",
        current_price=0.45,
        price_source="clob_sell",
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "event-follow-sports-stop-loss", "best_bid": "0.25"}],
        }
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "stop_loss" for trade in store.list_trades())


def test_swisstony_event_follow_sports_position_ignores_configured_stop_loss(tmp_path: Path) -> None:
    swisstony = "0x204f72f35326db932158cba6adff0b9a1da95e14"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: swisstony
    address: "{swisstony}"
    allowed_market_types: ["sports"]
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 40
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    source_trade = SourceTrade(
        idempotency_key=f"137:0xbuy-swisstony-sport:1:{swisstony}",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-swisstony-sport",
        block_number=100,
        block_timestamp="2026-05-02 09:00 PDT",
        log_index=1,
        source_wallet=swisstony,
        side="buy",
        asset_id="swisstony-event-follow-sports-stop-loss",
        price=0.45,
        quantity=20,
        notional_usdc=9,
    )
    store.insert_source_trade(source_trade)
    engine = CopyTradingEngine(config=config, store=store)
    fill = engine.broker.buy(source_trade, notional_usdc=3)
    store.record_paper_fill(fill, cash_after_usdc=97, position_quantity=fill.quantity, avg_entry_price=0.45)
    store.upsert_market_metadata(
        asset_id="swisstony-event-follow-sports-stop-loss",
        market_type="sports",
        title="Swisstony sports leg",
        current_price=0.45,
        price_source="clob_sell",
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "swisstony-event-follow-sports-stop-loss", "best_bid": "0.25"}],
        }
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert len(store.list_positions()) == 1
    assert not any(trade["close_reason"] == "stop_loss" for trade in store.list_trades())


def test_price_monitor_websocket_price_change_updates_mark_and_triggers_exit(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy",
        block_number=100,
        block_timestamp="2026-04-27 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="ws-stop-asset",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [
                {
                    "asset_id": "ws-stop-asset",
                    "best_bid": "0.30",
                    "best_ask": "0.31",
                }
            ],
        }
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert store.get_market_metadata("ws-stop-asset")["current_price"] == 0.3


def test_price_monitor_websocket_accepts_batch_payloads(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        [
            {
                "event_type": "price_change",
                "price_changes": [{"asset_id": "asset-one", "best_bid": "0.42"}],
            },
            {
                "event_type": "best_bid_ask",
                "asset_id": "asset-two",
                "best_bid": "0.66",
            },
        ]
    )

    assert stats == {"updated": 2, "exits": 0, "settlements": 0}
    assert store.get_market_metadata("asset-one")["current_price"] == 0.42
    assert store.get_market_metadata("asset-two")["current_price"] == 0.66


def test_price_monitor_websocket_price_one_closes_position_for_capital_reuse(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy",
        block_number=100,
        block_timestamp="2026-04-27 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="ws-one-asset",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_stop_loss_pct=25,
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [
                {
                    "asset_id": "ws-one-asset",
                    "best_bid": "1.00",
                    "best_ask": "1.00",
                }
            ],
        }
    )
    trades = store.list_trades()

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert store.overview()["paper_cash_usdc"] == 110
    assert any(trade["paper_side"] == "sell" and trade["close_reason"] == "price_at_one" for trade in trades)


def test_price_monitor_does_not_take_profit_event_follow_position_before_price_one(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 100
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy",
        block_number=100,
        block_timestamp="2026-04-29 03:33 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="rn1-tennis-asset",
        price=0.20,
        quantity=500,
        notional_usdc=100,
    )
    store.insert_source_trade(buy)
    store.record_paper_fill(
        CopyTradingEngine(config=config, store=store).broker.buy(buy, notional_usdc=4),
        cash_after_usdc=96,
        position_quantity=20,
        avg_entry_price=0.20,
    )
    store.upsert_market_metadata(
        asset_id="rn1-tennis-asset",
        market_type="sports",
        title="La Bisbal: Rebecca Sramkova vs Caroline Werner",
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "rn1-tennis-asset", "best_bid": "0.40"}],
        }
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert store.list_positions()[0]["status"] == "open"


def test_price_monitor_does_not_stop_loss_weather_event_follow_position(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: greerfew
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["weather"]
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 75
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-weather:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-weather",
        block_number=100,
        block_timestamp="2026-04-29 03:33 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="weather-event-asset",
        price=0.04,
        quantity=125,
        notional_usdc=5,
    )
    store.insert_source_trade(buy)
    store.record_paper_fill(
        CopyTradingEngine(config=config, store=store).broker.buy(buy, notional_usdc=5),
        cash_after_usdc=95,
        position_quantity=125,
        avg_entry_price=0.04,
    )
    store.upsert_market_metadata(
        asset_id="weather-event-asset",
        market_type="weather",
        title="Highest temperature in Seattle on April 29?",
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "weather-event-asset", "best_bid": "0.001"}],
        }
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert store.list_positions()[0]["status"] == "open"


def test_price_monitor_stops_non_weather_event_follow_position_on_configured_drawdown(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 35
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-sports:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-sports",
        block_number=100,
        block_timestamp="2026-04-29 03:33 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="sports-event-follow-asset",
        price=0.40,
        quantity=100,
        notional_usdc=40,
    )
    store.insert_source_trade(buy)
    store.record_paper_fill(
        CopyTradingEngine(config=config, store=store).broker.buy(buy, notional_usdc=4),
        cash_after_usdc=96,
        position_quantity=10,
        avg_entry_price=0.40,
    )
    store.upsert_market_metadata(asset_id="sports-event-follow-asset", market_type="sports", title="Sports market")

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "sports-event-follow-asset", "best_bid": "0.25"}],
        }
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "stop_loss" for trade in store.list_trades())


def test_price_monitor_ignores_unconfirmed_near_zero_non_weather_event_follow_position(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: RN1
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-near-zero:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-near-zero",
        block_number=100,
        block_timestamp="2026-04-29 03:33 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="near-zero-event-follow-asset",
        price=0.40,
        quantity=100,
        notional_usdc=40,
    )
    store.insert_source_trade(buy)
    store.record_paper_fill(
        CopyTradingEngine(config=config, store=store).broker.buy(buy, notional_usdc=4),
        cash_after_usdc=96,
        position_quantity=10,
        avg_entry_price=0.40,
    )
    store.upsert_market_metadata(asset_id="near-zero-event-follow-asset", market_type="sports", title="Sports market")

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "near-zero-event-follow-asset", "best_bid": "0.005"}],
        }
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert len(store.list_positions()) == 1


def test_price_monitor_uses_market_redirect_url_when_gamma_has_no_event(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    with store._connect() as conn:
        conn.execute(
            """
            insert into positions (asset_id, source_wallet, quantity, avg_entry_price, realized_pnl_usdc, status)
            values ('123', '0x1111111111111111111111111111111111111111', 10, 0.4, 0, 'open')
            """
        )

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/price"):
            return FakeResponse({"price": "0.55"})
        if url.endswith("/markets"):
            return FakeResponse(
                [
                    {
                        "id": "market-1",
                        "question": "Example market?",
                        "slug": "example-market",
                        "outcomes": '["Yes", "No"]',
                        "clobTokenIds": '["123", "456"]',
                    }
                ]
            )
        raise AssertionError(url)

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    PriceMonitor(config=load_config(config_path), store=store).refresh_once()
    holding = store.list_positions()[0]

    assert holding["market_url"] == "https://polymarket.com/market/example-market"


def test_price_monitor_enriches_recent_rolling_trade_assets_without_open_position(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(
        SourceTrade(
            idempotency_key="137:0xrolling:1:0x1111111111111111111111111111111111111111",
            chain_id=137,
            exchange_contract="ctf_exchange",
            tx_hash="0xrolling",
            block_number=100,
            block_timestamp="2026-04-27 09:24 PDT",
            log_index=1,
            source_wallet="0x1111111111111111111111111111111111111111",
            side="buy",
            asset_id="rolling-up",
            price=0.52,
            quantity=15,
            notional_usdc=7.8,
        )
    )

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/price") or url.endswith("/midpoint"):
            return FakeResponse({"error": "No orderbook exists"}, status_code=404)
        if url.endswith("/markets"):
            return FakeResponse(
                [
                    {
                        "id": "rolling-market",
                        "conditionId": "0xrolling",
                        "question": "Bitcoin Up or Down - April 27, 12:15PM-12:30PM ET",
                        "slug": "btc-updown-15m-1777306500",
                        "events": [{"slug": "btc-updown-15m-1777306500"}],
                        "outcomes": '["Up", "Down"]',
                        "outcomePrices": '["0.31", "0.69"]',
                        "clobTokenIds": '["rolling-up", "rolling-down"]',
                    }
                ]
            )
        raise AssertionError(url)

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    stats = PriceMonitor(config=load_config(config_path), store=store).refresh_once()
    trade = store.list_trades()[0]

    assert stats == {"priced": 1, "metadata": 1, "errors": 0, "exits": 0, "settlements": 0, "open_assets": 0}
    assert trade["title"] == "Bitcoin Up or Down - April 27, 12:15PM-12:30PM ET"
    assert trade["market_outcome"] == "Up"
    assert trade["current_price"] == 0.31
    assert trade["market_url"] == "https://polymarket.com/event/btc-updown-15m-1777306500/btc-updown-15m-1777306500"


def test_price_monitor_triggers_configured_stop_loss_exit(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
  max_holding_minutes: 1440
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy",
        block_number=100,
        block_timestamp="2026-04-27 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="stop-asset",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/price"):
            return FakeResponse({"price": "0.30"})
        if url.endswith("/markets"):
            return FakeResponse(
                [
                    {
                        "id": "stop-market",
                        "conditionId": "0xstop",
                        "question": "Stop-loss market?",
                        "slug": "stop-loss-market",
                        "events": [{"slug": "stop-loss-event"}],
                        "outcomes": '["Yes", "No"]',
                        "clobTokenIds": '["stop-asset", "other"]',
                    }
                ]
            )
        raise AssertionError(url)

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    stats = PriceMonitor(config=config, store=store).refresh_once()
    trades = store.list_trades()

    assert stats["exits"] == 1
    assert store.list_positions() == []
    assert any(trade["paper_side"] == "sell" and trade["close_reason"] == "stop_loss" for trade in trades)


def test_price_monitor_fixed_stop_applies_to_live_event_follow_sports(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    event_follow_strategy_enabled: true
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 35
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-sports:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-sports",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="sports-stop-asset",
        price=0.50,
        quantity=20,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        event_follow_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        event_follow_strategy_enabled=True,
    )
    store.upsert_market_metadata(asset_id="sports-stop-asset", market_type="sports", current_price=0.20)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "sports-stop-asset", "best_bid": "0.20"}]}
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    assert any(trade["close_reason"] == "stop_loss" for trade in store.list_trades())


def test_price_monitor_ignores_single_near_zero_ws_tick_for_live_event_position(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
    repeat_buy_stop_loss_pct: 25
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-near-zero:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-near-zero",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="near-zero-sports-asset",
        price=0.28,
        quantity=35.714285,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_stop_loss_pct=25,
    )
    store.upsert_market_metadata(asset_id="near-zero-sports-asset", market_type="sports", current_price=0.28)

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "near-zero-sports-asset", "best_bid": "0"}]}
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert len(store.list_positions()) == 1
    assert not any(trade["close_reason"] == "price_near_zero" for trade in store.list_trades())


def test_price_monitor_ignores_near_zero_clob_poll_for_unresolved_live_event(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
    repeat_buy_stop_loss_pct: 25
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-clob-zero:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-clob-zero",
        block_number=100,
        block_timestamp="2026-05-01 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="clob-confirmed-near-zero-sports-asset",
        price=0.28,
        quantity=35.714285,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_stop_loss_pct=25,
    )
    store.upsert_market_metadata(
        asset_id="clob-confirmed-near-zero-sports-asset",
        market_type="sports",
        current_price=0.0,
        price_source="clob_ws_price_change",
        market_close_time="2099-05-08 09:00 PDT",
        event_slug="nba-lal-bos-2099-05-08",
    )

    monitor = PriceMonitor(config=config, store=store)
    monitor.get_market_metadata = lambda asset_id: {
        "market_url": f"https://polymarket.com/search?q={asset_id}",
        "market_type": "sports",
        "event_slug": "nba-lal-bos-2026-05-08",
        "_has_market_metadata": True,
    }
    monitor._get_price = lambda asset_id, side: 0.001
    monitor._get_midpoint = lambda asset_id: 0.0005

    stats = monitor.refresh_once()

    assert stats["exits"] == 0
    assert len(store.list_positions()) == 1
    assert not any(trade["close_reason"] == "price_near_zero" for trade in store.list_trades())


def test_price_monitor_does_not_close_near_zero_live_event_after_market_close_time(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
    repeat_buy_stop_loss_pct: 25
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-closed-zero:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-closed-zero",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="closed-near-zero-sports-asset",
        price=0.28,
        quantity=35.714285,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_stop_loss_pct=25,
    )
    store.upsert_market_metadata(
        asset_id="closed-near-zero-sports-asset",
        market_type="sports",
        current_price=0.001,
        price_source="clob_ws",
        market_close_time="2026-04-30 09:00 PDT",
        event_slug="nba-lal-bos-2026-04-30",
        is_closed=False,
        resolution_price=None,
    )

    exits = CopyTradingEngine(config=config, store=store).process_local_exits()

    assert exits == 0
    assert len(store.list_positions()) == 1
    assert not any(trade["close_reason"] == "price_near_zero" for trade in store.list_trades())


def test_price_monitor_ignores_missing_orderbook_near_zero_for_unresolved_live_event(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
    repeat_buy_stop_loss_pct: 25
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-no-book-zero:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-no-book-zero",
        block_number=100,
        block_timestamp="2026-05-01 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="no-orderbook-near-zero-sports-asset",
        price=0.60,
        quantity=16.666667,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
        repeat_buy_stop_loss_pct=25,
    )
    store.upsert_market_metadata(
        asset_id="no-orderbook-near-zero-sports-asset",
        market_type="sports",
        current_price=0.0,
        price_source="clob_ws_price_change",
        market_close_time="2099-05-08 09:00 PDT",
        event_slug="nba-lal-bos-2099-05-08",
    )

    monitor = PriceMonitor(config=config, store=store)
    monitor.get_market_metadata = lambda asset_id: {
        "market_url": f"https://polymarket.com/search?q={asset_id}",
        "market_type": "sports",
        "event_slug": "nba-lal-bos-2099-05-08",
        "_has_market_metadata": False,
    }
    monitor._get_price = lambda asset_id, side: None
    monitor._get_midpoint = lambda asset_id: None

    stats = monitor.refresh_once()

    assert stats["exits"] == 0
    assert len(store.list_positions()) == 1
    trades = store.list_trades()
    assert not any(trade["close_reason"] == "price_near_zero" for trade in trades)
    metadata = store.get_market_metadata("no-orderbook-near-zero-sports-asset")
    assert metadata["price_source"] == "clob_no_orderbook"


def test_price_monitor_locks_sports_profit_before_event_ends(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-lock-profit:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-lock-profit",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="sports-lock-profit-asset",
        price=0.60,
        quantity=16.666667,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
    )
    store.upsert_market_metadata(
        asset_id="sports-lock-profit-asset",
        market_type="sports",
        current_price=0.96,
        is_closed=False,
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "sports-lock-profit-asset", "best_bid": "0.96"}]}
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    sell = [trade for trade in store.list_trades() if trade["paper_side"] == "sell"][0]
    assert sell["close_reason"] == "sports_pre_end_lock_profit"
    assert sell["realized_pnl_usdc"] > 0


def test_price_monitor_locks_sports_profit_after_market_close_time_when_unresolved(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-closed-lock-profit:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-closed-lock-profit",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="sports-closed-lock-profit-asset",
        price=0.60,
        quantity=16.666667,
        notional_usdc=10,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
    )
    store.upsert_market_metadata(
        asset_id="sports-closed-lock-profit-asset",
        market_type="sports",
        current_price=0.96,
        is_closed=False,
        market_close_time="2026-04-01 09:00 PDT",
        event_slug="nba-lal-bos-2026-04-01",
        resolution_price=None,
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [{"asset_id": "sports-closed-lock-profit-asset", "best_bid": "0.96"}],
        }
    )

    assert stats == {"updated": 1, "exits": 1, "settlements": 0}
    assert store.list_positions() == []
    sell = [trade for trade in store.list_trades() if trade["paper_side"] == "sell"][0]
    assert sell["close_reason"] == "sports_pre_end_lock_profit"


def test_price_monitor_does_not_lock_sports_profit_when_after_slippage_gain_is_small(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["sports", "other"]
    repeat_buy_strategy_enabled: false
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy-small-gain:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy-small-gain",
        block_number=100,
        block_timestamp="2026-04-30 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="sports-small-gain-asset",
        price=0.85,
        quantity=11.764706,
        notional_usdc=10,
    )
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=False,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"
    store.upsert_wallet(
        name="alpha",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports", "other"],
        repeat_buy_strategy_enabled=True,
    )
    store.upsert_market_metadata(
        asset_id="sports-small-gain-asset",
        market_type="sports",
        current_price=0.96,
        is_closed=False,
    )

    stats = PriceMonitor(config=config, store=store).handle_market_ws_message(
        {"event_type": "price_change", "price_changes": [{"asset_id": "sports-small-gain-asset", "best_bid": "0.96"}]}
    )

    assert stats == {"updated": 1, "exits": 0, "settlements": 0}
    assert len(store.list_positions()) == 1


def test_price_monitor_settles_closed_market_with_resolution_price(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
paper:
  starting_cash_usdc: 100
  slippage_pct: 5
sizing:
  max_trade_usdc: 10
  max_position_usdc: 10
  min_trade_usdc: 1
exits:
  mirror_source_sells: true
  stop_loss_pct: 0
  take_profit_pct: 0
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    buy = SourceTrade(
        idempotency_key="137:0xbuy:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbuy",
        block_number=100,
        block_timestamp="2026-04-27 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="winner-asset",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(buy) == "processed"

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/price"):
            return FakeResponse({"error": "closed"}, status_code=404)
        if url.endswith("/midpoint"):
            return FakeResponse({"error": "closed"}, status_code=404)
        if url.endswith("/markets"):
            return FakeResponse(
                [
                    {
                        "id": "settled-market",
                        "conditionId": "0xsettled",
                        "question": "Settled market?",
                        "slug": "settled-market",
                        "events": [{"slug": "settled-event"}],
                        "outcomes": '["Yes", "No"]',
                        "outcomePrices": '["1", "0"]',
                        "clobTokenIds": '["winner-asset", "loser-asset"]',
                        "closed": True,
                    }
                ]
            )
        raise AssertionError(url)

    monkeypatch.setattr("polymarket_copy_trading.price_monitor.requests.get", fake_get)

    stats = PriceMonitor(config=config, store=store).refresh_once()
    trades = store.list_trades()

    assert stats["settlements"] == 1
    assert store.list_positions() == []
    assert store.overview()["paper_cash_usdc"] == 109.047619
    assert any(trade["paper_side"] == "sell" and trade["close_reason"] == "market_settlement" for trade in trades)
