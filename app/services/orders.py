from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import now
from app.config import today as store_today
from app.domain.carriers import clean, detect_carrier
from app.domain.chase import Chase, chase_of
from app.domain.messages import chase_step, quiet_step
from app.domain.orders import Stages, expected_arrival, stages, tracking_fits
from app.domain.runway import Runway, empty_before, landing_day
from app.models import AlertLog, Order, OrderEvent, Outbox, Product, Tracking

STATUSES = ["placed", "in production", "on the way", "partial", "received", "closed", "cancelled"]


class OrderError(ValueError):
    """A rule the user broke; the message is shown on the page."""


DONE = ("received", "closed", "cancelled")


@dataclass
class OrderRow:
    order: Order
    stages: Stages
    chase: Chase | None
    age: int  # days since it was placed
    empty_before: int = 0  # empty-shelf days that open up before this order lands (0 unless list_orders was given `risk`)

    @property
    def attention(self) -> int:
        """Rank key: the most overdue first, waiting orders next, finished orders last."""
        return -2 if self.stages.status in DONE else (self.chase.over if self.chase else -1)

    @property
    def step(self) -> tuple[str, str, str]:
        """(tone, what to do, why)"""
        if self.chase:
            what, why = chase_step(self.chase, self.order.supplier.name)
            return ("serious" if self.chase.over >= 8 else "warn"), what, why
        return quiet_step(self.stages.status)


def chase_for(o: Order, st: Stages, today: date) -> Chase | None:
    shipped = [(today - t.shipped_at.date()).days for t in o.trackings if t.shipped_at]
    return chase_of(
        is_open=is_open(o), remaining=o.units - st.arrived, confirmed=st.confirmed,
        created_days=(today - o.created_at.date()).days,
        confirmed_days=None if o.confirmed_at is None else (today - o.confirmed_at.date()).days,
        untracked=o.units - tracked_units(o), on_the_way=st.on_the_way, oldest_shipped_days=max(shipped, default=0))


def build_row(o: Order, today: date) -> OrderRow:
    st = order_stages(o)
    return OrderRow(o, st, chase_for(o, st, today), (today - o.created_at.date()).days)


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


def shelf_gap(o: Order, risk: dict[int, tuple[Runway, int]], today: date) -> int:
    """Empty days that open up before this order lands, from its product's stock projection. 0 for an order that is
    finished or whose product has no sales."""
    if o.product_id not in risk or not is_open(o) or order_stages(o).to_come <= 0:
        return 0
    runway, lead_time = risk[o.product_id]
    return empty_before(runway, landing_day(expected_arrival(o.created_at.date(), lead_time), today))


def list_orders(db: Session, product_id: int | None = None, status: str | None = None, only_chase: bool = False,
                today: date | None = None, risk: dict[int, tuple[Runway, int]] | None = None) -> list[OrderRow]:
    """Orders that need attention first (most overdue on top), finished orders last. A supplier session only
    ever sees its own orders, because the database session filters them (app/tenancy.py). With `risk` (staff only,
    from products.gap_risk), orders whose product runs dry before they land come first, most empty days on top."""
    today = today or store_today()
    q = select(Order).options(selectinload(Order.trackings), selectinload(Order.allocations), joinedload(Order.product), joinedload(Order.supplier))
    if product_id:
        q = q.where(Order.product_id == product_id)
    rows = [build_row(o, today) for o in db.scalars(q)]
    rows = [r for r in rows if (not status or r.stages.status == status) and (not only_chase or r.chase)]
    if risk:
        for r in rows:
            r.empty_before = shelf_gap(r.order, risk, today)
    return sorted(rows, key=lambda r: (-r.empty_before, -r.attention, -r.age))


def orders_headline(rows: list[OrderRow]) -> str:
    n = sum(1 for r in rows if r.chase)
    text = "No order needs a message." if not n else f"{n} order{'s' if n != 1 else ''} need{'s' if n == 1 else ''} a message."
    done = [r.order.name for r in rows if r.stages.status == "received"]
    return text + (f" {', '.join(done)} {'is' if len(done) == 1 else 'are'} complete." if done else "")


def supplier_headline(rows: list[OrderRow], supplier: str) -> tuple[str, str]:
    """(sentence, quiet second half) for a supplier's own orders page."""
    open_rows = [r for r in rows if r.stages.status not in DONE]
    to_confirm = [r.order.name for r in open_rows if not r.stages.confirmed]
    to_track = [r.order.name for r in open_rows if r.stages.confirmed and tracked_units(r.order) < r.order.units
                and r.stages.arrived < r.order.units]
    n = len(open_rows)
    text = f"{n} order{'s' if n != 1 else ''} from {supplier} {'is' if n == 1 else 'are'} open."
    bits = ([f"{len(to_confirm)} need{'s' if len(to_confirm) == 1 else ''} confirming"] if to_confirm else []) + \
           ([f"{len(to_track)} need{'s' if len(to_track) == 1 else ''} tracking"] if to_track else [])
    return text, (" and ".join(bits) + ".").capitalize() if bits else "Nothing is waiting on you."


def waiting_on_supplier(r: OrderRow) -> tuple[str, str, str]:
    """(tone, what we wait for, icon) for the supplier's list."""
    o, st = r.order, r.stages
    if st.status in DONE:
        return "plain", {"received": "Nothing, all arrived", "closed": "Nothing, closed", "cancelled": "Nothing, cancelled"}[st.status], "circle-check"
    if not st.confirmed:
        return "warn", "Your confirmation", "clock"
    left = o.units - tracked_units(o)
    if left > 0 and st.arrived < o.units:
        return "warn", f"Tracking for {min(left, o.units - st.arrived):,} units", "package"
    return "good", "Nothing, all tracked", "circle-check"


@dataclass
class Step:
    label: str
    done: bool
    current: bool
    sub: str
    icon: str


def _d(d: date) -> str:
    return f"{d:%b} {d.day}"


def order_steps(o: Order, st: Stages) -> list[Step]:
    tracked = tracked_units(o)
    raw = [
        ("Placed", True, _d(o.created_at.date()), "clock"),
        ("Confirmed", st.confirmed, (_d(o.confirmed_at.date()) if o.confirmed_at else "has tracking") if st.confirmed else "waiting", "package"),
        ("Shipped", tracked > 0, f"{tracked:,} of {o.units:,} units" if tracked else "no tracking yet", "truck"),
        ("Arrived", o.units - st.arrived == 0, f"{st.arrived:,} of {o.units:,} units" if st.arrived else "nothing yet", "circle-check"),
    ]
    first_open = next((i for i, r in enumerate(raw) if not r[1]), -1)
    return [Step(label, done, is_open(o) and i == first_open, sub, icon) for i, (label, done, sub, icon) in enumerate(raw)]


def add_event(o: Order, action: str, detail: str = "", by: str = "staff") -> None:
    o.events.append(OrderEvent(action=action, detail=detail, by=by, at=now()))


def next_order_name(db: Session, product: Product) -> str:
    """Product code + next number, e.g. MOU-003."""
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
    for log in db.scalars(select(AlertLog).where(AlertLog.order_id == o.id)):
        db.delete(log)
    for m in db.scalars(select(Outbox).where(Outbox.order_id == o.id)):
        m.order_id = None  # the saved message stays in the Outbox as a record, it just no longer points at an order
    db.delete(o)
    db.commit()
