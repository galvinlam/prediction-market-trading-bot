from __future__ import annotations

from dataclasses import dataclass

from polymarket_copy_trading.config import ExitConfig


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str | None = None


class RiskEngine:
    def __init__(self, config: ExitConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        entry_price: float,
        mark_price: float | None,
        holding_minutes: int,
        source_sell_seen: bool,
    ) -> ExitDecision:
        if source_sell_seen and self.config.mirror_source_sells:
            return ExitDecision(True, "source_sell")
        if mark_price is None or entry_price <= 0:
            return ExitDecision(False)

        change_pct = ((mark_price - entry_price) / entry_price) * 100
        if change_pct <= -self.config.stop_loss_pct:
            return ExitDecision(True, "stop_loss")
        if holding_minutes >= self.config.max_holding_minutes:
            return ExitDecision(True, "max_holding_time")
        if change_pct >= self.config.take_profit_pct:
            return ExitDecision(True, "take_profit")
        return ExitDecision(False)
