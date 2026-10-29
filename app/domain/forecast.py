"""Section 4 forecast rules. Pure functions: no DB, no HTTP, `today` is injected."""
from dataclasses import dataclass
from datetime import date, timedelta
from math import floor

URGENT_DAYS = 21
WATCH_DAYS = 45


@dataclass(frozen=True)
class Params:
    lead_time: int = 45
    safety_days: int = 14
    target_days: int = 60


@dataclass(frozen=True)
class Forecast:
    sold_7: int
    daily_burn: float
    trend: float
    adjusted_burn: float
    days_of_stock: float | None
    days_with_ordered: float | None
    sells_out_on: date | None
    reorder_by: date | None
    suggested_order: int
    out_of_stock: bool
    reorder_now: bool
    ordered_not_enough: bool
    low: str | None  # "urgent" | "watch" | None


def _window(daily: dict[date, int], today: date, start: int, end: int) -> int:
    """Units sold on days today-start .. today-end (inclusive). Today itself is partial, so excluded."""
    return sum(daily.get(today - timedelta(days=i), 0) for i in range(end, start + 1))


def adjusted_burn(daily: dict[date, int], today: date) -> tuple[int, float, float, float]:
    last3 = _window(daily, today, 3, 1)
    prior4 = _window(daily, today, 7, 4)
    sold_7 = last3 + prior4
    burn = sold_7 / 7
    trend = 1.0 if prior4 == 0 else min(2.0, max(0.5, (last3 / 3) / (prior4 / 4)))
    return sold_7, burn, trend, round(burn * trend, 1)


def days_of(units: float, burn: float) -> float | None:
    return None if burn <= 0 else units / burn


def try_order(stock: int, ordered: int, extra: int, burn: float) -> float | None:
    return days_of(stock + ordered + extra, burn)


def compute(daily: dict[date, int], stock: int, ordered: int, today: date, p: Params) -> Forecast:
    sold_7, burn, trend, adj = adjusted_burn(daily, today)
    days = days_of(stock, adj)
    days_all = days_of(stock + ordered, adj)
    buffer = p.lead_time + p.safety_days
    reorder_now = days_all is not None and days_all < buffer
    low = None
    if days is not None:
        low = "urgent" if days < URGENT_DAYS else "watch" if days < WATCH_DAYS else None
    return Forecast(
        sold_7=sold_7,
        daily_burn=burn,
        trend=trend,
        adjusted_burn=adj,
        days_of_stock=days,
        days_with_ordered=days_all,
        sells_out_on=None if days is None else today + timedelta(days=floor(days)),
        reorder_by=None if days is None else today + timedelta(days=floor(days - buffer)),
        suggested_order=max(0, round((p.target_days + p.lead_time) * adj - stock)),
        out_of_stock=stock == 0,
        reorder_now=reorder_now,
        ordered_not_enough=reorder_now and ordered > 0,
        low=low,
    )
