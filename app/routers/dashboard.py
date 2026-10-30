from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import today
from app.db import get_session
from app.deps import is_staff, require_staff, require_user
from app.domain.forecast import try_order
from app.domain.orders import expected_arrival
from app.models import Product
from app.seed import sample_suppliers, seed
from app.services import orders as order_svc
from app.services.products import FILTERS, counts, get_settings, product_row, report, stock_headline
from app.services.settings import stale_days
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, show: str = "", user: dict = Depends(require_user), db: Session = Depends(get_session)):
    if not is_staff(user):
        return RedirectResponse("/orders", status_code=303)  # suppliers only have their own orders
    t = today()
    all_rows = report(db, t)
    flt = FILTERS.get(show)
    settings = get_settings(db)
    return templates.TemplateResponse(request, "dashboard.html", {
        "rows": [r for r in all_rows if not flt or r.flag.level == flt],
        "head": stock_headline(all_rows),
        "counts": counts(all_rows),
        "show": show if flt else "",
        "chase": order_svc.list_orders(db, only_chase=True, today=t)[:5],
        "settings": settings,
        "last_full_day": t - timedelta(days=1),
        "stale": stale_days(settings, t),
    })


@router.post("/sample-data")
def sample_data(user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    """Fills an empty company with the demo products and orders. Does nothing if it already has products."""
    seed(db, user["company_id"], sample_suppliers(user["company_id"]))
    return RedirectResponse("/", status_code=303)


@router.get("/products/{product_id}/try", response_class=HTMLResponse)
def try_an_order(request: Request, product_id: int, units: int = 0, user: dict = Depends(require_staff),
                 db: Session = Depends(get_session)):
    """What-if only: nothing is saved. Days of stock including everything on order, and when an order placed today lands."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    t = today()
    row = product_row(db, product, get_settings(db), t)
    days = try_order(product.stock, row.ordered, max(units, 0), row.forecast.adjusted_burn)
    return templates.TemplateResponse(request, "partials/try_summary.html", {
        "days": days, "lands": expected_arrival(t, row.params.lead_time)})
