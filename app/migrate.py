"""Adds columns that were introduced after a database was created. create_all() never alters an existing table,
and stock.db holds real orders, so each new column is added here with a default."""
from sqlalchemy import Engine, inspect, text

from app.domain.messages import parse_follow_up_subject

NEW_COLUMNS = {
    "outbox": {"kind": "VARCHAR NOT NULL DEFAULT ''", "order_id": "INTEGER REFERENCES \"order\" (id)",
               "follow_up_kind": "VARCHAR NOT NULL DEFAULT ''"},
    "arrival": {"by": "VARCHAR NOT NULL DEFAULT ''", "edited": "BOOLEAN NOT NULL DEFAULT 0"},
}


def ensure_current_schema(engine: Engine) -> None:
    """Companies were added after the first version. A database from before that cannot be upgraded in place, because
    every row needs an owner, so say how to start fresh instead of failing on the first page."""
    insp = inspect(engine)
    if insp.has_table("product") and "company_id" not in {c["name"] for c in insp.get_columns("product")}:
        raise RuntimeError("This database is from an older version without companies. Start fresh with: "
                           ".venv\\Scripts\\python -m app.reset  (it keeps a copy as stock.db.bak)")


def link_old_follow_ups(engine: Engine) -> None:
    """Follow-ups saved before the Outbox remembered an order get their order and kind back, read from the subject
    (domain/messages.py). The order must be in the same company. Safe to run on every start: a linked row is skipped,
    and a row that does not parse or whose order is gone is left alone."""
    insp = inspect(engine)
    if not (insp.has_table("outbox") and insp.has_table("order")):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, subject, company_id FROM outbox "
                                 "WHERE kind = 'follow-up' AND order_id IS NULL AND follow_up_kind = ''")).all()
        for mid, subject, company in rows:
            parsed = parse_follow_up_subject(subject)
            order = conn.execute(text('SELECT id FROM "order" WHERE name = :n AND company_id = :c'),
                                 {"n": parsed[1], "c": company}).scalar() if parsed else None
            if order:
                conn.execute(text("UPDATE outbox SET order_id = :o, follow_up_kind = :k WHERE id = :i"),
                             {"o": order, "k": parsed[0], "i": mid})


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
