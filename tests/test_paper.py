from polymarket_copy_trading.models import PaperFill, SourceTrade
import pytest

from polymarket_copy_trading.paper import PaperBroker, PaperExecutionError


def make_trade(
    side: str,
    price: float,
    quantity: float,
    notional: float,
    *,
    wallet: str = "0x1111111111111111111111111111111111111111",
) -> SourceTrade:
    return SourceTrade(
        idempotency_key=f"137:0x{side}:1:{wallet}",
        chain_id=137,
        exchange_contract="ctf_exchange",
        tx_hash=f"0x{side}",
        block_number=100,
        block_timestamp="2026-04-26 16:15 PDT",
        log_index=1,
        source_wallet=wallet,
        side=side,
        asset_id="123",
        price=price,
        quantity=quantity,
        notional_usdc=notional,
    )


def test_paper_buy_applies_adverse_slippage_and_opens_lot() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=5)

    fill = broker.buy(make_trade("buy", 0.50, 800, 400), notional_usdc=100)

    assert isinstance(fill, PaperFill)
    assert fill.side == "buy"
    assert fill.fill_price == 0.525
    assert round(fill.quantity, 6) == round(100 / 0.525, 6)
    assert broker.cash_usdc == 900
    position = broker.get_position("123", "0x1111111111111111111111111111111111111111")
    assert position is not None
    assert position.quantity == fill.quantity


def test_paper_buy_rejects_entries_that_slip_to_one_dollar() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=5)

    with pytest.raises(PaperExecutionError, match="slipped buy price must be below 1.00"):
        broker.buy(make_trade("buy", 0.96, 800, 768), notional_usdc=100)

    assert broker.cash_usdc == 1000
    assert broker.get_position("123", "0x1111111111111111111111111111111111111111") is None


def test_paper_buy_allows_point_ninety_five_before_five_percent_slippage() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=5)

    fill = broker.buy(make_trade("buy", 0.95, 800, 760), notional_usdc=100)

    assert fill.fill_price == 0.9975


def test_paper_sell_applies_adverse_slippage_and_realizes_pnl_fifo() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=5)
    broker.buy(make_trade("buy", 0.50, 800, 400), notional_usdc=100)

    fill = broker.sell(make_trade("sell", 0.70, 100, 70), quantity=100, close_reason="source_sell")

    assert fill.side == "sell"
    assert fill.fill_price == 0.665
    assert fill.quantity == 100
    assert round(fill.realized_pnl_usdc, 6) == 14
    assert broker.cash_usdc == 966.5
    position = broker.get_position("123", "0x1111111111111111111111111111111111111111")
    assert position is not None
    assert round(position.quantity, 6) == round((100 / 0.525) - 100, 6)


def test_paper_market_settlement_uses_settlement_slippage_not_trade_slippage() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=5, settlement_slippage_pct=0)
    broker.buy(make_trade("buy", 0.50, 800, 400), notional_usdc=100)

    fill = broker.sell(make_trade("sell", 1.0, 100, 100), quantity=100, close_reason="market_settlement")

    assert fill.fill_price == 1.0
    assert round(fill.realized_pnl_usdc, 6) == 47.5


def test_paper_market_settlement_can_apply_small_configured_slippage() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=5, settlement_slippage_pct=0.5)
    broker.buy(make_trade("buy", 0.50, 800, 400), notional_usdc=100)

    fill = broker.sell(make_trade("sell", 1.0, 100, 100), quantity=100, close_reason="market_settlement")

    assert fill.fill_price == 0.995


def test_paper_positions_are_isolated_by_source_wallet() -> None:
    broker = PaperBroker(starting_cash_usdc=1000, slippage_pct=0)
    first_wallet = "0x1111111111111111111111111111111111111111"
    second_wallet = "0x2222222222222222222222222222222222222222"

    broker.buy(make_trade("buy", 0.50, 200, 100, wallet=first_wallet), notional_usdc=100)
    broker.buy(make_trade("buy", 0.50, 400, 200, wallet=second_wallet), notional_usdc=200)

    first = broker.get_position("123", first_wallet)
    second = broker.get_position("123", second_wallet)

    assert first is not None
    assert second is not None
    assert first.cost_basis_usdc == 100
    assert second.cost_basis_usdc == 200
