from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.security import throttle
from app.services.users import authenticate, session_user
from app.templating import templates

router = APIRouter()


def home_for(user: dict) -> str:
    return "/" if user["role"] == "staff" else "/orders"


def safe_next(target: str) -> str:
    """Only same-site paths, so a login link cannot send someone to another site."""
    return target if target.startswith("/") and not target.startswith("//") and "\\" not in target else ""


def _form(request: Request, *, email: str = "", error: str = "", locked: bool = False, nxt: str = "", status: int = 200):
    return templates.TemplateResponse(request, "login.html", {
        "email": email, "error": error, "locked": locked, "next": safe_next(nxt)}, status_code=status)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = ""):
    user = request.session.get("user")
    return RedirectResponse(home_for(user), status_code=303) if user else _form(request, nxt=next)


@router.post("/login")
def login(request: Request, email: str = Form(max_length=200), password: str = Form(max_length=200),
          next: str = Form(""), db: Session = Depends(get_session)):
    key = email.strip().lower()
    if throttle.locked(key):
        return _form(request, email=email, locked=True, nxt=next, status=429)
    u = authenticate(db, key, password)
    if u is None:
        throttle.fail(key)
        return _form(request, email=email, error="The email or password is not right. Check both and try again.",
                     nxt=next, status=400)
    throttle.ok(key)
    request.session.clear()  # a fresh session on every sign-in
    request.session["user"] = session_user(u)
    return RedirectResponse(safe_next(next) or home_for(request.session["user"]), status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
