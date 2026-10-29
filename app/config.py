import os
import secrets
from datetime import date, datetime
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo("America/Denver")
DB_URL = os.getenv("DATABASE_URL", "sqlite:///stock.db")
# Read from the environment, never the repo. Without SECRET_KEY, sessions end whenever the server restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD")  # None: a random one is made and printed once when the demo users are created
SESSION_HOURS = 8
STALE_DAYS = 2  # stock or sales data older than this gets a warning
EMAIL_MODE = os.getenv("EMAIL_MODE", "test")  # "test" writes to the outbox and delivers nothing
SENDER_NAME = os.getenv("SENDER_NAME", "Sam")  # signs the messages staff copy to suppliers


def now() -> datetime:
    return datetime.now(STORE_TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()
