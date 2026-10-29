import html as htmllib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Order, OrderEvent, Product
from tests.conftest import ACME, NOVA, PASSWORD, STAFF, make_client, reset_db, sign_in


def text(r) -> str:
    return htmllib.unescape(r.text)


def oid(name: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Order).where(Order.name == name)).one().id


@pytest.fixture
def anon():
    with TestClient(app, follow_redirects=False) as c:
        reset_db()
        yield c


@pytest.fixture
def staff():
    c = make_client(STAFF)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def acme():
    c = make_client(ACME)
    yield c
    c.__exit__(None, None, None)


# ---- signing in ----

def test_every_page_needs_a_login(anon):
    for path in ("/", "/orders", "/arrivals", "/chase", "/settings", "/outbox", "/products/1", "/orders/1"):
        r = anon.get(path)
        assert r.status_code == 303 and r.headers["location"].startswith("/login"), path
    assert anon.get("/").headers["location"] == "/login?next=/"
    assert anon.post("/orders", data={"product_id": 1, "supplier_id": 1, "units": 5}).headers["location"] == "/login"


def test_htmx_requests_are_sent_to_the_login_page(anon):
    r = anon.get("/arrivals/new", headers={"HX-Request": "true"})
    assert r.status_code == 401 and r.headers["HX-Redirect"] == "/login"


def test_the_login_page_and_a_wrong_password(anon):
    t = text(anon.get("/login"))
    assert "Sign in to see what to reorder this week." in t and 'name="password"' in t and "Stock Report" in t
    assert 'aria-label="Primary"' not in t  # no navigation before signing in
    r = anon.post("/login", data={"email": STAFF, "password": "wrong"})
    assert r.status_code == 400 and "The email or password is not right" in text(r)
    assert anon.post("/login", data={"email": "nobody@example.com", "password": PASSWORD}).status_code == 400


def test_staff_land_on_stock_and_suppliers_on_their_orders(anon):
    assert sign_in(anon, STAFF).get("/").status_code == 200
    anon.post("/logout")
    r = anon.post("/login", data={"email": ACME, "password": PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/orders"
    assert anon.get("/").headers["location"] == "/orders"


def test_the_return_address_must_stay_on_this_site(anon):
    ok = anon.post("/login", data={"email": STAFF, "password": PASSWORD, "next": "/arrivals"})
    assert ok.headers["location"] == "/arrivals"
    anon.post("/logout")
    for evil in ("//evil.example.com", "https://evil.example.com", "/\\evil.example.com"):
        r = anon.post("/login", data={"email": STAFF, "password": PASSWORD, "next": evil})
        assert r.headers["location"] == "/", evil
        anon.post("/logout")


def test_too_many_wrong_passwords_lock_the_address(anon):
    for _ in range(5):
        assert anon.post("/login", data={"email": "ghost@example.com", "password": "x"}).status_code == 400
    r = anon.post("/login", data={"email": "ghost@example.com", "password": "x"})
    assert r.status_code == 429 and "Too many sign-in attempts. Try again in 5 minutes." in text(r)


def test_signing_out_ends_the_session(staff):
    assert staff.get("/").status_code == 200
    assert staff.post("/logout").headers["location"] == "/login"
    assert staff.get("/").status_code == 303


def test_the_navigation_matches_the_role(staff, acme):
    s = text(staff.get("/"))
    assert 'href="/arrivals"' in s and 'href="/chase"' in s and 'href="/settings"' in s and 'href="/outbox"' in s and "Sign out" in s
    a = text(acme.get("/orders"))
    assert 'href="/arrivals"' not in a and 'href="/chase"' not in a and 'href="/settings"' not in a and "Sign out" in a
    assert "Acme Manufacturing, supplier" in a


# ---- what a supplier may see and do ----

def test_a_supplier_sees_only_their_own_orders(acme):
    t = text(acme.get("/orders"))
    for mine in ("MOU-001", "MOU-002", "PHN-001"):
        assert mine in t
    for theirs in ("KEY-001", "HDP-001", "MON-001"):
        assert theirs not in t
    assert "3 orders from Acme Manufacturing are open." in t and "1 needs confirming and 1 needs tracking." in t
    assert "Confirm MOU-002" in t and t.count("btn primary") == 1
    assert "Phone" in t and "forecast" not in t.lower().replace("forecasts", "")


def test_the_finished_filter_for_a_supplier(acme):
    t = text(acme.get("/orders?show=arrived"))
    assert "No finished orders yet" in t
    nova = make_client(NOVA, fresh=False)
    assert "MON-001" in text(nova.get("/orders?show=arrived")) and "MOU-001" not in text(nova.get("/orders"))
    nova.__exit__(None, None, None)


@pytest.mark.parametrize("path", ["/arrivals", "/arrivals/new", "/chase", "/settings", "/outbox", "/products/1", "/products/1/runway",
                                  "/products/1/adjust", "/orders/new", "/settings/products/1", "/arrivals/1/match"])
def test_staff_pages_are_closed_to_suppliers(acme, path):
    r = acme.get(path)
    assert r.status_code == 403, path
    assert "That is not allowed" in text(r) and "Only staff can open this page." in text(r)


def test_a_supplier_cannot_touch_another_suppliers_order(acme):
    nova = oid("KEY-001")
    assert acme.get(f"/orders/{nova}").status_code == 403
    assert "This order is not yours." in text(acme.get(f"/orders/{nova}"))
    assert acme.post(f"/orders/{nova}/confirm").status_code == 403
    assert acme.post(f"/orders/{nova}/tracking", data={"number": "123", "units": 5}).status_code == 403
    assert acme.get(f"/orders/{nova}/dialog/tracking").status_code == 403
    with SessionLocal() as db:
        assert not db.get(Order, nova).trackings


def test_a_supplier_can_confirm_and_add_tracking_and_it_is_logged_in_their_name(acme):
    gid, gad = oid("MOU-002"), oid("PHN-001")
    assert acme.post(f"/orders/{gid}/confirm").status_code == 303
    assert acme.post(f"/orders/{gad}/tracking", data={"number": "1Z999AA10123456784", "units": 300}).status_code == 303
    with SessionLocal() as db:
        assert db.get(Order, gid).confirmed_at is not None
        events = db.scalars(select(OrderEvent).where(OrderEvent.by == "Acme")).all()
        assert {e.action for e in events} == {"confirmed", "tracking added"}
    t = text(acme.get("/orders"))
    assert "2 orders" not in t and "Fully tracked" in t


def test_tracking_cannot_exceed_the_order_even_for_a_supplier(acme):
    r = acme.post(f"/orders/{oid('PHN-001')}/tracking", data={"number": "1Z999AA10123456784", "units": 301})
    assert r.status_code == 400 and "Only 300 units are left to track" in text(r)


@pytest.mark.parametrize("action", ["cancel", "close", "reopen", "delete", "edit"])
def test_a_supplier_cannot_edit_cancel_close_or_delete(acme, action):
    gid = oid("MOU-002")
    r = acme.post(f"/orders/{gid}/{action}", data={"units": 5, "supplier_id": 1})
    assert r.status_code == 403
    with SessionLocal() as db:
        o = db.get(Order, gid)
        assert not o.cancelled and not o.closed and o.units == 150


def test_a_supplier_cannot_create_orders_or_open_staff_dialogs(acme):
    assert acme.post("/orders", data={"product_id": 1, "supplier_id": 1, "units": 5}).status_code == 403
    gid = oid("MOU-002")
    for what in ("edit", "message", "delete"):
        assert acme.get(f"/orders/{gid}/dialog/{what}").status_code == 403
    assert acme.get(f"/orders/{gid}/dialog/tracking").status_code in (200, 409)
    assert acme.post(f"/orders/{oid('MOU-001')}/tracking/1/remove").status_code == 403


def test_a_suppliers_order_page_offers_only_their_actions(acme):
    t = text(acme.get(f"/orders/{oid('MOU-002')}"))
    assert "Please confirm this order of 150 units." in t and "Confirm this order" in t
    for hidden in ("Cancel order", "Close, no more coming", "Copy order message", "Delete order", "Edit", "Arrivals matched", "SOP"):
        assert hidden not in t
    done = text(acme.get(f"/orders/{oid('MOU-001')}"))
    assert "Nothing is waiting on you" in done


def test_staff_order_pages_keep_every_action(staff):
    t = text(staff.get(f"/orders/{oid('MOU-002')}"))
    for shown in ("Cancel order", "Close, no more coming", "Copy order message", "Delete order", "Arrivals matched"):
        assert shown in t


# ---- other protections ----

def test_a_form_posted_from_another_site_is_refused(staff):
    gid = oid("MOU-002")
    r = staff.post(f"/orders/{gid}/cancel", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403 and "Cross-site request blocked." in r.text
    with SessionLocal() as db:
        assert not db.get(Order, gid).cancelled
    ok = staff.post(f"/orders/{gid}/cancel", headers={"Origin": "http://testserver"})
    assert ok.status_code == 303


def test_responses_carry_security_headers(staff):
    h = staff.get("/").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]
    assert h["referrer-policy"] == "same-origin"
    cookie = staff.cookies.get("sr_session")
    assert cookie and "test-password-only" not in cookie


def test_errors_are_pages_that_say_what_happened(staff):
    r = staff.get("/orders/99999")
    assert r.status_code == 404 and "That page does not exist" in text(r) and "Go to Stock" in text(r)
    r = staff.post("/orders", data={"product_id": 1, "supplier_id": 1, "units": 2_000_000})
    assert r.status_code == 422 and "Check what you entered" in text(r)


def test_foreign_keys_are_enforced(staff):
    from sqlalchemy.exc import IntegrityError
    from app.models import Allocation
    with SessionLocal() as db:
        db.add(Allocation(arrival_id=999999, order_id=None, units=1))
        with pytest.raises(IntegrityError):
            db.commit()
