from datetime import date, timedelta

from app.domain.chase import Chase, chase_of, due_again
from app.domain.forecast import LEVEL_RANK, Params, compute, main_flag, order_options
from app.domain.messages import chase_step, follow_up, order_message, quiet_step, takeaway
from app.domain.orders import expected_arrival

TODAY = date(2026, 10, 29)


def sales(last3_each, prior4_each):
    d = {TODAY - timedelta(days=i): last3_each for i in (1, 2, 3)}
    d.update({TODAY - timedelta(days=i): prior4_each for i in (4, 5, 6, 7)})
    return d


def facts(**over):
    base = dict(is_open=True, remaining=100, confirmed=True, created_days=30, confirmed_days=28, untracked=0,
                on_the_way=0, oldest_shipped_days=0)
    return base | over


# ---- chase rules: the SOP limits are 2 or more, 10 or more, and MORE than 10 ----
def test_confirm_at_exactly_two_days():
    assert chase_of(**facts(confirmed=False, confirmed_days=None, created_days=2)).kind == "confirm"
    assert chase_of(**facts(confirmed=False, confirmed_days=None, created_days=1)) is None


def test_tracking_at_exactly_ten_days_with_untracked_units():
    assert chase_of(**facts(confirmed_days=10, untracked=5, created_days=12)).kind == "tracking"
    assert chase_of(**facts(confirmed_days=9, untracked=5)) is None
    assert chase_of(**facts(confirmed_days=18, untracked=0)) is None


def test_where_is_it_needs_more_than_ten_days():
    assert chase_of(**facts(on_the_way=50, oldest_shipped_days=10)) is None
    assert chase_of(**facts(on_the_way=50, oldest_shipped_days=11)).kind == "where"


def test_nothing_to_chase_when_closed_or_complete():
    assert chase_of(**facts(is_open=False, on_the_way=50, oldest_shipped_days=30)) is None
    assert chase_of(**facts(remaining=0, on_the_way=50, oldest_shipped_days=30)) is None


def test_most_overdue_reason_wins():
    c = chase_of(**facts(confirmed_days=18, untracked=5, on_the_way=50, oldest_shipped_days=14))
    assert c == Chase("tracking", 18, 10, 8)


def test_alert_repeats_at_most_every_two_days():
    assert due_again(None) and due_again(2) and not due_again(1)


# ---- the one main flag ----
def fc(stock, ordered, l3, p4):
    return compute(sales(l3, p4), stock, ordered, TODAY, Params())


def test_flag_out_of_stock_with_orders_not_enough():
    f = main_flag(fc(0, 300, 7, 7))
    assert (f.level, f.label, f.note) == ("crit", "Out of stock", "Reorder now. Ordered units not enough.")


def test_flag_reorder_now_with_nothing_on_order():
    f = main_flag(fc(120, 0, 3, 3))
    assert (f.level, f.label, f.note) == ("serious", "Reorder now", "Nothing is on order.")


def test_flag_under_21_days_when_orders_cover_the_reorder_line():
    f = main_flag(fc(100, 270, 6, 6))
    assert (f.level, f.label, f.note) == ("crit", "Under 21 days", "")


def test_flag_healthy_and_no_sales():
    assert main_flag(fc(900, 0, 4, 4)).label == "Healthy"
    assert main_flag(compute({}, 50, 0, TODAY, Params())).note == "No sales yet."


def test_levels_sort_urgent_first():
    assert sorted(["good", "crit", "warn", "serious"], key=LEVEL_RANK.get) == ["crit", "serious", "warn", "good"]


# ---- order size options (Gizmo Mini: stock 100, 270 on order, 10.9 a day) ----
def test_order_options_for_gizmo():
    f = fc(100, 270, 9, 6)
    assert f.adjusted_burn == 10.9
    o = order_options(100, 270, f, Params())
    assert [x.units for x in o] == [274, 1044, 611]
    assert [round(x.days_incl, 1) for x in o] == [59.1, 129.7, 90.0]
    assert o[1].tag == "Suggested"


def test_order_options_empty_without_sales_and_zero_when_already_covered():
    assert order_options(50, 0, compute({}, 50, 0, TODAY, Params()), Params()) == []
    o = order_options(900, 250, fc(900, 250, 4, 4), Params())
    assert o[0].units == 0


# ---- text ----
def test_expected_arrival_is_order_date_plus_lead_time():
    assert expected_arrival(date(2026, 9, 29), 45) == date(2026, 11, 13)


def test_chase_step_text():
    assert chase_step(Chase("where", 14, 10, 4), "Acme Manufacturing") == ("Ask Acme where it is", "On the way 14 days")
    assert quiet_step("received")[1] == "Complete"
    assert quiet_step("in production")[1] == "Waiting for tracking"


def test_takeaway_sentences():
    kw = dict(status="on the way", units=120, arrived=0, remaining=120, on_the_way=120, untracked=0,
              supplier="Acme Manufacturing")
    assert takeaway(chase=Chase("where", 14, 10, 4), **kw) == \
        "120 units shipped 14 days ago and haven't arrived. Ask Acme where it is."
    assert takeaway(chase=None, **kw) == "120 units are still to come. Nothing to chase yet."
    assert takeaway(chase=None, **(kw | dict(status="received", remaining=0))) == "All 120 units arrived. Nothing left to do."


def test_messages_name_the_order_and_sender():
    m = order_message(supplier="Acme Manufacturing", order="GIZ-003", product="Gizmo Mini", code="GIZ", units=200,
                      notes="Rush", sender="Sam")
    assert m.startswith("Hi Acme,") and "Order: GIZ-003" in m and "Notes: Rush" in m and m.endswith("Sam")
    f = follow_up(Chase("where", 14, 10, 4), supplier="Acme Manufacturing", order="GIZ-001", product="Gizmo Mini",
                  units=120, untracked=0, tracking_number="1Z999AA10123456784", created_days=30, sender="Sam")
    assert "1Z999AA10123456784" in f and "14 days ago" in f
