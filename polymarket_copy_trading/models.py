from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceTrade:
    idempotency_key: str
    chain_id: int
    exchange_contract: str
    tx_hash: str
    block_number: int
    block_timestamp: str
    log_index: int
    source_wallet: str
    side: str
    asset_id: str
    price: float
    quantity: float
    notional_usdc: float
    condition_id: str | None = None
    market_id: str | None = None
    outcome: str | None = None
    raw_maker: str | None = None
    raw_taker: str | None = None
    raw_maker_asset_id: str | None = None
    raw_taker_asset_id: str | None = None
    raw_maker_amount_filled: str | None = None
    raw_taker_amount_filled: str | None = None
    copy_trade_key: str | None = None

    @property
    def normalized_copy_trade_key(self) -> str:
        if self.copy_trade_key:
            return self.copy_trade_key
        return f"{self.side.lower()}:{self.asset_id}:{self.price:.6f}:{self.notional_usdc:.6f}"


@dataclass(frozen=True)
class SizingDecision:
    should_trade: bool
    notional_usdc: float
    reason: str


@dataclass(frozen=True)
class PaperFill:
    source_idempotency_key: str
    side: str
    asset_id: str
    source_wallet: str
    observed_price: float
    fill_price: float
    quantity: float
    notional_usdc: float
    realized_pnl_usdc: float = 0.0
    close_reason: str | None = None


@dataclass
class PositionLot:
    quantity: float
    entry_price: float
    source_wallet: str
    source_idempotency_key: str


@dataclass
class Position:
    asset_id: str
    source_wallet: str
    lots: list[PositionLot] = field(default_factory=list)
    realized_pnl_usdc: float = 0.0

    @property
    def quantity(self) -> float:
        return sum(lot.quantity for lot in self.lots)

    @property
    def cost_basis_usdc(self) -> float:
        return sum(lot.quantity * lot.entry_price for lot in self.lots)

    @property
    def average_entry_price(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return self.cost_basis_usdc / self.quantity
