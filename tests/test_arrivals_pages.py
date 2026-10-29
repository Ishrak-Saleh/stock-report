import html as htmllib
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.config import today
from app.db import SessionLocal
from app.models import Allocation, Arrival, Order, OrderEvent, Product, StockMovement
from tests.conftest import make_client


@pytest.fixture
def client():
    c = make_client()
    yield c
    c.__exit__(None, None, None)


def text(r) -> str:
    return htmllib.unescape(r.text)


def pid(code: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Product).where(Product.code == code)).one().id


def stock(code: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Product).where(Product.code == code)).one().stock


def order(name: str):
    with SessionLocal() as db:
        o = db.scalars(select(Order).where(Order.name == name)).one()
        return o.id, sum(a.units for a in o.allocations)


def arrival_id(code: str, units: int) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Arrival).where(Arrival.product_id == pid(code), Arrival.units == units)).one().id


def record(client, code: str, units: int, day: date | None = None):
    return client.post("/arrivals", data={"product_id": pid(code), "units": units, "day": (day or today()).isoformat()})


def test_the_page_leads_with_what_needs_a_decision(client):
    t = text(client.get("/arrivals"))
    assert "1 arrival, 60 units in all, match no order." in t
    assert "Nothing is on order for this product." in t
    assert t.count("btn primary") == 1  # Record arrival is the one filled button
    assert "disabled" in t.split("Needs a decision")[1].split("All arrivals")[0]  # no order to match it to


def test_the_preview_shows_oldest_first_and_the_leftover(client):
    t = text(client.get(f"/arrivals/preview?product_id={pid('MOU')}&units=300"))
    assert t.index("MOU-001") < t.index("MOU-002")
    assert "120 of 120 open" in t and "150 of 150 open" in t and "30 units" in t
    assert "Warehouse stock goes from 100 to 400." in t


def test_the_preview_waits_for_a_number(client):
    assert "Type how many units arrived" in text(client.get(f"/arrivals/preview?product_id={pid('MOU')}&units="))
    assert "Type how many units arrived" in text(client.get(f"/arrivals/preview?product_id={pid('MOU')}&units=abc"))


def test_recording_matches_oldest_first_and_raises_stock(client):
    assert stock("MOU") == 100
    assert record(client, "MOU", 300).status_code == 303
    assert stock("MOU") == 400
    assert order("MOU-001")[1] == 120 and order("MOU-002")[1] == 150
    t = text(client.get("/arrivals"))
    assert "2 arrivals, 90 units in all, match no order." in t  # 60 Monitor + the 30 left over
    assert "MOU-001 120 · MOU-002 150 · Unmatched 30" in t
    with SessionLocal() as db:
        mv = db.scalars(select(StockMovement).where(StockMovement.product_id == pid("MOU"), StockMovement.delta == 300)).one()
        assert "matched to MOU-001 (120), MOU-002 (150), 30 unmatched" in mv.note and mv.by == "Sam"
        o = db.scalars(select(Order).where(Order.name == "MOU-001")).one()
        assert o.events[-1].action == "arrival matched" and o.events[-1].by == "Sam"


def test_a_small_arrival_only_partly_fills_the_oldest_order(client):
    record(client, "MOU", 50)
    assert order("MOU-001")[1] == 50 and order("MOU-002")[1] == 0
    assert "partial" in text(client.get(f"/orders/{order('MOU-001')[0]}")).lower()


def test_an_arrival_with_nothing_on_order_is_unmatched_but_counted(client):
    before = stock("CBL")
    record(client, "CBL", 25)
    assert stock("CBL") == before + 25
    assert "3 arrivals" not in text(client.get("/arrivals")) and "2 arrivals, 85 units" in text(client.get("/arrivals"))


def test_bad_input_shows_a_message_and_changes_nothing(client):
    r = record(client, "MOU", 0)
    assert r.status_code == 400 and "Enter at least 1 unit." in text(r)
    r = record(client, "MOU", 10, today() + timedelta(days=2))
    assert r.status_code == 400 and "can't be in the future" in text(r)
    assert stock("MOU") == 100


def test_not_from_an_order_settles_an_unmatched_arrival(client):
    a = arrival_id("MON", 60)
    assert client.post(f"/arrivals/{a}/not-from-order").status_code == 303
    t = text(client.get("/arrivals"))
    assert "Every arrival has an order." in t and "Not from an order 60" in t
    with SessionLocal() as db:
        free = db.scalars(select(Allocation).where(Allocation.arrival_id == a)).one()
        assert free.order_id is None and free.units == 60
        mv = db.scalars(select(StockMovement).where(StockMovement.kind == "reallocation")).one()
        assert "not from an order (60)" in mv.note and mv.delta == 0
        assert db.get(Arrival, a).edited


def test_a_match_can_be_split_by_hand(client):
    record(client, "KEY", 80)  # automatic: all 80 go to KEY-001
    a = arrival_id("KEY", 80)
    wid1 = order("KEY-001")[0]
    dialog = text(client.get(f"/arrivals/{a}/match"))
    assert "KEY-001" in dialog and "Not from an order" in dialog
    r = client.post(f"/arrivals/{a}/match", data={f"u_{wid1}": 30, "u_free": 50})
    assert r.status_code == 303
    assert order("KEY-001")[1] == 30
    assert stock("KEY") == 400  # splitting never changes the warehouse count
    with SessionLocal() as db:
        events = db.scalars(select(OrderEvent).where(OrderEvent.action == "arrival match changed")).all()
        assert len(events) == 1 and events[0].detail == "80 → 30 units"


def test_a_split_must_add_up_and_fit(client):
    record(client, "KEY", 80)
    a, wid1 = arrival_id("KEY", 80), order("KEY-001")[0]
    short = client.post(f"/arrivals/{a}/match", data={f"u_{wid1}": 30, "u_free": 20})
    assert short.status_code == 400 and "add up to 50, but 80 arrived. Assign 30 more" in text(short)
    big = client.post(f"/arrivals/{a}/match", data={f"u_{wid1}": 250, "u_free": -170})
    assert big.status_code == 400
    assert order("KEY-001")[1] == 80  # nothing changed
    assert client.post(f"/arrivals/{a}/match", data={f"u_{wid1}": "x"}).status_code == 400


def test_the_filter_and_empty_states(client):
    assert "Unmatched 1" in text(client.get("/arrivals")) and "Matched 2" in text(client.get("/arrivals"))
    only = text(client.get("/arrivals?status=unmatched"))
    assert "Monitor" in only.split("All arrivals")[1] and "Headphones" not in only.split("All arrivals")[1]
    assert "No arrivals match this filter" not in only
    client.post(f"/arrivals/{arrival_id('MON', 60)}/not-from-order")
    assert "No arrivals match this filter" in text(client.get("/arrivals?status=unmatched"))


def test_the_record_dialog_starts_on_a_product_with_something_on_order(client):
    t = text(client.get("/arrivals/new", headers={"HX-Request": "true"}))
    assert "<dialog" in t and 'name="day"' in t and "Match preview" in t
    assert client.get("/arrivals/999/match").status_code == 404
