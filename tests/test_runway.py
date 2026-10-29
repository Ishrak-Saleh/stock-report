from datetime import date

import pytest

from app.domain.runway import Landing, insight, landing_day, level_at, project

ARR = [Landing(15, 120, "MOU-001"), Landing(42, 150, "MOU-002")]


def test_runway_for_mouse_matches_the_design():
    r = project(100, 10.9, ARR, 90)
    assert len(r.empty) == 3
    (a0, a1), (b0, b1), _ = r.empty
    assert a0 == pytest.approx(9.17, abs=0.01) and a1 == 15
    assert b0 == pytest.approx(26.0, abs=0.05) and b1 == 42


def test_stock_jumps_when_an_order_lands():
    r = project(100, 10.9, ARR, 90)
    assert level_at(r.points, 14) == 0 and level_at(r.points, 15) == 120
    assert level_at(r.points, 0) == 100


def test_the_suggested_order_closes_the_last_gap_only():
    r = project(100, 10.9, ARR, 90, Landing(45, 1044, "New order"))
    assert [round(a) for a, _ in r.empty] == [9, 26] and [b for _, b in r.empty] == [15, 42]


def test_starting_at_zero_the_gap_begins_today():
    r = project(0, 5, [Landing(10, 100, "x")], 30)
    assert r.empty[0] == (0.0, 10.0) and r.empty_days >= 10


def test_with_no_burn_stock_stays_flat():
    r = project(50, 0, [], 30)
    assert r.empty == () and level_at(r.points, 30) == 50


def test_orders_after_the_horizon_are_left_out():
    r = project(100, 10, [Landing(60, 500, "late")], 30)
    assert level_at(r.points, 30) == 0 and r.empty[-1][1] == 30


def test_an_overdue_order_is_assumed_to_land_tomorrow():
    assert landing_day(date(2026, 10, 1), date(2026, 10, 30)) == 1
    assert landing_day(date(2026, 11, 14), date(2026, 10, 30)) == 15


def test_the_insight_says_when_orders_cannot_close_the_gap():
    r = project(100, 10.9, ARR, 90)
    t = insight(r, 45, 90)
    assert "starting on day 9" in t and "lands on day 45" in t and "Chase what is already ordered" in t
    assert insight(project(500, 1, [], 30), None, 30) == "Stock lasts the next 30 days if every order lands on time."
