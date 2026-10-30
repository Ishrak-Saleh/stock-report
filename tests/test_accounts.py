"""Sign-up, company separation and "nothing opens without signing in". Every test starts from a fresh database."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import ACME, STAFF, make_client, reset_db

from app.db import SessionLocal
from app.main import app
from app.models import Order, Product, Supplier, User
from app.security import signups, throttle
from app.tenancy import scope_for


@pytest.fixture(autouse=True)
def fresh():
    reset_db()
    signups.fails.clear()
    throttle.fails.clear()


def client() -> TestClient:
    c = TestClient(app, follow_redirects=False)
    c.__enter__()
    return c


def sign_up(c, email="new@buyer.example.com", kind="buyer", name="Buyer Co", password="secret1"):
    return c.post("/signup", data={"email": email, "password": password, "confirm": password, "kind": kind, "name": name})


def order_id(name: str, company_id: int = 1) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Order).where(Order.name == name, Order.company_id == company_id)).one().id


def test_a_buyer_can_sign_up_and_lands_on_an_empty_workspace():
    c = client()
    r = sign_up(c)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = c.get("/")
    assert page.status_code == 200 and "No products yet" in page.text and "Load sample data" in page.text
    assert "MOU" not in page.text and "Keyboard" not in page.text


def test_a_new_company_sees_nothing_of_company_1():
    c = client()
    sign_up(c)
    mou = order_id("MOU-001")
    assert "MOU-001" not in c.get("/orders").text
    assert c.get(f"/orders/{mou}").status_code == 404
    assert c.post(f"/orders/{mou}/cancel").status_code == 404
    assert c.post(f"/orders/{mou}/delete").status_code == 404
    with SessionLocal() as db:
        pid = db.scalars(select(Product)).first().id
    for path in (f"/products/{pid}", f"/products/{pid}/runway", f"/products/{pid}/adjust", f"/products/{pid}/try"):
        assert c.get(path).status_code == 404, path
    assert "Acme" not in c.get("/settings").text and "Keyboard" not in c.get("/settings").text
    assert "Mouse" not in c.get("/arrivals").text and "MOU" not in c.get("/outbox").text


def test_company_1_is_unchanged_by_a_new_company():
    sam = make_client(STAFF)
    before = sam.get("/orders").text.count("MOU-002")
    c = client()
    sign_up(c)
    c.post("/sample-data")
    page = sam.get("/orders").text
    assert "MOU-001" in page and page.count("MOU-002") == before  # not doubled by the other company's copy
    with SessionLocal() as db:
        assert len(db.scalars(select(Product)).all()) == 12  # 6 for Company 1 and 6 sample products


def test_sample_data_fills_an_empty_company_once():
    c = client()
    sign_up(c)
    assert c.post("/sample-data").status_code == 303
    page = c.get("/")
    assert "Keyboard" in page.text and "No products yet" not in page.text
    c.post("/sample-data")  # a second press changes nothing
    with SessionLocal() as db:
        assert len(db.scalars(select(Product).where(Product.company_id == 2)).all()) == 6


def test_two_companies_can_use_the_same_product_code_and_order_name():
    c = client()
    sign_up(c)
    c.post("/sample-data")
    with SessionLocal() as db:
        assert len(db.scalars(select(Order.name).where(Order.name == "MOU-001")).all()) == 2


def test_a_supplier_sees_only_the_orders_addressed_to_its_email():
    buyer = client()
    sign_up(buyer)
    buyer.post("/sample-data")
    sample_email = "acme-2@acme.example.com"  # the sample Acme of company 2
    with SessionLocal() as db:
        assert db.scalars(select(Supplier).where(Supplier.email == sample_email)).first()

    sup = client()
    assert sign_up(sup, sample_email, "supplier", "Acme Parts").status_code == 303
    orders = sup.get("/orders")
    assert orders.status_code == 200 and "MOU-002" in orders.text
    assert "KEY-001" not in orders.text  # that order is Nova's, not this supplier's
    mine, theirs = order_id("MOU-002", 2), order_id("MOU-002", 1)
    assert sup.get(f"/orders/{mine}").status_code == 200
    assert sup.get(f"/orders/{theirs}").status_code == 404  # Company 1's order, even with the same name
    assert sup.post(f"/orders/{mine}/confirm").status_code == 303
    assert sup.post(f"/orders/{theirs}/confirm").status_code == 404


def test_the_buyer_sees_what_its_supplier_did():
    buyer = client()
    sign_up(buyer)
    buyer.post("/sample-data")
    sup = client()
    sign_up(sup, "acme-2@acme.example.com", "supplier", "Acme Parts")
    mine = order_id("MOU-002", 2)
    assert "In production" not in buyer.get(f"/orders/{mine}").text
    sup.post(f"/orders/{mine}/confirm")
    assert "In production" in buyer.get(f"/orders/{mine}").text  # a confirmed order moves to "in production"


def test_a_supplier_with_an_unknown_email_sees_no_orders_and_no_buyer_pages():
    sup = client()
    sign_up(sup, "nobody@elsewhere.example.com", "supplier", "Nobody Ltd")
    page = sup.get("/orders")
    assert page.status_code == 200 and "MOU-" not in page.text and "KEY-" not in page.text
    for path in ("/settings", "/arrivals", "/chase", "/outbox", "/orders/new"):
        assert sup.get(path).status_code == 403, path
    assert sup.get("/").status_code == 303


def test_a_new_supplier_lands_on_its_orders():
    sup = client()
    assert sign_up(sup, "s@s.example.com", "supplier", "S Ltd").headers["location"] == "/orders"


@pytest.mark.parametrize("data, text", [
    ({"email": "not-an-email", "password": "secret1", "name": "X"}, "valid email"),
    ({"email": "a@b.example.com", "password": "12345", "name": "X"}, "at least 6 characters"),
    ({"email": "a@b.example.com", "password": "secret1", "name": "   "}, "company name"),
    ({"email": STAFF, "password": "secret1", "name": "X"}, "already has an account"),
    ({"email": STAFF.upper(), "password": "secret1", "name": "X"}, "already has an account"),
])
def test_sign_up_rules(data, text):
    r = client().post("/signup", data={"kind": "buyer", "confirm": data["password"], **data})
    assert r.status_code == 400 and text in r.text


def test_six_characters_is_enough_so_the_demo_password_works():
    assert sign_up(client(), "p@p.example.com", password="P@ss123").status_code == 303


def test_the_role_comes_from_two_fixed_choices_not_from_the_form():
    c = client()
    assert c.post("/signup", data={"email": "x@x.example.com", "password": "secret1", "confirm": "secret1", "kind": "admin", "name": "X"}).status_code == 422
    c.post("/signup", data={"email": "y@y.example.com", "password": "secret1", "confirm": "secret1", "kind": "supplier", "name": "Y",
                            "role": "staff", "company_id": "1"})
    assert c.get("/settings").status_code == 403  # extra "role" and "company_id" fields changed nothing


def test_the_new_account_can_sign_in_again_after_signing_out():
    c = client()
    sign_up(c, "back@b.example.com", password="secret1")
    assert c.post("/logout").status_code == 303
    assert c.get("/").status_code == 303
    assert c.post("/login", data={"email": "back@b.example.com", "password": "wrong-pass"}).status_code == 400
    assert c.post("/login", data={"email": "back@b.example.com", "password": "secret1"}).status_code == 303
    assert c.get("/").status_code == 200


def test_one_address_cannot_create_endless_accounts():
    c = client()
    for i in range(10):
        assert sign_up(c, f"bulk{i}@x.example.com").status_code == 303
        c.post("/logout")
    assert sign_up(c, "bulk99@x.example.com").status_code == 429


def test_passwords_are_stored_hashed():
    sign_up(client(), "h@h.example.com", password="secret1")
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == "h@h.example.com")).one()
    assert "secret1" not in u.password_hash and u.password_hash.startswith("scrypt$")


# ---- nothing opens without signing in ----

PUBLIC = {"/login", "/signup"}


def _paths():
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/static") or path in PUBLIC:
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            yield method, re.sub(r"\{[^}]+\}", "1", path)


def test_every_page_and_action_needs_a_sign_in():
    c = client()
    seen = list(_paths())
    assert len(seen) > 30  # the crawl really found the app's routes
    for method, path in seen:
        r = c.request(method, path)
        assert r.status_code in (303, 401), (method, path, r.status_code)
        assert "/login" in r.headers.get("location", "/login") or r.status_code == 401, (method, path)


def test_api_docs_are_not_public():
    c = client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404


def test_a_tampered_session_cookie_is_not_a_login():
    c = client()
    sign_up(c, "t@t.example.com")
    c.cookies.set("sr_session", c.cookies.get("sr_session")[:-3] + "xyz")
    assert c.get("/").status_code == 303


def test_pages_are_not_cached_so_back_after_sign_out_shows_nothing():
    c = client()
    sign_up(c, "n@n.example.com")
    assert c.get("/").headers["cache-control"] == "no-store"
    assert c.get("/login").headers["cache-control"] == "no-store"


def test_signed_out_database_sessions_see_no_company_data():
    with SessionLocal() as db:
        db.info["scope"] = scope_for(None)
        assert db.scalars(select(Product)).all() == []
        assert db.scalars(select(Order)).all() == []
    with SessionLocal() as db:
        db.info["scope"] = scope_for({"role": "staff", "company_id": None})  # a broken session also sees nothing
        assert db.scalars(select(Supplier)).all() == []


def test_a_supplier_session_cannot_change_company_data():
    with SessionLocal() as db:
        db.info["scope"] = scope_for({"role": "supplier", "email": ACME})
        p = db.scalars(select(Product)).first()
        assert p is not None  # visible, because it is on one of its orders
        p.stock = 9999
        with pytest.raises(PermissionError):
            db.commit()


def test_the_password_box_has_a_show_button_on_both_forms():
    c = client()
    for path, boxes in (("/login", 1), ("/signup", 2)):
        html = c.get(path).text
        assert html.count("data-toggle-password") == boxes and html.count('type="password"') == boxes, path
        assert 'aria-pressed="false"' in html


def test_sam_still_signs_in_to_company_1():
    assert "Mouse" in make_client(STAFF, fresh=False).get("/").text


# ---- the tracking flow ----

def _events(order_name: str) -> list[tuple[str, str]]:
    with SessionLocal() as db:
        o = db.scalars(select(Order).where(Order.name == order_name, Order.company_id == 1)).one()
        return [(e.action, e.by) for e in o.events]


def test_staff_adding_tracking_is_named_as_acting_for_the_supplier():
    sam = make_client(STAFF)
    oid = order_id("PHN-001")
    assert 'for Acme' in sam.get(f"/orders/{oid}/dialog/tracking").text
    r = sam.post(f"/orders/{oid}/tracking", data={"number": "1Z999AA10123456784", "units": 100})
    assert r.status_code == 303 and r.headers["location"] == f"/orders/{oid}?saved=tracking"
    assert ("tracking added", "Sam for Acme") in _events("PHN-001")


def test_a_supplier_adding_tracking_is_named_as_itself():
    sup = make_client(ACME, fresh=False)
    oid = order_id("PHN-001")
    assert "for Acme" not in sup.get(f"/orders/{oid}/dialog/tracking").text
    sup.post(f"/orders/{oid}/tracking", data={"number": "1Z999AA10123456785", "units": 50})
    assert ("tracking added", "Acme") in _events("PHN-001")


def test_staff_marking_an_order_confirmed_is_named_as_acting_for_the_supplier():
    sam = make_client(STAFF)
    oid = order_id("MOU-002")  # placed, not confirmed
    sam.post(f"/orders/{oid}/confirm")
    assert ("confirmed", "Sam for Acme") in _events("MOU-002")


def test_after_saving_tracking_the_page_says_how_many_units_are_left():
    sam = make_client(STAFF)
    oid = order_id("PHN-001")  # 300 units
    sam.post(f"/orders/{oid}/tracking", data={"number": "1Z999AA10123456784", "units": 100})
    page = sam.get(f"/orders/{oid}?saved=tracking").text
    assert "Tracking saved. 200 of 300 units still have none" in page and "Add another shipment" in page
    assert "Tracking saved" not in sam.get(f"/orders/{oid}").text  # only right after saving
    sam.post(f"/orders/{oid}/tracking", data={"number": "1Z999AA10123456785", "units": 200})
    done = sam.get(f"/orders/{oid}?saved=tracking").text
    assert "All 300 units are tracked" in done and "Add another shipment" not in done


def test_a_supplier_with_no_orders_is_told_which_email_buyers_must_use():
    sup = client()
    sign_up(sup, "newsupplier@parts.example.com", "supplier", "Parts Ltd")
    page = sup.get("/orders").text
    assert "newsupplier@parts.example.com" in page and "Copy email" in page and "Settings, Suppliers" in page


def test_the_buyers_supplier_form_says_how_the_supplier_finds_it():
    sam = make_client(STAFF)
    assert "/signup" in sam.get("/settings/suppliers/new").text


# ---- a company that has not set anything up yet ----

HX = {"HX-Request": "true"}


def test_the_order_dialog_explains_what_is_missing_instead_of_doing_nothing():
    c = client()
    sign_up(c)
    r = c.get("/orders/new", headers=HX)
    assert r.status_code == 200 and "Add a product and a supplier in Settings" in r.text and "Open Settings" in r.text
    assert c.get("/orders/new").status_code == 409  # without HTMX it is a plain error page
    c.post("/settings/suppliers", data={"name": "Acme", "email": "a@acme.example.com"})
    assert "Add a product in Settings" in c.get("/orders/new", headers=HX).text  # only the product is missing now


def test_the_arrival_dialog_explains_that_a_product_is_needed():
    c = client()
    sign_up(c)
    r = c.get("/arrivals/new", headers=HX)
    assert r.status_code == 200 and "Add a product in Settings" in r.text


def test_an_empty_orders_page_has_no_dead_new_order_button():
    c = client()
    sign_up(c)
    page = c.get("/orders")
    assert 'hx-get="/orders/new"' not in page.text and "No orders yet" in page.text
    filtered = c.get("/orders", headers={**HX, "HX-Target": "order-list"})
    assert 'hx-get="/orders/new"' not in filtered.text and "Open Settings" in filtered.text


def test_a_company_with_a_product_and_supplier_can_open_the_order_dialog():
    c = client()
    sign_up(c)
    c.post("/sample-data")
    assert "Not ready to order" not in c.get("/orders/new", headers=HX).text
    assert 'hx-get="/orders/new"' in c.get("/orders").text


# ---- confirm password ----

def test_a_mismatched_confirm_password_creates_no_account_and_keeps_what_was_typed():
    c = client()
    r = c.post("/signup", data={"email": "mm@m.example.com", "password": "secret1", "confirm": "secret2",
                                "kind": "supplier", "name": "Mismatch Ltd"})
    assert r.status_code == 400 and "The two passwords do not match." in r.text
    assert 'value="mm@m.example.com"' in r.text and 'value="Mismatch Ltd"' in r.text  # typed text stays
    assert "secret1" not in r.text and "secret2" not in r.text  # passwords never come back
    with SessionLocal() as db:
        assert db.scalars(select(User).where(User.email == "mm@m.example.com")).first() is None
    assert c.get("/orders").status_code == 303  # not signed in


def test_the_confirm_password_is_required():
    r = client().post("/signup", data={"email": "nc@n.example.com", "password": "secret1", "kind": "buyer", "name": "No Confirm"})
    assert r.status_code == 422
