"""Edit the forecast defaults, products, suppliers and alert settings. Every rule that can fail raises SettingsError
with a message the page shows next to the form."""
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import STALE_DAYS, now
from app.models import Order, Product, Settings, Supplier
from app.services.chase import EMAIL, check_recipients
from app.services.orders import is_open

CODE = re.compile(r"^[A-Z0-9]{1,8}$")


class SettingsError(ValueError):
    """A rule the user broke; the message is shown on the page."""


def _int(text: str, label: str, low: int, high: int = 3650, blank_ok: bool = False) -> int | None:
    text = (text or "").strip()
    if not text and blank_ok:
        return None
    if not re.fullmatch(r"\d+", text) or not low <= int(text) <= high:
        raise SettingsError(f"{label} must be a whole number from {low} to {high}.")
    return int(text)


def save_defaults(db: Session, s: Settings, lead: str, safety: str, target: str) -> None:
    s.lead_time = _int(lead, "Lead time", 0)
    s.safety_days = _int(safety, "Safety days", 0)
    s.target_days = _int(target, "Target days", 1)
    db.commit()


def parse_identifiers(text: str) -> list[str]:
    seen: list[str] = []
    for part in re.split(r"[,\n]", text):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return seen


def parse_bundles(text: str) -> dict[str, int]:
    """One bundle per line, 'Buy 2 Get 2 = 4'. The number is how many units one sale of that variant means."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        title, sep, units = line.rpartition("=")
        if not sep or not title.strip() or not re.fullmatch(r"\s*[1-9]\d*\s*", units):
            raise SettingsError(f"Bundle line '{line.strip()}' should look like: Buy 2 Get 2 = 4")
        out[title.strip()] = int(units)
    return out


def bundles_text(p: Product) -> str:
    return "\n".join(f"{k} = {v}" for k, v in (p.bundle_map or {}).items())


def _fill_product(db: Session, p: Product, name: str, code: str, identifiers: str, bundles: str,
                  lead: str, safety: str, target: str, unshipped: str = "") -> None:
    name, code = name.strip(), code.strip().upper()
    if not name:
        raise SettingsError("Enter a product name.")
    if not CODE.match(code):
        raise SettingsError("The short code must be 1 to 8 letters or digits.")
    other = db.scalars(select(Product).where(func.upper(Product.code) == code, Product.id != (p.id or 0))).first()
    if other:
        raise SettingsError(f"{code} is used by {other.name}. Pick a different code.")
    p.name, p.code = name, code
    p.identifiers = parse_identifiers(identifiers)
    p.bundle_map = parse_bundles(bundles)
    p.lead_time = _int(lead, "Lead time", 0, blank_ok=True)
    p.safety_days = _int(safety, "Safety days", 0, blank_ok=True)
    p.target_days = _int(target, "Target days", 1, blank_ok=True)
    sold_not_shipped = _int(unshipped, "Sold, not shipped", 0, blank_ok=True)
    if sold_not_shipped is not None:  # blank keeps the current number
        p.unshipped = sold_not_shipped


def save_product(db: Session, p: Product, **form: str) -> None:
    _fill_product(db, p, **form)
    db.commit()


def add_product(db: Session, **form: str) -> Product:
    p = Product(stock=0, unshipped=0)
    _fill_product(db, p, **form)
    if not p.identifiers:
        p.identifiers = [p.name]
    db.add(p)
    db.commit()
    return p


def _supplier_fields(name: str, email: str) -> tuple[str, str]:
    name, email = name.strip(), email.strip().lower()
    if not name:
        raise SettingsError("Enter a supplier name.")
    if not EMAIL.match(email):
        raise SettingsError(f"{email or 'That'} is not an email address.")
    return name, email


def save_supplier(db: Session, s: Supplier, name: str, email: str) -> None:
    s.name, s.email = _supplier_fields(name, email)
    db.commit()


def add_supplier(db: Session, name: str, email: str) -> Supplier:
    name, email = _supplier_fields(name, email)
    s = Supplier(name=name, email=email)
    db.add(s)
    db.commit()
    return s


def open_orders_by_supplier(db: Session) -> dict[int, int]:
    counts: dict[int, int] = {}
    for o in db.scalars(select(Order)):
        if is_open(o):
            counts[o.supplier_id] = counts.get(o.supplier_id, 0) + 1
    return counts


def save_alerts(db: Session, s: Settings, enabled: bool, recipients: str) -> None:
    check_recipients(recipients)
    s.alerts_enabled, s.recipients = enabled, recipients.strip()
    db.commit()


def mark_data_updated(db: Session, s: Settings) -> None:
    s.data_updated_at = now()
    db.commit()


def stale_days(s: Settings, today: date) -> int | None:
    """How many days old the stock and sales data is, when that is more than STALE_DAYS."""
    if s.data_updated_at is None:
        return None
    age = (today - s.data_updated_at.date()).days
    return age if age > STALE_DAYS else None
