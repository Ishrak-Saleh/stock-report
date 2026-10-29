import html as htmllib
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Order, Product
from tests.conftest import reset_db, sign_in

HX = {"HX-Request": "true"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, follow_redirects=False) as c:  # starts the app, which seeds the throwaway database
        reset_db()
        yield sign_in(c)


def text(r) -> str:
    return htmllib.unescape(r.text)


def order_id(name: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Order).where(Order.name == name)).one().id


def product_id(code: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Product).where(Product.code == code)).one().id


# ---- Stock ----
def test_stock_page_tells_the_story(client):
    r = client.get("/")
    t = text(r)
    assert r.status_code == 200
    assert "3 products need a reorder, and Phone is out." in t and "Suggested order: 1,963 units." in t
    assert t.count('class="orow srow"') == 6 and t.count("<svg") >= 6 * 3
    assert t.count("btn primary") == 1  # one filled button: the reorder
    assert t.index("Phone") < t.index("Mouse") < t.index("Monitor") < t.index("Keyboard")
    assert "Under 21 days" in t and "Reorder now. Ordered units not enough." in t and "No sales yet." in t
    assert t.count('class="crow"') == 5 and "5 orders need a message" in t


def test_stock_filter(client):
    t = text(client.get("/?show=critical"))
    assert t.count('class="orow srow"') == 2
    assert text(client.get("/?show=nonsense")).count('class="orow srow"') == 6


# ---- Orders ----
def test_orders_page_ranks_by_attention(client):
    t = text(client.get("/orders"))
    assert "5 orders need a message. MON-001 is complete." in t
    assert t.count('class="orow link"') == 6
    assert t.index("HDP-001") < t.index("KEY-001") < t.index("MOU-001") and t.rindex("MON-001") > t.rindex("MOU-002")
    assert "Ask Nova where it is" in t and "Ask Nova for tracking" in t and "Ask Acme to confirm" in t


def test_orders_filters_and_htmx_partial(client):
    assert text(client.get("/orders?chase=1")).count('class="orow link"') == 5
    assert text(client.get("/orders?status=partial")).count('class="orow link"') == 1
    part = client.get(f"/orders?product={product_id('MOU')}", headers=HX | {"HX-Target": "order-list"})
    assert "<html" not in part.text and part.text.count('class="orow link"') == 2
    assert "No orders match" in text(client.get("/orders?status=cancelled"))


# ---- New order dialog ----
def test_new_order_dialog_has_three_sizes_and_warns_about_the_sop_formula(client):
    mouse = product_id("MOU")
    r = client.get(f"/orders/new?product={mouse}", headers=HX)
    t = text(r)
    assert "<dialog" in t and "274 units" in t and "1,044 units" in t and "611 units" in t
    assert "59.1 days" in t and "129.7 days" in t and "90.0 days" in t
    assert "does not subtract the 270 units already on order" in t
    assert "<dialog" not in client.get(f"/orders/new?product={mouse}").text  # page version without JavaScript


def test_what_if_endpoint(client):
    t = text(client.get(f"/products/{product_id('PHN')}/try?units=55"))
    assert "days of stock including everything on order" in t and "<html" not in t
    assert client.get("/products/999/try").status_code == 404


# ---- Order detail ----
def test_order_detail_leads_with_the_next_step(client):
    t = text(client.get(f"/orders/{order_id('MOU-001')}"))
    assert "120 units shipped 14 days ago and haven't arrived. Ask Acme where it is." in t
    assert "Copy follow-up message" in t and t.count("btn primary") == 1
    assert "Expected" in t and "assumption" in t
    t2 = text(client.get(f"/orders/{order_id('MOU-002')}"))
    assert "still not confirmed" in t2 and "Mark confirmed" in t2
    t3 = text(client.get(f"/orders/{order_id('HDP-001')}"))
    assert re.search(r'dng"[^>]*disabled', t3) and "Arrivals are matched to this order" in t3
    t4 = text(client.get(f"/orders/{order_id('MON-001')}"))
    assert "All 100 units arrived" in t4 and "Cancel order" not in t4


def test_dialogs(client):
    gid = order_id("MOU-001")
    m = text(client.get(f"/orders/{gid}/dialog/message?kind=where"))
    assert "1Z999AA10123456784" in m and "Hi Acme," in m and "<dialog" in m
    assert "Please confirm this order" in text(client.get(f"/orders/{gid}/dialog/message?kind=order"))
    assert "Add tracking" in text(client.get(f"/orders/{order_id('KEY-001')}/dialog/tracking"))
    assert client.get(f"/orders/{order_id('MON-001')}/dialog/tracking").status_code == 409
    assert "Units cannot go below 120" in text(client.get(f"/orders/{gid}/dialog/edit"))
    assert "Yes, delete" in text(client.get(f"/orders/{gid}/dialog/delete"))
    assert client.get(f"/orders/{gid}/dialog/nope").status_code == 404


# ---- Actions and input limits ----
def test_create_order_then_rules_and_limits(client):
    r = client.post("/orders", data={"product_id": product_id("KEY"), "supplier_id": 1, "units": 40, "notes": "test"})
    assert r.status_code == 303
    detail = r.headers["location"]
    assert "Created" in text(client.get(detail))
    over = client.post(detail + "/tracking", data={"number": "794644790138", "units": 41})
    assert over.status_code == 400 and "Only 40 units are left to track" in text(over)
    assert client.post(detail + "/tracking", data={"number": "794644790138", "units": 40}).status_code == 303
    low = client.post(detail + "/edit", data={"units": 10, "supplier_id": 1})
    assert low.status_code == 400 and "can't go below 40" in text(low)
    assert client.post(detail + "/close").status_code == 303 and "closed" in text(client.get(detail)).lower()
    assert client.post(detail + "/delete").headers["location"] == "/orders"


def test_input_limits_reject_oversized_values(client):
    base = {"product_id": product_id("KEY"), "supplier_id": 1}
    assert client.post("/orders", data=base | {"units": 2_000_000}).status_code == 422
    assert client.post("/orders", data=base | {"units": 5, "notes": "x" * 501}).status_code == 422
    assert client.post(f"/orders/{order_id('KEY-001')}/tracking", data={"number": "x" * 65, "units": 1}).status_code == 422
    assert client.post(f"/orders/{order_id('KEY-001')}/tracking", data={"number": "1", "units": 1, "carrier": "EVIL"}).status_code == 422


def test_notes_are_escaped(client):
    r = client.post("/orders", data={"product_id": product_id("KEY"), "supplier_id": 1, "units": 5, "notes": "<script>alert(1)</script>"})
    page = client.get(r.headers["location"]).text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_static_assets_are_served_locally(client):
    assert client.get("/static/vendor/htmx.min.js").status_code == 200
    base = client.get("/").text
    assert "unpkg.com" not in base and "cdn.jsdelivr" not in base
