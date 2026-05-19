from pathlib import Path

import pytest

from polymarket_copy_trading.config import ConfigError, default_wallet_profile_json, load_config


def test_load_config_reads_wallets_and_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
sizing:
  copy_scale: 0.5
paper:
  starting_cash_usdc: 1000
watcher:
  ws_ping_interval_seconds: 12
  ws_ping_timeout_seconds: 34
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.mode.paper_trading is True
    assert config.mode.live_trading is False
    assert config.wallets[0].name == "alpha"
    assert config.wallets[0].address == "0x1111111111111111111111111111111111111111"
    assert config.wallets[0].enabled is True
    assert config.sizing.copy_scale == 0.5
    assert config.sizing.max_trade_usdc == 100
    assert config.paper.slippage_pct == 5
    assert config.paper.settlement_slippage_pct == 0
    assert config.exits.mirror_source_sells is True
    assert config.watcher.ws_ping_interval_seconds == 12
    assert config.watcher.ws_ping_timeout_seconds == 34
    assert config.price_monitor.enabled is True
    assert config.price_monitor.poll_interval_seconds == 30.0
    assert config.price_monitor.idle_poll_interval_seconds == 300.0
    assert config.wallets[0].profile_json == default_wallet_profile_json()


def test_config_reads_wallet_profile_json(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: rn1
    address: "0x1111111111111111111111111111111111111111"
    strategy_label: Custom
    profile_json:
      source_follow:
        copy_scale: 0.002
        max_asset_exposure_usdc: 12
      event_book:
        min_dominance_share: 0.55
        min_dominance_ratio: 1.4
""",
        encoding="utf-8",
    )

    wallet = load_config(path).wallets[0]

    assert wallet.profile_json["source_follow"]["copy_scale"] == 0.002
    assert wallet.profile_json["source_follow"]["max_asset_exposure_usdc"] == 12.0
    assert wallet.profile_json["event_book"]["min_dominance_share"] == 0.55
    assert wallet.profile_json["event_book"]["min_dominance_ratio"] == 1.4
    assert wallet.profile_json["strategy"]["custom"] is True


def test_config_reads_full_wallet_profile_json(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: rn1
    address: "0x1111111111111111111111111111111111111111"
    profile_json:
      market_filters:
        allowed_market_types: ["sports", "weather"]
      weather_bracket:
        enabled: true
        copy_source_leg_size: true
        buy_size_usdc: 11
        stop_loss_pct: 9
        max_open_events: 2
        allowed_patterns: ["exact_or_binary"]
      repeat_buy:
        enabled: true
        buy_size_usdc: 7
        stop_loss_pct: 12
        min_source_notional_usdc: 3000
        min_buy_count: 4
        min_avg_price: 0.2
        max_avg_price: 0.7
        max_total_exposure_usdc: 60
        blocked_title_patterns: ["winner"]
        allowed_sports: ["MLB"]
        allowed_bet_types: ["Moneyline_WinLose"]
      event_follow:
        enabled: true
        buy_size_usdc: 3
        max_event_exposure_usdc: 15
        max_total_exposure_usdc: 50
        min_source_trade_usdc: 0
        min_event_source_notional_usdc: 3000
        min_event_buy_count: 3
        min_avg_price: 0.3
        max_avg_price: 0.8
        allowed_sports: ["MLB"]
        allowed_bet_types: ["Moneyline_WinLose"]
      sports_trailing:
        enabled: true
        activation_pct: 30
        stop_pct: 20
        floor_delta: 0.04
      risk:
        reserved_cash_usdc: 25
        local_stop_loss_enabled: false
      source_follow:
        enabled: true
        copy_scale: 0.002
        max_asset_exposure_usdc: 12
        min_trade_usdc: 1
      event_book:
        min_source_notional_usdc: 3000
        min_avg_price: 0.4
        max_avg_price: 0.7
        min_dominance_share: 0.55
        min_dominance_ratio: 1.4
      fixed_buy:
        enabled: true
        buy_size_usdc: 4
        market_types: ["crypto"]
      binary_hedge:
        enabled: true
      limit_copy:
        limit_price_premium: 0.003
        limit_price_multiple: 1.2
        source_copy_scale: 0.25
      tier_sizing:
        tiers:
          - min_price: 0.3
            max_price: 0.65
            buy_size_usdc: 3
      esports_repeat_buy:
        min_buy_count: 40
        min_source_notional_usdc: 3000
        min_avg_price: 0.4
        max_avg_price: 0.7
        allowed_bet_types: ["Moneyline_WinLose"]
      high_conviction:
        min_buy_count: 10
        min_source_notional_usdc: 3000
        min_avg_price: 0.4
        max_avg_price: 0.7
      strategy:
        custom: true
""",
        encoding="utf-8",
    )

    profile = load_config(path).wallets[0].profile_json

    assert profile["market_filters"]["allowed_market_types"] == ["sports", "weather"]
    assert profile["weather_bracket"]["enabled"] is True
    assert profile["weather_bracket"]["copy_source_leg_size"] is True
    assert profile["weather_bracket"]["buy_size_usdc"] == 11.0
    assert profile["weather_bracket"]["allowed_patterns"] == ["exact_or_binary"]
    assert profile["repeat_buy"]["enabled"] is True
    assert profile["repeat_buy"]["min_source_notional_usdc"] == 3000.0
    assert profile["repeat_buy"]["allowed_sports"] == ["mlb"]
    assert profile["repeat_buy"]["allowed_bet_types"] == ["moneyline_winlose"]
    assert profile["event_follow"]["min_source_trade_usdc"] == 0.0
    assert profile["event_follow"]["max_event_exposure_usdc"] == 15.0
    assert profile["event_follow"]["allowed_sports"] == ["mlb"]
    assert profile["event_follow"]["allowed_bet_types"] == ["moneyline_winlose"]
    assert profile["sports_trailing"]["stop_pct"] == 20.0
    assert profile["risk"]["reserved_cash_usdc"] == 25.0
    assert profile["risk"]["local_stop_loss_enabled"] is False
    assert profile["source_follow"]["enabled"] is True
    assert profile["source_follow"]["min_trade_usdc"] == 1.0
    assert profile["event_book"]["min_source_notional_usdc"] == 3000.0
    assert profile["event_book"]["min_avg_price"] == 0.4
    assert profile["event_book"]["max_avg_price"] == 0.7
    assert profile["fixed_buy"]["enabled"] is True
    assert profile["fixed_buy"]["buy_size_usdc"] == 4.0
    assert profile["fixed_buy"]["market_types"] == ["crypto"]
    assert profile["binary_hedge"]["enabled"] is True
    assert profile["limit_copy"]["limit_price_premium"] == 0.003
    assert profile["limit_copy"]["limit_price_multiple"] == 1.2
    assert profile["limit_copy"]["source_copy_scale"] == 0.25
    assert profile["tier_sizing"]["tiers"] == [{"min_price": 0.3, "max_price": 0.65, "buy_size_usdc": 3.0}]
    assert profile["esports_repeat_buy"]["allowed_bet_types"] == ["moneyline_winlose"]
    assert profile["high_conviction"]["min_buy_count"] == 10
    assert profile["strategy"]["custom"] is True


def test_config_rejects_invalid_wallet_profile_json(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: bad
    address: "0x1111111111111111111111111111111111111111"
    profile_json: ["not", "a", "mapping"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="profile_json"):
        load_config(path)


@pytest.mark.parametrize(
    ("profile_yaml", "message"),
    [
        ("market_filters:\n        allowed_market_types: sports", "allowed_market_types"),
        ("weather_bracket:\n        allowed_patterns: ['bad_pattern']", "allowed_patterns"),
        ("repeat_buy:\n        min_buy_count: 1", "min_buy_count"),
        ("repeat_buy:\n        min_avg_price: 0.8\n        max_avg_price: 0.2", "repeat_buy price band"),
        ("event_follow:\n        max_total_exposure_usdc: 0", "max_total_exposure_usdc"),
        ("sports_trailing:\n        stop_pct: 100", "stop_pct"),
        ("risk:\n        reserved_cash_usdc: -1", "reserved_cash_usdc"),
        ("risk:\n        local_stop_loss_enabled: nope", "local_stop_loss_enabled"),
        ("source_follow:\n        copy_scale: -0.1", "copy_scale"),
        ("source_follow:\n        enabled: nope", "enabled"),
        ("event_book:\n        min_avg_price: 0.9\n        max_avg_price: 0.2", "event_book price band"),
        ("fixed_buy:\n        buy_size_usdc: 0", "buy_size_usdc"),
        ("fixed_buy:\n        market_types: ['bad']", "market_types"),
        ("binary_hedge:\n        enabled: nope", "enabled"),
        ("limit_copy:\n        limit_price_multiple: 0", "limit_price_multiple"),
        ("limit_copy:\n        source_copy_scale: -0.1", "source_copy_scale"),
        ("tier_sizing:\n        tiers:\n          - min_price: 0.8\n            max_price: 0.4\n            buy_size_usdc: 1", "tier_sizing"),
        ("esports_repeat_buy:\n        min_buy_count: 0", "min_buy_count"),
        ("high_conviction:\n        min_avg_price: 0.9\n        max_avg_price: 0.2", "high_conviction price band"),
        ("strategy:\n        custom: nope", "custom"),
    ],
)
def test_config_rejects_invalid_wallet_profile_values(tmp_path: Path, profile_yaml: str, message: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: bad
    address: "0x1111111111111111111111111111111111111111"
    profile_json:
      {profile_yaml}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_config_accepts_live_trading_as_runtime_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: false
  live_trading: true
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.mode.trading_mode == "live"
    assert config.mode.paper_trading is False
    assert config.mode.live_trading is True


def test_config_rejects_invalid_wallet_address(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: bad
    address: "not-an-address"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="wallet"):
        load_config(path)


def test_config_allows_zero_copy_scale_for_local_cap_sizing(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
sizing:
  copy_scale: 0
""",
        encoding="utf-8",
    )

    assert load_config(path).sizing.copy_scale == 0


def test_config_reads_market_type_filters_and_exit_profiles(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode:
  paper_trading: true
  live_trading: false
wallets:
  - name: alpha
    address: "0x1111111111111111111111111111111111111111"
    allowed_market_types: ["crypto", "sports"]
market_filters:
  enabled_market_types: ["crypto", "weather"]
exits:
  mirror_source_sells: true
  stop_loss_pct: 25
  take_profit_pct: 50
  market_profiles:
    crypto:
      stop_loss_pct: 12
      take_profit_pct: 20
      max_holding_minutes: 60
    weather:
      stop_loss_pct: 0
      take_profit_pct: 0
      max_holding_minutes: 0
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.wallets[0].allowed_market_types == ("crypto", "sports")
    assert config.market_filters.enabled_market_types == ("crypto", "weather")
    assert config.exits.profile_for("crypto").stop_loss_pct == 12
    assert config.exits.profile_for("weather").take_profit_pct == 0
