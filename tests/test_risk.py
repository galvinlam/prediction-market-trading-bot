from polymarket_copy_trading.config import ExitConfig
from polymarket_copy_trading.risk import RiskEngine


def test_risk_engine_prioritizes_source_sell_over_local_exits() -> None:
    engine = RiskEngine(ExitConfig(stop_loss_pct=10, take_profit_pct=20, max_holding_minutes=60))

    decision = engine.evaluate(
        entry_price=0.50,
        mark_price=0.40,
        holding_minutes=120,
        source_sell_seen=True,
    )

    assert decision.should_exit is True
    assert decision.reason == "source_sell"


def test_risk_engine_uses_stop_loss_before_max_age_and_take_profit() -> None:
    engine = RiskEngine(ExitConfig(stop_loss_pct=10, take_profit_pct=20, max_holding_minutes=60))

    decision = engine.evaluate(
        entry_price=0.50,
        mark_price=0.40,
        holding_minutes=120,
        source_sell_seen=False,
    )

    assert decision.should_exit is True
    assert decision.reason == "stop_loss"


def test_risk_engine_uses_take_profit_when_no_more_conservative_exit_applies() -> None:
    engine = RiskEngine(ExitConfig(stop_loss_pct=10, take_profit_pct=20, max_holding_minutes=60))

    decision = engine.evaluate(
        entry_price=0.50,
        mark_price=0.62,
        holding_minutes=10,
        source_sell_seen=False,
    )

    assert decision.should_exit is True
    assert decision.reason == "take_profit"
