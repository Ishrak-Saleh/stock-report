"""A one-time message for the page a button sends you to: what happened and where to check it.
It rides in the signed session cookie, is read once by the page after the redirect, and is gone on the next page."""
from fastapi import Request


def flash(request: Request, text: str, href: str = "", label: str = "") -> None:
    """Keep one message for the next page. href must be a path on this site, so a message can never link outside."""
    if href and (not href.startswith("/") or href.startswith("//")):
        href = label = ""
    request.session["flash"] = {"text": text, "href": href, "label": label}


def pop_flash(request: Request) -> dict | None:
    """The waiting message, removed so it shows once. None on a request with no session (error pages)."""
    session = request.scope.get("session")
    return session.pop("flash", None) if session else None
