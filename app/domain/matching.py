"""Arrival matching (SOP section 3). Pure functions: oldest open order first, spilling into the next."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Open:
    order_id: int
    name: str
    placed: datetime
    remaining: int  # units still to come on this order


@dataclass(frozen=True)
class Match:
    parts: tuple[tuple[int, int], ...]  # (order_id, units), oldest order first
    unmatched: int                      # units no open order could take


class SplitError(ValueError):
    """A hand-made split that breaks a rule; the message is shown on the page."""


def fifo(units: int, open_orders: list[Open]) -> Match:
    """Fill the oldest open order first, then spill into the next. Units left over are unmatched, not lost."""
    left, parts = units, []
    for o in sorted(open_orders, key=lambda o: (o.placed, o.order_id)):
        take = min(left, max(o.remaining, 0))
        if take > 0:
            parts.append((o.order_id, take))
            left -= take
    return Match(tuple(parts), left)


def check_split(total: int, parts: dict[int | None, int], capacity: dict[int, int]) -> None:
    """A hand-made split. Key None is "not from an order". Every unit of the arrival must be assigned, and an order
    cannot take more than it still has room for."""
    if any(u < 0 for u in parts.values()):
        raise SplitError("Units can't be negative.")
    assigned = sum(parts.values())
    if assigned != total:
        diff = assigned - total
        raise SplitError(f"The assigned units add up to {assigned}, but {total} arrived. "
                         + (f"Remove {diff} units to save." if diff > 0 else f"Assign {-diff} more units to save."))
    for order_id, units in parts.items():
        if order_id is not None and units > capacity.get(order_id, 0):
            raise SplitError(f"That order only has room for {capacity.get(order_id, 0)} more units.")
