from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import today
from app.db import get_session
from app.deps import require_staff
from app.models import Product, Supplier
from app.services import chase as chase_svc
from app.services import settings as svc
from app.services.products import get_settings, params_for
from app.templating import templates

router = APIRouter()
# The notice comes back through the address, so only these fixed sentences are ever shown.
NOTICES = frozenset({
    "Forecast defaults saved.", "Product added.", "Product saved.", "Supplier added.", "Supplier saved.",
    "Alert settings saved.", "Test saved to the Outbox. Nothing was delivered.",
    "Reorder alert saved to the Outbox. Nothing was delivered.", "Data marked as updated today."})


def _page(request: Request, db: Session, error: str = "", notice: str = "", code: int = 200):
    s = get_settings(db)
    products = db.scalars(select(Product).order_by(Product.name)).all()
    counts = svc.open_orders_by_supplier(db)
    return templates.TemplateResponse(request, "settings.html", {
        "s": s, "products": products, "suppliers": db.scalars(select(Supplier).order_by(Supplier.name)).all(),
        "open_counts": counts, "error": error, "notice": notice, "bundles": svc.bundles_text,
        "stale": svc.stale_days(s, today()), "reorder_line": s.lead_time + s.safety_days,
        "params": {p.id: params_for(p, s) for p in products}}, status_code=code)


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request, notice: str = "", user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _page(request, db, notice=notice if notice in NOTICES else "")


def _try(request: Request, db: Session, action, notice: str):
    try:
        action()
    except (svc.SettingsError, chase_svc.ChaseError) as e:
        db.rollback()
        return _page(request, db, error=str(e), code=400)
    return RedirectResponse(f"/settings?notice={notice}", status_code=303)


@router.post("/settings/defaults")
def defaults(request: Request, lead_time: str = Form("", max_length=8), safety_days: str = Form("", max_length=8),
             target_days: str = Form("", max_length=8), user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: svc.save_defaults(db, get_settings(db), lead_time, safety_days, target_days),
                "Forecast defaults saved.")


# ---- products ----

@router.get("/settings/products/new", response_class=HTMLResponse)
def new_product_dialog(request: Request, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/dlg_product.html", {"p": None, "s": get_settings(db), "bundles": ""})


@router.get("/settings/products/{product_id}", response_class=HTMLResponse)
def product_dialog(request: Request, product_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return templates.TemplateResponse(request, "partials/dlg_product.html", {
        "p": p, "s": get_settings(db), "bundles": svc.bundles_text(p), "ids": ", ".join(p.identifiers or [])})


@router.post("/settings/products")
def create_product(request: Request, name: str = Form("", max_length=80), code: str = Form("", max_length=12),
                   identifiers: str = Form("", max_length=500), bundles: str = Form("", max_length=500),
                   lead: str = Form("", max_length=8), safety: str = Form("", max_length=8), target: str = Form("", max_length=8),
                   unshipped: str = Form("", max_length=8),
                   user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: svc.add_product(
        db, name=name, code=code, identifiers=identifiers, bundles=bundles, lead=lead, safety=safety, target=target,
        unshipped=unshipped),
        "Product added.")


@router.post("/settings/products/{product_id}")
def update_product(request: Request, product_id: int, name: str = Form("", max_length=80), code: str = Form("", max_length=12),
                   identifiers: str = Form("", max_length=500), bundles: str = Form("", max_length=500),
                   lead: str = Form("", max_length=8), safety: str = Form("", max_length=8), target: str = Form("", max_length=8),
                   unshipped: str = Form("", max_length=8),
                   user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return _try(request, db, lambda: svc.save_product(
        db, p, name=name, code=code, identifiers=identifiers, bundles=bundles, lead=lead, safety=safety, target=target,
        unshipped=unshipped),
        "Product saved.")


# ---- suppliers ----

@router.get("/settings/suppliers/new", response_class=HTMLResponse)
def new_supplier_dialog(request: Request, user: dict = Depends(require_staff)):
    return templates.TemplateResponse(request, "partials/dlg_supplier.html", {"sp": None})


@router.get("/settings/suppliers/{supplier_id}", response_class=HTMLResponse)
def supplier_dialog(request: Request, supplier_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    sp = db.get(Supplier, supplier_id)
    if not sp:
        raise HTTPException(404, "Supplier not found")
    return templates.TemplateResponse(request, "partials/dlg_supplier.html", {"sp": sp})


@router.post("/settings/suppliers")
def create_supplier(request: Request, name: str = Form("", max_length=80), email: str = Form("", max_length=120),
                    user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: svc.add_supplier(db, name, email), "Supplier added.")


@router.post("/settings/suppliers/{supplier_id}")
def update_supplier(request: Request, supplier_id: int, name: str = Form("", max_length=80),
                    email: str = Form("", max_length=120), user: dict = Depends(require_staff),
                    db: Session = Depends(get_session)):
    sp = db.get(Supplier, supplier_id)
    if not sp:
        raise HTTPException(404, "Supplier not found")
    return _try(request, db, lambda: svc.save_supplier(db, sp, name, email), "Supplier saved.")


# ---- alerts and data freshness ----

@router.post("/settings/alerts")
def alerts(request: Request, enabled: str = Form(""), recipients: str = Form("", max_length=300),
           user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: svc.save_alerts(db, get_settings(db), bool(enabled), recipients),
                "Alert settings saved.")


@router.post("/settings/alerts/test")
def alerts_test(request: Request, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: chase_svc.add_reorder_alert(db, today(), test=True),
                "Test saved to the Outbox. Nothing was delivered.")


@router.post("/settings/alerts/send")
def alerts_send(request: Request, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: chase_svc.add_reorder_alert(db, today(), test=False),
                "Reorder alert saved to the Outbox. Nothing was delivered.")


@router.post("/settings/data-updated")
def data_updated(request: Request, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _try(request, db, lambda: svc.mark_data_updated(db, get_settings(db)), "Data marked as updated today.")
