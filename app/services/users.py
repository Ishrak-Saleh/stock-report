"""Sign-in and the demo accounts. The session holds a small dict, so no page needs a query to know who is signed in."""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_PASSWORD
from app.domain.messages import short_name
from app.models import Supplier, User
from app.security import hash_password, verify_password

_DUMMY = hash_password("not-a-real-password")  # checked when the email is unknown, so timing does not give it away


def first_name(email: str) -> str:
    return email.split("@")[0].split(".")[0].title()


def session_user(u: User) -> dict:
    name = first_name(u.email)
    supplier = short_name(u.supplier.name) if u.supplier else ""
    return {"id": u.id, "email": u.email, "role": u.role, "supplier_id": u.supplier_id, "name": name,
            "label": supplier or name,  # what order history shows as "who"
            "supplier": u.supplier.name if u.supplier else ""}


def authenticate(db: Session, email: str, password: str) -> User | None:
    u = db.scalars(select(User).where(User.email == email.strip().lower())).first()
    if u is None:
        verify_password(password, _DUMMY)
        return None
    return u if verify_password(password, u.password_hash) else None


def ensure_demo_users(db: Session) -> str | None:
    """Creates one staff and one login per supplier when there are no users. Returns the password if it made them."""
    if db.scalars(select(User)).first():
        return None
    password = DEMO_PASSWORD or secrets.token_urlsafe(9)
    digest = hash_password(password)
    db.add(User(email="sam@example.com", password_hash=digest, role="staff"))
    for s in db.scalars(select(Supplier).order_by(Supplier.id)):
        db.add(User(email=f"{s.name.split()[0].lower()}@{s.name.split()[0].lower()}.example.com",
                    password_hash=digest, role="supplier", supplier_id=s.id))
    db.commit()
    return password
