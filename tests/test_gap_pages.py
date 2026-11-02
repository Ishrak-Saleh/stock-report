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
    assert "Arrival dates are estimates" in t and "Days with no stock before a new order placed today could arrive" in t   # the card explains the symbol


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
        assert t.count("<b>Shelf empty") == 3  # one card each; HDP-001 and KEY-001 are late too, but their products have plenty of stock
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
    assert "Reading the bars" in page and "Hover over an icon" not in page   # one "i" by the title explains the bar, no hint line


def test_the_symbol_cards_are_wired_up_for_hover_focus_and_tap():
    js = open("app/static/app.js", encoding="utf-8").read()
    for needle in ('closest("[data-tip]")', '"pointerover"', '"focusin"', '"click"', 'tipHide()', "aria-expanded"):
        assert needle in js
    css = open("app/static/app.css", encoding="utf-8").read()
    assert ".tipcard { position: fixed" in css   # fixed, so the table that scrolls sideways never clips the card



# ---- the same symbols beside the name on every list and order page, for staff and for suppliers ----

def order_row(page: str, name: str, marker: str = '<div class="orow lstrow link"') -> str:
    return next(chunk for chunk in page.split(marker)[1:] if f"<strong>{name}</strong>" in chunk).split("</div>\n</div>")[0]


def test_stock_symbols_sit_on_the_name_line_right_after_the_code(client):
    page = text(client.get("/"))
    for code in ("PHN", "MOU", "MON", "KEY", "HDP", "CBL"):
        assert re.search(rf'<span class="code">{code}</span>\s*<div class="flags">', page), code


def test_the_orders_list_shows_symbols_beside_the_order_name(client):
    page = text(client.get("/orders"))
    phn, hdp = order_row(page, "PHN-001"), order_row(page, "HDP-001")
    assert phn.count('class="tipbtn') == 2 and 'aria-label="In production. 0 of 300 units have arrived."' in phn
    assert "<b>Shelf empty 33 days</b>" in phn and 'class="badge' not in phn
    assert hdp.count('class="tipbtn') == 1 and "Shelf empty" not in hdp      # plenty of stock, so only the status symbol
    assert re.search(r'<strong>PHN-001</strong></a>\s*<div class="flags">', phn)   # the product has its own column now


def test_the_chase_list_has_the_alert_symbol_beside_the_order_name_and_no_alert_column(client):
    t = text(client.get("/chase"))
    due = t.split("Due now")[1].split("The three rules")[0]
    assert "<span>Alert</span>" not in due and 'class="badge' not in due
    assert due.count('class="pname"') == 5
    assert re.search(r'aria-label="Ask for tracking\. Confirmed \d+ days ago, no tracking\. Waited \d+ days, the limit is 10 \(\d+ over\)\."', due)
    assert 'class="tipbtn serious"' in due and 'class="tipbtn warn"' in due and due.count("<b>Shelf empty") == 3
    assert 'href="/chase?kind=tracking"' in due  # the filter still works
    client.post(f"/chase/{oid('KEY-001')}/outbox", data={"kind": "tracking"})
    quiet = text(client.get("/chase")).split("Chased recently")[1].split("The three rules")[0]
    assert "<span>Alert</span>" not in quiet and 'class="badge' not in quiet
    assert 'aria-label="Ask for tracking. Confirmed' in quiet and "Can be sent again on" in quiet


def test_the_order_page_has_the_status_symbol_beside_the_name_and_keeps_the_warning_box(client):
    page = text(client.get(f"/orders/{oid('PHN-001')}"))
    head = page.split("<h2")[1].split("</h2>")[0]
    assert head.count('class="tipbtn') == 2 and 'aria-label="In production.' in head and "<b>Shelf empty 33 days</b>" in head
    assert 'class="badge' not in head   # no pill beside the order name any more
    assert "Phone is empty for about 33 days" in page            # the long warning box stays, as chosen
    hdp = text(client.get(f"/orders/{oid('HDP-001')}")).split("<h2")[1].split("</h2>")[0]
    assert hdp.count('class="tipbtn') == 1


def test_the_explaining_text_lives_in_the_info_icons_not_on_the_page(client):
    """Each phrase is printed twice: in the icon's aria-label and in its hidden card. Printed a third time would mean it is back on the page."""
    def once_in_an_icon(page: str, *phrases: str):
        for phrase in phrases:
            assert page.count(phrase) == 2, (phrase, page.count(phrase))

    once_in_an_icon(text(client.get("/")), "Each dot shows how long the order has waited.", "Arrival dates are estimates: the order date plus the lead time.")
    client.post(f"/chase/{oid('KEY-001')}/outbox", data={"kind": "tracking"})   # the "Chased recently" panel needs one chased order
    once_in_an_icon(text(client.get("/chase")), "The same message can be sent again after 2 days, if the order still needs it.", "These rules decide when an order needs a message.")
    once_in_an_icon(text(client.get("/arrivals")), "Units stay in warehouse stock either way.")
    once_in_an_icon(text(client.get("/settings")), "Used by every product that has no override of its own.", "Blank forecast numbers use the defaults above.",
                    "Messages are sent to the email address on file.", "Warehouse stock is not changed.", "Sends an email when a product falls below its reorder line.")
    once_in_an_icon(text(client.get(f"/products/{pid('KEY')}")), "The count is the last stock count plus the changes recorded here.",
                    "because orders have no confirmed arrival date.")
    once_in_an_icon(text(client.get(f"/orders/{oid('MOU-001')}")), "This is an estimate, because orders have no confirmed arrival date.")
    once_in_an_icon(text(client.get(f"/products/{pid('KEY')}/runway?horizon=90", headers={"HX-Request": "true"})), "because orders have no confirmed arrival date.")
    supplier = make_client(ACME, fresh=False)
    once_in_an_icon(text(supplier.get("/orders")), "These limits are set by your account and enforced on every request.")


def test_each_chase_row_on_stock_has_an_info_icon_with_its_days(client):
    page = text(client.get("/"))
    rows = page.split('<div class="crow">')[1:]
    assert rows and all("Follow-up limit: " in row and " days over the limit." in row and " days · limit " not in row for row in rows)


def test_the_stage_bar_key_lives_in_an_info_icon_with_its_colors(client):
    page = text(client.get("/orders"))
    assert "Stage bar:" not in page and "Reading the stage bar" in page
    for mark in ("st1", "st2", "st3", "st4"):
        assert f'<i class="k {mark}"></i>' in page
    assert page.index("Reading the stage bar") < page.index('name="product"') < page.index('name="chase"')   # title, then the filters at its right
    supplier = text(make_client(ACME, fresh=False).get("/orders"))   # the supplier's list has the same key
    assert "Reading the stage bar" in supplier and '<i class="k st3"></i>' in supplier


def test_the_match_bar_key_lives_in_an_info_icon_with_its_colors(client):
    page = text(client.get("/arrivals"))
    assert 'class="legend' not in page.split("All arrivals")[1] and "Reading the match bar" in page
    for mark in ("st2", "st3", "free", "none"):
        assert f'<i class="k {mark}"></i>' in page


def test_no_page_mentions_the_assignment_brief(client):
    """Staff should never read "SOP": it is the assignment's word, not theirs."""
    client.post(f"/chase/{oid('KEY-001')}/outbox", data={"kind": "tracking"})
    paths = ["/", "/orders", "/chase", "/arrivals", "/settings", "/outbox", f"/products/{pid('KEY')}", f"/orders/{oid('MOU-001')}",
             f"/products/{pid('KEY')}/runway?horizon=90", f"/orders/new?product_id={pid('MOU')}"]
    for path in paths:
        r = client.get(path, headers={"HX-Request": "true"} if "runway" in path or "/new" in path else {})
        assert "SOP" not in r.text, path
    assert "SOP" not in make_client(ACME, fresh=False).get("/orders").text
    assert "Days of stock" in text(client.get(f"/products/{pid('KEY')}")) and "days left" not in text(client.get(f"/products/{pid('KEY')}"))


def test_a_supplier_sees_the_same_symbols_but_never_the_stock_gap():
    supplier = make_client(ACME)
    page = text(supplier.get("/orders"))
    rows = page.split("What this login can do")[0].split('<div class="orow sorow link"')[1:]   # the rows only, not the panel after them
    assert rows and all(row.count('class="tipbtn') == 1 and "<b>Shelf empty" not in row for row in rows)
    assert all('class="badge' not in row for row in rows) and 'class="wait warn"' in page   # "Waiting on" keeps its words
    assert "Your confirmation" in page and "calendar" not in page
    assert "<span>Status</span>" in page and "Where it is" not in page   # the SOP word, same as the staff list
    detail = text(supplier.get(f"/orders/{oid('MOU-001')}")).split("<h2")[1].split("</h2>")[0]
    assert detail.count('class="tipbtn') == 1 and "Shelf empty" not in detail
