from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventBookLeg:
    asset_id: str
    net_notional_usdc: float
    net_quantity: float
    title: str = ""
    outcome: str = ""
    avg_price: float | None = None
    current_price: float | None = None


@dataclass(frozen=True)
class EventBookPlannerSettings:
    total_bankroll_usdc: float = 100.0
    normal_capital_usdc: float = 80.0
    reserve_capital_usdc: float = 20.0
    base_event_budget_usdc: float = 5.0
    max_event_budget_usdc: float = 10.0
    max_rebalance_reserve_usdc: float = 5.0
    available_normal_cash_usdc: float = 80.0
    available_reserve_cash_usdc: float = 20.0
    min_order_notional_usdc: float = 1.0
    fresh_min_price: float = 0.01
    fresh_max_price: float = 0.80
    rebalance_min_price: float = 0.01
    rebalance_max_price: float = 0.95
    conviction_floor_source_notional_usdc: float = 3000.0
    reserve_shape_improvement_fraction: float = 0.20


@dataclass(frozen=True)
class PlannerDecision:
    asset_id: str
    decision: str
    reason: str
    target_notional_usdc: float
    local_notional_usdc: float
    current_price: float
    source_notional_weight: float
    source_quantity_weight: float


@dataclass(frozen=True)
class BuyPlan(PlannerDecision):
    notional_usdc: float
    quantity: float
    used_normal_cash_usdc: float
    used_reserve_usdc: float
    target_quantity: float


@dataclass(frozen=True)
class EventBookPlan:
    orders: tuple[BuyPlan, ...]
    rejections: tuple[PlannerDecision, ...]
    target_event_notional_usdc: float
    target_event_quantity: float
    normal_cash_remaining_usdc: float
    reserve_cash_remaining_usdc: float


@dataclass(frozen=True)
class _Candidate:
    leg: EventBookLeg
    decision: str
    target_notional_usdc: float
    local_notional_usdc: float
    current_price: float
    source_notional_weight: float
    source_quantity_weight: float
    target_quantity: float
    source_index: int

    @property
    def deficit_usdc(self) -> float:
        return max(0.0, self.target_notional_usdc - self.local_notional_usdc)

    @property
    def deficit_ratio(self) -> float:
        if self.target_notional_usdc <= 0:
            return 0.0
        return self.deficit_usdc / self.target_notional_usdc


def plan_event_book_buys(
    *,
    source_book: list[EventBookLeg] | tuple[EventBookLeg, ...],
    local_book: list[EventBookLeg] | tuple[EventBookLeg, ...],
    settings: EventBookPlannerSettings,
) -> EventBookPlan:
    source_legs = [leg for leg in source_book if leg.net_notional_usdc > 0]
    source_notional = sum(max(0.0, leg.net_notional_usdc) for leg in source_legs)
    source_quantity = sum(max(0.0, leg.net_quantity) for leg in source_legs)
    target_event_notional = _target_event_notional(settings, source_notional)
    target_event_quantity = 0.0
    normal_remaining = _normal_cash(settings)
    reserve_remaining = _reserve_cash(settings)
    rejections: list[PlannerDecision] = []

    if source_notional <= 0 or target_event_notional <= 0:
        return EventBookPlan((), (), 0.0, 0.0, normal_remaining, reserve_remaining)

    local_by_asset = _book_by_asset(local_book)
    local_event_notional = sum(max(0.0, leg.net_notional_usdc) for leg in local_by_asset.values())
    local_notional_by_asset = {
        asset_id: max(0.0, leg.net_notional_usdc)
        for asset_id, leg in local_by_asset.items()
    }
    event_has_local_exposure = local_event_notional > 0
    candidates: list[_Candidate] = []

    for index, source_leg in enumerate(source_legs):
        price = _leg_price(source_leg)
        local_leg = local_by_asset.get(source_leg.asset_id, _empty_leg(source_leg.asset_id))
        local_notional = max(0.0, local_leg.net_notional_usdc)
        notional_weight = source_leg.net_notional_usdc / source_notional
        quantity_weight = source_leg.net_quantity / source_quantity if source_quantity > 0 else notional_weight
        target_notional = round(target_event_notional * notional_weight, 6)
        target_quantity = round(target_notional / price, 6) if price > 0 else 0.0
        target_event_quantity += target_quantity
        decision = "rebalance" if event_has_local_exposure else "fresh_entry"

        candidate = _Candidate(
            leg=source_leg,
            decision=decision,
            target_notional_usdc=target_notional,
            local_notional_usdc=round(local_notional, 6),
            current_price=price,
            source_notional_weight=round(notional_weight, 6),
            source_quantity_weight=round(quantity_weight, 6),
            target_quantity=target_quantity,
            source_index=index,
        )
        if candidate.deficit_usdc <= 0:
            continue
        price_block_reason = _price_block_reason(candidate, settings)
        if price_block_reason is not None:
            rejections.append(_reject(candidate, price_block_reason))
            continue
        candidates.append(candidate)

    orders: list[BuyPlan] = []
    for candidate in sorted(candidates, key=_candidate_priority):
        if candidate.decision == "fresh_entry":
            amount = min(candidate.deficit_usdc, normal_remaining)
            used_normal = amount
            used_reserve = 0.0
            if normal_remaining <= 0:
                rejections.append(_reject(candidate, "fresh_requires_normal_cash"))
                continue
        else:
            used_normal = min(candidate.deficit_usdc, normal_remaining)
            used_reserve = min(candidate.deficit_usdc - used_normal, reserve_remaining)
            if used_reserve > 0 and not _reserve_materially_improves_shape(
                candidate=candidate,
                amount=used_normal + used_reserve,
                source_legs=source_legs,
                local_notional_by_asset=local_notional_by_asset,
                settings=settings,
            ):
                used_reserve = 0.0
            amount = used_normal + used_reserve
            if amount <= 0:
                reason = "reserve_shape_not_improved" if reserve_remaining > 0 else "rebalance_cash_limited"
                rejections.append(_reject(candidate, reason))
                continue

        if amount < settings.min_order_notional_usdc:
            rejections.append(_reject(candidate, f"{candidate.decision}_below_min_order"))
            continue

        reason = _order_reason(candidate, amount)
        orders.append(
            BuyPlan(
                asset_id=candidate.leg.asset_id,
                decision=candidate.decision,
                reason=reason,
                target_notional_usdc=round(candidate.target_notional_usdc, 6),
                local_notional_usdc=round(candidate.local_notional_usdc, 6),
                current_price=round(candidate.current_price, 6),
                source_notional_weight=candidate.source_notional_weight,
                source_quantity_weight=candidate.source_quantity_weight,
                notional_usdc=round(amount, 6),
                quantity=round(amount / candidate.current_price, 6),
                used_normal_cash_usdc=round(used_normal, 6),
                used_reserve_usdc=round(used_reserve, 6),
                target_quantity=candidate.target_quantity,
            )
        )
        normal_remaining = round(normal_remaining - used_normal, 6)
        reserve_remaining = round(reserve_remaining - used_reserve, 6)
        local_notional_by_asset[candidate.leg.asset_id] = round(
            local_notional_by_asset.get(candidate.leg.asset_id, 0.0) + amount,
            6,
        )

    return EventBookPlan(
        orders=tuple(orders),
        rejections=tuple(rejections),
        target_event_notional_usdc=round(target_event_notional, 6),
        target_event_quantity=round(target_event_quantity, 6),
        normal_cash_remaining_usdc=round(normal_remaining, 6),
        reserve_cash_remaining_usdc=round(reserve_remaining, 6),
    )


def _book_by_asset(book: list[EventBookLeg] | tuple[EventBookLeg, ...]) -> dict[str, EventBookLeg]:
    by_asset: dict[str, EventBookLeg] = {}
    for leg in book:
        if leg.asset_id in by_asset:
            current = by_asset[leg.asset_id]
            by_asset[leg.asset_id] = EventBookLeg(
                asset_id=leg.asset_id,
                title=leg.title or current.title,
                outcome=leg.outcome or current.outcome,
                net_notional_usdc=current.net_notional_usdc + leg.net_notional_usdc,
                net_quantity=current.net_quantity + leg.net_quantity,
                avg_price=leg.avg_price or current.avg_price,
                current_price=leg.current_price or current.current_price,
            )
        else:
            by_asset[leg.asset_id] = leg
    return by_asset


def _candidate_priority(candidate: _Candidate) -> tuple[int, float, int]:
    hedge_rebalance_priority = 0 if candidate.decision == "rebalance" and candidate.local_notional_usdc <= 0 else 1
    fresh_priority = 2 if candidate.decision == "fresh_entry" else hedge_rebalance_priority
    return fresh_priority, -candidate.deficit_ratio, candidate.source_index


def _empty_leg(asset_id: str) -> EventBookLeg:
    return EventBookLeg(asset_id=asset_id, net_notional_usdc=0.0, net_quantity=0.0)


def _leg_price(leg: EventBookLeg) -> float:
    if leg.current_price is not None and leg.current_price > 0:
        return float(leg.current_price)
    if leg.avg_price is not None and leg.avg_price > 0:
        return float(leg.avg_price)
    if leg.net_quantity > 0:
        return max(0.0, leg.net_notional_usdc / leg.net_quantity)
    return 0.0


def _normal_cash(settings: EventBookPlannerSettings) -> float:
    return round(max(0.0, min(settings.available_normal_cash_usdc, settings.normal_capital_usdc)), 6)


def _reserve_cash(settings: EventBookPlannerSettings) -> float:
    return round(
        max(
            0.0,
            min(
                settings.available_reserve_cash_usdc,
                settings.reserve_capital_usdc,
                settings.max_rebalance_reserve_usdc,
                max(0.0, settings.total_bankroll_usdc - settings.normal_capital_usdc),
            ),
        ),
        6,
    )


def _target_event_notional(settings: EventBookPlannerSettings, source_notional: float) -> float:
    if source_notional <= 0:
        return 0.0
    conviction_floor = max(0.000001, settings.conviction_floor_source_notional_usdc)
    conviction_multiplier = max(1.0, (source_notional / conviction_floor) ** 0.5)
    target = max(0.0, settings.base_event_budget_usdc) * conviction_multiplier
    return max(
        0.0,
        min(
            target,
            settings.max_event_budget_usdc,
            settings.normal_capital_usdc,
            settings.total_bankroll_usdc,
        ),
    )


def _reserve_materially_improves_shape(
    *,
    candidate: _Candidate,
    amount: float,
    source_legs: list[EventBookLeg],
    local_notional_by_asset: dict[str, float],
    settings: EventBookPlannerSettings,
) -> bool:
    before = _shape_distance(source_legs=source_legs, local_notional_by_asset=local_notional_by_asset)
    after_book = dict(local_notional_by_asset)
    after_book[candidate.leg.asset_id] = after_book.get(candidate.leg.asset_id, 0.0) + amount
    after = _shape_distance(source_legs=source_legs, local_notional_by_asset=after_book)
    if before <= 0:
        return False
    required_after = before * (1.0 - max(0.0, settings.reserve_shape_improvement_fraction))
    return after <= required_after + 0.000001


def _shape_distance(
    *,
    source_legs: list[EventBookLeg],
    local_notional_by_asset: dict[str, float],
) -> float:
    source_total = sum(max(0.0, leg.net_notional_usdc) for leg in source_legs)
    local_total = sum(max(0.0, value) for value in local_notional_by_asset.values())
    if source_total <= 0:
        return 0.0
    source_weights = {
        leg.asset_id: max(0.0, leg.net_notional_usdc) / source_total
        for leg in source_legs
    }
    asset_ids = set(source_weights) | set(local_notional_by_asset)
    distance = 0.0
    for asset_id in asset_ids:
        source_weight = source_weights.get(asset_id, 0.0)
        local_weight = (
            max(0.0, local_notional_by_asset.get(asset_id, 0.0)) / local_total
            if local_total > 0
            else 0.0
        )
        distance += abs(local_weight - source_weight)
    return distance


def _price_block_reason(candidate: _Candidate, settings: EventBookPlannerSettings) -> str | None:
    if candidate.current_price <= 0:
        return "invalid_price"
    if candidate.decision == "rebalance":
        if (
            candidate.current_price < settings.rebalance_min_price
            or candidate.current_price > settings.rebalance_max_price
        ):
            return "rebalance_price_blocked"
        return None
    if candidate.current_price < settings.fresh_min_price or candidate.current_price > settings.fresh_max_price:
        return "fresh_price_blocked"
    return None


def _order_reason(candidate: _Candidate, amount: float) -> str:
    if amount + 0.000001 < candidate.deficit_usdc:
        return f"partial_cash_limited_{candidate.decision}"
    if candidate.decision == "rebalance":
        return "rebalance_price_band"
    return "fresh_price_band"


def _reject(candidate: _Candidate, reason: str) -> PlannerDecision:
    return PlannerDecision(
        asset_id=candidate.leg.asset_id,
        decision=candidate.decision,
        reason=reason,
        target_notional_usdc=round(candidate.target_notional_usdc, 6),
        local_notional_usdc=round(candidate.local_notional_usdc, 6),
        current_price=round(candidate.current_price, 6),
        source_notional_weight=candidate.source_notional_weight,
        source_quantity_weight=candidate.source_quantity_weight,
    )


__all__ = [
    "BuyPlan",
    "EventBookLeg",
    "EventBookPlan",
    "EventBookPlannerSettings",
    "PlannerDecision",
    "plan_event_book_buys",
]
