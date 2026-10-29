"""Who is signed in, and what they may do. Staff may do everything; a supplier only sees their own orders,
confirms them and adds tracking. The routes say which; the services filter by supplier, so a hidden button is never
the only protection."""
from fastapi import Depends, HTTPException, Request


class LoginRequired(Exception):
    pass


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise LoginRequired
    return user


def require_staff(user: dict = Depends(require_user)) -> dict:
    if user["role"] != "staff":
        raise HTTPException(403, "Only staff can open this page.")
    return user


def is_staff(user: dict) -> bool:
    return user["role"] == "staff"
