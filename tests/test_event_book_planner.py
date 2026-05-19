from polymarket_copy_trading.event_book_planner import (
    EventBookLeg,
    EventBookPlannerSettings,
    plan_event_book_buys,
)


def leg(
    asset_id: str,
    *,
    notional: float,
    quantity: float | None = None,
    avg_price: float | None = None,
    current_price: float | None = None,
    outcome: str = "Yes",
) -> EventBookLeg:
    price = current_price or avg_price or 0.50
    return EventBookLeg(
        asset_id=asset_id,
        title=f"{asset_id} market",
        outcome=outcome,
        net_notional_usdc=notional,
        net_quantity=quantity if quantity is not None else notional / price if price > 0 else 0.0,
        avg_price=avg_price,
        current_price=current_price,
    )


def settings(**overrides: float) -> EventBookPlannerSettings:
    values = {
        "total_bankroll_usdc": 100.0,
        "normal_capital_usdc": 80.0,
        "reserve_capital_usdc": 20.0,
        "base_event_budget_usdc": 5.0,
        "max_event_budget_usdc": 10.0,
        "max_rebalance_reserve_usdc": 5.0,
        "available_normal_cash_usdc": 80.0,
        "available_reserve_cash_usdc": 20.0,
        "min_order_notional_usdc": 1.0,
        "fresh_max_price": 0.80,
        "rebalance_max_price": 0.95,
        "conviction_floor_source_notional_usdc": 3000.0,
        "reserve_shape_improvement_fraction": 0.20,
    }
    values.update(overrides)
    return EventBookPlannerSettings(**values)


def test_two_leg_source_book_targets_proportional_notional_and_quantity() -> None:
    plan = plan_event_book_buys(
        source_book=[
            leg("fav", notional=3000.0, avg_price=0.60, current_price=0.60, outcome="Favorite"),
            leg("dog", notional=1000.0, avg_price=0.25, current_price=0.25, outcome="Underdog"),
        ],
        local_book=[],
        settings=settings(base_event_budget_usdc=20.0, max_event_budget_usdc=20.0),
    )

    orders = {order.asset_id: order for order in plan.orders}

    assert orders["fav"].notional_usdc == 15.0
    assert orders["fav"].quantity == 25.0
    assert orders["fav"].source_notional_weight == 0.75
    assert orders["dog"].notional_usdc == 5.0
    assert orders["dog"].quantity == 20.0
    assert orders["dog"].source_notional_weight == 0.25
    assert plan.target_event_notional_usdc == 20.0


def test_default_event_budget_is_ten_dollars_for_hundred_dollar_wallet() -> None:
    plan = plan_event_book_buys(
        source_book=[leg("anchor", notional=12000.0, avg_price=0.50, current_price=0.50)],
        local_book=[],
        settings=settings(),
    )

    assert plan.target_event_notional_usdc == 10.0
    assert plan.orders[0].notional_usdc == 10.0


def test_conviction_scales_event_budget_between_base_and_cap() -> None:
    weak = plan_event_book_buys(
        source_book=[leg("weak", notional=3000.0, avg_price=0.50, current_price=0.50)],
        local_book=[],
        settings=settings(),
    )
    strong = plan_event_book_buys(
        source_book=[leg("strong", notional=12000.0, avg_price=0.50, current_price=0.50)],
        local_book=[],
        settings=settings(),
    )

    assert weak.target_event_notional_usdc == 5.0
    assert strong.target_event_notional_usdc == 10.0


def test_reserve_rebalance_requires_material_shape_improvement() -> None:
    blocked = plan_event_book_buys(
        source_book=[
            leg("anchor", notional=7000.0, avg_price=0.50, current_price=0.50),
            leg("hedge", notional=3000.0, avg_price=0.50, current_price=0.50),
        ],
        local_book=[
            leg("anchor", notional=6.8, avg_price=0.50, current_price=0.50),
            leg("hedge", notional=1.5, avg_price=0.50, current_price=0.50),
            leg("offbook", notional=20.0, avg_price=0.50, current_price=0.50),
        ],
        settings=settings(available_normal_cash_usdc=0.0, available_reserve_cash_usdc=5.0),
    )
    allowed = plan_event_book_buys(
        source_book=[
            leg("anchor", notional=7000.0, avg_price=0.50, current_price=0.50),
            leg("hedge", notional=3000.0, avg_price=0.50, current_price=0.50),
        ],
        local_book=[leg("anchor", notional=7.0, avg_price=0.50, current_price=0.50)],
        settings=settings(available_normal_cash_usdc=0.0, available_reserve_cash_usdc=5.0),
    )

    assert blocked.orders == ()
    assert blocked.rejections[0].reason == "reserve_shape_not_improved"
    assert allowed.orders[0].asset_id == "hedge"
    assert round(allowed.orders[0].used_reserve_usdc, 3) == 2.739


def test_cash_limited_plan_prioritizes_underweight_hedge_leg_before_partial_anchor_topup() -> None:
    plan = plan_event_book_buys(
        source_book=[
            leg("anchor", notional=3000.0, avg_price=0.50, current_price=0.50),
            leg("hedge", notional=1000.0, avg_price=0.50, current_price=0.50, outcome="No"),
        ],
        local_book=[leg("anchor", notional=10.0, avg_price=0.50, current_price=0.50)],
        settings=settings(
            base_event_budget_usdc=20.0,
            max_event_budget_usdc=20.0,
            available_normal_cash_usdc=2.0,
            available_reserve_cash_usdc=2.0,
        ),
    )

    assert [order.asset_id for order in plan.orders] == ["hedge"]
    assert plan.orders[0].notional_usdc == 4.0
    assert plan.orders[0].used_reserve_usdc == 2.0
    assert plan.orders[0].decision == "rebalance"
    assert plan.orders[0].reason == "partial_cash_limited_rebalance"


def test_in_play_rebalance_uses_wider_price_band() -> None:
    plan = plan_event_book_buys(
        source_book=[
            leg("anchor", notional=3000.0, avg_price=0.50, current_price=0.50),
            leg("hedge", notional=1000.0, avg_price=0.90, current_price=0.90, outcome="No"),
        ],
        local_book=[leg("anchor", notional=15.0, avg_price=0.50, current_price=0.50)],
        settings=settings(
            base_event_budget_usdc=20.0,
            max_event_budget_usdc=20.0,
            fresh_max_price=0.80,
            rebalance_max_price=0.95,
        ),
    )

    assert [order.asset_id for order in plan.orders] == ["hedge"]
    assert plan.orders[0].notional_usdc == 5.0
    assert plan.orders[0].decision == "rebalance"
    assert plan.orders[0].reason == "rebalance_price_band"


def test_fresh_high_price_standalone_leg_is_rejected() -> None:
    plan = plan_event_book_buys(
        source_book=[leg("expensive", notional=1000.0, avg_price=0.90, current_price=0.90)],
        local_book=[],
        settings=settings(fresh_max_price=0.80, rebalance_max_price=0.95),
    )

    assert plan.orders == ()
    assert plan.rejections[0].asset_id == "expensive"
    assert plan.rejections[0].decision == "fresh_entry"
    assert plan.rejections[0].reason == "fresh_price_blocked"


def test_reserve_cash_is_available_only_for_rebalance_or_hedge() -> None:
    fresh = plan_event_book_buys(
        source_book=[leg("fresh", notional=1000.0, avg_price=0.50, current_price=0.50)],
        local_book=[],
        settings=settings(available_normal_cash_usdc=0.0, available_reserve_cash_usdc=20.0),
    )

    rebalance = plan_event_book_buys(
        source_book=[
            leg("existing", notional=1000.0, avg_price=0.50, current_price=0.50),
            leg("hedge", notional=1000.0, avg_price=0.50, current_price=0.50),
        ],
        local_book=[leg("existing", notional=5.0, avg_price=0.50, current_price=0.50)],
        settings=settings(
            max_event_budget_usdc=10.0,
            base_event_budget_usdc=10.0,
            available_normal_cash_usdc=0.0,
            available_reserve_cash_usdc=5.0,
        ),
    )

    assert fresh.orders == ()
    assert fresh.rejections[0].reason == "fresh_requires_normal_cash"
    assert rebalance.orders[0].asset_id == "hedge"
    assert rebalance.orders[0].notional_usdc == 5.0
    assert rebalance.orders[0].used_reserve_usdc == 5.0
    assert rebalance.orders[0].reason == "rebalance_price_band"
