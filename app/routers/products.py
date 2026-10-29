from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import today
from app.db import get_session
from app.deps import require_staff
from app.domain.runway import HORIZONS
from app.models import Product
from app.services import stock as svc
from app.services.products import get_settings, product_row
from app.templating import templates

router = APIRouter()
UNITS_MAX = 1_000_000


def _product(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


def _page(request: Request, db: Session, p: Product, kind: str = "", error: str = "", code: int = 200):
    t = today()
    h = svc.history(db, p, t)
    text, sub = h.sentence(p.name, p.stock)
    return templates.TemplateResponse(request, "product.html", {
        "p": p, "row": product_row(db, p, get_settings(db), t), "hist": h, "headline": text, "sub": sub,
        "moves": svc.movements(db, p, kind), "kind": kind if kind in svc.FILTERS else "", "total": len(svc.movements(db, p)),
        "rw": svc.runway_view(db, p, t), "horizons": HORIZONS, "today": t, "error": error,
        "kinds": svc.KINDS}, status_code=code)


@router.get("/products/{product_id}", response_class=HTMLResponse)
def product(request: Request, product_id: int, kind: str = "", user: dict = Depends(require_staff),
            db: Session = Depends(get_session)):
    return _page(request, db, _product(db, product_id), kind)


@router.get("/products/{product_id}/runway", response_class=HTMLResponse)
def runway(request: Request, product_id: int, horizon: int = 90, closed: str = "", user: dict = Depends(require_staff),
           db: Session = Depends(get_session)):
    """The runway chart as a drawer under a Stock row, or on the product page."""
    p = _product(db, product_id)
    if closed:
        return HTMLResponse(f'<div id="runway-{p.id}"></div>')
    t = today()
    return templates.TemplateResponse(request, "partials/runway.html", {
        "p": p, "rw": svc.runway_view(db, p, t, horizon if horizon in HORIZONS else 90), "horizons": HORIZONS,
        "today": t, "closable": request.query_params.get("from") != "page"})


@router.get("/products/{product_id}/adjust", response_class=HTMLResponse)
def adjust_dialog(request: Request, product_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    p = _product(db, product_id)
    row = product_row(db, p, get_settings(db), today())
    return templates.TemplateResponse(request, "partials/dlg_adjust.html", {
        "p": p, "burn": row.forecast.adjusted_burn, "kinds": svc.KINDS, "today": today()})


@router.post("/products/{product_id}/adjust")
def adjust(request: Request, product_id: int, kind: str = Form(), units: int = Form(le=UNITS_MAX), note: str = Form("", max_length=200),
           day: date = Form(), variant: str = Form("", max_length=60), user: dict = Depends(require_staff),
           db: Session = Depends(get_session)):
    p = _product(db, product_id)
    try:
        svc.log_adjustment(db, p, kind, units, note, day, user["label"], variant)
    except svc.StockError as e:
        db.rollback()
        return _page(request, db, p, error=str(e), code=400)
    return RedirectResponse(f"/products/{p.id}", status_code=303)
