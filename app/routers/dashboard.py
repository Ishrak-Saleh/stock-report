from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import today
from app.db import get_session
from app.domain.forecast import try_order
from app.models import Product
from app.services.products import get_settings, product_row, report
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_session)):
    s = get_settings(db)
    return templates.TemplateResponse(request, "dashboard.html", {
        "rows": report(db, today()), "settings": s, "today": today()})


@router.get("/products/{product_id}/try", response_class=HTMLResponse)
def try_an_order(request: Request, product_id: int, units: int = 0, db: Session = Depends(get_session)):
    """Pure what-if: nothing is saved."""
    row = product_row(db, db.get(Product, product_id), get_settings(db), today())
    days = try_order(row.product.stock, row.ordered, max(units, 0), row.forecast.adjusted_burn)
    return templates.TemplateResponse(request, "partials/try_result.html", {
        "days": days, "units": max(units, 0), "stock": row.product.stock, "ordered": row.ordered,
        "burn": row.forecast.adjusted_burn})
