import html as htmllib
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import now
from app.db import SessionLocal
from app.models import Outbox, Product, Settings, Supplier
from tests.conftest import make_client


@pytest.fixture
def client():
    c = make_client()
    yield c
    c.__exit__(None, None, None)


def text(r) -> str:
    return htmllib.unescape(r.text)


def product(code: str) -> Product:
    with SessionLocal() as db:
        return db.scalars(select(Product).where(Product.code == code)).one()


def settings_row() -> Settings:
    with SessionLocal() as db:
        return db.scalars(select(Settings)).one()


def edit_product(client, which="MOU", **over):
    p = product(which)
    form = {"name": p.name, "code": p.code, "identifiers": ", ".join(p.identifiers), "bundles": "", "lead": "", "safety": "", "target": ""}
    return client.post(f"/settings/products/{p.id}", data=form | over)


def test_the_page_states_the_reorder_line(client):
    t = text(client.get("/settings"))
    assert "Reorder line is 59 days." in t and "An order lands 45 days after you place it" in t
    assert 'value="45"' in t and 'value="14"' in t and 'value="60"' in t
    assert "Buy 2 Get 2 = 4 units" in t and "Acme Manufacturing" in t and "Monitor" in t
    assert t.count("btn primary") == 1  # Save settings


def test_saving_defaults_changes_the_forecast_everywhere(client):
    r = client.post("/settings/defaults", data={"lead_time": 30, "safety_days": 10, "target_days": 50})
    assert r.status_code == 303 and "notice=Forecast" in r.headers["location"]
    t = text(client.get("/settings?notice=Forecast defaults saved."))
    assert "Reorder line is 40 days." in t and "Forecast defaults saved." in t
    stock = text(client.get("/"))
    assert "lead time 30 days" in stock


def test_defaults_must_be_whole_numbers_in_range(client):
    for bad in ({"lead_time": "abc", "safety_days": 14, "target_days": 60}, {"lead_time": 45, "safety_days": -1, "target_days": 60},
                {"lead_time": 45, "safety_days": 14, "target_days": 0}, {"lead_time": "", "safety_days": 14, "target_days": 60}):
        r = client.post("/settings/defaults", data=bad)
        assert r.status_code == 400 and "must be a whole number" in text(r)
    assert settings_row().lead_time == 45


def test_a_notice_from_the_address_is_only_shown_if_it_is_one_of_ours(client):
    assert "send your password" not in text(client.get("/settings?notice=Please send your password"))


def test_a_product_override_applies_and_is_shown(client):
    assert edit_product(client, "MON", lead="60").status_code == 303
    t = text(client.get("/settings"))
    assert "Lead 60" in t and "Monitor" in t
    assert product("MON").lead_time == 60 and product("MON").safety_days is None
    assert edit_product(client, "MON", lead="").status_code == 303 and product("MON").lead_time is None  # blank means default


def test_product_edits_follow_the_rules(client):
    r = edit_product(client, "MOU", code="key")
    assert r.status_code == 400 and "KEY is used by Keyboard. Pick a different code." in text(r)
    assert "1 to 8 letters or digits" in text(edit_product(client, "MOU", code="bad code!"))
    assert "Enter a product name" in text(edit_product(client, "MOU", name="  "))
    assert "should look like: Buy 2 Get 2 = 4" in text(edit_product(client, "MOU", bundles="Buy 2 Get 2"))
    assert "Lead time must be a whole number" in text(edit_product(client, "MOU", lead="-4"))
    assert product("MOU").code == "MOU"


def test_bundles_and_identifiers_are_saved(client):
    edit_product(client, "MOU", identifiers="MOUSE-01, Mouse, MOUSE-01", bundles="Buy 2 Get 2 = 4\n3-pack = 3")
    p = product("MOU")
    assert p.identifiers == ["MOUSE-01", "Mouse"] and p.bundle_map == {"Buy 2 Get 2": 4, "3-pack": 3}
    assert "3-pack = 3 units" in text(client.get("/settings"))


def test_adding_a_product(client):
    r = client.post("/settings/products", data={"name": "Mouse Pro", "code": "mpr", "identifiers": "", "bundles": "", "lead": "", "safety": "", "target": ""})
    assert r.status_code == 303
    p = product("MPR")
    assert p.name == "Mouse Pro" and p.stock == 0 and p.identifiers == ["Mouse Pro"]
    assert "Mouse Pro" in text(client.get("/")) and "Products 7" in text(client.get("/settings"))


def test_supplier_edits(client):
    with SessionLocal() as db:
        sid = db.scalars(select(Supplier).where(Supplier.name == "Nova Imports")).one().id
    assert client.post(f"/settings/suppliers/{sid}", data={"name": "Nova Imports", "email": "Orders@Nova.example.com"}).status_code == 303
    with SessionLocal() as db:
        assert db.get(Supplier, sid).email == "orders@nova.example.com"  # lower-cased
    r = client.post(f"/settings/suppliers/{sid}", data={"name": "Nova Imports", "email": "not-an-email"})
    assert r.status_code == 400 and "not-an-email is not an email address." in text(r)
    assert client.post("/settings/suppliers", data={"name": "Zed Parts", "email": "zed@example.com"}).status_code == 303
    assert "Zed Parts" in text(client.get("/settings"))
    assert "Enter a supplier name" in text(client.post("/settings/suppliers", data={"name": "", "email": "a@b.co"}))


def test_the_dialogs_open(client):
    h = {"HX-Request": "true"}
    gid = product("MOU").id
    t = text(client.get(f"/settings/products/{gid}", headers=h))
    assert "<dialog" in t and "Edit Mouse" in t and "Buy 2 Get 2 = 4" in t and "45 (default)" in t
    assert "Add product" in text(client.get("/settings/products/new", headers=h))
    assert "Add supplier" in text(client.get("/settings/suppliers/new", headers=h))
    assert client.get("/settings/products/999", headers=h).status_code == 404


def test_alert_settings_and_the_test_send(client):
    bad = client.post("/settings/alerts", data={"enabled": "1", "recipients": "ops@example.com, nope"})
    assert bad.status_code == 400 and "nope is not an email address." in text(bad)
    assert client.post("/settings/alerts", data={"enabled": "1", "recipients": "ops@example.com, sam@example.com"}).status_code == 303
    s = settings_row()
    assert s.alerts_enabled and s.recipients == "ops@example.com, sam@example.com"
    assert client.post("/settings/alerts/test").status_code == 303
    with SessionLocal() as db:
        msgs = db.scalars(select(Outbox)).all()
        assert [m.to for m in msgs] == ["ops@example.com", "sam@example.com"] and all(m.kind == "test" for m in msgs)
        assert msgs[0].subject.startswith("Test: Reorder alert: 3 products need a reorder")
        assert "Phone" in msgs[0].body and "suggested order" in msgs[0].body


def test_a_real_alert_needs_alerts_turned_on(client):
    client.post("/settings/alerts", data={"recipients": "ops@example.com"})
    r = client.post("/settings/alerts/send")
    assert r.status_code == 400 and "Reorder alerts are off" in text(r)
    client.post("/settings/alerts", data={"enabled": "1", "recipients": "ops@example.com"})
    assert client.post("/settings/alerts/send").status_code == 303
    with SessionLocal() as db:
        assert db.scalars(select(Outbox)).one().kind == "alert"


def test_a_test_needs_someone_to_send_to(client):
    r = client.post("/settings/alerts/test")
    assert r.status_code == 400 and "Add at least one email address" in text(r)


def test_old_data_gets_a_warning_until_it_is_marked_updated(client):
    assert "days old" not in text(client.get("/"))
    with SessionLocal() as db:
        db.scalars(select(Settings)).one().data_updated_at = now() - timedelta(days=5)
        db.commit()
    for page in ("/", "/arrivals", "/settings"):
        assert "The stock and sales data is 5 days old." in text(client.get(page))
    assert client.post("/settings/data-updated").status_code == 303
    assert "days old" not in text(client.get("/"))


def test_two_days_old_is_not_yet_a_warning(client):
    with SessionLocal() as db:
        db.scalars(select(Settings)).one().data_updated_at = now() - timedelta(days=2)
        db.commit()
    assert "days old" not in text(client.get("/"))
