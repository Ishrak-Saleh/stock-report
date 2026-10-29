from datetime import datetime

import pytest

from app.domain.matching import Open, SplitError, check_split, fifo

D = datetime(2026, 10, 1)


def orders():
    return [Open(2, "MOU-002", datetime(2026, 10, 26), 150), Open(1, "MOU-001", datetime(2026, 9, 29), 120)]


def test_oldest_order_is_filled_first_and_the_rest_spills_over():
    m = fifo(300, orders())  # the list is given newest first on purpose
    assert m.parts == ((1, 120), (2, 150)) and m.unmatched == 30


def test_a_small_arrival_only_partly_fills_the_oldest_order():
    m = fifo(50, orders())
    assert m.parts == ((1, 50),) and m.unmatched == 0


def test_an_arrival_that_ends_inside_the_second_order():
    m = fifo(200, orders())
    assert m.parts == ((1, 120), (2, 80)) and m.unmatched == 0


def test_with_no_open_order_every_unit_is_unmatched():
    m = fifo(60, [])
    assert m.parts == () and m.unmatched == 60


def test_an_order_with_no_room_left_is_skipped():
    m = fifo(10, [Open(1, "A", D, 0), Open(2, "B", datetime(2026, 10, 5), 40)])
    assert m.parts == ((2, 10),)


def test_same_day_orders_go_by_id():
    m = fifo(5, [Open(7, "B", D, 3), Open(3, "A", D, 3)])
    assert m.parts == ((3, 3), (7, 2))


def test_every_unit_is_either_matched_or_unmatched():
    for units in (0, 1, 119, 120, 121, 270, 271, 1000):
        m = fifo(units, orders())
        assert sum(u for _, u in m.parts) + m.unmatched == units


def test_a_hand_made_split_must_assign_every_unit():
    check_split(80, {1: 30, 2: 20, None: 30}, {1: 200, 2: 150})
    with pytest.raises(SplitError, match="add up to 70, but 80 arrived. Assign 10 more"):
        check_split(80, {1: 30, 2: 20, None: 20}, {1: 200, 2: 150})
    with pytest.raises(SplitError, match="add up to 90, but 80 arrived. Remove 10"):
        check_split(80, {1: 30, 2: 20, None: 40}, {1: 200, 2: 150})


def test_an_order_cannot_take_more_than_its_room():
    with pytest.raises(SplitError, match="only has room for 120"):
        check_split(150, {1: 150}, {1: 120})
    with pytest.raises(SplitError, match="negative"):
        check_split(10, {1: -5, None: 15}, {1: 120})
