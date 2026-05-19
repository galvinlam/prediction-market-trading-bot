from __future__ import annotations

from polymarket_copy_trading.config import SizingConfig
from polymarket_copy_trading.models import SizingDecision, SourceTrade


class ScaledSourceSizer:
    def __init__(self, config: SizingConfig) -> None:
        self.config = config

    def size_buy(
        self,
        source_trade: SourceTrade,
        *,
        current_position_usdc: float,
        available_cash_usdc: float,
    ) -> SizingDecision:
        position_room = max(0.0, self.config.max_position_usdc - current_position_usdc)
        target = max(0.0, source_trade.notional_usdc * self.config.copy_scale)
        capped = min(target, self.config.max_trade_usdc, position_room, available_cash_usdc)

        if capped < self.config.min_trade_usdc:
            return SizingDecision(False, 0.0, "below_min_trade")

        reason = "sized" if capped == target else "reduced_by_cap"
        return SizingDecision(True, round(capped, 6), reason)
