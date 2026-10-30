"""The look is held together by tokens. These tests fail when a rule goes around them, so the type scale, the shape scale and the
delivery headers cannot drift without someone noticing."""
import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import STAFF, make_client, reset_db

CSS = Path("app/static/app.css").read_text(encoding="utf-8")
BODY = CSS[CSS.index("* { box-sizing"):]  # everything after the token block


def decls(prop: str) -> list[str]:
    return re.findall(rf"(?<![\w-]){prop}\s*:\s*([^;}}]+)", BODY)


def test_type_comes_only_from_the_scale():
    for value in decls("font-size"):
        assert "var(--" in value, f"raw font-size: {value}"
    for value in decls("font-weight"):
        assert "var(--" in value, f"raw font-weight: {value}"
    for value in decls("font"):
        assert "var(--t-" in value or value.strip() == "inherit", f"font outside the scale: {value}"


def test_the_scale_has_exactly_seven_roles_and_two_weights():
    roles = re.findall(r"--t-([a-z-]+):\s*(\d+)\s+(\d+)px/(\d+)px", CSS)
    assert [r[0] for r in roles] == ["title-lg", "title-md", "title-sm", "body-md", "body-sm", "label-lg", "label-md"]
    assert {r[1] for r in roles} == {"400", "500"}
    assert {r[2] for r in roles} == {"12", "14", "16", "20"}


def test_corners_come_only_from_the_shape_scale():
    for value in decls("border-radius"):
        assert not re.search(r"\d+px", value), f"raw radius: {value}"


def test_surfaces_are_flat():
    assert "gradient" not in BODY and "blur(" not in BODY
    for value in decls("box-shadow"):
        assert "oklch" not in value and not re.search(r"\d+px \d+px \d+px", value), f"a drop shadow: {value}"


def test_only_cheap_properties_are_animated():
    for value in decls("transition"):
        for part in value.split(","):
            prop = part.strip().split(" ")[0]
            assert prop in {"transform", "opacity", "background-color", "color", "box-shadow", "overlay", "display", "none"}, prop


def test_every_page_loads_only_its_own_files():
    c = TestClient(__import__("app.main", fromlist=["app"]).app, follow_redirects=False)
    with c:
        for path in ("/login", "/signup"):
            html = c.get(path).text
            assert "googleapis" not in html and "gstatic" not in html
            assert re.search(r'href="/static/app\.css\?v=[0-9a-f]{10}"', html)
            assert 'rel="preload" href="/static/fonts/roboto-var.woff2"' in html
        csp = c.get("/login").headers["content-security-policy"]
        assert "googleapis" not in csp and "gstatic" not in csp and "font-src 'self'" in csp


def test_responses_are_compressed_and_assets_are_cached_for_a_year():
    c = TestClient(__import__("app.main", fromlist=["app"]).app, follow_redirects=False)
    with c:
        page = c.get("/login", headers={"Accept-Encoding": "gzip"})
        assert page.headers["content-encoding"] == "gzip" and page.headers["cache-control"] == "no-store"
        css_url = re.search(r'href="(/static/app\.css\?v=[0-9a-f]{10})"', page.text).group(1)
        css = c.get(css_url, headers={"Accept-Encoding": "gzip"})
        assert css.headers["content-encoding"] == "gzip"
        assert css.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert c.get("/static/app.css").headers["cache-control"] == "no-cache"  # no version in the address, so revalidate
        font = c.get("/static/fonts/roboto-var.woff2")
        assert font.status_code == 200 and "immutable" in font.headers["cache-control"]


def test_the_chase_badge_counts_only_your_own_company():
    from app.db import SessionLocal
    from app.templating import chase_count
    reset_db()
    sam = make_client(STAFF, fresh=False)
    mine = chase_count({"role": "staff", "company_id": 1, "email": STAFF})
    assert mine > 0
    other = TestClient(__import__("app.main", fromlist=["app"]).app, follow_redirects=False)
    with other:
        other.post("/signup", data={"email": "fresh@co.example.com", "password": "secret1", "confirm": "secret1", "kind": "buyer", "name": "Fresh"})
        other.post("/sample-data")
    assert chase_count({"role": "staff", "company_id": 1, "email": STAFF}) == mine  # company 2's sample orders are not added
    assert chase_count({"role": "staff", "company_id": 2, "email": "fresh@co.example.com"}) > 0
    assert chase_count(None) == 0  # signed out sees nothing
    assert sam.get("/").status_code == 200


def test_there_are_no_pills_and_every_control_uses_the_same_corner_language():
    assert "--r-full" not in CSS and not re.search(r"border-radius:\s*9{3,}px", CSS)  # no pill shape anywhere
    assert re.search(r"\*\s*\{[^}]*corner-shape:\s*squircle", CSS)  # continuous corners by default
    for value in decls("border-radius"):
        assert value.strip() in {"var(--r-xs)", "var(--r-sm)", "var(--r-md)", "var(--r-lg)", "var(--r-xl)", "50%", "0"}, value
    assert "0 0" not in " ".join(decls("border-radius")).replace("0 0)", "")  # no top-only rounding on fields


def test_page_is_never_white_while_the_stylesheet_loads():
    """theme-init.js paints <html> before the first paint, app.css gives <html> a background (the cross-fade needs one),
    and the page tells the browser it is a dark page."""
    init = Path("app/static/theme-init.js").read_text(encoding="utf-8")
    assert "style.backgroundColor" in init and "#0f0f0f" in init
    assert re.search(r"^html\s*\{[^}]*background:\s*var\(--page\)", CSS, re.M)
    base = Path("app/templates/base.html").read_text(encoding="utf-8")
    assert '<meta name="color-scheme" content="dark light">' in base
