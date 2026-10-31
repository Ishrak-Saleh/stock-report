"""Sales import (SOP section 3: the identifiers match sales to products). Pure functions: no database, `today` is passed in.

A sales file has three columns: date, item and units. An item is matched to a product through the product's sales
identifiers or the titles of its bundle variants (a bundle sale counts its units, like a manual sale does)."""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime

MAX_ROWS = 15_000
SHOW_ERRORS = 5  # how many problems one message lists

DATE_NAMES = ("date", "day")
ITEM_NAMES = ("item", "sku", "title", "product")
UNIT_NAMES = ("units", "quantity", "qty")


class SalesFileError(ValueError):
    """The file cannot be used; the message says why and is shown to the person."""


@dataclass(frozen=True)
class SaleRow:
    line: int
    day: date
    item: str
    quantity: int


@dataclass
class Matched:
    totals: dict[tuple[int, date], int]  # (product id, day) -> units, all matched rows added up
    matched: int                         # rows that found a product
    unknown: dict[str, int]              # item as written -> rows, for items no product claims
    ambiguous: dict[str, int]            # item as written -> rows, for items two products claim


def norm(text: str) -> str:
    """Capitals and extra spaces never matter when matching an item."""
    return " ".join(text.lower().split())


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    for i, cell in enumerate(header):
        if norm(cell) in names:
            return i
    return None


def _day(text: str) -> date | None:
    for form in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.strip(), form).date()
        except ValueError:
            continue
    return None


def parse_csv(text: str, today: date) -> list[SaleRow]:
    """The rows of a sales file, or a SalesFileError that lists what is wrong (with line numbers)."""
    lines = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    lines = [(n, r) for n, r in enumerate(lines, start=1) if any(c.strip() for c in r)]
    if not lines:
        raise SalesFileError("The file is empty.")
    _, header = lines[0]
    cols = (_column(header, DATE_NAMES), _column(header, ITEM_NAMES), _column(header, UNIT_NAMES))
    if None in cols:
        raise SalesFileError("The first row must name three columns: date, item and units.")
    if len(lines) - 1 > MAX_ROWS:
        raise SalesFileError(f"The file has more than {MAX_ROWS:,} rows. Split it into smaller files.")
    rows: list[SaleRow] = []
    problems: list[str] = []
    for n, cells in lines[1:]:
        if len(cells) <= max(cols):
            problems.append(f"Line {n}: the row has too few columns.")
            continue
        day, item, units = _day(cells[cols[0]]), cells[cols[1]].strip(), cells[cols[2]].strip()
        if day is None:
            problems.append(f"Line {n}: '{cells[cols[0]].strip()}' is not a date. Use 2026-10-28 or 10/28/2026.")
        elif day > today:
            problems.append(f"Line {n}: {day:%b} {day.day} is in the future.")
        elif not item:
            problems.append(f"Line {n}: the item is empty.")
        elif not re.fullmatch(r"\d+", units):
            problems.append(f"Line {n}: '{units}' is not a whole number of units (0 or more).")
        else:
            rows.append(SaleRow(n, day, item, int(units)))
    if problems:
        more = len(problems) - SHOW_ERRORS
        raise SalesFileError(" ".join(problems[:SHOW_ERRORS]) + (f" And {more} more." if more > 0 else ""))
    if not rows:
        raise SalesFileError("The file has a header but no sales rows.")
    return rows


def match_rows(rows: list[SaleRow], lookup: dict[str, list[tuple[int, int]]]) -> Matched:
    """Add the rows up per product and day. `lookup` maps a normalized item to the (product id, units per sale) pairs
    that claim it: every identifier counts 1 unit per sale, a bundle title counts its bundle size."""
    out = Matched({}, 0, {}, {})
    for r in rows:
        claims = lookup.get(norm(r.item), [])
        if not claims:
            out.unknown[r.item] = out.unknown.get(r.item, 0) + 1
        elif len({pid for pid, _ in claims}) > 1:
            out.ambiguous[r.item] = out.ambiguous.get(r.item, 0) + 1
        else:
            pid, per = claims[0]
            out.totals[(pid, r.day)] = out.totals.get((pid, r.day), 0) + r.quantity * per
            out.matched += 1
    return out
