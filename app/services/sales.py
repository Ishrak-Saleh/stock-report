"""Sales import: load the company's products, call the rules in domain/sales_import.py, save the daily sales.
The check (preview) and the import run the very same steps, so the import never trusts what the preview showed."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.bundles import units_sold
from app.domain.sales_import import Matched, SalesFileError, match_rows, norm, parse_csv
from app.models import DailySale, Product
from app.services.products import get_settings
from app.services.settings import mark_data_updated


@dataclass
class ProductChange:
    product: Product
    days: int      # days the file sets for this product
    units: int     # units on those days, all added up
    changed: int   # of those days, how many already have a different number saved


@dataclass
class Preview:
    rows: int
    matched: Matched
    changes: list[ProductChange]

    @property
    def unknown(self) -> list[tuple[str, int]]:
        return sorted(self.matched.unknown.items(), key=lambda kv: (-kv[1], kv[0]))

    @property
    def ambiguous(self) -> list[tuple[str, int]]:
        return sorted(self.matched.ambiguous.items(), key=lambda kv: (-kv[1], kv[0]))


def build_lookup(products: list[Product]) -> dict[str, list[tuple[int, int]]]:
    """Every identifier counts one unit per sale; every bundle title counts the units of that bundle."""
    lookup: dict[str, list[tuple[int, int]]] = {}
    for p in products:
        for ident in p.identifiers or []:
            if norm(ident):
                lookup.setdefault(norm(ident), []).append((p.id, 1))
        for title in (p.bundle_map or {}):
            lookup.setdefault(norm(title), []).append((p.id, units_sold(1, title, p.bundle_map)))
    return lookup


def _plan(db: Session, text: str, today: date) -> tuple[Preview, dict[int, Product]]:
    rows = parse_csv(text, today)
    products = {p.id: p for p in db.scalars(select(Product)).all()}  # the session only sees this company's products
    matched = match_rows(rows, build_lookup(list(products.values())))
    changes = []
    for pid in sorted({pid for pid, _ in matched.totals}, key=lambda i: products[i].name):
        days = {day: units for (p_id, day), units in matched.totals.items() if p_id == pid}
        saved = {s.day: s.units for s in products[pid].sales}
        changes.append(ProductChange(products[pid], len(days), sum(days.values()),
                                     sum(1 for d, u in days.items() if d in saved and saved[d] != u)))
    return Preview(len(rows), matched, changes), products


def preview(db: Session, text: str, today: date) -> Preview:
    """What an import would do. Saves nothing."""
    return _plan(db, text, today)[0]


def commit(db: Session, text: str, today: date) -> Preview:
    """Save the file's daily totals. A day the file mentions replaces the saved total for that product and day, so
    importing the same file twice changes nothing. Warehouse stock is never touched: imported sales only set the burn."""
    pv, products = _plan(db, text, today)
    if not pv.matched.totals:
        raise SalesFileError("None of the items match a product's sales identifiers, so nothing was imported.")
    for (pid, day), units in pv.matched.totals.items():
        saved = db.get(DailySale, (pid, day))
        if saved:
            saved.units = units
        else:
            db.add(DailySale(product_id=pid, day=day, units=units))
    mark_data_updated(db, get_settings(db))  # commits, and clears the old-data warning
    return pv
