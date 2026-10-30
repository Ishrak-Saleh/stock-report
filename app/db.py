from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import DB_URL
from app.tenancy import scope_for

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _foreign_keys_on(conn, _):
    """SQLite ignores foreign keys unless every connection asks for them."""
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_session(request: Request):
    """One session per request, limited to what the signed-in user may see (app/tenancy.py). Signed out sees nothing."""
    with SessionLocal() as session:
        session.info["scope"] = scope_for(request.session.get("user"))
        yield session
