import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo("America/Denver")
DB_URL = os.getenv("DATABASE_URL", "sqlite:///stock.db")
EMAIL_MODE = os.getenv("EMAIL_MODE", "test")  # "test" writes to the outbox and delivers nothing


def now() -> datetime:
    return datetime.now(STORE_TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()
