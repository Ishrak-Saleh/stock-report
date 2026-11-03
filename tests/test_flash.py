"""The toast after a button: what happened and where to check it (app/flash.py). It shows once, on the page after the redirect."""
import html as htmllib
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import today
from app.db import SessionLocal
from app.flash import flash
from app.models import Order, Outbox, Product, Settings
from tests.conftest import ACME, make_client


@pytest.fixture
def client():
    c = make_client()
    yield c
    c.__exit__(None, None, None)


def text(r) -> str:
    return htmllib.unescape(r.text)


def toast(page: str) -> str:
    m = re.search(r'<div class="toast".*?</div>', page, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(0))).strip() if m else ""


def link(page: str) -> str:
    m = re.search(r'<div class="toast".*?<a class="btn small" href="([^"]*)"', page, re.S)
    return m.group(1) if m else ""


def landing(client, r) -> str:
    """The page the redirect sends the browser to."""
    assert r.status_code == 303, r.text[:300]
    return text(client.get(r.headers["location"]))


def product(code: str) -> Product:
    with SessionLocal() as db:
        return db.scalars(select(Product).where(Product.code == code)).one()


def an_order(name: str) -> Order:
    with SessionLocal() as db:
        return db.scalars(select(Order).where(Order.name == name)).one()


def test_the_message_shows_once_and_is_gone_on_the_next_page(client):
    page = landing(client, client.post("/settings/defaults", data={"lead_time": 45, "safety_days": 14, "target_days": 60}))
    assert "Forecast defaults saved." in toast(page) and link(page) == "/"
    assert toast(text(client.get("/settings"))) == ""


def test_a_page_with_no_message_has_no_toast(client):
    assert 'class="toast"' not in text(client.get("/"))


def test_flash_refuses_links_outside_this_site():
    class Req:
        session: dict = {}
    for bad in ("https://evil.example/x", "//evil.example/x", "javascript:alert(1)", "orders"):
        r = Req()
        r.session = {}
        flash(r, "Done.", bad, "Go")
        assert r.session["flash"] == {"text": "Done.", "href": "", "label": ""}
    r = Req()
    r.session = {}
    flash(r, "Done.", "/outbox?kind=test", "Open the Outbox")
    assert r.session["flash"]["href"] == "/outbox?kind=test"


def test_the_alerts_panel_answers_with_the_message_and_the_outbox_link_inside_it(client):
    hx = {"HX-Request": "true"}
    client.post("/settings/alerts", data={"enabled": "1", "recipients": "ops@example.com, sam@example.com"}, headers=hx)
    r = client.post("/settings/alerts/test", headers=hx)
    page = text(r)
    assert r.status_code == 200 and "Test saved for 2 addresses. Nothing was delivered." in page
    assert 'href="/outbox?kind=test"' in page and "Open the Outbox" in page
    r = client.post("/settings/alerts/send", headers=hx)
    assert "Alert saved for 2 addresses. Nothing was delivered." in text(r) and 'href="/outbox?kind=alert"' in text(r)
    with SessionLocal() as db:
        assert {m.kind for m in db.scalars(select(Outbox))} == {"test", "alert"}


def test_the_alert_buttons_without_htmx_redirect_and_show_the_toast(client):
    client.post("/settings/alerts", data={"enabled": "1", "recipients": "ops@example.com"})
    r = client.post("/settings/alerts/test")
    assert r.headers["location"] == "/settings#alerts"
    page = text(client.get("/settings"))
    assert toast(page).startswith("Test saved for 1 address. Nothing was delivered.") and link(page) == "/outbox?kind=test"


def test_placing_an_order_points_to_stock(client):
    p = product("PHN")
    r = client.post("/orders", data={"product_id": p.id, "supplier_id": p.id and 1, "units": 500})
    page = landing(client, r)
    assert " placed. Stock now counts its 500 units as on order." in toast(page) and link(page) == "/"


def test_recording_an_arrival_points_to_stock(client):
    r = client.post("/arrivals", data={"product_id": product("PHN").id, "units": 40, "day": str(today())})
    page = landing(client, r)
    assert "40 Phone units recorded." in toast(page) and link(page) == "/"


def test_editing_a_match_points_to_orders(client):
    with SessionLocal() as db:
        from app.models import Arrival
        a = db.scalars(select(Arrival).where(Arrival.units == 150)).one()
    r = client.post(f"/arrivals/{a.id}/match", data={"u_free": "150"})
    page = landing(client, r)
    assert "Match saved." in toast(page) and link(page) == "/orders"


def test_cancel_close_reopen_and_delete_an_order_each_point_to_stock(client):
    o = an_order("KEY-001")
    for action, said in (("cancel", "KEY-001 cancelled."), ("reopen", "KEY-001 reopened."), ("close", "KEY-001 closed."),
                         ("reopen", "KEY-001 reopened.")):
        page = landing(client, client.post(f"/orders/{o.id}/{action}"))
        assert said in toast(page) and link(page) == "/", action
    page = landing(client, client.post(f"/orders/{o.id}/delete"))
    assert "KEY-001 deleted. Stock no longer counts it." in toast(page) and link(page) == "/"


def test_a_stock_adjustment_says_how_much_it_changed(client):
    p = product("KEY")
    r = client.post(f"/products/{p.id}/adjust", data={"kind": "damage", "units": 5, "note": "dropped", "day": str(today())})
    page = landing(client, r)
    assert "Keyboard stock changed by -5." in toast(page) and link(page) == "/"
    r = client.post(f"/products/{p.id}/adjust", data={"kind": "found", "units": 7, "note": "recount", "day": str(today())})
    assert "Keyboard stock changed by +7." in toast(landing(client, r))


def test_saving_products_suppliers_and_marking_data_updated_each_say_where_it_shows(client):
    p = product("MOU")
    form = {"name": p.name, "code": p.code, "identifiers": ", ".join(p.identifiers), "bundles": "", "lead": "", "safety": "", "target": ""}
    page = landing(client, client.post(f"/settings/products/{p.id}", data=form))
    assert "Product saved. Its numbers on Stock changed." in toast(page) and link(page) == "/"
    page = landing(client, client.post("/settings/suppliers", data={"name": "Zed Parts", "email": "zed@zed.example.com"}))
    assert "Supplier added." in toast(page) and link(page) == "/orders"
    page = landing(client, client.post("/settings/data-updated"))
    assert "Marked as updated today." in toast(page) and link(page) == "/"


def test_deleting_a_follow_up_points_to_the_chase_list_and_another_message_does_not(client):
    ids = {m.group(2): int(m.group(1)) for m in re.finditer(r'href="/orders/(\d+)">([A-Z]{3}-\d+)<', client.get("/chase").text)}
    client.post(f"/chase/{ids['KEY-001']}/outbox", data={"kind": "tracking"})
    client.post("/settings/alerts", data={"enabled": "1", "recipients": "ops@example.com"})
    client.post("/settings/alerts/test")
    with SessionLocal() as db:
        follow = db.scalars(select(Outbox).where(Outbox.kind == "follow-up")).one()
        test = db.scalars(select(Outbox).where(Outbox.kind == "test")).one()
    page = landing(client, client.post(f"/outbox/{follow.id}/delete"))
    assert "Message deleted. The order's wait for a follow-up was updated." in toast(page) and link(page) == "/chase"
    page = landing(client, client.post(f"/outbox/{test.id}/delete"))
    assert toast(page) == "Message deleted." or toast(page).startswith("Message deleted.")
    assert link(page) == ""


def test_one_person_never_sees_anothers_message(client):
    client.post("/settings/data-updated")
    other = make_client(ACME, fresh=False)
    assert toast(text(other.get("/orders"))) == ""
    other.__exit__(None, None, None)
    assert "Marked as updated today." in toast(text(client.get("/")))
