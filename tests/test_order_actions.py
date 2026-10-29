import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Allocation, Arrival, Base, Product, Supplier
from app.services import orders as svc
from datetime import date


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Product(code="GIZ", name="Gizmo"), Supplier(name="Acme", email="a@example.com")])
        session.commit()
        yield session


def new_order(db, units=100):
    return svc.create_order(db, db.get(Product, 1), 1, units, "")


def actions(o):
    return [e.action for e in o.events]


def test_names_count_up_per_product(db):
    assert [new_order(db).name for _ in range(3)] == ["GIZ-001", "GIZ-002", "GIZ-003"]


def test_confirm_moves_to_in_production(db):
    o = new_order(db)
    assert svc.order_stages(o).status == "placed"
    svc.confirm_order(db, o)
    assert svc.order_stages(o).status == "in production"
    assert actions(o) == ["created", "confirmed"]


def test_tracking_cap_and_later_entry(db):
    o = new_order(db, 100)
    svc.add_tracking(db, o, "1Z999AA10123456784", "", 60)
    assert o.trackings[0].carrier == "UPS"  # detected
    assert svc.order_stages(o).status == "on the way" and svc.order_stages(o).on_the_way == 60
    with pytest.raises(svc.OrderError, match="40 units are left"):
        svc.add_tracking(db, o, "794644790138", "", 41)
    svc.add_tracking(db, o, "794644790138", "", 40)  # the rest can be added later, exactly to the cap
    assert svc.tracked_units(o) == 100


def test_remove_tracking_frees_units(db):
    o = new_order(db)
    svc.add_tracking(db, o, "794644790138", "", 100)
    svc.remove_tracking(db, o, o.trackings[0].id)
    assert svc.tracked_units(o) == 0 and "tracking removed" in actions(o)


def test_edit_cannot_go_below_tracked_or_arrived(db):
    o = new_order(db, 100)
    svc.add_tracking(db, o, "794644790138", "", 70)
    with pytest.raises(svc.OrderError):
        svc.edit_order(db, o, 50, "", 1)
    svc.edit_order(db, o, 70, "new note", 1)
    assert o.units == 70 and o.notes == "new note" and actions(o)[-1] == "edited"


def test_cancel_close_reopen(db):
    o = new_order(db)
    svc.close_order(db, o)
    assert svc.order_stages(o).status == "closed" and svc.order_stages(o).to_come == 0
    svc.reopen_order(db, o)
    assert svc.order_stages(o).status == "placed"
    svc.cancel_order(db, o)
    assert svc.order_stages(o).status == "cancelled"
    with pytest.raises(svc.OrderError):
        svc.confirm_order(db, o)
    assert actions(o) == ["created", "closed", "reopened", "cancelled"]


def test_delete_blocked_when_arrivals_matched(db):
    o = new_order(db)
    arrival = Arrival(product_id=1, units=10, day=date(2026, 10, 1))
    arrival.allocations.append(Allocation(order_id=o.id, units=10))
    db.add(arrival)
    db.commit()
    with pytest.raises(svc.OrderError):
        svc.delete_order(db, o)


def test_delete_removes_order(db):
    o = new_order(db)
    svc.add_tracking(db, o, "794644790138", "", 10)
    svc.delete_order(db, o)
    assert svc.list_orders(db) == []
