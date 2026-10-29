"""Deterministic fake data. One product per flag state so every dashboard badge is visible."""
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now, today
from app.models import (Allocation, Arrival, DailySale, Order, OrderEvent, Product, Settings, StockMovement,
                        Supplier, Tracking)

# code, name, base/day, last-3-days multiplier, stock, bundle map
PRODUCTS = [
    ("KEY", "Keyboard", 5, 1.0, 320, {}),            # healthy
    ("PHN", "Phone", 8, 1.0, 0, {}),                  # out of stock
    ("MOU", "Mouse", 6, 1.5, 100, {"Buy 2 Get 2": 4}),  # urgent, speeding up, ordered not enough
    ("MON", "Monitor", 3, 0.7, 120, {}),             # watch, slowing, reorder now with nothing ordered
    ("HDP", "Headphones", 4, 1.0, 900, {}),            # plenty
    ("CBL", "Cable", 0, 1.0, 50, {}),             # no sales -> blank days
]


def seed(db: Session) -> None:
    if db.scalars(select(Product)).first():
        return
    rng = random.Random(42)
    t, n = today(), now()
    db.add(Settings(data_updated_at=n))
    acme = Supplier(name="Acme Manufacturing", email="orders@acme.example.com")
    nova = Supplier(name="Nova Imports", email="sales@nova.example.com")
    db.add_all([acme, nova])

    prods = {}
    for code, name, base, mult, stock, bundles in PRODUCTS:
        p = Product(code=code, name=name, stock=stock, unshipped=rng.randint(0, 12) if base else 0,
                    identifiers=[f"{code}-001", name], bundle_map=bundles)
        for i in range(1, 41):  # 40 days of sales ending yesterday
            if base:
                level = base * (mult if i <= 3 else 1)
                p.sales.append(DailySale(day=t - timedelta(days=i), units=max(0, round(level + rng.uniform(-1, 1)))))
        db.add(p)
        prods[code] = p
    db.flush()

    def order(code, num, supplier, units, days_ago, confirmed_days_ago=None, tracking=(), notes=""):
        o = Order(name=f"{code}-{num:03d}", product_id=prods[code].id, supplier_id=supplier.id, units=units,
                  notes=notes, created_at=n - timedelta(days=days_ago),
                  confirmed_at=None if confirmed_days_ago is None else n - timedelta(days=confirmed_days_ago))
        o.events.append(OrderEvent(action="created", detail=f"{units} units", by="seed", at=o.created_at))
        if o.confirmed_at:
            o.events.append(OrderEvent(action="confirmed", by=supplier.name, at=o.confirmed_at))
        for num_, u, ship_days_ago, carrier in tracking:
            o.trackings.append(Tracking(number=num_, units=u, carrier=carrier, shipped_at=n - timedelta(days=ship_days_ago)))
            o.events.append(OrderEvent(action="tracking added", detail=f"{num_} x {u}", by=supplier.name,
                                       at=n - timedelta(days=ship_days_ago)))
        db.add(o)
        return o

    order("MOU", 1, acme, 120, 30, 28, [("1Z999AA10123456784", 120, 14, "UPS")])       # on the way > 10 days
    order("MOU", 2, acme, 150, 3)                                                       # unconfirmed, chase
    order("KEY", 1, nova, 200, 20, 18)                                                  # confirmed, no tracking
    partial = order("HDP", 1, nova, 400, 40, 38, [("794644790138", 400, 25, "FedEx")])  # partially arrived
    order("PHN", 1, acme, 300, 12, 11, notes="Rush if possible")                        # in production, 11 days
    done = order("MON", 1, nova, 100, 60, 58, [("9400111899223344556677", 100, 40, "USPS")])
    db.flush()

    # HDP-001 partially arrived (150 of 400); MON-001 fully received.
    for prod, ordr, units, days_ago in ((prods["HDP"], partial, 150, 5), (prods["MON"], done, 100, 20)):
        arr = Arrival(product_id=prod.id, units=units, day=t - timedelta(days=days_ago), note="Dock receipt", by="seed")
        arr.allocations.append(Allocation(order_id=ordr.id, units=units))
        db.add(arr)
        db.add(StockMovement(product_id=prod.id, kind="arrival", delta=units, note=f"Arrival matched to {ordr.name}",
                             at=n - timedelta(days=days_ago), by="seed"))
        ordr.events.append(OrderEvent(action="arrival matched", detail=f"{units} units", by="seed",
                                      at=n - timedelta(days=days_ago)))
    # Monitor has nothing on order, so this delivery matches no order and waits on the Arrivals page.
    db.add(Arrival(product_id=prods["MON"].id, units=60, day=t - timedelta(days=1), note="Extra pallet, no paperwork", by="seed"))
    db.add(StockMovement(product_id=prods["MON"].id, kind="arrival", delta=60, note="Arrival not matched to an order",
                         at=n - timedelta(days=1), by="seed"))
    db.add(StockMovement(product_id=prods["MOU"].id, kind="adjustment", delta=-6,
                         note="Count correction: shelf count was 6 lower", at=n - timedelta(days=17), by="seed"))
    db.commit()
