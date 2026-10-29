"""Warehouse arrivals: record, match to open orders, fix a match by hand. The matching rules live in domain/matching.py."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now
from app.config import today as store_today
from app.domain.matching import Match, Open, SplitError, check_split, fifo
from app.models import Allocation, Arrival, Order, Product, StockMovement
from app.services.orders import add_event, is_open


class ArrivalError(ValueError):
    """A rule the user broke; the message is shown on the page."""


@dataclass
class Seg:
    kind: str   # order | free | none  (matched to an order, "not from an order", unmatched)
    label: str
    units: int


@dataclass
class ArrivalRow:
    arrival: Arrival
    segs: list[Seg]

    @property
    def unmatched(self) -> int:
        return sum(s.units for s in self.segs if s.kind == "none")

    @property
    def parts(self) -> list[tuple[str, int]]:
        return [(s.kind, s.units) for s in self.segs]

    @property
    def text(self) -> str:
        name = {"free": "Not from an order", "none": "Unmatched"}
        return " · ".join(f"{s.label if s.kind == 'order' else name[s.kind]} {s.units}" for s in self.segs)


def assigned(a: Arrival) -> int:
    return sum(x.units for x in a.allocations)


def received_by_others(o: Order, arrival_id: int | None) -> int:
    return sum(x.units for x in o.allocations if x.arrival_id != arrival_id)


def open_orders(db: Session, product_id: int, arrival_id: int | None = None) -> list[Open]:
    """Open orders of a product that still have room, oldest first. `arrival_id` ignores that arrival's own units."""
    out = []
    for o in db.scalars(select(Order).where(Order.product_id == product_id)):
        room = o.units - received_by_others(o, arrival_id)
        if is_open(o) and room > 0:
            out.append(Open(o.id, o.name, o.created_at, room))
    return sorted(out, key=lambda x: (x.placed, x.order_id))


def preview(db: Session, product: Product, units: int) -> tuple[Match, list[Open], dict[int, Order]]:
    opens = open_orders(db, product.id)
    return fifo(max(units, 0), opens), opens, {o.id: o for o in db.scalars(select(Order).where(Order.product_id == product.id))}


def _note(parts: list[tuple[str, int]], free: int, unmatched: int) -> str:
    bits = [f"{n} ({u})" for n, u in parts]
    if free:
        bits.append(f"not from an order ({free})")
    text = "matched to " + ", ".join(bits) if bits else "not matched to an order"
    return text + (f", {unmatched} unmatched" if unmatched and bits else "")


def record_arrival(db: Session, product: Product, units: int, day: date, note: str, by: str) -> Arrival:
    if units < 1:
        raise ArrivalError("Enter at least 1 unit.")
    if day > store_today():
        raise ArrivalError("The arrival date can't be in the future.")
    m = fifo(units, open_orders(db, product.id))
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.product_id == product.id))}
    arr = Arrival(product_id=product.id, units=units, day=day, note=note.strip(), by=by)
    for order_id, u in m.parts:
        arr.allocations.append(Allocation(order_id=order_id, units=u))
    db.add(arr)
    product.stock += units
    named = [(orders[i].name, u) for i, u in m.parts]
    db.add(StockMovement(product_id=product.id, kind="arrival", delta=units, at=now(), by=by,
                         note="Arrival " + _note(named, 0, m.unmatched)))
    for order_id, u in m.parts:
        add_event(orders[order_id], "arrival matched", f"{u} units", by)
    db.commit()
    db.expire_all()
    return arr


def split_parts(db: Session, arrival: Arrival) -> dict[int | None, int]:
    parts: dict[int | None, int] = {}
    for x in arrival.allocations:
        parts[x.order_id] = parts.get(x.order_id, 0) + x.units
    return parts


def editor_orders(db: Session, arrival: Arrival) -> list[tuple[Order, int]]:
    """Orders the arrival could be split across, oldest first, with how many units each has room for."""
    ids = {o.order_id for o in open_orders(db, arrival.product_id, arrival.id)} | {x.order_id for x in arrival.allocations if x.order_id}
    orders = [o for o in db.scalars(select(Order).where(Order.id.in_(ids))) ] if ids else []
    return [(o, o.units - received_by_others(o, arrival.id)) for o in sorted(orders, key=lambda o: (o.created_at, o.id))]


def edit_match(db: Session, arrival: Arrival, parts: dict[int | None, int], by: str) -> None:
    """Replace the whole split. Every unit must be assigned to an order or to "not from an order"."""
    editor = editor_orders(db, arrival)
    capacity = {o.id: room for o, room in editor}
    try:
        check_split(arrival.units, {k: v for k, v in parts.items() if v}, capacity)
    except SplitError as e:
        raise ArrivalError(str(e)) from None
    before = split_parts(db, arrival)
    names = {o.id: o for o, _ in editor}
    arrival.allocations.clear()
    db.flush()
    for k, v in parts.items():
        if v:
            arrival.allocations.append(Allocation(order_id=k, units=v))
    arrival.edited = True
    after = {k: v for k, v in parts.items() if v}
    for order_id in {k for k in (*before, *after) if k}:
        was, now_ = before.get(order_id, 0), after.get(order_id, 0)
        if was != now_:
            add_event(names[order_id], "arrival match changed", f"{was} → {now_} units", by)
    named = [(names[k].name, v) for k, v in after.items() if k]
    db.add(StockMovement(product_id=arrival.product_id, kind="reallocation", delta=0, at=now(), by=by,
                         note=f"Arrival of {arrival.day:%b} {arrival.day.day} " + _note(named, after.get(None, 0), 0)))
    db.commit()
    db.expire_all()


def mark_not_from_order(db: Session, arrival: Arrival, by: str) -> None:
    """The units that matched nothing were counted in but belong to no order: record that decision."""
    parts = split_parts(db, arrival)
    left = arrival.units - sum(parts.values())
    if left <= 0:
        return
    parts[None] = parts.get(None, 0) + left
    edit_match(db, arrival, parts, by)


# ---- lists ----

def row_of(a: Arrival, orders: dict[int, Order]) -> ArrivalRow:
    segs = [Seg("order", orders[x.order_id].name, x.units) for x in a.allocations if x.order_id]
    segs += [Seg("free", "", x.units) for x in a.allocations if not x.order_id]
    left = a.units - assigned(a)
    if left > 0:
        segs.append(Seg("none", "", left))
    return ArrivalRow(a, segs)


def arrival_rows(db: Session, status: str = "") -> list[ArrivalRow]:
    orders = {o.id: o for o in db.scalars(select(Order))}
    rows = [row_of(a, orders) for a in db.scalars(select(Arrival).order_by(Arrival.day.desc(), Arrival.id.desc()))]
    if status == "unmatched":
        rows = [r for r in rows if r.unmatched]
    elif status == "matched":
        rows = [r for r in rows if not r.unmatched]
    return rows


def why_unmatched(db: Session, a: Arrival) -> tuple[str, bool]:
    """(why nothing took these units, whether an open order could still take them). An order that has fully arrived,
    or was closed or cancelled, has nothing left to come, so it is not open for matching."""
    if open_orders(db, a.product_id, a.id):
        return "Open orders could take these. Match them, or say they are not from an order.", True
    return "Nothing is on order for this product.", False
