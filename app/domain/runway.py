"""Stock projection for the runway chart. Pure functions: stock falls at the adjusted burn and jumps when an order lands.
Landing dates are an assumption (order date plus lead time), because the SOP has no expected-date field."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

HORIZONS = (30, 60, 90)


@dataclass(frozen=True)
class Landing:
    day: int    # days from today, 1 or more
    units: int
    name: str


@dataclass(frozen=True)
class Runway:
    points: tuple[tuple[float, float], ...]  # (day, units), a step line
    empty: tuple[tuple[float, float], ...]   # (from day, to day) spans with no stock

    @property
    def empty_days(self) -> float:
        return sum(b - a for a, b in self.empty)


def landing_day(expected: date, today: date) -> int:
    """Days from today until an order is expected. An order already overdue is assumed to land tomorrow."""
    return max(1, (expected - today).days)


def project(stock: int, burn: float, landings: list[Landing], horizon: int, extra: Landing | None = None) -> Runway:
    adds: dict[int, int] = defaultdict(int)
    for lnd in [*landings, *([extra] if extra else [])]:
        if lnd.day <= horizon:
            adds[lnd.day] += lnd.units
    level = float(stock)
    pts: list[tuple[float, float]] = [(0.0, level)]
    empty: list[tuple[float, float]] = []
    gap_from: float | None = 0.0 if level <= 0 else None
    for d in range(1, horizon + 1):
        after = level - burn
        if after <= 0:
            if level > 0:  # it runs out part-way through this day
                gap_from = d - 1 + (level / burn if burn > 0 else 0)
                pts.append((gap_from, 0.0))
            level = 0.0
        else:
            level = after
        pts.append((float(d), level))
        if adds.get(d):
            if gap_from is not None:
                empty.append((gap_from, float(d)))
                gap_from = None
            level += adds[d]
            pts.append((float(d), level))
    if gap_from is not None:
        empty.append((gap_from, float(horizon)))
    return Runway(tuple(pts), tuple(empty))


def insight(a: Runway, lands_on: int | None, horizon: int) -> str:
    """The one sentence under the chart: does stock run out even if every order lands on time?"""
    if not a.empty:
        return f"Stock lasts the next {horizon} days if every order lands on time."
    days = round(a.empty_days)
    text = (f"Stock is empty for about {days} {'day' if days == 1 else 'days'} in the next {horizon}, "
            f"starting on day {int(a.empty[0][0])}, even if every order lands on time.")
    if lands_on and a.empty[0][0] < lands_on:
        text += f" An order placed today lands on day {lands_on}, so it cannot fill the gap before then. Chase what is already ordered."
    return text


def level_at(points: tuple[tuple[float, float], ...], day: float) -> float:
    """The stock level on a given day (the last step at or before it)."""
    level = points[0][1]
    for x, y in points:
        if x <= day:
            level = y
        else:
            break
    return level
