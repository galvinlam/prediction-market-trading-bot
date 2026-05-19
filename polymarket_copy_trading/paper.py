from __future__ import annotations

from polymarket_copy_trading.models import PaperFill, Position, PositionLot, SourceTrade


class PaperExecutionError(RuntimeError):
    pass


class PaperBroker:
    def __init__(
        self,
        *,
        starting_cash_usdc: float,
        slippage_pct: float,
        settlement_slippage_pct: float = 0.0,
    ) -> None:
        self.cash_usdc = float(starting_cash_usdc)
        self.slippage_pct = float(slippage_pct)
        self.settlement_slippage_pct = float(settlement_slippage_pct)
        self.positions: dict[tuple[str, str], Position] = {}

    @staticmethod
    def position_key(asset_id: str, source_wallet: str) -> tuple[str, str]:
        return (str(asset_id), str(source_wallet).lower())

    def get_position(self, asset_id: str, source_wallet: str) -> Position | None:
        return self.positions.get(self.position_key(asset_id, source_wallet))

    def buy(self, source_trade: SourceTrade, *, notional_usdc: float, observed_price: float | None = None) -> PaperFill:
        if source_trade.side != "buy":
            raise PaperExecutionError("buy requires a source buy trade")
        if notional_usdc <= 0:
            raise PaperExecutionError("buy notional must be positive")
        if notional_usdc > self.cash_usdc:
            raise PaperExecutionError("insufficient paper cash")

        entry_price = source_trade.price if observed_price is None else observed_price
        if entry_price <= 0:
            raise PaperExecutionError("buy observed price must be positive")

        fill_price = round(entry_price * (1 + self.slippage_pct / 100), 6)
        if fill_price >= 1.0:
            raise PaperExecutionError("slipped buy price must be below 1.00")
        quantity = notional_usdc / fill_price
        position = self.positions.setdefault(
            self.position_key(source_trade.asset_id, source_trade.source_wallet),
            Position(asset_id=source_trade.asset_id, source_wallet=source_trade.source_wallet),
        )
        position.lots.append(
            PositionLot(
                quantity=quantity,
                entry_price=fill_price,
                source_wallet=source_trade.source_wallet,
                source_idempotency_key=source_trade.idempotency_key,
            )
        )
        self.cash_usdc -= notional_usdc

        return PaperFill(
            source_idempotency_key=source_trade.idempotency_key,
            side="buy",
            asset_id=source_trade.asset_id,
            source_wallet=source_trade.source_wallet,
            observed_price=entry_price,
            fill_price=fill_price,
            quantity=quantity,
            notional_usdc=notional_usdc,
        )

    def sell(
        self,
        source_trade: SourceTrade,
        *,
        quantity: float,
        close_reason: str,
        fill_price_override: float | None = None,
    ) -> PaperFill:
        if source_trade.side != "sell":
            raise PaperExecutionError("sell requires a source sell trade")
        if quantity <= 0:
            raise PaperExecutionError("sell quantity must be positive")

        position = self.get_position(source_trade.asset_id, source_trade.source_wallet)
        if position is None or position.quantity <= 0:
            raise PaperExecutionError("cannot sell without an open paper position")

        sell_quantity = min(quantity, position.quantity)
        if fill_price_override is not None:
            fill_price = round(max(0.0, fill_price_override), 6)
        else:
            slippage_pct = self.settlement_slippage_pct if close_reason == "market_settlement" else self.slippage_pct
            fill_price = round(max(0.0, source_trade.price * (1 - slippage_pct / 100)), 6)
        realized = self._consume_lots(position, sell_quantity, fill_price)
        proceeds = sell_quantity * fill_price
        self.cash_usdc += proceeds
        position.realized_pnl_usdc += realized

        return PaperFill(
            source_idempotency_key=source_trade.idempotency_key,
            side="sell",
            asset_id=source_trade.asset_id,
            source_wallet=source_trade.source_wallet,
            observed_price=source_trade.price,
            fill_price=fill_price,
            quantity=sell_quantity,
            notional_usdc=proceeds,
            realized_pnl_usdc=realized,
            close_reason=close_reason,
        )

    def _consume_lots(self, position: Position, quantity: float, fill_price: float) -> float:
        remaining = quantity
        realized = 0.0
        while remaining > 0 and position.lots:
            lot = position.lots[0]
            consumed = min(lot.quantity, remaining)
            realized += (fill_price - lot.entry_price) * consumed
            lot.quantity -= consumed
            remaining -= consumed
            if lot.quantity <= 1e-9:
                position.lots.pop(0)
        return realized
