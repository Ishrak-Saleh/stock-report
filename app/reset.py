"""Starts fresh: copies the database to a backup, then rebuilds it with Company 1 and the demo accounts.
Run it with the server stopped:  python -m app.reset"""
import filecmp
import shutil
import sys
from datetime import datetime
from pathlib import Path

from app.db import SessionLocal, engine
from app.models import Base
from app.services.users import ensure_demo_users


def main() -> None:
    path = Path(engine.url.database or "")
    if engine.url.get_backend_name() != "sqlite" or not path.name:
        sys.exit("This only resets a SQLite file database.")
    engine.dispose()
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        if backup.exists() and not filecmp.cmp(path, backup, shallow=False):  # never overwrite a different, older backup
            backup = path.with_name(f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        try:
            path.unlink()
        except PermissionError:
            sys.exit(f"{path} is open in a running server. Stop the server first, then run this again. "
                     f"Nothing was changed; the backup is {backup}.")
        print(f"Kept a copy of the old database as {backup}")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        password = ensure_demo_users(db)
    print("Created Company 1 with demo data: sam@example.com (staff), acme@acme.example.com and nova@nova.example.com "
          f"(suppliers)\nPassword for all three: {password}\nSet DEMO_PASSWORD first to choose it.")


if __name__ == "__main__":
    main()
