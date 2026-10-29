from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _foreign_keys_on(conn, _):
    """SQLite ignores foreign keys unless every connection asks for them."""
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_session():
    with SessionLocal() as session:
        yield session
