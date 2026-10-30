from contextlib import asynccontextmanager
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import SECRET_KEY, SESSION_HOURS
from app.db import SessionLocal, engine
from app.deps import LoginRequired
from app.migrate import ensure_columns, ensure_current_schema
from app.models import Base
from app.routers import arrivals, auth, chase, dashboard, orders, products, settings
from app.services.users import ensure_demo_users
from app.templating import templates


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_current_schema(engine)
    Base.metadata.create_all(engine)
    ensure_columns(engine)
    with SessionLocal() as db:
        password = ensure_demo_users(db)
    if password:  # shown once, never stored in the repo
        print(f"\nCompany 1 and its demo accounts were created: sam@example.com (staff), acme@acme.example.com and "
              f"nova@nova.example.com (suppliers)\nPassword for all three: {password}\n", flush=True)
    yield


# No /docs, /redoc or /openapi.json: they would list every route to someone who is not signed in.
app = FastAPI(title="Stock Report", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; "
       "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")


@app.middleware("http")
async def guard(request: Request, call_next):
    """CSRF: the session cookie is SameSite=Lax, and a browser POST from another site is refused here because its
    Origin does not match this host. Every response also carries the standard security headers."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return PlainTextResponse("Cross-site request blocked.", status_code=403)
    response = await call_next(request)
    response.headers.update({
        "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
    path = request.url.path
    if not path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store"  # the Back button after signing out must not show a cached page
    elif "v" in request.query_params or path.startswith("/static/fonts/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # the address changes when the file does
    else:
        response.headers["Cache-Control"] = "no-cache"  # revalidate (a quick 304 when unchanged)
    return response


app.add_middleware(GZipMiddleware, minimum_size=500)  # compresses every page, stylesheet and script
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_HOURS * 3600, same_site="lax",
                   session_cookie="sr_session")

for module in (auth, dashboard, orders, arrivals, products, chase, settings):
    app.include_router(module.router)


# ---- errors: every one says what happened and gives a way forward ----

TITLES = {
    400: "That could not be done", 403: "That is not allowed", 404: "That page does not exist",
    409: "That can't be done right now", 422: "Check what you entered", 429: "Too many tries",
}
HINTS = {
    404: "The address may be old, or the order was deleted.",
    422: "One of the fields is missing or out of range. Go back, fix it and try again.",
}


def error_page(request: Request, code: int, message: str = ""):
    return templates.TemplateResponse(request, "error.html", {
        "code": code, "title": TITLES.get(code, "Something went wrong on our side"),
        "message": message or HINTS.get(code, "Nothing was changed. Try again in a moment.")}, status_code=code)


@app.exception_handler(LoginRequired)
async def login_required(request: Request, _: LoginRequired):
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    if request.method != "GET":
        return RedirectResponse("/login", status_code=303)
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return error_page(request, exc.status_code, str(exc.detail) if exc.status_code in (403, 409) else "")


@app.exception_handler(RequestValidationError)
async def invalid(request: Request, _: RequestValidationError):
    return error_page(request, 422)
