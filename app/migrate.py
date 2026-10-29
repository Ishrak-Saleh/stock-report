"""Adds columns that were introduced after a database was created. create_all() never alters an existing table,
and stock.db holds real orders, so each new column is added here with a default."""
from sqlalchemy import Engine, inspect, text

NEW_COLUMNS = {
    "outbox": {"kind": "VARCHAR NOT NULL DEFAULT ''"},
    "arrival": {"by": "VARCHAR NOT NULL DEFAULT ''", "edited": "BOOLEAN NOT NULL DEFAULT 0"},
}


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
