from pathlib import Path

from polymarket_copy_trading.config import load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.models import SourceTrade
from polymarket_copy_trading.store import Store


WALLET = "0xb40e89677d59665d5188541ad860450a6e2a7cc9"


def weather_trade(
    key: str,
    *,
    asset_id: str = "asset-66-yes",
    price: float = 0.25,
    notional: float = 0.5,
    quantity: float | None = None,
) -> SourceTrade:
    qty = quantity if quantity is not None else notional / price
    return SourceTrade(
        idempotency_key=key,
        chain_id=137,
        exchange_contract="neg_risk_ctf_exchange",
        tx_hash=key,
        block_number=100,
        block_timestamp="2026-04-27 20:45 PDT",
        log_index=int(key.rsplit("-", 1)[-1]),
        source_wallet=WALLET,
        side="buy",
        asset_id=asset_id,
        price=price,
        quantity=qty,
        notional_usdc=notional,
        market_id="m1",
        outcome="Yes",
    )


def test_wallet_config_parses_bracket_strategy_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: poligarch
    address: "{WALLET}"
    enabled: true
    bracket_strategy_enabled: true
    bracket_buy_size_usdc: 12.5
    bracket_stop_loss_pct: 18
    bracket_max_open_events: 10
    bracket_allowed_patterns: ["exact_or_binary"]
    reserved_cash_usdc: 3
""",
        encoding="utf-8",
    )

    config = load_config(path)

    wallet = config.wallets[0]
    assert wallet.bracket_strategy_enabled is True
    assert wallet.bracket_buy_size_usdc == 12.5
    assert wallet.bracket_stop_loss_pct == 18
    assert wallet.bracket_max_open_events == 10
    assert wallet.bracket_allowed_patterns == ("exact_or_binary",)
    assert wallet.reserved_cash_usdc == 3


def test_weather_bracket_accumulates_small_buys_until_target_is_reached(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="poligarch",
        address=WALLET,
        enabled=True,
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=5.0,
        bracket_stop_loss_pct=0.0,
    )
    store.upsert_market_metadata(
        asset_id="asset-66-yes",
        market_type="weather",
        event_slug="highest-temperature-in-chicago-on-april-27-2026",
        event_title="Highest temperature in Chicago on April 27",
        title="Chicago 66-67F",
        outcome="Yes",
        market_slug="highest-temperature-in-chicago-on-april-27-2026-66-67f",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.25,
    )

    assert engine.process_trade(weather_trade("tx-1", notional=0.4)) == "skipped"
    assert engine.process_trade(weather_trade("tx-2", notional=0.4)) == "skipped"
    assert engine.process_trade(weather_trade("tx-3", notional=0.4)) == "processed"

    bracket = store.get_weather_bracket(WALLET, "highest-temperature-in-chicago-on-april-27-2026")
    assert bracket is not None
    assert bracket["source_notional_usdc"] == 1.2
    assert bracket["copied_notional_usdc"] == 1.2
    assert len(store.list_positions()) == 1


def test_weather_bracket_allocates_buy_size_across_multiple_legs(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="poligarch",
        address=WALLET,
        enabled=True,
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=10.0,
        bracket_stop_loss_pct=0.0,
    )
    for asset_id, outcome in (("asset-66-yes", "Yes"), ("asset-68-no", "No")):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="weather",
            event_slug="highest-temperature-in-chicago-on-april-27-2026",
            event_title="Highest temperature in Chicago on April 27",
            title=asset_id,
            outcome=outcome,
            market_slug=asset_id,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.25,
    )

    assert engine.process_trade(weather_trade("tx-1", asset_id="asset-66-yes", notional=6.0)) == "processed"
    assert engine.process_trade(weather_trade("tx-2", asset_id="asset-68-no", notional=4.0)) == "processed"

    legs = store.list_weather_bracket_legs(WALLET, "highest-temperature-in-chicago-on-april-27-2026")
    by_asset = {leg["asset_id"]: leg for leg in legs}
    assert by_asset["asset-66-yes"]["target_notional_usdc"] == 6.0
    assert by_asset["asset-68-no"]["target_notional_usdc"] == 4.0


def test_weather_bracket_respects_wallet_open_event_cap(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="poligarch",
        address=WALLET,
        enabled=True,
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=5.0,
        bracket_stop_loss_pct=0.0,
        bracket_max_open_events=1,
    )
    store.upsert_market_metadata(
        asset_id="asset-chicago",
        market_type="weather",
        event_slug="highest-temperature-in-chicago-on-april-27-2026",
        event_title="Highest temperature in Chicago on April 27",
        title="Chicago 66-67F",
        outcome="Yes",
        market_slug="chicago-66-67f",
    )
    store.upsert_market_metadata(
        asset_id="asset-seoul",
        market_type="weather",
        event_slug="highest-temperature-in-seoul-on-april-27-2026",
        event_title="Highest temperature in Seoul on April 27",
        title="Seoul 21C",
        outcome="Yes",
        market_slug="seoul-21c",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.25,
    )

    assert engine.process_trade(weather_trade("tx-1", asset_id="asset-chicago", notional=3.0)) == "processed"
    assert engine.process_trade(weather_trade("tx-2", asset_id="asset-seoul", notional=3.0)) == "skipped"

    assert store.count_open_weather_events(WALLET) == 1
    assert store.list_positions()[0]["asset_id"] == "asset-chicago"
    assert store.skip_reason_summary()[0]["skip_reason"] == "weather_bracket_event_cap"


def test_weather_bracket_respects_cash_reserved_for_other_wallets(tmp_path: Path) -> None:
    rn1 = "0x1111111111111111111111111111111111111111"
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="poligarch",
        address=WALLET,
        enabled=True,
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=5.0,
        bracket_stop_loss_pct=0.0,
    )
    store.upsert_wallet(name="RN1", address=rn1, enabled=True, reserved_cash_usdc=50.0)
    store.upsert_market_metadata(
        asset_id="asset-66-yes",
        market_type="weather",
        event_slug="highest-temperature-in-chicago-on-april-27-2026",
        event_title="Highest temperature in Chicago on April 27",
        title="Chicago 66-67F",
        outcome="Yes",
        market_slug="chicago-66-67f",
    )
    settings = _settings(tmp_path)
    store.set_runtime_state("paper_cash_usdc", "50.5")
    engine = CopyTradingEngine(
        config=settings,
        store=store,
        buy_price_resolver=lambda asset_id: 0.25,
    )

    assert engine.process_trade(weather_trade("tx-1", notional=3.0)) == "skipped"

    assert store.list_positions() == []
    assert store.skip_reason_summary()[0]["skip_reason"] == "reserved_cash"


def test_weather_bracket_skips_patterns_not_allowed_by_wallet(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="poligarch",
        address=WALLET,
        enabled=True,
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=3.0,
        bracket_stop_loss_pct=70.0,
        bracket_allowed_patterns=["exact_or_binary"],
    )
    store.upsert_market_metadata(
        asset_id="asset-range",
        market_type="weather",
        event_slug="highest-temperature-in-miami-on-april-28-2026",
        event_title="Highest temperature in Miami on April 28",
        title="Will the highest temperature in Miami be between 86-87°F on April 28?",
        outcome="No",
        market_slug="highest-temperature-in-miami-on-april-28-2026-between-86-87f",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.25,
    )

    assert engine.process_trade(weather_trade("tx-1", asset_id="asset-range", notional=3.0)) == "skipped"

    assert store.list_positions() == []
    assert store.skip_reason_summary()[0]["skip_reason"] == "weather_bracket_pattern_blocked"


def test_weather_bracket_allows_exact_binary_with_larger_configured_size(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="poligarch",
        address=WALLET,
        enabled=True,
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=3.0,
        bracket_stop_loss_pct=70.0,
        bracket_allowed_patterns=["exact_or_binary"],
    )
    store.upsert_market_metadata(
        asset_id="asset-exact",
        market_type="weather",
        event_slug="highest-temperature-in-kuala-lumpur-on-april-28-2026",
        event_title="Highest temperature in Kuala Lumpur on April 28",
        title="Will the highest temperature in Kuala Lumpur be 35°C on April 28?",
        outcome="No",
        market_slug="highest-temperature-in-kuala-lumpur-on-april-28-2026-35c",
    )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.25,
    )

    assert engine.process_trade(weather_trade("tx-1", asset_id="asset-exact", notional=3.0)) == "processed"

    assert store.list_positions()[0]["cost_basis_usdc"] == 3.0


def test_weather_bracket_applies_source_trade_minimum_and_price_band(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="vip68",
        address=WALLET,
        enabled=True,
        strategy_label="Custom",
        allowed_market_types=["weather"],
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=5.0,
        bracket_stop_loss_pct=0.0,
        bracket_max_open_events=3,
        repeat_buy_strategy_enabled=False,
        event_follow_strategy_enabled=False,
        event_follow_min_source_trade_usdc=5.0,
        event_follow_min_avg_price=0.15,
        event_follow_max_avg_price=0.899,
        reserved_cash_usdc=20.0,
    )
    for asset_id in ("asset-small", "asset-cheap", "asset-expensive", "asset-valid"):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="weather",
            event_slug=f"weather-{asset_id}",
            event_title="Highest temperature in Chicago",
            title="Chicago 66-67F",
            outcome="Yes" if asset_id == "asset-valid" else "No",
            market_slug=f"weather-{asset_id}",
        )
    engine = CopyTradingEngine(config=_settings(tmp_path), store=store)

    assert engine.process_trade(weather_trade("tx-1", asset_id="asset-small", price=0.25, notional=4.0)) == "skipped"
    assert engine.process_trade(weather_trade("tx-2", asset_id="asset-cheap", price=0.10, notional=5.0)) == "skipped"
    assert engine.process_trade(weather_trade("tx-3", asset_id="asset-expensive", price=0.90, notional=5.0)) == "skipped"
    assert engine.process_trade(weather_trade("tx-4", asset_id="asset-valid", price=0.899, notional=5.0)) == "processed"

    summary = {row["skip_reason"]: row["count"] for row in store.skip_reason_summary()}
    assert summary["weather_bracket_source_trade_too_small"] == 1
    assert summary["weather_bracket_price_band_blocked"] == 2
    position = store.list_positions()[0]
    assert position["asset_id"] == "asset-valid"
    assert position["cost_basis_usdc"] == 5.0


def test_vip68_weather_bracket_copies_source_leg_size_capped_at_configured_size(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.sqlite3")
    store.initialize()
    store.upsert_wallet(
        name="vip68",
        address=WALLET,
        enabled=True,
        strategy_label="Custom",
        allowed_market_types=["weather"],
        bracket_strategy_enabled=True,
        bracket_buy_size_usdc=5.0,
        bracket_stop_loss_pct=0.0,
        bracket_max_open_events=8,
        repeat_buy_strategy_enabled=False,
        event_follow_strategy_enabled=False,
        event_follow_min_source_trade_usdc=2.5,
        event_follow_min_avg_price=0.05,
        event_follow_max_avg_price=0.899,
        reserved_cash_usdc=0.0,
    )
    for asset_id, slug in (
        ("asset-dominant", "highest-temperature-in-guangzhou-on-may-1-2026-27c"),
        ("asset-upside", "highest-temperature-in-guangzhou-on-may-1-2026-30c"),
    ):
        store.upsert_market_metadata(
            asset_id=asset_id,
            market_type="weather",
            event_slug="highest-temperature-in-guangzhou-on-may-1-2026",
            event_title="Highest temperature in Guangzhou on May 1?",
            title=slug,
            outcome="Yes",
            market_slug=slug,
        )
    engine = CopyTradingEngine(
        config=_settings(tmp_path),
        store=store,
        buy_price_resolver=lambda asset_id: 0.06 if asset_id == "asset-upside" else 0.80,
    )

    assert engine.process_trade(weather_trade("tx-1", asset_id="asset-dominant", price=0.80, notional=100.0)) == "processed"
    assert engine.process_trade(weather_trade("tx-2", asset_id="asset-upside", price=0.06, notional=3.0)) == "processed"

    positions = {position["asset_id"]: position for position in store.list_positions()}
    assert positions["asset-dominant"]["cost_basis_usdc"] == 5.0
    assert positions["asset-upside"]["cost_basis_usdc"] == 3.0


def _settings(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: poligarch
    address: "{WALLET}"
    enabled: true
    bracket_strategy_enabled: true
    bracket_buy_size_usdc: 5
    bracket_stop_loss_pct: 0
sizing:
  min_trade_usdc: 1
  max_trade_usdc: 100
  max_position_usdc: 100
paper:
  starting_cash_usdc: 100
  slippage_pct: 0
""",
        encoding="utf-8",
    )
    return load_config(path)
