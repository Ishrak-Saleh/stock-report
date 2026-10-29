import os
import tempfile

# Page tests run against a throwaway database, never stock.db. This must be set before the app is imported.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='stockreport-tests-')}/test.db"
PASSWORD = "test-password-only"  # the demo accounts get this on the throwaway database
os.environ["DEMO_PASSWORD"] = PASSWORD
os.environ["SECRET_KEY"] = "test-key-only"

STAFF, ACME, NOVA = "sam@example.com", "acme@acme.example.com", "nova@nova.example.com"


def sign_in(client, email: str = STAFF, password: str = PASSWORD):
    r = client.post("/login", data={"email": email, "password": password})
    assert r.status_code == 303, r.text[:200]
    return client


def reset_db():
    """A fresh seeded database with the demo accounts. Modules that change data call this first, so test order never matters."""
    from app.db import SessionLocal, engine
    from app.models import Base
    from app.seed import seed
    from app.services.users import ensure_demo_users
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        ensure_demo_users(db)


def make_client(email: str = STAFF, fresh: bool = True):
    """A signed-in test client on a freshly reset database."""
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, follow_redirects=False)
    c.__enter__()  # runs the app startup
    if fresh:
        reset_db()
    return sign_in(c, email)
