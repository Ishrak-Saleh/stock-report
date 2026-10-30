"""Adds columns that were introduced after a database was created. create_all() never alters an existing table,
and stock.db holds real orders, so each new column is added here with a default."""
from sqlalchemy import Engine, inspect, text

NEW_COLUMNS = {
    "outbox": {"kind": "VARCHAR NOT NULL DEFAULT ''"},
    "arrival": {"by": "VARCHAR NOT NULL DEFAULT ''", "edited": "BOOLEAN NOT NULL DEFAULT 0"},
}


def ensure_current_schema(engine: Engine) -> None:
    """Companies were added after the first version. A database from before that cannot be upgraded in place, because
    every row needs an owner, so say how to start fresh instead of failing on the first page."""
    insp = inspect(engine)
    if insp.has_table("product") and "company_id" not in {c["name"] for c in insp.get_columns("product")}:
        raise RuntimeError("This database is from an older version without companies. Start fresh with: "
                           ".venv\\Scripts\\python -m app.reset  (it keeps a copy as stock.db.bak)")


def ensure_columns(engine: Engine) -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
