from datetime import date, timedelta

from app.domain.forecast import Params, compute, adjusted_burn, try_order
from app.domain.orders import stages, tracking_fits

TODAY = date(2026, 10, 29)


def sales(last3_each: int, prior4_each: int) -> dict[date, int]:
    d = {TODAY - timedelta(days=i): last3_each for i in (1, 2, 3)}
    d.update({TODAY - timedelta(days=i): prior4_each for i in (4, 5, 6, 7)})
    return d


def test_trend_and_burn():
    # last3 = 6/day, prior4 = 3/day -> sold7 = 30, burn 4.2857, trend 2 (clamped from 2.0), adj 8.6
    sold, burn, trend, adj = adjusted_burn(sales(6, 3), TODAY)
    assert sold == 30 and trend == 2.0 and adj == 8.6


def test_trend_clamped_and_no_prior():
    assert adjusted_burn(sales(10, 1), TODAY)[2] == 2.0
    assert adjusted_burn(sales(1, 10), TODAY)[2] == 0.5
    assert adjusted_burn(sales(5, 0), TODAY)[2] == 1.0


def test_forecast_numbers_and_flags():
    f = compute(sales(2, 2), stock=100, ordered=50, today=TODAY, p=Params())
    assert f.adjusted_burn == 2.0
    assert f.days_of_stock == 50 and f.days_with_ordered == 75
    assert f.sells_out_on == TODAY + timedelta(days=50)
    assert f.reorder_by == TODAY + timedelta(days=50 - 59)
    assert f.low is None and not f.reorder_now  # 50 days is not under 45
    assert compute(sales(2, 2), 80, 0, TODAY, Params()).low == "watch"  # 40 days
    assert f.suggested_order == max(0, (60 + 45) * 2 - 100)


def test_reorder_now_even_with_ordered():
    f = compute(sales(2, 2), stock=10, ordered=20, today=TODAY, p=Params())
    assert f.reorder_now and f.ordered_not_enough and f.low == "urgent"


def test_zero_burn_blank():
    f = compute({}, stock=10, ordered=0, today=TODAY, p=Params())
    assert f.days_of_stock is None and f.days_with_ordered is None and not f.reorder_now
    assert compute({}, 0, 0, TODAY, Params()).out_of_stock


def test_try_order():
    assert try_order(100, 50, 100, 2.0) == 125


def kw(**o):
    base = dict(marked_confirmed=False, tracking_units=0, arrived=0, closed=False, cancelled=False)
    return base | o


def test_status_precedence():
    assert stages(10, **kw()).status == "placed"
    assert stages(10, **kw(marked_confirmed=True)).status == "in production"
    assert stages(10, **kw(tracking_units=4)).status == "on the way"
    s = stages(10, **kw(tracking_units=6, arrived=4))
    assert s.status == "partial" and (s.on_the_way, s.arrived) == (6, 4) and s.confirmed
    assert stages(10, **kw(arrived=10)).status == "received"
    assert stages(10, **kw(arrived=10, closed=True)).status == "closed"
    s = stages(10, **kw(closed=True, cancelled=True, tracking_units=5))
    assert s.status == "cancelled" and s.to_come == 0


def test_tracking_cap():
    assert tracking_fits(10, 6, 4) and not tracking_fits(10, 6, 5) and not tracking_fits(10, 0, 0)


def test_bundle_variants_count_every_unit():
    from app.domain.bundles import units_sold
    bundles = {"Buy 2 Get 2": 4}
    assert units_sold(3, "Buy 2 Get 2", bundles) == 12
    assert units_sold(3, "", bundles) == 3
    import pytest
    with pytest.raises(ValueError, match="not a bundle"):
        units_sold(1, "Buy 9 Get 9", bundles)
