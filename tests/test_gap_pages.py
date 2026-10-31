"""The stock gap: will the shelf be empty before the orders arrive? The rules are in domain/runway.py (tests/test_runway.py);
these tests check what the pages show, that the Stock row and the Runway drawer give one number, and that suppliers get none."""
import html as htmllib
import re

import pytest
from sqlalchemy import event, select

from app.db import SessionLocal, engine
from app.models import Order, Product
from tests.conftest import ACME, make_client


@pytest.fixture
def client():
    c = make_client()
    yield c
    c.__exit__(None, None, None)


def text(r) -> str:
    return htmllib.unescape(r.text)


def pid(code: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Product).where(Product.code == code, Product.company_id == 1)).one().id


def oid(name: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Order).where(Order.name == name)).one().id


def row_of(page: str, name: str) -> str:
    """The Stock page row for one product."""
    return page.split('<div class="orow srow">')[[n for n in re.findall(r"<strong>([^<]+)</strong></a><span class=\"code\">", page)].index(name) + 1].split('<div id="runway-')[0]


def test_the_stock_row_says_how_many_days_cannot_be_saved_by_ordering_today(client):
    t = text(client.get("/"))
    phone, mouse = row_of(t, "Phone"), row_of(t, "Mouse")
    assert "Empty 33 days" in phone and "First order: PHN-001" in phone and "(est.)" in phone
    assert "Empty 22 days" in mouse and "First order: MOU-001" in mouse  # 6 days, then 16 more before MOU-002 lands
    # Monitor has nothing on order and runs out on day 48, but a new order lands on day 45: ordering today still saves it.
    assert "Empty" not in row_of(t, "Monitor") and "Reorder now" in row_of(t, "Monitor")
    assert "Empty" not in row_of(t, "Keyboard") and "Empty" not in row_of(t, "Headphones")
    assert "Empty" not in row_of(t, "Cable")  # no sales, so no forecast to compare


def test_the_headline_counts_the_products_with_days_of_no_stock_and_the_page_explains_the_number(client):
    t = text(client.get("/"))
    assert "Suggested order: 1,963 units. 2 will have days with no stock." in t
    assert "Arrival dates are an estimate" in t and "Ordering today cannot prevent them" in t


def test_the_stock_row_and_the_runway_drawer_give_the_same_number_for_every_product(client):
    page = text(client.get("/"))
    for code, name in [("PHN", "Phone"), ("MOU", "Mouse"), ("MON", "Monitor"), ("KEY", "Keyboard"), ("HDP", "Headphones"), ("CBL", "Cable")]:
        shown = re.search(r"Empty (\d+) days?", row_of(page, name))
        drawer = text(client.get(f"/products/{pid(code)}/runway?horizon=90", headers={"HX-Request": "true"}))
        said = re.search(r"(\d+) days? with no stock comes? before day", drawer)
        assert (shown and shown.group(1)) == (said and said.group(1)), name


def test_the_chase_list_and_the_orders_list_say_how_many_empty_days_come_before_an_order_lands(client):
    for url in ("/chase", "/orders"):
        t = text(client.get(url))
        assert "Shelf empty 33 days" in t and "Shelf empty 22 days" in t and "Shelf empty 6 days" in t
        assert t.count("Shelf empty") == 3  # HDP-001 and KEY-001 are late too, but their products have plenty of stock
        assert "Empty shelf first" in t


def test_the_order_page_warns_only_when_the_product_runs_dry_before_the_order_lands(client):
    t = text(client.get(f"/orders/{oid('PHN-001')}"))
    assert "Phone is empty for about 33 days" in t and "an estimate" in t
    for name in ("HDP-001", "KEY-001", "MON-001"):
        assert "is empty for about" not in text(client.get(f"/orders/{oid(name)}"))


def test_a_supplier_never_gets_a_stock_gap_and_the_gap_code_is_not_even_run_for_them(monkeypatch):
    def boom(*_, **__):
        raise AssertionError("the gap must not be computed in a supplier session")
    supplier = make_client(ACME)
    monkeypatch.setattr("app.services.products.gap_of", boom)
    monkeypatch.setattr("app.services.orders.empty_before", boom)
    page = text(supplier.get("/orders"))
    assert "Empty" not in page and "Shelf empty" not in page and "will have days" not in page
    mou = oid("MOU-001")
    detail = text(supplier.get(f"/orders/{mou}"))
    assert "is empty for about" not in detail and "Shelf empty" not in detail


def count_queries(client, url: str) -> int:
    seen = []
    def count(*_):
        seen.append(1)
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get(url).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(seen)


def test_the_gap_adds_no_queries_to_the_stock_page_and_a_fixed_six_to_the_chase_and_orders_pages(client):
    count_queries(client, "/")  # the first request warms nothing we count, but keeps the comparison fair
    assert count_queries(client, "/") <= 14          # the Stock page was 14 before the gap: the rows are already loaded
    assert count_queries(client, "/chase") <= 15     # the product report adds a fixed six, however many orders there are
    assert count_queries(client, "/orders") <= 18


def add_product(code: str, stock: int, per_day: int, lead_time: int | None = None) -> None:
    """A product with 10 days of steady sales, no orders, and the given stock."""
    from datetime import timedelta

    from app.config import today
    from app.models import DailySale
    with SessionLocal() as db:
        p = Product(company_id=1, name=f"Test {code}", code=code, identifiers=[code], stock=stock, unshipped=0, lead_time=lead_time)
        db.add(p)
        db.flush()
        db.add_all(DailySale(product_id=p.id, day=today() - timedelta(days=d), units=per_day) for d in range(1, 11))
        db.commit()


def test_a_product_the_sop_calls_healthy_never_shows_an_empty_badge(client):
    add_product("HLT", stock=700, per_day=10)  # 70 days of stock, nothing on order: Healthy, and there is time to reorder
    page = text(client.get("/"))
    row = row_of(page, "Test HLT")
    assert "Healthy" in row and "Empty" not in row
    for name in ("Keyboard", "Headphones", "Cable"):
        assert "Healthy" in row_of(page, name) and "Empty" not in row_of(page, name)


def test_a_product_that_runs_out_before_a_new_order_could_land_is_flagged_with_no_order_covering_it(client):
    add_product("LOW", stock=400, per_day=10)  # 40 days of stock against a 45-day lead time: 5 days nothing can save
    row = row_of(text(client.get("/")), "Test LOW")
    assert "Empty 5 days" in row and "No order covers it, and a new one takes 45 days" in row


def test_the_window_follows_the_products_own_lead_time(client):
    add_product("OVR", stock=400, per_day=10, lead_time=60)  # now 20 days nothing can save
    assert "Empty 20 days" in row_of(text(client.get("/")), "Test OVR")
    add_product("SHT", stock=400, per_day=10, lead_time=30)  # an order placed today lands on day 30, before day 40
    assert "Empty" not in row_of(text(client.get("/")), "Test SHT")


def test_stock_rows_show_warning_symbols_and_keep_the_details_in_a_card(client):
    page = text(client.get("/"))
    phone, mouse, monitor = row_of(page, "Phone"), row_of(page, "Mouse"), row_of(page, "Monitor")
    for row in (phone, mouse, monitor, row_of(page, "Keyboard")):
        assert 'class="badge' not in row            # no pills on the Stock rows any more, only symbols
        assert row.count('role="tooltip" hidden') == row.count('class="tipbtn')  # every symbol has its own card
    assert phone.count('class="tipbtn') == 2 and mouse.count('class="tipbtn') == 2   # status symbol plus gap symbol
    assert monitor.count('class="tipbtn') == 1                                          # reorder now, but no gap
    assert 'aria-label="Out of stock. Reorder now. Ordered units not enough."' in phone
    assert re.search(r'aria-label="Empty 33 days\. Days with no stock before a new order placed today could arrive.*First order: PHN-001, \w+ \d+ \(est\.\)"', phone)
    assert "<b>Empty 33 days</b>" in phone and "<b>Out of stock</b>" in phone and 'class="tipbtn serious"' in monitor
    for name in ("Keyboard", "Headphones", "Cable"):   # Healthy keeps a quiet check, and its card says Healthy
        row = row_of(page, name)
        assert row.count('class="tipbtn') == 1 and 'class="tipbtn good"' in row and 'aria-label="Healthy' in row
    assert "Hover over an icon, or tap it on a phone, for details." in page


def test_the_symbol_cards_are_wired_up_for_hover_focus_and_tap():
    js = open("app/static/app.js", encoding="utf-8").read()
    for needle in ('closest("[data-tip]")', '"pointerover"', '"focusin"', '"click"', 'tipHide()', "aria-expanded"):
        assert needle in js
    css = open("app/static/app.css", encoding="utf-8").read()
    assert ".tipcard { position: fixed" in css   # fixed, so the table that scrolls sideways never clips the card
