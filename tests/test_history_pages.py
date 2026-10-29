import html as htmllib
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import today
from app.db import SessionLocal
from app.models import Product, StockMovement
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


def adjust(client, code: str, kind: str, units, note: str = "Trade show sample", day=None):
    return client.post(f"/products/{pid(code)}/adjust", data={
        "kind": kind, "units": units, "note": note, "day": (day or today()).isoformat()})


def test_the_product_page_explains_why_the_stock_is_what_it_is(client):
    t = text(client.get(f"/products/{pid('MOU')}"))
    assert "Mouse has 100 units, down 6 in 30 days." in t
    assert "Count correction: shelf count was 6 lower" in t and "Log adjustment" in t
    assert 'data-chart=' in t and "Warehouse stock, last 30 days" in t and "Mouse runway" in t


def test_arrivals_show_up_in_the_headline(client):
    assert "Headphones has 900 units, up 150 in 30 days." in text(client.get(f"/products/{pid('HDP')}"))


def test_a_product_with_no_movements_still_renders(client):
    t = text(client.get(f"/products/{pid('CBL')}"))
    assert "Cable has 50 units, with no changes in the last 30 days." in t
    assert "No stock changes for Cable" in t and "Days left cannot be worked out" in t


def test_movements_can_be_filtered(client):
    gid = pid("MOU")
    assert "Count correction" in text(client.get(f"/products/{gid}?kind=manual"))
    assert "No movements of this kind" in text(client.get(f"/products/{gid}?kind=arrivals"))
    assert "Count correction" in text(client.get(f"/products/{gid}?kind=bogus"))  # an unknown filter shows everything


def test_a_manual_sale_lowers_stock_and_is_written_down(client):
    assert adjust(client, "MOU", "sale", 12).status_code == 303
    assert stock("MOU") == 88
    with SessionLocal() as db:
        m = db.scalars(select(StockMovement).where(StockMovement.delta == -12)).one()
        assert m.kind == "sale" and m.note == "Manual sale: Trade show sample" and m.by == "Sam"
    t = text(client.get(f"/products/{pid('MOU')}"))
    assert "down 18 in 30 days" in t and "Manual sale: Trade show sample" in t


def test_found_units_raise_stock_and_damage_lowers_it(client):
    adjust(client, "MOU", "found", 5, "Found a box behind shelf 3")
    adjust(client, "MOU", "damage", 2, "Water damage")
    assert stock("MOU") == 103
    with SessionLocal() as db:
        kinds = {m.note: m.kind for m in db.scalars(select(StockMovement).where(StockMovement.product_id == pid("MOU")))}
        assert kinds["Found or recount: Found a box behind shelf 3"] == "adjustment"


def test_stock_after_always_ends_on_todays_count(client):
    adjust(client, "MOU", "sale", 12)
    t = text(client.get(f"/products/{pid('MOU')}"))
    movements = t.split("Movements")[1]
    assert movements.index("Trade show sample") < movements.index("Count correction")  # newest first
    assert ">88<" in movements.replace(" ", "").replace("\n", "") or "88" in movements


def test_rules_for_adjustments(client):
    r = adjust(client, "MOU", "sale", 500)
    assert r.status_code == 400 and "Only 100 units are in stock. Enter 100 or fewer." in text(r)
    assert "Say why" in text(adjust(client, "MOU", "sale", 5, note="  "))
    assert "at least 1 unit" in text(adjust(client, "MOU", "sale", 0))
    assert "can't be in the future" in text(adjust(client, "MOU", "sale", 1, day=today() + timedelta(days=1)))
    assert client.post(f"/products/{pid('MOU')}/adjust", data={"kind": "nope", "units": 1, "note": "x y z", "day": today().isoformat()}).status_code == 400
    assert stock("MOU") == 100


def test_an_older_adjustment_is_dated_on_its_day(client):
    adjust(client, "MOU", "sale", 4, "Counted late", day=today() - timedelta(days=3))
    with SessionLocal() as db:
        m = db.scalars(select(StockMovement).where(StockMovement.delta == -4)).one()
        assert m.at.date() == today() - timedelta(days=3)


def test_the_runway_drawer(client):
    t = text(client.get(f"/products/{pid('MOU')}/runway?horizon=90"))
    assert 'id="runway-' in t and "data-chart=" in t and "Out of stock" in t
    assert "Stock is empty for about" in t and "Show as a table" in t
    assert "If you order 1,044 today" in t  # the SOP suggestion is the second line
    assert "Mouse runway" in text(client.get(f"/products/{pid('MOU')}/runway?horizon=30"))
    assert "Days left cannot be worked out" in text(client.get(f"/products/{pid('CBL')}/runway"))
    assert client.get(f"/products/{pid('MOU')}/runway?closed=1").text == f'<div id="runway-{pid("MOU")}"></div>'
    assert client.get("/products/999/runway").status_code == 404


def test_a_bad_horizon_falls_back_to_90_days(client):
    assert "90 days" in text(client.get(f"/products/{pid('MOU')}/runway?horizon=7"))


def test_the_stock_page_opens_the_runway_in_place(client):
    t = text(client.get("/"))
    assert t.count("/runway?horizon=90") == 6 and t.count('id="runway-') == 6
    assert f'href="/products/{pid("MOU")}"' in t


def test_the_adjustment_dialog(client):
    t = text(client.get(f"/products/{pid('MOU')}/adjust", headers={"HX-Request": "true"}))
    assert "<dialog" in t and "Manual sale" in t and "Damaged or lost" in t and "Found or recount" in t
    assert 'data-stock="100"' in t


def test_a_bundle_sale_counts_every_unit_in_the_bundle(client):
    """Buy 2 Get 2 is 4 units, so 3 sales of it take 12 units out of the warehouse."""
    r = client.post(f"/products/{pid('MOU')}/adjust", data={
        "kind": "sale", "units": 3, "variant": "Buy 2 Get 2", "note": "Web orders", "day": today().isoformat()})
    assert r.status_code == 303 and stock("MOU") == 88
    with SessionLocal() as db:
        m = db.scalars(select(StockMovement).where(StockMovement.delta == -12)).one()
        assert m.note == "Manual sale: Web orders (3 × Buy 2 Get 2, 12 units)"
    assert "Buy 2 Get 2 (4 units each)" in text(client.get(f"/products/{pid('MOU')}/adjust"))
    assert "Sold as" not in text(client.get(f"/products/{pid('KEY')}/adjust"))  # no bundles, no choice


def test_an_unknown_bundle_is_refused_and_only_sales_use_bundles(client):
    r = client.post(f"/products/{pid('MOU')}/adjust", data={
        "kind": "sale", "units": 1, "variant": "Buy 9 Get 9", "note": "x y z", "day": today().isoformat()})
    assert r.status_code == 400 and "is not a bundle for this product" in text(r) and stock("MOU") == 100
    client.post(f"/products/{pid('MOU')}/adjust", data={
        "kind": "found", "units": 3, "variant": "Buy 2 Get 2", "note": "found three", "day": today().isoformat()})
    assert stock("MOU") == 103  # a bundle only changes manual sales
