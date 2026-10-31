from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import EMAIL_MODE, now, today
from app.db import get_session
from app.deps import require_staff
from app.models import Order, Outbox
from app.services import chase as svc
from app.services.products import get_settings
from app.templating import templates

router = APIRouter()
KIND_LABELS = {"confirm": "Ask to confirm", "tracking": "Ask for tracking", "where": "Ask where it is"}


def _page(request: Request, db: Session, kind: str = "", error: str = "", code: int = 200):
    due, quiet = svc.chase_list(db, today())
    shown = [c for c in due if not kind or c.row.chase.kind == kind]
    late = sum(1 for c in due if c.row.chase.over >= 8)
    return templates.TemplateResponse(request, "chase.html", {
        "due": shown, "quiet": quiet, "all_due": len(due), "kind": kind if kind in KIND_LABELS else "", "error": error,
        "counts": {k: sum(1 for c in due if c.row.chase.kind == k) for k in KIND_LABELS}, "late": late,
        "labels": KIND_LABELS, "total": len(due) + len(quiet), "settings": get_settings(db)}, status_code=code)


@router.get("/chase", response_class=HTMLResponse)
def chase(request: Request, kind: str = "", user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    return _page(request, db, kind)


@router.post("/chase/send-all")
def send_all(request: Request, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    try:
        svc.add_all_due(db, today(), user["label"])
    except svc.ChaseError as e:
        db.rollback()
        return _page(request, db, error=str(e), code=400)
    return RedirectResponse("/outbox", status_code=303)


@router.post("/chase/{order_id}/outbox")
def add_one(request: Request, order_id: int, kind: str = Form(pattern="^(confirm|tracking|where)$"),
            user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    try:
        svc.add_follow_up(db, o, kind, today(), user["label"])
    except svc.ChaseError as e:
        db.rollback()
        return _page(request, db, error=str(e), code=400)
    return RedirectResponse("/outbox", status_code=303)


@router.get("/outbox", response_class=HTMLResponse)
def outbox(request: Request, kind: str = "", user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    kind = kind if kind in svc.KINDS else ""
    everything = svc.outbox(db)
    t = now().date()
    rows = svc.outbox(db, kind)
    return templates.TemplateResponse(request, "outbox.html", {
        "rows": rows, "waits": svc.waits_for(db, rows, today()), "kind": kind, "kinds": svc.KINDS, "total": len(everything),
        "today_n": sum(1 for m in everything if m.at.date() == t), "mode": EMAIL_MODE,
        "counts": {k: sum(1 for m in everything if m.kind == k) for k in svc.KINDS}})


@router.get("/outbox/{message_id}", response_class=HTMLResponse)
def outbox_message(request: Request, message_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    m = db.get(Outbox, message_id)
    if not m:
        raise HTTPException(404, "Message not found")
    return templates.TemplateResponse(request, "partials/dlg_outbox.html", {
        "m": m, "kinds": svc.KINDS, "wait": svc.wait_for(db, m, today())})


@router.get("/outbox/{message_id}/delete", response_class=HTMLResponse)
def outbox_delete_dialog(request: Request, message_id: int, user: dict = Depends(require_staff),
                         db: Session = Depends(get_session)):
    m = db.get(Outbox, message_id)
    if not m:
        raise HTTPException(404, "Message not found")
    return templates.TemplateResponse(request, "partials/dlg_outbox_delete.html", {
        "m": m, "resets": m.kind == "follow-up" and m.order_id is not None})


@router.post("/outbox/{message_id}/delete")
def outbox_delete(message_id: int, user: dict = Depends(require_staff), db: Session = Depends(get_session)):
    m = db.get(Outbox, message_id)
    if not m:
        raise HTTPException(404, "Message not found")
    svc.delete_message(db, m, user["label"])
    return RedirectResponse("/outbox", status_code=303)
