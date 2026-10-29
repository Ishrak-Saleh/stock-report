from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now
from app.db import get_session
from app.domain.carriers import CARRIERS
from app.models import Order, Product, Supplier
from app.services import orders as svc
from app.templating import templates

router = APIRouter()


def _get(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


def _detail(request: Request, db: Session, o: Order, error: str = "", status_code: int = 200):
    ctx = {"o": o, "s": svc.order_stages(o), "open": svc.is_open(o), "untracked": o.units - svc.tracked_units(o),
           "carriers": CARRIERS, "suppliers": db.scalars(select(Supplier).order_by(Supplier.name)).all(),
           "error": error}
    return templates.TemplateResponse(request, "order_detail.html", ctx, status_code=status_code)


def _run(request: Request, db: Session, o: Order, action, to: str | None = None):
    """Run an order action. Rule breaks show on the detail page instead of crashing."""
    try:
        action()
    except svc.OrderError as e:
        db.rollback()
        return _detail(request, db, o, str(e), 400)
    return RedirectResponse(to or f"/orders/{o.id}", status_code=303)


@router.get("/orders", response_class=HTMLResponse)
def orders(request: Request, product: str = "", status: str = "", db: Session = Depends(get_session)):
    product_id = int(product) if product.isdigit() else None
    ctx = {"rows": svc.list_orders(db, product_id, status or None), "now": now()}
    if request.headers.get("HX-Request"):  # filter change: send only the list
        return templates.TemplateResponse(request, "partials/order_list.html", ctx)
    ctx |= {"products": db.scalars(select(Product).order_by(Product.name)).all(), "statuses": svc.STATUSES,
            "product": product_id, "status": status}
    return templates.TemplateResponse(request, "orders.html", ctx)


@router.get("/orders/new", response_class=HTMLResponse)
def new_order_form(request: Request, product: int | None = None, units: int | None = None,
                   db: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "order_new.html", {"units": units,
        "products": db.scalars(select(Product).order_by(Product.name)).all(),
        "suppliers": db.scalars(select(Supplier).order_by(Supplier.name)).all(), "product": product})


@router.post("/orders")
def create(product_id: int = Form(), supplier_id: int = Form(), units: int = Form(gt=0), notes: str = Form(""),
           db: Session = Depends(get_session)):
    product, supplier = db.get(Product, product_id), db.get(Supplier, supplier_id)
    if not product or not supplier:
        raise HTTPException(404, "Unknown product or supplier")
    order = svc.create_order(db, product, supplier.id, units, notes)
    return RedirectResponse(f"/orders/{order.id}", status_code=303)


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int, db: Session = Depends(get_session)):
    return _detail(request, db, _get(db, order_id))


@router.post("/orders/{order_id}/confirm")
def confirm(request: Request, order_id: int, db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.confirm_order(db, o))


@router.post("/orders/{order_id}/tracking")
def add_tracking(request: Request, order_id: int, number: str = Form(), units: int = Form(gt=0),
                 carrier: str = Form(""), db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.add_tracking(db, o, number, carrier, units))


@router.post("/orders/{order_id}/tracking/{tracking_id}/remove")
def remove_tracking(request: Request, order_id: int, tracking_id: int, db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.remove_tracking(db, o, tracking_id))


@router.post("/orders/{order_id}/edit")
def edit(request: Request, order_id: int, units: int = Form(gt=0), supplier_id: int = Form(), notes: str = Form(""),
         db: Session = Depends(get_session)):
    o = _get(db, order_id)
    if not db.get(Supplier, supplier_id):
        raise HTTPException(404, "Unknown supplier")
    return _run(request, db, o, lambda: svc.edit_order(db, o, units, notes, supplier_id))


@router.post("/orders/{order_id}/cancel")
def cancel(request: Request, order_id: int, db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.cancel_order(db, o))


@router.post("/orders/{order_id}/close")
def close(request: Request, order_id: int, db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.close_order(db, o))


@router.post("/orders/{order_id}/reopen")
def reopen(request: Request, order_id: int, db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.reopen_order(db, o))


@router.post("/orders/{order_id}/delete")
def delete(request: Request, order_id: int, db: Session = Depends(get_session)):
    o = _get(db, order_id)
    return _run(request, db, o, lambda: svc.delete_order(db, o), to="/orders")
