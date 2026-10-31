from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SENDER_NAME, today
from app.db import get_session
from app.deps import is_staff, require_staff, require_user
from app.domain import messages
from app.domain.carriers import CARRIERS
from app.domain.orders import expected_arrival
from app.models import Order, Product, Supplier
from app.services import orders as svc
from app.services.products import gap_risk, get_settings, params_for, product_row, report
from app.templating import templates

router = APIRouter()
NOTES_MAX, UNITS_MAX = 500, 1_000_000


def _get(db: Session, order_id: int, user: dict) -> Order:
    """The order, or 404. The session only sees its own orders (app/tenancy.py), so another company's or another
    supplier's order is "not found", which also does not reveal that it exists."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


def _by(user: dict, o: Order) -> str:
    """Who the history names. Staff acting for a supplier are named as that: "Sam for Acme"."""
    return f"{user['label']} for {messages.short_name(o.supplier.name)}" if is_staff(user) else user["label"]


def _suppliers(db: Session) -> list[Supplier]:
    return db.scalars(select(Supplier).order_by(Supplier.name)).all()


def _detail(request: Request, db: Session, o: Order, user: dict, error: str = "", status_code: int = 200,
            saved: bool = False):
    t = today()
    r = svc.build_row(o, t)
    st = r.stages
    tracked = svc.tracked_units(o)
    lead = params_for(o.product, get_settings(db, o.company_id)).lead_time
    staff = is_staff(user)
    # How many empty-shelf days open up before this order lands. Staff only: a supplier cannot see the other orders.
    empty = svc.shelf_gap(o, gap_risk([product_row(db, o.product, get_settings(db, o.company_id), t)]), t) if staff else 0
    ctx = {
        "o": o, "r": r, "st": st, "open": svc.is_open(o), "error": error, "staff": staff, "saved": saved,
        "steps": svc.order_steps(o, st), "tracked": tracked, "untracked": o.units - tracked,
        "expected": expected_arrival(o.created_at.date(), lead), "lead_time": lead, "empty_before": empty,
        "events": list(reversed(o.events)),
        "takeaway": messages.takeaway(
            status=st.status, units=o.units, arrived=st.arrived, remaining=o.units - st.arrived,
            on_the_way=st.on_the_way, untracked=o.units - tracked, chase=r.chase, supplier=o.supplier.name)
        if staff else messages.supplier_takeaway(
            status=st.status, units=o.units, arrived=st.arrived, confirmed=st.confirmed, untracked=o.units - tracked),
    }
    return templates.TemplateResponse(request, "order_detail.html", ctx, status_code=status_code)


def _run(request: Request, db: Session, o: Order, user: dict, action, to: str | None = None):
    """Run an order action. Rule breaks show on the detail page instead of crashing."""
    try:
        action()
    except svc.OrderError as e:
        db.rollback()
        return _detail(request, db, o, user, str(e), 400)
    return RedirectResponse(to or f"/orders/{o.id}", status_code=303)


# ---- lists and the new order form ----

def _supplier_list(request: Request, db: Session, user: dict, show: str):
    rows = svc.list_orders(db)
    head, sub = svc.supplier_headline(rows, user["supplier"])
    shown = [r for r in rows if (r.stages.status in svc.DONE) == (show == "arrived")]
    open_n = sum(1 for r in rows if r.stages.status not in svc.DONE)
    return templates.TemplateResponse(request, "supplier_orders.html", {
        "rows": shown, "head": head, "sub": sub, "show": show, "open_n": open_n, "done_n": len(rows) - open_n,
        "waiting": {r.order.id: svc.waiting_on_supplier(r) for r in rows}, "first": next(
            (r for r in rows if r.stages.status not in svc.DONE and not r.stages.confirmed), None)})


@router.get("/orders", response_class=HTMLResponse)
def orders(request: Request, product: str = "", status: str = "", chase: str = "", show: str = "",
           user: dict = Depends(require_user), db: Session = Depends(get_session)):
    if not is_staff(user):
        return _supplier_list(request, db, user, show if show == "arrived" else "open")
    product_id = int(product) if product.isdigit() else None
    status = status if status in svc.STATUSES else ""
    rows = svc.list_orders(db, product_id, status or None, only_chase=bool(chase), risk=gap_risk(report(db, today())))
    products = db.scalars(select(Product).order_by(Product.name)).all()
    can_order = bool(products and _suppliers(db))  # a company with no product or supplier cannot place an order yet
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "order-list":
        return templates.TemplateResponse(request, "partials/order_list.html", {"rows": rows, "can_order": can_order})
    return templates.TemplateResponse(request, "orders.html", {
        "rows": rows, "headline": svc.orders_headline(svc.list_orders(db)),
        "products": products, "statuses": svc.STATUSES, "can_order": can_order,
        "product": product_id, "status": status, "chase_only": bool(chase)})


@router.get("/orders/new", response_class=HTMLResponse)
def new_order_form(request: Request, product: int | None = None, product_id: int | None = None,
                   units: int | None = None, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    """The New order dialog (HTMX) or, without JavaScript, the same form as a page."""
    t, settings = today(), get_settings(db)
    missing = [name for name, found in (("a product", db.scalars(select(Product).limit(1)).first()),
                                        ("a supplier", _suppliers(db))) if not found]
    if missing:
        message = f"Add {' and '.join(missing)} in Settings before placing an order."
        if request.headers.get("HX-Request"):  # HTMX ignores error replies, so the dialog itself explains
            return templates.TemplateResponse(request, "partials/dlg_setup.html", {"title": "Not ready to order", "message": message})
        raise HTTPException(409, message)
    chosen = db.get(Product, product or product_id) if (product or product_id) else None
    if chosen is None:
        rows = report(db, t)
        chosen = next((r for r in rows if r.forecast.reorder_now), rows[0]).product
    row = product_row(db, chosen, settings, t)
    in_dialog = bool(request.headers.get("HX-Request"))
    return templates.TemplateResponse(
        request, "partials/dlg_new_order.html" if in_dialog else "order_new.html", {
            "product": chosen, "products": db.scalars(select(Product).order_by(Product.name)).all(),
            "suppliers": _suppliers(db), "options": row.options(), "ordered": row.ordered,
            "units": units if units is not None else (row.forecast.suggested_order or None), "in_dialog": in_dialog})


@router.post("/orders")
def create(product_id: int = Form(), supplier_id: int = Form(), units: int = Form(gt=0, le=UNITS_MAX),
           notes: str = Form("", max_length=NOTES_MAX), user: dict = Depends(require_staff),
           db: Session = Depends(get_session)):
    product, supplier = db.get(Product, product_id), db.get(Supplier, supplier_id)
    if not product or not supplier:
        raise HTTPException(404, "Unknown product or supplier")
    order = svc.create_order(db, product, supplier.id, units, notes, user["label"])
    return RedirectResponse(f"/orders/{order.id}", status_code=303)


# ---- one order ----

@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int, saved: str = "", user: dict = Depends(require_user),
                 db: Session = Depends(get_session)):
    return _detail(request, db, _get(db, order_id, user), user, saved=saved == "tracking")


@router.get("/orders/{order_id}/dialog/{what}", response_class=HTMLResponse)
def dialog(request: Request, order_id: int, what: str, kind: str = "order", user: dict = Depends(require_user),
           db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    if what != "tracking" and not is_staff(user):
        raise HTTPException(403, "Only staff can open this.")
    r = svc.build_row(o, today())
    tracked = svc.tracked_units(o)
    ctx: dict = {"o": o}
    if what == "message":
        if r.chase and r.chase.kind == kind:
            ctx["message"] = messages.follow_up(
                r.chase, supplier=o.supplier.name, order=o.name, product=o.product.name, units=o.units,
                untracked=o.units - tracked, tracking_number=o.trackings[0].number if o.trackings else "",
                created_days=r.age, sender=SENDER_NAME)
            ctx["chase_kind"] = kind
            subject = messages.follow_up_subject(r.chase, o.name)
        else:
            ctx["message"] = messages.order_message(
                supplier=o.supplier.name, order=o.name, product=o.product.name, code=o.product.code, units=o.units,
                notes=o.notes, sender=SENDER_NAME)
            subject = messages.order_subject(o.name)
        ctx["gmail"] = messages.gmail_link(o.supplier.email, subject, ctx["message"])
        ctx["mailto"] = messages.mailto_link(o.supplier.email, subject, ctx["message"])
    elif what == "tracking":
        if not svc.is_open(o) or o.units - tracked <= 0:
            raise HTTPException(409, "This order has nothing left to track")
        ctx |= {"left": o.units - tracked, "carriers": CARRIERS, "staff": is_staff(user), "by": _by(user, o),
                "supplier": messages.short_name(o.supplier.name)}
    elif what == "edit":
        ctx |= {"suppliers": _suppliers(db), "floor": max(tracked, r.stages.arrived, 1)}
    elif what != "delete":
        raise HTTPException(404, "Unknown dialog")
    return templates.TemplateResponse(request, f"partials/dlg_{what}.html", ctx)


# ---- actions ----

@router.post("/orders/{order_id}/confirm")
def confirm(request: Request, order_id: int, user: dict = Depends(require_user), db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.confirm_order(db, o, _by(user, o)))


@router.post("/orders/{order_id}/tracking")
def add_tracking(request: Request, order_id: int, number: str = Form(max_length=64), units: int = Form(gt=0, le=UNITS_MAX),
                 carrier: str = Form("", pattern="^(|UPS|FedEx|USPS|DHL)$"), user: dict = Depends(require_user),
                 db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.add_tracking(db, o, number, carrier, units, _by(user, o)),
                to=f"/orders/{o.id}?saved=tracking")


@router.post("/orders/{order_id}/tracking/{tracking_id}/remove")
def remove_tracking(request: Request, order_id: int, tracking_id: int, user: dict = Depends(require_staff),
                    db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.remove_tracking(db, o, tracking_id, user["label"]))


@router.post("/orders/{order_id}/edit")
def edit(request: Request, order_id: int, units: int = Form(gt=0, le=UNITS_MAX), supplier_id: int = Form(),
         notes: str = Form("", max_length=NOTES_MAX), user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    if not db.get(Supplier, supplier_id):
        raise HTTPException(404, "Unknown supplier")
    return _run(request, db, o, user, lambda: svc.edit_order(db, o, units, notes, supplier_id, user["label"]))


@router.post("/orders/{order_id}/cancel")
def cancel(request: Request, order_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.cancel_order(db, o, user["label"]))


@router.post("/orders/{order_id}/close")
def close(request: Request, order_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.close_order(db, o, user["label"]))


@router.post("/orders/{order_id}/reopen")
def reopen(request: Request, order_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.reopen_order(db, o, user["label"]))


@router.post("/orders/{order_id}/delete")
def delete(request: Request, order_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    o = _get(db, order_id, user)
    return _run(request, db, o, user, lambda: svc.delete_order(db, o), to="/orders")
