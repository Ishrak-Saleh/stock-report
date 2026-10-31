from datetime import date

import pytest

from app.domain.runway import Landing, empty_before, gap_of, insight, landing_day, level_at, project, window_insight

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


# ---- the stock gap: will the shelf be empty before the orders arrive? ----

def test_no_gap_when_stock_lasts_the_whole_horizon():
    assert gap_of(project(500, 1, [], 90), [], 90) is None
    assert gap_of(project(100, 1, [Landing(30, 50, "A")], 90), [Landing(30, 50, "A")], 90) is None


def test_the_gap_counts_every_empty_stretch_and_names_the_first_order_that_ends_the_first_one():
    r = project(100, 10.9, ARR, 90)
    g = gap_of(r, ARR, 90)
    assert g.empty_days == 56 and g.starts_in == pytest.approx(9.17, abs=0.01)
    assert g.first_landing.name == "MOU-001" and g.first_landing.day == 15 and g.horizon == 90


def test_the_gap_says_when_nothing_on_order_ends_it():
    g = gap_of(project(100, 10, [], 90), [], 90)
    assert g.empty_days == 80 and g.first_landing is None and g.starts_in == pytest.approx(10.0)


def test_already_empty_with_nothing_coming_is_the_whole_horizon():
    g = gap_of(project(0, 5, [], 90), [], 90)
    assert g.empty_days == 90 and g.starts_in == 0 and g.first_landing is None


def test_an_order_that_lands_before_stock_runs_out_is_not_the_one_that_ends_the_gap():
    early, late = Landing(3, 30, "EARLY"), Landing(40, 500, "LATE")
    r = project(100, 10, [early, late], 90)  # runs out on day 13, EARLY has already landed, LATE lands on day 40
    g = gap_of(r, [early, late], 90)
    assert g.first_landing.name == "LATE" and g.starts_in == pytest.approx(13.0)


def test_a_part_day_still_counts_as_one_day_and_the_drawer_says_the_same():
    big = [Landing(2, 1000, "A")]
    assert gap_of(project(10, 10, big, 30), big, 30).empty_days == 1  # empty from day 1 to day 2, exactly 1 day
    one = [Landing(1, 1000, "A")]
    short = project(10, 11, one, 30)  # runs out about 0.9 days in and lands on day 1: about 0.1 days empty
    assert gap_of(short, one, 30).empty_days == 1
    assert "about 1 day " in insight(short, None, 30) and "about 0 days" not in insight(short, None, 30)


def test_the_drawer_sentence_and_the_row_use_the_same_number():
    for stock, burn, arrivals in [(100, 10.9, ARR), (0, 5, [Landing(10, 100, "x")]), (100, 10, [])]:
        r = project(stock, burn, arrivals, 90)
        g = gap_of(r, arrivals, 90)
        assert f"about {g.empty_days} " in insight(r, None, 90)


def test_an_order_landing_exactly_on_the_last_day_still_ends_the_gap():
    g = gap_of(project(100, 10, [Landing(90, 500, "LAST")], 90), [Landing(90, 500, "LAST")], 90)
    assert g.first_landing.name == "LAST" and g.empty_days == 80
    assert gap_of(project(100, 10, [Landing(91, 500, "OUT")], 90), [Landing(91, 500, "OUT")], 90).first_landing is None


def test_empty_before_an_order_lands_only_counts_the_gap_that_opens_before_it():
    r = project(100, 10.9, ARR, 90)
    assert empty_before(r, 15) == 6      # the first stretch, 9.17 to 15
    assert empty_before(r, 42) == 22     # plus the second stretch, 26 to 42
    assert empty_before(r, 5) == 0       # stock still lasts
    assert empty_before(project(500, 1, [], 90), 60) == 0


def test_only_empty_days_before_a_new_order_could_land_count_as_a_gap():
    # 70 days of stock, nothing on order, lead time 45: the SOP calls this Healthy and there is time to reorder, so no gap.
    assert gap_of(project(700, 10, [], 45), [], 45) is None
    # 40 days of stock against a 45-day lead time: five days that ordering today cannot save.
    g = gap_of(project(400, 10, [], 45), [], 45)
    assert g.empty_days == 5 and g.first_landing is None and g.horizon == 45
    # an order that lands on day 30 saves it: the stock is 400 + 300 and lasts past day 45
    assert gap_of(project(400, 10, [Landing(30, 300, "A")], 45), [Landing(30, 300, "A")], 45) is None


def test_the_window_sentence_says_how_many_empty_days_ordering_today_cannot_prevent():
    g = gap_of(project(400, 10, [], 45), [], 45)
    assert window_insight(g, 45) == "5 days with no stock come before day 45 and cannot be prevented by ordering today."
    assert "1 day with no stock comes before day 45" in window_insight(gap_of(project(440, 10, [], 45), [], 45), 45)
    assert window_insight(None, 45) == ""
