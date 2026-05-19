from polymarket_copy_trading.bet_sizing import ScaledSourceSizer
from polymarket_copy_trading.config import SizingConfig
from polymarket_copy_trading.models import SourceTrade


def make_buy(notional: float = 400.0) -> SourceTrade:
    return SourceTrade(
        idempotency_key="137:0xaaa:1:0x1111111111111111111111111111111111111111",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash="0xaaa",
        block_number=100,
        block_timestamp="2026-04-26 16:15 PDT",
        log_index=1,
        source_wallet="0x1111111111111111111111111111111111111111",
        side="buy",
        asset_id="123",
        price=0.50,
        quantity=800.0,
        notional_usdc=notional,
    )


def test_scaled_source_sizer_applies_copy_scale_before_local_caps() -> None:
    sizer = ScaledSourceSizer(SizingConfig(copy_scale=0.01, max_trade_usdc=100, max_position_usdc=10))

    decision = sizer.size_buy(make_buy(), current_position_usdc=0, available_cash_usdc=1000)

    assert decision.should_trade is False
    assert decision.notional_usdc == 0
    assert decision.reason == "below_min_trade"


def test_scaled_source_sizer_uses_scaled_source_size_when_inside_caps() -> None:
    sizer = ScaledSourceSizer(SizingConfig(copy_scale=0.02, max_trade_usdc=100, max_position_usdc=10))

    decision = sizer.size_buy(make_buy(), current_position_usdc=0, available_cash_usdc=1000)

    assert decision.should_trade is True
    assert decision.notional_usdc == 8
    assert decision.reason == "sized"


def test_scaled_source_sizer_applies_trade_position_and_cash_caps() -> None:
    sizer = ScaledSourceSizer(SizingConfig(copy_scale=1, max_trade_usdc=300, max_position_usdc=250))

    decision = sizer.size_buy(make_buy(), current_position_usdc=100, available_cash_usdc=80)

    assert decision.should_trade is True
    assert decision.notional_usdc == 80
    assert decision.reason == "reduced_by_cap"


def test_scaled_source_sizer_skips_when_reduced_below_min_trade() -> None:
    sizer = ScaledSourceSizer(SizingConfig(copy_scale=1, max_trade_usdc=300, max_position_usdc=250, min_trade_usdc=25))

    decision = sizer.size_buy(make_buy(), current_position_usdc=240, available_cash_usdc=1000)

    assert decision.should_trade is False
    assert decision.notional_usdc == 0
    assert decision.reason == "below_min_trade"
