"""Stock history, manual adjustments and the runway projection. Rules live in domain/; this loads rows and saves results."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now
from app.config import today as store_today
from app.domain.bundles import units_sold
from app.domain.runway import Landing, Runway, insight, level_at, project, window_insight
from app.models import Product, StockMovement
from app.services.products import ProductRow, get_settings, open_landings, product_row

KINDS = {"sale": ("Manual sale", -1), "damage": ("Damaged or lost", -1), "found": ("Found or recount", 1)}
FILTERS = {"arrivals": ("arrival",), "moves": ("reallocation",), "manual": ("sale", "adjustment")}
WINDOW = 30


class StockError(ValueError):
    """A rule the user broke; the message is shown on the page."""


def log_adjustment(db: Session, product: Product, kind: str, units: int, note: str, day: date, by: str,
                   variant: str = "") -> None:
    """`units` is a unit count, or a number of sales when a manual sale names a bundle variant."""
    if kind not in KINDS:
        raise StockError("Pick what kind of change this is.")
    if units < 1:
        raise StockError("Enter at least 1 unit.")
    if variant and kind == "sale":
        try:
            sales, units = units, units_sold(units, variant, product.bundle_map or {})
        except ValueError as e:
            raise StockError(str(e)) from None
        note = f"{note.strip()} ({sales} × {variant}, {units} units)"
    note = note.strip()
    if len(note) < 3:
        raise StockError("Say why. A short note is required.")
    if day > store_today():
        raise StockError("The date can't be in the future.")
    label, sign = KINDS[kind]
    delta = sign * units
    if product.stock + delta < 0:
        raise StockError(f"Only {product.stock} units are in stock. Enter {product.stock} or fewer.")
    product.stock += delta
    at = now() if day == store_today() else datetime.combine(day, time(12, 0))
    db.add(StockMovement(product_id=product.id, kind="sale" if kind == "sale" else "adjustment", delta=delta,
                         note=f"{label}: {note}", at=at, by=by))
    db.commit()


@dataclass
class Mv:
    m: StockMovement
    after: int  # warehouse stock right after this movement


def _all(db: Session, product: Product) -> list[StockMovement]:
    return list(db.scalars(select(StockMovement).where(StockMovement.product_id == product.id)
                           .order_by(StockMovement.at, StockMovement.id)))


def movements(db: Session, product: Product, kind: str = "") -> list[Mv]:
    """Newest first. 'Stock after' is worked back from today's count, so it always ends on the real number."""
    ms, level, after = _all(db, product), product.stock, {}
    for m in reversed(ms):
        after[m.id] = level
        level -= m.delta
    rows = [Mv(m, after[m.id]) for m in reversed(ms)]
    return [r for r in rows if r.m.kind in FILTERS[kind]] if kind in FILTERS else rows


@dataclass
class History:
    points: list[tuple[float, float]]
    markers: list[tuple[float, float, str]]  # (day, stock after, arrival | manual)
    net: int
    added: int
    removed: int

    def sentence(self, name: str, stock: int) -> tuple[str, str]:
        """(headline, quiet second half)"""
        if not self.markers and not self.net:
            return f"{name} has {stock:,} units, with no changes in the last 30 days.", ""
        way = f"up {self.net:,}" if self.net > 0 else f"down {-self.net:,}" if self.net < 0 else "unchanged"
        return (f"{name} has {stock:,} units, {way} in 30 days.",
                f"Arrivals and found units added {self.added:,}. Manual sales and losses took {self.removed:,}.")


def history(db: Session, product: Product, today: date, days: int = WINDOW) -> History:
    ms = _all(db, product)
    cur = product.stock - sum(m.delta for m in ms)
    pts: list[tuple[float, float]] = []
    marks: list[tuple[float, float, str]] = []
    net = added = removed = 0
    for m in ms:
        x = (m.at.date() - today).days
        if x < -days:
            cur += m.delta
            continue
        if not pts:
            pts.append((-days, cur))
        pts += [(x, cur), (x, cur + m.delta)]
        cur += m.delta
        net += m.delta
        added += max(m.delta, 0)
        removed += max(-m.delta, 0)
        if m.delta:
            marks.append((x, cur, "arrival" if m.kind == "arrival" else "manual"))
    if not pts:
        pts.append((-days, cur))
    pts.append((0, cur))
    return History(pts, marks, net, added, removed)


# ---- runway ----

@dataclass
class RunwayView:
    row: ProductRow
    horizon: int
    a: Runway               # current orders only
    b: Runway | None        # plus the suggested order placed today
    landings: list[Landing]
    extra: Landing | None
    insight: str
    today: date
    window: str = ""  # the empty days no new order can prevent (same number as the Stock row badge)

    @property
    def tick(self) -> int:
        return {30: 5, 60: 10}.get(self.horizon, 15)

    def series(self) -> list[tuple[str, str, list[tuple[float, float]]]]:
        out = [("Current orders only", "ser-a", list(self.a.points))]
        if self.b and self.extra:
            out.append((f"If you order {self.extra.units:,} today", "ser-b", list(self.b.points)))
        return out

    def markers(self) -> list[tuple[float, float, str, str]]:
        m = [(x.day, level_at(self.a.points, x.day), "ser-a", f"+{x.units:,}") for x in self.landings if x.day <= self.horizon]
        if self.b and self.extra and self.extra.day <= self.horizon:
            m.append((self.extra.day, level_at(self.b.points, self.extra.day), "ser-b", ""))
        return m

    def label(self) -> str:
        gap = f" Out of stock for about {round(self.a.empty_days)} days even if every order lands on time." if self.a.empty else ""
        return f"Projected stock for {self.row.product.name} over {self.horizon} days.{gap}"

    def rows(self) -> list[tuple[str, int, int | None]]:
        """(date, stock on current orders, stock with the new order) every few days, for the table view."""
        step = 5 if self.horizon == 30 else 10
        out = []
        for d in range(0, self.horizon + 1, step):
            when = "Today" if d == 0 else f"{self.today + timedelta(days=d):%b} {(self.today + timedelta(days=d)).day}"
            out.append((when, round(level_at(self.a.points, d)), round(level_at(self.b.points, d)) if self.b else None))
        return out


def runway_view(db: Session, product: Product, today: date, horizon: int = 90) -> RunwayView | None:
    """None when the product has no sales: with no burn there is no runway to draw."""
    row = product_row(db, product, get_settings(db), today)
    burn = row.forecast.adjusted_burn
    if burn <= 0:
        return None
    landings = open_landings(product, row.params.lead_time, today)
    extra = Landing(max(1, row.params.lead_time), row.forecast.suggested_order, "New order") \
        if row.forecast.suggested_order > 0 else None
    a = project(product.stock, burn, landings, horizon)
    b = project(product.stock, burn, landings, horizon, extra) if extra else None
    return RunwayView(row, horizon, a, b, landings, extra, insight(a, extra.day if extra else None, horizon), today,
                      window_insight(row.gap, max(1, row.params.lead_time)))
