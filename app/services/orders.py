from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now
from app.domain.carriers import clean, detect_carrier
from app.domain.orders import Stages, stages, tracking_fits
from app.models import Order, OrderEvent, Product, Tracking

STATUSES = ["placed", "in production", "on the way", "partial", "received", "closed", "cancelled"]


class OrderError(ValueError):
    """A rule the user broke; the message is shown on the page."""


@dataclass
class OrderRow:
    order: Order
    stages: Stages


def order_stages(o: Order) -> Stages:
    return stages(
        o.units,
        marked_confirmed=o.confirmed_at is not None,
        tracking_units=sum(t.units for t in o.trackings),
        arrived=sum(a.units for a in o.allocations),
        closed=o.closed,
        cancelled=o.cancelled,
    )


def is_open(o: Order) -> bool:
    return not (o.closed or o.cancelled)


def tracked_units(o: Order) -> int:
    return sum(t.units for t in o.trackings)


def list_orders(db: Session, product_id: int | None = None, status: str | None = None) -> list[OrderRow]:
    q = select(Order).order_by(Order.created_at.desc())
    if product_id:
        q = q.where(Order.product_id == product_id)
    rows = [OrderRow(o, order_stages(o)) for o in db.scalars(q)]
    return [r for r in rows if not status or r.stages.status == status]


def add_event(o: Order, action: str, detail: str = "", by: str = "staff") -> None:
    o.events.append(OrderEvent(action=action, detail=detail, by=by, at=now()))


def next_order_name(db: Session, product: Product) -> str:
    """Product code + next number, e.g. GIZ-003."""
    names = db.scalars(select(Order.name).where(Order.product_id == product.id)).all()
    last = max((int(n.rsplit("-", 1)[1]) for n in names), default=0)
    return f"{product.code}-{last + 1:03d}"


def create_order(db: Session, product: Product, supplier_id: int, units: int, notes: str, by: str = "staff") -> Order:
    o = Order(name=next_order_name(db, product), product_id=product.id, supplier_id=supplier_id,
              units=units, notes=notes.strip(), created_at=now())
    add_event(o, "created", f"{units} units" + (f" · {o.notes}" if o.notes else ""), by)
    db.add(o)
    db.commit()
    return o


def confirm_order(db: Session, o: Order, by: str = "staff") -> None:
    if not is_open(o):
        raise OrderError("Reopen the order before confirming it.")
    if o.confirmed_at is None:
        o.confirmed_at = now()
        add_event(o, "confirmed", "", by)
        db.commit()


def add_tracking(db: Session, o: Order, number: str, carrier: str, units: int, by: str = "staff") -> None:
    if not is_open(o):
        raise OrderError("Reopen the order before adding tracking.")
    number = clean(number)
    if not number:
        raise OrderError("Enter a tracking number.")
    if not tracking_fits(o.units, tracked_units(o), units):
        room = o.units - tracked_units(o)
        raise OrderError(f"Tracking units can't go over the order. Only {room} units are left to track.")
    carrier = carrier or detect_carrier(number)
    o.trackings.append(Tracking(number=number, carrier=carrier, units=units, shipped_at=now()))
    add_event(o, "tracking added", f"{number} × {units}" + (f" ({carrier})" if carrier else ""), by)
    db.commit()


def remove_tracking(db: Session, o: Order, tracking_id: int, by: str = "staff") -> None:
    t = next((t for t in o.trackings if t.id == tracking_id), None)
    if t is None:
        raise OrderError("Tracking number not found.")
    o.trackings.remove(t)
    add_event(o, "tracking removed", f"{t.number} × {t.units}", by)
    db.commit()


def edit_order(db: Session, o: Order, units: int, notes: str, supplier_id: int, by: str = "staff") -> None:
    floor = max(tracked_units(o), sum(a.units for a in o.allocations))
    if units < max(1, floor):
        raise OrderError(f"Units can't go below {max(1, floor)} (already on tracking or arrived).")
    changes = []
    if units != o.units:
        changes.append(f"units {o.units} → {units}")
        o.units = units
    if supplier_id != o.supplier_id:
        changes.append("supplier changed")
        o.supplier_id = supplier_id
    if notes.strip() != o.notes:
        changes.append("notes changed")
        o.notes = notes.strip()
    if changes:
        add_event(o, "edited", ", ".join(changes), by)
        db.commit()


def cancel_order(db: Session, o: Order, by: str = "staff") -> None:
    if o.cancelled:
        return
    o.cancelled = True
    add_event(o, "cancelled", "", by)
    db.commit()


def close_order(db: Session, o: Order, by: str = "staff") -> None:
    """'No more coming': the units that never arrived stop counting as ordered."""
    if o.closed or o.cancelled:
        return
    o.closed = True
    add_event(o, "closed", "no more coming", by)
    db.commit()


def reopen_order(db: Session, o: Order, by: str = "staff") -> None:
    if is_open(o):
        return
    o.closed = o.cancelled = False
    add_event(o, "reopened", "", by)
    db.commit()


def delete_order(db: Session, o: Order) -> None:
    if o.allocations:
        raise OrderError("This order has arrivals matched to it, so it can't be deleted. Cancel or close it instead.")
    db.delete(o)
    db.commit()
