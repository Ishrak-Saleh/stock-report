from datetime import date, datetime

from fastapi.templating import Jinja2Templates

from app import charts
from app.config import today as store_today
from app.domain.carriers import tracking_url
from app.domain.messages import short_name
from app.icons import icon

templates = Jinja2Templates(directory="app/templates")


def days(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


def short_date(v: date | None) -> str:
    return "—" if v is None else f"{v:%b} {v.day}"


def num(v: int | None) -> str:
    return "—" if v is None else f"{v:,}"


def me(request) -> dict | None:
    """The signed-in person, or None (also on error pages that run before the session is read)."""
    return request.scope.get("session", {}).get("user")


def chase_count() -> int:
    """Orders due a message today, for the badge on the More menu."""
    from app.db import SessionLocal
    from app.services.chase import due_count
    with SessionLocal() as db:
        return due_count(db, store_today())


def clock(v: datetime | None) -> str:
    return "—" if v is None else f"{v:%b} {v.day}, {v:%H:%M}"


templates.env.filters.update({
    "tracking_url": lambda t: tracking_url(t.carrier, t.number),
    "num": num, "days": days, "short_date": short_date, "short_name": short_name, "clock": clock,
})
templates.env.globals.update(icon=icon, charts=charts, store_today=store_today, me=me, chase_count=chase_count)
