from sqlalchemy import create_engine, inspect, text

from app.migrate import ensure_columns, link_old_follow_ups
from app.security import Throttle, hash_password, verify_password


def old_database():
    """A database made before Outbox.kind and Arrival.by existed, with a row in each."""
    e = create_engine("sqlite://")
    with e.begin() as c:
        c.execute(text('CREATE TABLE outbox (id INTEGER PRIMARY KEY, "to" VARCHAR, subject VARCHAR, body VARCHAR, at DATETIME)'))
        c.execute(text("CREATE TABLE arrival (id INTEGER PRIMARY KEY, product_id INTEGER, units INTEGER, day DATE, note VARCHAR)"))
        c.execute(text("INSERT INTO outbox VALUES (1, 'a@b.co', 's', 'b', '2026-10-01')"))
        c.execute(text("INSERT INTO arrival VALUES (1, 1, 10, '2026-10-01', '')"))
    return e


def test_new_columns_are_added_to_an_old_database_and_keep_its_rows():
    e = old_database()
    ensure_columns(e)
    cols = {c["name"] for c in inspect(e).get_columns("arrival")}
    assert {"by", "edited"} <= cols
    assert {"kind", "order_id", "follow_up_kind"} <= {c["name"] for c in inspect(e).get_columns("outbox")}
    with e.connect() as c:
        assert c.execute(text("SELECT kind, order_id, follow_up_kind FROM outbox")).one() == ("", None, "")
        assert c.execute(text("SELECT by, edited FROM arrival")).one() == ("", 0)


def test_running_the_migration_twice_changes_nothing():
    e = old_database()
    ensure_columns(e)
    ensure_columns(e)
    assert [c["name"] for c in inspect(e).get_columns("arrival")].count("by") == 1


def test_old_follow_ups_are_linked_to_their_order_by_the_subject_and_only_in_their_own_company():
    e = create_engine("sqlite://")
    with e.begin() as c:
        c.execute(text('CREATE TABLE "order" (id INTEGER PRIMARY KEY, name VARCHAR, company_id INTEGER)'))
        c.execute(text('CREATE TABLE outbox (id INTEGER PRIMARY KEY, "to" VARCHAR, subject VARCHAR, body VARCHAR, at DATETIME, '
                       "kind VARCHAR NOT NULL DEFAULT '', company_id INTEGER, order_id INTEGER, follow_up_kind VARCHAR NOT NULL DEFAULT '')"))
        c.execute(text("INSERT INTO \"order\" VALUES (1, 'KEY-001', 1), (2, 'HDP-001', 1), (3, 'MOU-001', 2)"))
        c.execute(text("INSERT INTO outbox (id, \"to\", subject, body, at, kind, company_id) VALUES "
                       "(1, 'a', 'Tracking for order KEY-001', 'b', '2026-10-30', 'follow-up', 1),"
                       "(2, 'a', 'Where is order HDP-001?', 'b', '2026-10-30', 'follow-up', 1),"
                       "(3, 'a', 'Please confirm order MOU-001', 'b', '2026-10-30', 'follow-up', 1),"  # that order is in company 2
                       "(4, 'a', 'Where is order GONE-001?', 'b', '2026-10-30', 'follow-up', 1),"      # deleted order
                       "(5, 'a', 'Test: Reorder alert: 1 product needs a reorder', 'b', '2026-10-30', 'test', 1)"))
    link_old_follow_ups(e)
    link_old_follow_ups(e)  # a second run changes nothing
    with e.connect() as c:
        got = {r[0]: (r[1], r[2]) for r in c.execute(text("SELECT id, order_id, follow_up_kind FROM outbox"))}
    assert got == {1: (1, "tracking"), 2: (2, "where"), 3: (None, ""), 4: (None, ""), 5: (None, "")}
    link_old_follow_ups(create_engine("sqlite://"))  # no tables yet: no error


def test_a_missing_table_is_left_for_create_all():
    ensure_columns(create_engine("sqlite://"))  # no error


def test_passwords_are_hashed_and_checked():
    h = hash_password("correct horse")
    assert "correct horse" not in h and h.startswith("scrypt$")
    assert verify_password("correct horse", h) and not verify_password("wrong", h)
    assert hash_password("correct horse") != h  # a new salt each time
    assert not verify_password("x", "not-a-hash") and not verify_password("x", "a$zz$zz")


def test_the_lock_opens_again_after_the_wait(monkeypatch):
    t = Throttle(tries=3, lock=300)
    clock = [1000.0]
    monkeypatch.setattr("app.security.time.time", lambda: clock[0])
    for _ in range(3):
        t.fail("a@b.co")
    assert t.locked("a@b.co") and not t.locked("other@b.co")
    clock[0] += 301
    assert not t.locked("a@b.co")
    t.fail("a@b.co")
    t.ok("a@b.co")
    assert not t.locked("a@b.co") and "a@b.co" not in t.fails
