from pathlib import Path

from polymarket_copy_trading.config import MARKET_TYPES, default_wallet_profile_json, load_config
from polymarket_copy_trading.dashboard import create_app
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import PaperFill, SourceTrade
from polymarket_copy_trading.store import Store


def sample_config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
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
    return path


def sample_config(tmp_path: Path):
    path = sample_config_path(tmp_path)
    return load_config(path)


def make_source() -> SourceTrade:
    return SourceTrade(
        idempotency_key="137:0xaaa:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xaaa",
        block_number=100,
        block_timestamp="2026-04-26 16:30 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="123",
        price=1.0,
        quantity=10,
        notional_usdc=10,
    )


def make_fill() -> PaperFill:
    return PaperFill(
        source_idempotency_key="137:0xaaa:1:0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="123",
        source_wallet="0x1111111111111111111111111111111111111111",
        observed_price=1.0,
        fill_price=1.0,
        quantity=10,
        notional_usdc=10,
    )


def test_dashboard_api_returns_json_sections(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()

    for path in [
        "/api/overview",
        "/api/holdings",
        "/api/closed-positions",
        "/api/trades",
        "/api/skip-reasons",
        "/api/wallets",
        "/api/settings",
        "/api/pnl",
        "/api/performance",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.is_json


def test_dashboard_default_wallet_profile_api_uses_canonical_python_defaults(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)

    response = app.test_client().get("/api/wallet-profile/default")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["default_wallet_profile_json"] == default_wallet_profile_json()
    profile = payload["default_wallet_profile_json"]
    assert profile["strategy"]["copy_buys_enabled"] is True
    assert profile["filter_copy"]["source_sell_exit_fraction"] == 0.0
    assert profile["filter_copy"]["allowed_bet_types"] == [
        "moneyline_winlose",
        "total_or_over_under",
        "spread_handicap",
        "both_teams_score",
        "map_or_game_winner",
    ]


def test_dashboard_wallet_api_saves_bracket_strategy_settings(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()

    response = client.post(
        "/api/wallets",
        json={
            "name": "poligarch",
            "address": "0xb40e89677d59665d5188541ad860450a6e2a7cc9",
            "enabled": True,
            "allowed_market_types": ["weather"],
            "bracket_strategy_enabled": True,
            "bracket_buy_size_usdc": 11.5,
            "bracket_stop_loss_pct": 12,
            "bracket_max_open_events": 10,
            "bracket_allowed_patterns": ["exact_or_binary"],
            "repeat_buy_strategy_enabled": True,
            "repeat_buy_size_usdc": 6.5,
            "repeat_buy_stop_loss_pct": 14,
            "repeat_buy_min_source_notional_usdc": 100,
            "repeat_buy_min_buy_count": 3,
            "repeat_buy_min_avg_price": 0.05,
            "repeat_buy_max_avg_price": 0.75,
            "repeat_buy_max_total_exposure_usdc": 80,
            "repeat_buy_blocked_title_patterns": ["O/U"],
            "repeat_buy_allowed_sports": ["nba", "mlb"],
            "repeat_buy_allowed_bet_types": ["moneyline_winlose"],
            "sports_trailing_stop_enabled": True,
            "sports_trailing_activation_pct": 35,
            "sports_trailing_stop_pct": 25,
            "sports_trailing_floor_delta": 0.03,
            "reserved_cash_usdc": 50,
        },
    )

    assert response.status_code == 201
    wallet = response.get_json()["wallet"]
    assert wallet["bracket_strategy_enabled"] is True
    assert wallet["bracket_buy_size_usdc"] == 11.5
    assert wallet["bracket_stop_loss_pct"] == 12
    assert wallet["bracket_max_open_events"] == 10
    assert wallet["bracket_allowed_patterns"] == ["exact_or_binary"]
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 6.5
    assert wallet["repeat_buy_stop_loss_pct"] == 14
    assert wallet["repeat_buy_min_source_notional_usdc"] == 100
    assert wallet["repeat_buy_min_buy_count"] == 3
    assert wallet["repeat_buy_min_avg_price"] == 0.05
    assert wallet["repeat_buy_max_avg_price"] == 0.75
    assert wallet["repeat_buy_max_total_exposure_usdc"] == 80
    assert wallet["repeat_buy_blocked_title_patterns"] == ["O/U"]
    assert wallet["repeat_buy_allowed_sports"] == ["nba", "mlb"]
    assert wallet["repeat_buy_allowed_bet_types"] == ["moneyline_winlose"]
    assert wallet["sports_trailing_stop_enabled"] is True
    assert wallet["sports_trailing_activation_pct"] == 35
    assert wallet["sports_trailing_stop_pct"] == 25
    assert wallet["sports_trailing_floor_delta"] == 0.03
    assert wallet["reserved_cash_usdc"] == 50
    assert wallet["profile_json"]["weather_bracket"]["buy_size_usdc"] == 11.5
    assert wallet["profile_json"]["repeat_buy"]["buy_size_usdc"] == 6.5
    assert wallet["profile_json"]["risk"]["reserved_cash_usdc"] == 50.0


def test_dashboard_wallet_api_prefers_profile_json_strategy_settings(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()

    response = client.post(
        "/api/wallets",
        json={
            "name": "json wallet",
            "address": "0x2222222222222222222222222222222222222222",
            "enabled": True,
            "allowed_market_types": ["crypto"],
            "bracket_strategy_enabled": False,
            "bracket_buy_size_usdc": 10,
            "repeat_buy_strategy_enabled": False,
            "reserved_cash_usdc": 5,
            "profile_json": {
                "market_filters": {"allowed_market_types": ["sports", "weather"]},
                "weather_bracket": {"enabled": True, "buy_size_usdc": 12.5, "stop_loss_pct": 8},
                "repeat_buy": {
                    "enabled": True,
                    "buy_size_usdc": 7,
                    "min_source_notional_usdc": 3000,
                    "min_buy_count": 4,
                },
                "risk": {"reserved_cash_usdc": 42},
            },
        },
    )

    assert response.status_code == 201
    wallet = response.get_json()["wallet"]
    assert wallet["allowed_market_types"] == ["sports", "weather"]
    assert wallet["bracket_strategy_enabled"] is True
    assert wallet["bracket_buy_size_usdc"] == 12.5
    assert wallet["bracket_stop_loss_pct"] == 8
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 7
    assert wallet["repeat_buy_min_source_notional_usdc"] == 3000
    assert wallet["repeat_buy_min_buy_count"] == 4
    assert wallet["reserved_cash_usdc"] == 42
    assert wallet["profile_json"]["market_filters"]["allowed_market_types"] == ["sports", "weather"]


def test_dashboard_wallet_api_create_ignores_legacy_strategy_fields_when_profile_json_is_explicit(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()

    response = client.post(
        "/api/wallets",
        json={
            "name": "json create",
            "address": "0x3333333333333333333333333333333333333333",
            "enabled": True,
            "allowed_market_types": ["crypto"],
            "repeat_buy_strategy_enabled": False,
            "repeat_buy_size_usdc": 99,
            "repeat_buy_min_buy_count": 9,
            "profile_json": {
                "market_filters": {"allowed_market_types": ["sports"]},
                "repeat_buy": {"enabled": True},
            },
        },
    )

    assert response.status_code == 201
    wallet = response.get_json()["wallet"]
    assert wallet["allowed_market_types"] == ["sports"]
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 5.0
    assert wallet["repeat_buy_min_buy_count"] == 2
    assert wallet["profile_json"]["repeat_buy"]["buy_size_usdc"] == 5.0


def test_dashboard_wallet_api_patch_ignores_legacy_strategy_fields_when_profile_json_is_explicit(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()
    client.post(
        "/api/wallets",
        json={
            "name": "json patch",
            "address": "0x4444444444444444444444444444444444444444",
            "enabled": True,
            "profile_json": {
                "market_filters": {"allowed_market_types": ["sports"]},
                "repeat_buy": {"enabled": False, "buy_size_usdc": 5, "min_buy_count": 2},
            },
        },
    )

    response = client.patch(
        "/api/wallets/0x4444444444444444444444444444444444444444",
        json={
            "allowed_market_types": ["crypto"],
            "repeat_buy_strategy_enabled": False,
            "repeat_buy_size_usdc": 99,
            "repeat_buy_min_buy_count": 9,
            "profile_json": {
                "market_filters": {"allowed_market_types": ["sports"]},
                "repeat_buy": {"enabled": True},
            },
        },
    )

    assert response.status_code == 200
    wallet = response.get_json()["wallet"]
    assert wallet["allowed_market_types"] == ["sports"]
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 5.0
    assert wallet["repeat_buy_min_buy_count"] == 2
    assert wallet["profile_json"]["repeat_buy"]["buy_size_usdc"] == 5.0


def test_dashboard_wallet_api_explicit_profile_json_ignores_unmentioned_legacy_sections(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()

    response = client.post(
        "/api/wallets",
        json={
            "name": "json-only",
            "address": "0x5555555555555555555555555555555555555555",
            "enabled": True,
            "allowed_market_types": ["sports"],
            "repeat_buy_strategy_enabled": True,
            "repeat_buy_size_usdc": 99,
            "event_follow_strategy_enabled": True,
            "event_follow_buy_size_usdc": 44,
            "sports_trailing_stop_enabled": True,
            "reserved_cash_usdc": 88,
            "profile_json": {"source_follow": {"enabled": False}},
        },
    )

    assert response.status_code == 201
    wallet = response.get_json()["wallet"]
    assert wallet["allowed_market_types"] == list(MARKET_TYPES)
    assert wallet["repeat_buy_strategy_enabled"] is False
    assert wallet["repeat_buy_size_usdc"] == 5.0
    assert wallet["event_follow_strategy_enabled"] is False
    assert wallet["event_follow_buy_size_usdc"] == 2.0
    assert wallet["sports_trailing_stop_enabled"] is False
    assert wallet["reserved_cash_usdc"] == 0.0
    assert wallet["profile_json"]["source_follow"]["enabled"] is False


def test_dashboard_wallet_api_accepts_profile_json_string_patch(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()
    client.post(
        "/api/wallets",
        json={
            "name": "sharp",
            "address": "0x1111111111111111111111111111111111111111",
            "enabled": True,
        },
    )

    response = client.patch(
        "/api/wallets/0x1111111111111111111111111111111111111111",
        json={"profile_json": '{"fixed_buy":{"buy_size_usdc":4}}'},
    )

    assert response.status_code == 200
    wallet = response.get_json()["wallet"]
    assert wallet["profile_json"]["version"] == 1
    assert wallet["profile_json"]["fixed_buy"]["buy_size_usdc"] == 4.0


def test_dashboard_partial_profile_patch_preserves_known_wallet_defaults(tmp_path: Path) -> None:
    rn1 = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"
    swisstony = "0x204f72f35326db932158cba6adff0b9a1da95e14"
    sharp = "0x8a091656e5f4c6bc4fdf37b2585be0235f68e317"
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()
    for name, address in (("RN1", rn1), ("Sharp_0x8a091", sharp)):
        assert client.post("/api/wallets", json={"name": name, "address": address, "enabled": True}).status_code == 201
    assert client.post(
        "/api/wallets",
        json={
            "name": "swisstony",
            "address": swisstony,
            "enabled": True,
            "event_follow_strategy_enabled": True,
            "event_follow_max_event_exposure_usdc": 75,
            "event_follow_max_total_exposure_usdc": 350,
        },
    ).status_code == 201

    rn1_response = client.patch(f"/api/wallets/{rn1}", json={"profile_json": {"fixed_buy": {"buy_size_usdc": 4}}})
    swisstony_response = client.patch(
        f"/api/wallets/{swisstony}",
        json={"profile_json": {"tier_sizing": {"tiers": [{"min_price": 0.4, "max_price": 0.7, "buy_size_usdc": 3}]}}},
    )
    sharp_response = client.patch(f"/api/wallets/{sharp}", json={"profile_json": {"fixed_buy": {"buy_size_usdc": 4}}})

    assert rn1_response.status_code == 200
    rn1_profile = rn1_response.get_json()["wallet"]["profile_json"]
    assert rn1_profile["source_follow"]["enabled"] is True
    assert rn1_profile["binary_hedge"]["enabled"] is True
    assert "soccer" in rn1_profile["event_follow"]["allowed_sports"]

    assert swisstony_response.status_code == 200
    swisstony_profile = swisstony_response.get_json()["wallet"]["profile_json"]
    assert swisstony_profile["source_follow"]["enabled"] is True
    assert swisstony_profile["binary_hedge"]["enabled"] is True
    assert swisstony_profile["risk"]["local_stop_loss_enabled"] is False

    assert sharp_response.status_code == 200
    sharp_profile = sharp_response.get_json()["wallet"]["profile_json"]
    assert sharp_profile["fixed_buy"]["enabled"] is True
    assert sharp_profile["fixed_buy"]["buy_size_usdc"] == 4.0
    assert sharp_profile["risk"]["local_stop_loss_enabled"] is False


def test_dashboard_wallet_api_edits_profile_json_strategy_settings(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()
    client.post(
        "/api/wallets",
        json={
            "name": "json wallet",
            "address": "0x2222222222222222222222222222222222222222",
            "enabled": True,
            "profile_json": {
                "market_filters": {"allowed_market_types": ["crypto"]},
                "repeat_buy": {"enabled": False, "buy_size_usdc": 5},
            },
        },
    )

    response = client.patch(
        "/api/wallets/0x2222222222222222222222222222222222222222",
        json={
            "profile_json": {
                "market_filters": {"allowed_market_types": ["sports"]},
                "repeat_buy": {
                    "enabled": True,
                    "buy_size_usdc": 9,
                    "min_source_notional_usdc": 3000,
                    "min_buy_count": 3,
                },
                "sports_trailing": {"enabled": True, "activation_pct": 35, "stop_pct": 20},
            }
        },
    )

    assert response.status_code == 200
    wallet = response.get_json()["wallet"]
    assert wallet["allowed_market_types"] == ["sports"]
    assert wallet["repeat_buy_strategy_enabled"] is True
    assert wallet["repeat_buy_size_usdc"] == 9
    assert wallet["repeat_buy_min_source_notional_usdc"] == 3000
    assert wallet["repeat_buy_min_buy_count"] == 3
    assert wallet["sports_trailing_stop_enabled"] is True
    assert wallet["sports_trailing_stop_pct"] == 20
    assert wallet["profile_json"]["market_filters"]["allowed_market_types"] == ["sports"]


def test_dashboard_overview_includes_watcher_status(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.set_runtime_state("paper_watcher_status", "running_ws")
    app = create_app(store=store)

    payload = app.test_client().get("/api/overview").get_json()

    assert payload["paper_watcher_status"] == "running_ws"


def test_dashboard_settings_include_ws_keepalive(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store, config=sample_config(tmp_path))

    payload = app.test_client().get("/api/settings").get_json()

    assert payload["settings"]["ws_ping_interval_seconds"] == 15.0
    assert payload["settings"]["ws_ping_timeout_seconds"] == 45.0
    assert payload["settings"]["settlement_slippage_pct"] == 0.0
    assert payload["settings"]["price_monitor_enabled"] is True
    assert payload["settings"]["price_monitor_poll_interval_seconds"] == 30.0
    assert payload["settings"]["price_monitor_idle_poll_interval_seconds"] == 300.0


def test_dashboard_pnl_uses_configured_starting_cash_baseline(tmp_path: Path) -> None:
    config_path = sample_config_path(tmp_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.insert_source_trade(make_source())
    store.record_paper_fill(make_fill(), cash_after_usdc=90, position_quantity=10, avg_entry_price=1)
    store.upsert_market_metadata(asset_id="123", current_price=0.5)
    app = create_app(store=store, config=load_config(config_path), config_path=config_path)

    payload = app.test_client().get("/api/pnl").get_json()

    assert payload["portfolio_value_usdc"] == 95
    assert payload["starting_cash_usdc"] == 100.0
    assert payload["pnl"]["lifetime"] == -5


def test_dashboard_performance_groups_wallet_pnl_by_market_bucket(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="RN1",
        address="0x1111111111111111111111111111111111111111",
        enabled=True,
        allowed_market_types=["sports"],
    )
    store.upsert_wallet(
        name="swisstony",
        address="0x2222222222222222222222222222222222222222",
        enabled=True,
        allowed_market_types=["sports"],
    )
    store.upsert_market_metadata(
        asset_id="mlb-asset",
        market_type="sports",
        sport_key="mlb",
        title="Participant A / Participant B",
        event_slug="daily-match-event",
        current_price=0.70,
    )
    store.upsert_market_metadata(
        asset_id="soccer-asset",
        market_type="sports",
        title="Will Arsenal FC win on 2026-05-02?",
        event_slug="epl-ars-che-2026-05-02",
        current_price=0.20,
    )
    buy = SourceTrade(
        idempotency_key="137:0xaaa:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xaaa",
        block_number=100,
        block_timestamp="2026-05-02 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="mlb-asset",
        price=1.0,
        quantity=10,
        notional_usdc=10,
    )
    store.insert_source_trade(buy)
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key=buy.idempotency_key,
            side="buy",
            asset_id="mlb-asset",
            source_wallet=buy.source_wallet,
            observed_price=1.0,
            fill_price=1.0,
            quantity=10,
            notional_usdc=10,
        ),
        cash_after_usdc=90,
        position_quantity=10,
        avg_entry_price=1,
    )
    sell = SourceTrade(
        idempotency_key="137:0xbbb:1:0x2222222222222222222222222222222222222222",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xbbb",
        block_number=101,
        block_timestamp="2026-05-02 10:00 PDT",
        log_index=1,
        source_wallet="0x2222222222222222222222222222222222222222",
        side="sell",
        asset_id="soccer-asset",
        price=0.20,
        quantity=10,
        notional_usdc=2,
    )
    store.insert_source_trade(sell)
    store.record_paper_fill(
        PaperFill(
            source_idempotency_key=sell.idempotency_key,
            side="sell",
            asset_id="soccer-asset",
            source_wallet=sell.source_wallet,
            observed_price=0.20,
            fill_price=0.20,
            quantity=10,
            notional_usdc=2,
            realized_pnl_usdc=-3,
            close_reason="source_sell",
        ),
        cash_after_usdc=92,
        position_quantity=0,
        avg_entry_price=0,
    )
    app = create_app(store=store)

    payload = app.test_client().get("/api/performance").get_json()

    wallets = {row["wallet_name"]: row for row in payload["wallets"]}
    rn1 = wallets["RN1"]
    swisstony = wallets["swisstony"]
    assert rn1["pnl_24h_usdc"] == -3.0
    assert rn1["pnl_window_usdc"] == -3.0
    assert rn1["trades_window"] == 0
    assert rn1["markets"][0]["market"] == "mlb"
    assert rn1["markets"][0]["unrealized_pnl_usdc"] == -3.0
    assert rn1["markets"][0]["pnl_window_usdc"] == -3.0
    assert swisstony["pnl_24h_usdc"] == -3.0
    assert swisstony["markets"][0]["market"] == "soccer"
    assert swisstony["markets"][0]["realized_pnl_usdc"] == -3.0


def test_dashboard_performance_supports_short_window_selector(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)

    payload = app.test_client().get("/api/performance?hours=4").get_json()
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    index_html = (
        Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "index.html"
    ).read_text(encoding="utf-8")

    assert payload["window_hours"] == 4
    for hours in (1, 4, 8, 12, 24):
        assert f'data-performance-hours="{hours}"' in index_html
    assert "PERFORMANCE_WINDOWS = [1, 4, 8, 12, 24]" in app_js
    assert "/api/performance?hours=${state.performanceHours}" in app_js
    assert "function setPerformanceHours(hours)" in app_js


def test_dashboard_can_patch_editable_settings_to_config_file(tmp_path: Path) -> None:
    config_path = sample_config_path(tmp_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store, config=load_config(config_path), config_path=config_path)
    client = app.test_client()

    response = client.patch(
        "/api/settings",
        json={
            "max_position_usdc": 12.5,
            "settlement_slippage_pct": 0.25,
            "mirror_source_sells": False,
            "enabled_market_types": ["crypto", "sports"],
        },
    )

    assert response.status_code == 200
    settings = response.get_json()["settings"]
    assert settings["max_position_usdc"] == 12.5
    assert settings["settlement_slippage_pct"] == 0.25
    assert settings["mirror_source_sells"] is False
    assert settings["enabled_market_types"] == ["crypto", "sports"]
    reloaded = load_config(config_path)
    assert reloaded.sizing.max_position_usdc == 12.5
    assert reloaded.paper.settlement_slippage_pct == 0.25
    assert reloaded.exits.mirror_source_sells is False
    assert reloaded.market_filters.enabled_market_types == ("crypto", "sports")


def test_dashboard_can_switch_to_live_trading_mode(tmp_path: Path) -> None:
    config_path = sample_config_path(tmp_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store, config=load_config(config_path), config_path=config_path)

    response = app.test_client().patch("/api/settings", json={"trading_mode": "live"})

    assert response.status_code == 200
    settings = response.get_json()["settings"]
    assert settings["trading_mode"] == "live"
    assert settings["paper_trading"] is False
    assert settings["live_trading"] is True
    reloaded = load_config(config_path)
    assert reloaded.mode.trading_mode == "live"


def test_dashboard_serves_pwa_shell(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"Polymarket Copy" in response.data


def test_dashboard_shell_cache_busts_static_assets(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)

    response = app.test_client().get("/")

    assert b"/static/app.css?v=" in response.data
    assert b"/static/app.js?v=" in response.data


def test_dashboard_shell_does_not_render_standalone_sports_bracket_section(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"sports-brackets-section" not in response.data
    assert b"Sports Brackets" not in response.data


def test_dashboard_static_js_removes_brackets_position_tab() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    index_html = (
        Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "index.html"
    ).read_text(encoding="utf-8")

    assert "function openSportsBrackets()" not in app_js
    assert "renderSportsBracket" not in app_js
    assert "sportsBrackets" not in app_js
    assert "function buildPositionBooks()" in app_js
    assert "function renderPositionBook(book)" in app_js
    assert "const books = positionBooksForTab(state.activePositionTab)" in app_js
    assert 'data-position-tab="brackets"' not in index_html
    assert ">Brackets<" not in index_html
    assert "function renderSportsBrackets()" not in app_js


def test_dashboard_static_js_labels_sell_close_reasons() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "Copied sell" not in app_js
    assert "Copied buy" not in app_js
    assert "Mirrored source sell" in app_js
    assert "Bot stop loss" in app_js
    assert "Close ${escapeHtml(closeReason)}" in app_js
    assert "Exit reason ${escapeHtml(closeReason)}" in app_js


def test_dashboard_static_js_labels_legacy_unresolved_sports_time_as_event_start() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "function isEventStartTime(item)" in app_js
    assert 'String(item.market_type || "").toLowerCase() === "sports"' in app_js
    assert "item.resolution_price == null" in app_js


def test_dashboard_static_js_edits_wallet_strategy_only_through_profile_json() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert 'fetchJsonOr("/api/wallet-profile/default"' in app_js
    assert "state.defaultWalletProfile" in app_js
    assert "source_sell_exit_fraction: 0.5" not in app_js
    assert 'allowed_bet_types: ["moneyline_winlose"]' not in app_js
    assert "strategy: { custom: false }" not in app_js
    assert "allowed_market_types: selectedModalWalletMarketTypes(form)" not in app_js
    assert "selectedModalWalletMarketTypes" not in app_js
    assert 'name="strategy_label"' not in app_js
    assert 'name="reserved_cash_usdc"' not in app_js
    assert "Reserve $" not in app_js
    assert 'name="bracket_' not in app_js
    assert 'name="repeat_buy_' not in app_js
    assert 'name="event_follow_' not in app_js
    assert 'name="sports_trailing_' not in app_js
    assert "walletProfileJsonText(wallet)" in app_js
    assert "profile_json: parseWalletProfileJson(form.elements.profile_json.value)" in app_js


def test_dashboard_static_js_surfaces_copy_buys_paused_wallet_state() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "copyBuysEnabled(wallet)" in app_js
    assert "Copy paused" in app_js
    assert "Copy buys paused" in app_js


def test_dashboard_static_js_settings_page_keeps_only_operational_controls() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "polymarket_copy_trading" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "const SETTINGS_GROUPS" in app_js
    assert 'title: "Mode"' in app_js
    assert 'title: "Capital & Entry Risk"' in app_js
    assert 'title: "Markets & Pricing"' in app_js
    assert '<select name="trading_mode">' in app_js
    assert "SETTINGS_KEYS.forEach" in app_js
    assert "Object.entries(state.settings)" not in app_js
    assert "Winner Capture" not in app_js
    assert "WebSocket" not in app_js
    assert '"winner_capture_enabled"' not in app_js
    assert '"ws_ping_interval_seconds"' not in app_js


def test_dashboard_can_add_update_and_delete_copy_wallets(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    app = create_app(store=store)
    client = app.test_client()

    add_response = client.post(
        "/api/wallets",
        json={
            "name": "alpha",
            "address": "0x1111111111111111111111111111111111111111",
            "enabled": True,
            "allowed_market_types": ["crypto", "weather"],
        },
    )
    update_response = client.patch(
        "/api/wallets/0x1111111111111111111111111111111111111111",
        json={"name": "alpha updated", "enabled": False, "allowed_market_types": ["sports"]},
    )
    wallets_after_update = client.get("/api/wallets").get_json()["wallets"]
    delete_response = client.delete("/api/wallets/0x1111111111111111111111111111111111111111")

    assert add_response.status_code == 201
    assert update_response.status_code == 200
    assert len(wallets_after_update) == 1
    wallet = wallets_after_update[0]
    assert wallet["name"] == "alpha updated"
    assert wallet["address"] == "0x1111111111111111111111111111111111111111"
    assert wallet["enabled"] is False
    assert wallet["allowed_market_types"] == ["sports"]
    assert wallet["profile_json"]["market_filters"]["allowed_market_types"] == ["sports"]
    assert wallet["profile_json"]["source_follow"]["enabled"] is False
    assert wallet["profile_json"]["event_book"]["min_source_notional_usdc"] == 3000.0
    assert wallet["profile_json"]["fixed_buy"]["enabled"] is False
    assert delete_response.status_code == 200
    assert client.get("/api/wallets").get_json()["wallets"] == []


def test_dashboard_can_manually_sell_open_holding(tmp_path: Path) -> None:
    config_path = sample_config_path(tmp_path)
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
        asset_id="manual-asset",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )
    engine = CopyTradingEngine(config=config, store=store)
    assert engine.process_trade(buy) == "processed"
    store.upsert_market_metadata(asset_id="manual-asset", current_price=0.70, title="Manual sell market")
    app = create_app(store=store, config=config, config_path=config_path)

    response = app.test_client().post(
        "/api/holdings/sell",
        json={
            "asset_id": "manual-asset",
            "source_wallet": "0x1111111111111111111111111111111111111111",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sold"] is True
    assert store.list_positions() == []
    assert any(
        trade["paper_side"] == "sell" and trade["close_reason"] == "manual_sell"
        for trade in store.list_trades()
    )


def test_dashboard_returns_skip_reason_summary(tmp_path: Path) -> None:
    config_path = sample_config_path(tmp_path)
    config = load_config(config_path)
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.sync_wallets(config.wallets)
    store.update_wallet("0x1111111111111111111111111111111111111111", allowed_market_types=["weather"])
    store.upsert_market_metadata(asset_id="manual-asset", market_type="crypto")
    trade = SourceTrade(
        idempotency_key="137:0xskip:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xskip",
        block_number=100,
        block_timestamp="2026-04-27 09:00 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="manual-asset",
        price=0.50,
        quantity=100,
        notional_usdc=50,
    )
    assert CopyTradingEngine(config=config, store=store).process_trade(trade) == "skipped"
    app = create_app(store=store, config=config, config_path=config_path)

    response = app.test_client().get("/api/skip-reasons")

    assert response.status_code == 200
    assert response.get_json()["skip_reasons"] == [
        {
            "skip_reason": "market_type_blocked",
            "count": 1,
            "source_notional_usdc": 50.0,
        }
    ]
