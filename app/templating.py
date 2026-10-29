from datetime import date

from fastapi.templating import Jinja2Templates

from app.domain.carriers import tracking_url

templates = Jinja2Templates(directory="app/templates")


def days(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


def short_date(v: date | None) -> str:
    return "—" if v is None else v.strftime("%b %d")


templates.env.filters["tracking_url"] = lambda t: tracking_url(t.carrier, t.number)
templates.env.filters["days"] = days
templates.env.filters["short_date"] = short_date
