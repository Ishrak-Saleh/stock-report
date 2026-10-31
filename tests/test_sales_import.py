"""Sales import: the file rules (pure), then the Settings pages that use them. The identifiers match sales to products."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.config import now, today
from app.db import SessionLocal
from app.domain.sales_import import SalesFileError, match_rows, parse_csv
from app.models import Company, DailySale, Product, Settings
from tests.conftest import ACME, make_client

T = date(2026, 10, 30)


# ---- the file rules ----

def test_header_names_and_capitals_and_a_bom_are_accepted():
    rows = parse_csv("﻿Day, SKU ,Qty\n2026-10-28,Mouse,3\n10/27/2026,Mouse,2\n", T)
    assert [(r.day, r.item, r.quantity) for r in rows] == [(date(2026, 10, 28), "Mouse", 3), (date(2026, 10, 27), "Mouse", 2)]


def test_blank_lines_are_skipped_and_line_numbers_follow_the_file():
    with pytest.raises(SalesFileError, match="Line 4"):
        parse_csv("date,item,units\n\n2026-10-28,Mouse,3\n2026-10-28,Mouse,x\n", T)


@pytest.mark.parametrize("text, words", [
    ("", "empty"),
    ("date,item\n2026-10-28,Mouse\n", "three columns"),
    ("date,item,units\n", "no sales rows"),
    ("date,item,units\n2026-13-45,Mouse,1\n", "not a date"),
    ("date,item,units\n2026-11-02,Mouse,1\n", "in the future"),
    ("date,item,units\n2026-10-28,Mouse,-2\n", "whole number"),
    ("date,item,units\n2026-10-28,Mouse,1.5\n", "whole number"),
    ("date,item,units\n2026-10-28,,3\n", "item is empty"),
    ("date,item,units\n2026-10-28,Mouse\n", "too few columns"),
])
def test_bad_files_say_what_is_wrong(text, words):
    with pytest.raises(SalesFileError, match=words):
        parse_csv(text, T)


def test_only_the_first_problems_are_listed():
    text = "date,item,units\n" + "".join(f"2026-10-28,Mouse,bad{i}\n" for i in range(9))
    with pytest.raises(SalesFileError, match="And 4 more"):
        parse_csv(text, T)


def test_matching_ignores_capitals_and_spaces_and_adds_rows_up():
    rows = parse_csv("date,item,units\n2026-10-28,  wireless   MOUSE ,3\n2026-10-28,MOU-001,2\n2026-10-27,Wireless Mouse,1\n", T)
    out = match_rows(rows, {"wireless mouse": [(1, 1)], "mou-001": [(1, 1)]})
    assert out.totals == {(1, date(2026, 10, 28)): 5, (1, date(2026, 10, 27)): 1}
    assert out.matched == 3 and not out.unknown and not out.ambiguous


def test_a_bundle_row_counts_every_unit_in_the_bundle():
    rows = parse_csv("date,item,units\n2026-10-28,Buy 2 Get 2,3\n", T)
    assert match_rows(rows, {"buy 2 get 2": [(7, 4)]}).totals == {(7, date(2026, 10, 28)): 12}


def test_unknown_and_ambiguous_items_are_reported_and_skipped():
    rows = parse_csv("date,item,units\n2026-10-28,Mouse pad,1\n2026-10-28,Mouse pad,2\n2026-10-28,Shared,5\n2026-10-28,Mouse,4\n", T)
    out = match_rows(rows, {"mouse": [(1, 1)], "shared": [(1, 1), (2, 1)]})
    assert out.unknown == {"Mouse pad": 2} and out.ambiguous == {"Shared": 1}
    assert out.totals == {(1, date(2026, 10, 28)): 4} and out.matched == 1


# ---- the Settings pages ----

def csv_for(item: str, days: int = 10, units: int = 5, extra: str = "") -> bytes:
    last = today() - timedelta(days=1)
    lines = ["date,item,units"] + [f"{last - timedelta(days=d)},{item},{units}" for d in range(days)]
    return ("\n".join(lines) + "\n" + extra).encode()


def upload(client, content: bytes, name: str = "sales.csv"):
    return client.post("/settings/sales/check", files={"file": (name, content, "text/csv")})


def do_import(client, content: bytes):
    return client.post("/settings/sales/import", data={"data": content.decode()})


def saved(code: str) -> dict[date, int]:
    with SessionLocal() as db:
        p = db.scalars(select(Product).where(Product.code == code, Product.company_id == 1)).one()
        return {s.day: s.units for s in p.sales}


def test_the_settings_page_has_the_sales_import_panel():
    client = make_client()
    page = client.get("/settings").text
    assert 'id="sales"' in page and 'href="#sales"' in page and 'hx-post="/settings/sales/check"' in page


def test_checking_a_file_saves_nothing_and_shows_what_would_happen():
    client = make_client()
    before = saved("CBL")
    r = upload(client, csv_for("CBL-001", extra=f"{today() - timedelta(days=1)},Mouse pad,2\n"))
    assert r.status_code == 200
    assert "Cable" in r.text and "10 days set" in r.text and "50 units" in r.text
    assert "1 item not recognised" in r.text and "Mouse pad (1)" in r.text
    assert 'name="data"' in r.text and "Import 10 matched rows" in r.text
    assert saved("CBL") == before


def test_importing_gives_a_product_with_no_sales_its_forecast():
    client = make_client()
    assert saved("CBL") == {} and "No sales yet" in client.get("/").text
    r = do_import(client, csv_for("Cable"))
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith("/settings?notice=Sales%20imported")
    assert len(saved("CBL")) == 10
    assert "No sales yet" not in client.get("/").text
    assert "Sales imported. The Stock page has the new numbers." in client.get(r.headers["HX-Redirect"]).text


def test_importing_the_same_file_twice_does_not_double_the_sales_and_a_new_file_replaces_the_day():
    client = make_client()
    last = today() - timedelta(days=1)
    do_import(client, csv_for("CBL-001"))
    do_import(client, csv_for("CBL-001"))
    assert saved("CBL")[last] == 5
    do_import(client, csv_for("CBL-001", days=1, units=9))
    got = saved("CBL")
    assert got[last] == 9 and got[last - timedelta(days=1)] == 5  # only the day in the file changed


def test_rows_for_one_day_are_added_up_and_a_bundle_counts_its_units():
    client = make_client()
    last = today() - timedelta(days=1)
    do_import(client, f"date,item,units\n{last},Mouse,2\n{last},MOU-001,1\n{last},Buy 2 Get 2,2\n".encode())
    assert saved("MOU")[last] == 2 + 1 + 2 * 4


def test_matched_rows_import_even_when_some_items_are_unknown():
    client = make_client()
    do_import(client, csv_for("Cable", days=3, extra=f"{today() - timedelta(days=1)},Mystery,4\n"))
    assert len(saved("CBL")) == 3


def test_importing_marks_the_data_as_updated():
    client = make_client()
    with SessionLocal() as db:
        db.scalars(select(Settings).where(Settings.company_id == 1)).one().data_updated_at = now() - timedelta(days=9)
        db.commit()
    assert "days old" in client.get("/").text
    do_import(client, csv_for("Cable", days=2))
    assert "days old" not in client.get("/").text


def test_a_file_with_nothing_that_matches_says_so_and_imports_nothing():
    client = make_client()
    r = upload(client, csv_for("Nothing like it"))
    assert "nothing to import" in r.text and "disabled" in r.text
    r = do_import(client, csv_for("Nothing like it"))
    assert r.status_code == 200 and "nothing was imported" in r.text and "HX-Redirect" not in r.headers


def test_bad_files_get_a_message_in_the_dialog():
    client = make_client()
    assert "first row must name three columns" in upload(client, b"a,b\n1,2\n").text
    assert "not UTF-8" in upload(client, b"date,item,units\n\xff\xfe,x,1\n").text
    assert "larger than 500 KB" in upload(client, b"x" * 600_000).text
    assert "cannot be imported" in do_import(client, b"date,item,units\n2099-01-01,Cable,1\n").text


def test_the_example_file_downloads_and_imports_cleanly():
    client = make_client()
    r = client.get("/settings/sales/example.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.text.startswith("date,item,units")
    pv = upload(client, r.content)
    assert "cannot be imported" not in pv.text and "matched a product" in pv.text


def test_only_staff_can_import_and_only_into_their_own_companys_products():
    supplier = make_client(ACME)
    assert upload(supplier, csv_for("Cable")).status_code in (302, 303, 403)
    assert do_import(supplier, csv_for("Cable")).status_code in (302, 303, 403)
    assert supplier.get("/settings/sales/example.csv").status_code in (302, 303, 403)

    client = make_client()
    with SessionLocal() as db:  # another company has a product that claims the same item
        db.add(Company(id=2, name="Other Co", created_at=now()))
        db.flush()
        db.add(Product(company_id=2, name="Cable", code="CBL", identifiers=["Cable", "CBL-001"], stock=10, unshipped=0))
        db.commit()
    do_import(client, csv_for("Cable", days=3))
    assert len(saved("CBL")) == 3
    with SessionLocal() as db:
        other = db.scalars(select(Product).where(Product.company_id == 2)).one()
        assert db.scalars(select(DailySale).where(DailySale.product_id == other.id)).all() == []
