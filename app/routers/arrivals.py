from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import today
from app.db import get_session
from app.deps import require_staff
from app.models import Arrival, Product
from app.services import arrivals as svc
from app.services.products import get_settings
from app.services.settings import stale_days
from app.templating import templates

router = APIRouter()
UNITS_MAX = 1_000_000


def _arrival(db: Session, arrival_id: int) -> Arrival:
    a = db.get(Arrival, arrival_id)
    if not a:
        raise HTTPException(404, "Arrival not found")
    return a


def _page(request: Request, db: Session, status: str = "", error: str = "", code: int = 200):
    status = status if status in ("unmatched", "matched") else ""
    everything = svc.arrival_rows(db)
    un = [r for r in everything if r.unmatched][::-1]  # oldest first
    waiting = [(r, *svc.why_unmatched(db, r.arrival)) for r in un]
    units = sum(r.unmatched for r in un)
    return templates.TemplateResponse(request, "arrivals.html", {
        "rows": svc.arrival_rows(db, status), "waiting": waiting, "status": status, "error": error,
        "counts": {"all": len(everything), "unmatched": len(un), "matched": len(everything) - len(un)},
        "units": units, "stale": stale_days(get_settings(db), today()),
        "has_products": db.scalars(select(Product).limit(1)).first() is not None}, status_code=code)


@router.get("/arrivals", response_class=HTMLResponse)
def arrivals(request: Request, status: str = "", user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _page(request, db, status)


def _preview_ctx(db: Session, product: Product, units: int) -> dict:
    match, opens, _ = svc.preview(db, product, units)
    got = dict(match.parts)
    return {"product": product, "units": max(units, 0), "unmatched": match.unmatched, "stock": product.stock,
            "after": product.stock + max(units, 0),
            "rows": [{"name": o.name, "placed": o.placed, "room": o.remaining, "take": got.get(o.order_id, 0)} for o in opens]}


@router.get("/arrivals/new", response_class=HTMLResponse)
def new_arrival(request: Request, product_id: int | None = None, units: int = 0, user: dict = Depends(require_staff),
                db: Session = Depends(get_session)):
    products = db.scalars(select(Product).order_by(Product.name)).all()
    if not products:
        message = "Add a product in Settings before recording an arrival."
        if request.headers.get("HX-Request"):  # HTMX ignores error replies, so the dialog itself explains
            return templates.TemplateResponse(request, "partials/dlg_setup.html", {"title": "Not ready to record an arrival", "message": message})
        raise HTTPException(409, message)
    chosen = db.get(Product, product_id) if product_id else None
    if chosen is None:  # start on a product that has something on order
        chosen = next((p for p in products if svc.open_orders(db, p.id)), products[0])
    return templates.TemplateResponse(request, "partials/dlg_arrival.html", {
        "products": products, "today": today(), "units": units or "", **_preview_ctx(db, chosen, units)})


@router.get("/arrivals/preview", response_class=HTMLResponse)
def preview(request: Request, product_id: int, units: str = "", user: dict = Depends(require_staff),
            db: Session = Depends(get_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    n = int(units) if units.isdigit() and len(units) <= 9 else 0  # the box may be empty while someone types
    return templates.TemplateResponse(request, "partials/arrival_preview.html", _preview_ctx(db, product, n))


@router.post("/arrivals")
def record(request: Request, product_id: int = Form(), units: int = Form(le=UNITS_MAX), day: date = Form(),
           note: str = Form("", max_length=200), user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    try:
        svc.record_arrival(db, product, units, day, note, user["label"])
    except svc.ArrivalError as e:
        db.rollback()
        return _page(request, db, error=str(e), code=400)
    return RedirectResponse("/arrivals", status_code=303)


@router.get("/arrivals/{arrival_id}/match", response_class=HTMLResponse)
def match_dialog(request: Request, arrival_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    a = _arrival(db, arrival_id)
    parts = svc.split_parts(db, a)
    editor = svc.editor_orders(db, a)
    return templates.TemplateResponse(request, "partials/dlg_match.html", {
        "a": a, "editor": [(o, room, parts.get(o.id, 0)) for o, room in editor], "free": parts.get(None, 0),
        "assigned": sum(parts.values())})


@router.post("/arrivals/{arrival_id}/match")
async def match(request: Request, arrival_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    a = _arrival(db, arrival_id)
    form = await request.form()
    parts: dict[int | None, int] = {}
    try:
        for key, value in form.items():
            if key.startswith("u_"):
                parts[None if key == "u_free" else int(key[2:])] = int(str(value) or 0)
    except ValueError:
        return _page(request, db, error="Units must be whole numbers.", code=400)
    try:
        svc.edit_match(db, a, parts, user["label"])
    except svc.ArrivalError as e:
        db.rollback()
        return _page(request, db, error=str(e), code=400)
    return RedirectResponse("/arrivals", status_code=303)


@router.post("/arrivals/{arrival_id}/not-from-order")
def not_from_order(arrival_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    svc.mark_not_from_order(db, _arrival(db, arrival_id), user["label"])
    return RedirectResponse("/arrivals", status_code=303)
