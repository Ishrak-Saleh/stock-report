"""The Chase list and the Outbox. The three rules are in domain/chase.py; this adds the repeat limit (AlertLog) and
saves messages in test mode, so nothing is ever delivered."""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SENDER_NAME, now
from app.domain import messages
from app.domain.chase import REPEAT_EVERY, days_until_again, due_again
from app.models import AlertLog, Order, Outbox
from app.services import orders as order_svc
from app.services.orders import OrderRow
from app.services.products import get_settings, report

EMAIL = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")
KINDS = {"follow-up": "Follow-up", "alert": "Reorder alert", "test": "Test"}


class ChaseError(ValueError):
    """A rule the user broke; the message is shown on the page."""


@dataclass
class ChaseRow:
    row: OrderRow
    last_sent: datetime | None
    next_on: date | None  # when it can be sent again, if it was sent recently
    days_left: int = 0    # days of the wait still to go

    @property
    def due(self) -> bool:
        return self.next_on is None


def chase_list(db: Session, today: date, risk: dict | None = None) -> tuple[list[ChaseRow], list[ChaseRow]]:
    """(due now, chased recently). The most overdue order is first in each. With `risk` (see products.gap_risk), orders
    whose product runs dry before they land come first."""
    sent = {(a.order_id, a.kind): a.last_sent_at for a in db.scalars(select(AlertLog))}
    due, quiet = [], []
    for r in order_svc.list_orders(db, only_chase=True, today=today, risk=risk):
        last = sent.get((r.order.id, r.chase.kind))
        ago = None if last is None else (today - last.date()).days
        if due_again(ago):
            due.append(ChaseRow(r, last, None))
        else:
            quiet.append(ChaseRow(r, last, last.date() + timedelta(days=REPEAT_EVERY), days_until_again(ago)))
    return due, quiet


def due_count(db: Session, today: date) -> int:
    return len(chase_list(db, today)[0])


def follow_up_text(o: Order, r: OrderRow) -> tuple[str, str]:
    tracked = order_svc.tracked_units(o)
    body = messages.follow_up(
        r.chase, supplier=o.supplier.name, order=o.name, product=o.product.name, units=o.units,
        untracked=o.units - tracked, tracking_number=o.trackings[0].number if o.trackings else "",
        created_days=r.age, sender=SENDER_NAME)
    return messages.follow_up_subject(r.chase, o.name), body


def add_follow_up(db: Session, o: Order, kind: str, today: date, by: str) -> Outbox:
    r = order_svc.build_row(o, today)
    if not r.chase or r.chase.kind != kind:
        raise ChaseError(f"{o.name} doesn't need that message right now.")
    log = db.scalars(select(AlertLog).where(AlertLog.order_id == o.id, AlertLog.kind == kind)).first()
    if log and not due_again((today - log.last_sent_at.date()).days):
        raise ChaseError(f"{o.name} was chased on {log.last_sent_at:%b} {log.last_sent_at.day}. "
                         f"It can be sent again on {(log.last_sent_at.date() + timedelta(days=REPEAT_EVERY)):%b %d}.")
    subject, body = follow_up_text(o, r)
    msg = Outbox(to=o.supplier.email, subject=subject, body=body, at=now(), kind="follow-up", order_id=o.id,
                 follow_up_kind=kind)
    db.add(msg)
    if log:
        log.last_sent_at = now()
    else:
        db.add(AlertLog(order_id=o.id, kind=kind, last_sent_at=now()))
    order_svc.add_event(o, "follow-up saved", subject, by)
    db.commit()
    return msg


def waits_for(db: Session, messages: list[Outbox], today: date) -> dict[int, tuple[int, date]]:
    """For each follow-up whose 2-day wait is still running: message id -> (days left, the day it may be sent again).
    One query for the whole list."""
    sent = {(a.order_id, a.kind): a.last_sent_at.date() for a in db.scalars(select(AlertLog))}
    out = {}
    for m in messages:
        if m.kind != "follow-up" or m.order_id is None or (m.order_id, m.follow_up_kind) not in sent:
            continue
        day = sent[(m.order_id, m.follow_up_kind)]
        left = days_until_again((today - day).days)
        if left:
            out[m.id] = (left, day + timedelta(days=REPEAT_EVERY))
    return out


def wait_for(db: Session, m: Outbox, today: date) -> tuple[int, date] | None:
    """(days left, the day it may be sent again) for one follow-up whose 2-day wait is still running, else None."""
    return waits_for(db, [m], today).get(m.id)


def delete_message(db: Session, m: Outbox, by: str) -> None:
    """Remove a saved message. For a follow-up, the 2-day wait goes back to what the newest message left in the
    Outbox says, or is cleared when none is left, so deleting an older duplicate changes nothing."""
    order, kind = (db.get(Order, m.order_id) if m.order_id else None), m.follow_up_kind
    db.delete(m)
    db.flush()
    if order and kind:
        newest = db.scalars(select(Outbox).where(Outbox.order_id == order.id, Outbox.follow_up_kind == kind)
                            .order_by(Outbox.at.desc(), Outbox.id.desc())).first()
        log = db.scalars(select(AlertLog).where(AlertLog.order_id == order.id, AlertLog.kind == kind)).first()
        if log and newest:
            log.last_sent_at = newest.at
        elif log:
            db.delete(log)
        order_svc.add_event(order, "follow-up removed", m.subject, by)
    db.commit()


def add_all_due(db: Session, today: date, by: str) -> int:
    due, _ = chase_list(db, today)
    for c in due:
        add_follow_up(db, c.row.order, c.row.chase.kind, today, by)
    return len(due)


# ---- Outbox and reorder alerts ----

def outbox(db: Session, kind: str = "") -> list[Outbox]:
    q = select(Outbox).order_by(Outbox.at.desc(), Outbox.id.desc())
    if kind in KINDS:
        q = q.where(Outbox.kind == kind)
    return list(db.scalars(q))


def recipients(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,\n;]", text) if a.strip()]


def check_recipients(text: str) -> list[str]:
    addrs = recipients(text)
    for a in addrs:
        if not EMAIL.match(a):
            raise ChaseError(f"{a} is not an email address.")
    return addrs


def add_reorder_alert(db: Session, today: date, test: bool) -> int:
    """Saves the reorder alert for every recipient. A test is marked as one. Returns how many were saved."""
    s = get_settings(db)
    if not test and not s.alerts_enabled:
        raise ChaseError("Reorder alerts are off. Turn them on first, or send a test.")
    addrs = check_recipients(s.recipients)
    if not addrs:
        raise ChaseError("Add at least one email address to send to.")
    items = [(r.product.name, r.forecast.days_with_ordered, r.forecast.suggested_order)
             for r in report(db, today) if r.forecast.reorder_now]
    subject, body = messages.reorder_alert(items, SENDER_NAME)
    for a in addrs:
        db.add(Outbox(to=a, subject=("Test: " if test else "") + subject, body=body, at=now(),
                      kind="test" if test else "alert"))
    db.commit()
    return len(addrs)
