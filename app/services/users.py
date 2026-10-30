"""Sign-in, sign-up and the demo accounts. The session holds a small dict, so no page needs a query to know who is signed in.
There is no email check: this is a demo, so anyone may create an account with any address (the design note says so)."""
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import DEMO_PASSWORD, now
from app.domain.messages import short_name
from app.models import Company, Settings, User
from app.security import hash_password, verify_password
from app.services.chase import EMAIL

MIN_PASSWORD, MAX_PASSWORD = 6, 200
DEMO_COMPANY = "Company 1"

_DUMMY = hash_password("not-a-real-password")  # checked when the email is unknown, so timing does not give it away


class AccountError(ValueError):
    """A sign-up rule the user broke; the message is shown on the form."""


def first_name(email: str) -> str:
    return email.split("@")[0].split(".")[0].title()


def session_user(u: User) -> dict:
    name = first_name(u.email)
    supplier = short_name(u.name) if u.name and u.role == "supplier" else ""
    return {"id": u.id, "email": u.email, "role": u.role, "company_id": u.company_id, "name": name,
            "label": supplier or name,  # what order history shows as "who"
            "supplier": u.name if supplier else "", "company": u.company.name if u.company else ""}


def authenticate(db: Session, email: str, password: str) -> User | None:
    u = db.scalars(select(User).where(User.email == email.strip().lower())).first()
    if u is None:
        verify_password(password, _DUMMY)
        return None
    return u if verify_password(password, u.password_hash) else None


def _new_credentials(db: Session, email: str, password: str) -> str:
    email = email.strip().lower()
    if len(email) > 120 or not EMAIL.match(email):
        raise AccountError("Enter a valid email address, like you@example.com.")
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise AccountError(f"The password needs at least {MIN_PASSWORD} characters.")
    if db.scalars(select(User).where(User.email == email)).first():
        raise AccountError("That email already has an account. Sign in instead.")
    return email


def _clean_name(text: str, label: str) -> str:
    text = " ".join(text.split())
    if not 1 <= len(text) <= 60:
        raise AccountError(f"Enter {label} (up to 60 characters).")
    return text


def create_buyer(db: Session, email: str, password: str, company_name: str) -> User:
    """A new buying company, empty, with its first staff user."""
    email, company_name = _new_credentials(db, email, password), _clean_name(company_name, "your company name")
    company = Company(name=company_name, created_at=now())
    db.add(company)
    db.flush()
    db.add(Settings(company_id=company.id, data_updated_at=now()))
    user = User(email=email, password_hash=hash_password(password), role="staff", company_id=company.id, created_at=now())
    db.add(user)
    return _save(db, user)


def create_supplier(db: Session, email: str, password: str, name: str) -> User:
    """A supplier login. It sees the orders of every company that lists this email as a supplier."""
    email, name = _new_credentials(db, email, password), _clean_name(name, "your company name")
    user = User(email=email, password_hash=hash_password(password), role="supplier", name=name, created_at=now())
    db.add(user)
    return _save(db, user)


def _save(db: Session, user: User) -> User:
    try:
        db.commit()
    except IntegrityError:  # two sign-ups with the same email at the same moment
        db.rollback()
        raise AccountError("That email already has an account. Sign in instead.") from None
    return user


def ensure_demo_users(db: Session) -> str | None:
    """On an empty database: Company 1 with the demo data, its staff user (Sam) and the two supplier logins.
    Returns the password if it made them."""
    from app.seed import DEMO_SUPPLIERS, seed  # imported here: seed needs the services, which need this module
    if db.scalars(select(User)).first():
        return None
    password = DEMO_PASSWORD or secrets.token_urlsafe(9)
    digest = hash_password(password)
    company = Company(name=DEMO_COMPANY, created_at=now())
    db.add(company)
    db.flush()
    seed(db, company.id, DEMO_SUPPLIERS)
    db.add(User(email="sam@example.com", password_hash=digest, role="staff", company_id=company.id, created_at=now()))
    for name, email in DEMO_SUPPLIERS:
        db.add(User(email=email, password_hash=digest, role="supplier", name=name, created_at=now()))
    db.commit()
    return password
