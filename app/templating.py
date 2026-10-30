import hashlib
from datetime import date, datetime
from pathlib import Path

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


def chase_count(user: dict | None) -> int:
    """Orders due a message today, for the badge on the More menu. It counts only the signed-in company's orders."""
    from app.db import SessionLocal
    from app.services.chase import due_count
    from app.tenancy import scope_for
    with SessionLocal() as db:
        db.info["scope"] = scope_for(user)
        return due_count(db, store_today())


_ASSETS: dict[str, tuple[tuple[int, int], str]] = {}


def static_url(name: str) -> str:
    """/static/<name> with a short content hash, so a changed file gets a new address and the old one can be cached for a year."""
    path = Path("app/static") / name
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    hit = _ASSETS.get(name)
    if hit is None or hit[0] != key:
        hit = _ASSETS[name] = (key, hashlib.md5(path.read_bytes()).hexdigest()[:10])
    return f"/static/{name}?v={hit[1]}"


def clock(v: datetime | None) -> str:
    return "—" if v is None else f"{v:%b} {v.day}, {v:%H:%M}"


templates.env.filters.update({
    "tracking_url": lambda t: tracking_url(t.carrier, t.number),
    "num": num, "days": days, "short_date": short_date, "short_name": short_name, "clock": clock,
})
templates.env.globals.update(icon=icon, charts=charts, store_today=store_today, me=me, chase_count=chase_count, static_url=static_url)
