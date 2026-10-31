import html as htmllib
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import now
from app.db import SessionLocal
from app.models import AlertLog, Order, Outbox
from tests.conftest import make_client


@pytest.fixture
def client():
    c = make_client()
    yield c
    c.__exit__(None, None, None)


def text(r) -> str:
    return htmllib.unescape(r.text)


def oid(name: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Order).where(Order.name == name)).one().id


def add(client, name: str, kind: str):
    return client.post(f"/chase/{oid(name)}/outbox", data={"kind": kind})


def test_the_list_is_ranked_by_days_past_the_limit(client):
    t = text(client.get("/chase"))
    assert "5 orders need chasing, and 5 are due a message today." in t
    assert "2 are more than a week past the limit." in t
    due = t.split("Due now")[1]
    assert due.index("HDP-001") < due.index("KEY-001") < due.index("MOU-001") < due.index("PHN-001") < due.index("MOU-002")
    assert "Ask where it is" in t and "Ask for tracking" in t and "Ask to confirm" in t
    assert t.count("btn primary") == 1 and "Add 5 messages to the Outbox" in t


def test_the_filter_by_alert_type(client):
    t = text(client.get("/chase?kind=tracking"))
    due = t.split("Due now")[1].split("The three rules")[0]
    assert "KEY-001" in due and "PHN-001" in due and "HDP-001" not in due


def test_adding_one_follow_up_saves_it_and_starts_the_2_day_wait(client):
    r = add(client, "KEY-001", "tracking")
    assert r.status_code == 303 and r.headers["location"] == "/outbox"
    with SessionLocal() as db:
        m = db.scalars(select(Outbox)).one()
        assert m.to == "nova@nova.example.com" and m.subject == "Tracking for order KEY-001" and m.kind == "follow-up"
        assert "Hi Nova," in m.body and "200 of 200" in m.body
        o = db.scalars(select(Order).where(Order.name == "KEY-001")).one()
        assert o.events[-1].action == "follow-up saved" and o.events[-1].by == "Sam"
    t = text(client.get("/chase"))
    assert "5 orders need chasing, and 4 are due a message today." in t
    assert "Chased recently" in t and "Can be sent again on" in t
    assert "Add 4 messages to the Outbox" in t


def test_the_same_reason_cannot_be_sent_twice_in_2_days(client):
    add(client, "KEY-001", "tracking")
    r = add(client, "KEY-001", "tracking")
    assert r.status_code == 400 and "was chased on" in text(r) and "can be sent again on" in text(r)
    with SessionLocal() as db:
        assert len(db.scalars(select(Outbox)).all()) == 1


def test_after_2_days_the_alert_is_due_again(client):
    add(client, "KEY-001", "tracking")
    with SessionLocal() as db:
        db.scalars(select(AlertLog)).one().last_sent_at = now() - timedelta(days=2)
        db.commit()
    assert "5 are due a message today" in text(client.get("/chase"))
    assert add(client, "KEY-001", "tracking").status_code == 303
    with SessionLocal() as db:
        assert len(db.scalars(select(AlertLog)).all()) == 1  # the log is updated, not duplicated
        assert len(db.scalars(select(Outbox)).all()) == 2


def test_a_message_the_order_does_not_need_is_refused(client):
    r = add(client, "KEY-001", "where")
    assert r.status_code == 400 and "doesn't need that message right now" in text(r)
    assert client.post(f"/chase/{oid('KEY-001')}/outbox", data={"kind": "bogus"}).status_code == 422
    assert client.post("/chase/9999/outbox", data={"kind": "where"}).status_code == 404


def test_send_all_saves_every_due_message_once(client):
    assert client.post("/chase/send-all").status_code == 303
    with SessionLocal() as db:
        subjects = sorted(m.subject for m in db.scalars(select(Outbox)))
    assert subjects == sorted(["Please confirm order MOU-002", "Tracking for order PHN-001", "Tracking for order KEY-001",
                               "Where is order MOU-001?", "Where is order HDP-001?"])
    t = text(client.get("/chase"))
    assert "5 orders need chasing, and 0 are due a message today." in t
    assert "Nothing is due until the next reminder date" in t and "5 orders were chased in the last 2 days." in t
    assert t.count("Can be sent again on") == 5  # all five wait in "Chased recently"
    assert "Add 0 messages" in t and "disabled" in t
    assert client.post("/chase/send-all").status_code == 303
    with SessionLocal() as db:
        assert len(db.scalars(select(Outbox)).all()) == 5  # a second click adds nothing


def test_the_outbox_lists_and_opens_messages(client):
    client.post("/chase/send-all")
    t = text(client.get("/outbox"))
    assert "5 messages saved today." in t and "None were delivered, because test mode is on." in t
    assert "Where is order HDP-001?" in t and "nova@nova.example.com" in t
    only = text(client.get("/outbox?kind=test"))
    assert "No messages of this kind" in only
    with SessionLocal() as db:
        mid = db.scalars(select(Outbox).where(Outbox.subject == "Where is order HDP-001?")).one().id
    d = text(client.get(f"/outbox/{mid}", headers={"HX-Request": "true"}))
    assert "<dialog" in d and "has not arrived" in d and "Test mode" in d
    assert client.get("/outbox/9999").status_code == 404


def test_an_empty_outbox_says_so(client):
    t = text(client.get("/outbox"))
    assert "0 messages saved today." in t and "No messages saved yet" in t


def test_the_preview_dialog_offers_the_outbox_for_chase_messages_only(client):
    gid = oid("MOU-002")
    chase = text(client.get(f"/orders/{gid}/dialog/message?kind=confirm"))
    assert "Add to Outbox" in chase and f"/chase/{gid}/outbox" in chase
    plain = text(client.get(f"/orders/{gid}/dialog/message?kind=order"))
    assert "Add to Outbox" not in plain and "Please confirm this order" in plain


def test_the_more_menu_shows_how_many_are_due(client):
    t = text(client.get("/arrivals"))
    assert 'badge crit count' in t and ">5</span>" in t
    client.post("/chase/send-all")
    assert "badge crit count" not in text(client.get("/arrivals"))


def outbox_id(subject: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(Outbox).where(Outbox.subject == subject)).one().id


def test_the_chase_list_counts_down_the_2_day_wait(client):
    add(client, "KEY-001", "tracking")
    t = text(client.get("/chase"))
    assert "2 days left" in t and "Can be sent again on" in t
    with SessionLocal() as db:
        db.scalars(select(AlertLog)).one().last_sent_at = now() - timedelta(days=1)
        db.commit()
    assert "1 day left" in text(client.get("/chase"))


def test_the_outbox_list_shows_the_days_left_for_each_follow_up(client):
    add(client, "KEY-001", "tracking")
    with SessionLocal() as db:  # a test message and an old follow-up that never knew its order
        db.add_all([Outbox(company_id=1, to="a@example.com", subject="Test: alert", body="b", at=now(), kind="test"),
                    Outbox(company_id=1, to="nova@nova.example.com", subject="Old follow-up", body="b", at=now(),
                           kind="follow-up")])
        db.commit()
    t = text(client.get("/outbox"))
    assert "Wait" in t and "2 days left" in t and "until " in t and t.count("days left") == 1
    assert "Test: alert" in t and "Old follow-up" in t and "Can be chased now" not in t
    with SessionLocal() as db:
        log = db.scalars(select(AlertLog)).one()
        log.last_sent_at = now() - timedelta(days=1)
        db.commit()
    assert "1 day left" in text(client.get("/outbox"))
    with SessionLocal() as db:
        log = db.scalars(select(AlertLog)).one()
        log.last_sent_at = now() - timedelta(days=3)
        db.commit()
    t = text(client.get("/outbox"))
    assert "Can be chased now" in t and "days left" not in t


def test_a_follow_up_saved_before_orders_were_remembered_gets_its_timer_after_the_upgrade(client):
    from app.db import engine
    from app.migrate import link_old_follow_ups
    add(client, "KEY-001", "tracking")
    with SessionLocal() as db:  # make it look like an old message
        m = db.scalars(select(Outbox)).one()
        m.order_id, m.follow_up_kind = None, ""
        db.commit()
    assert "2 days left" not in text(client.get("/outbox"))
    link_old_follow_ups(engine)
    t = text(client.get("/outbox"))
    assert "2 days left" in t
    with SessionLocal() as db:
        m = db.scalars(select(Outbox)).one()
        assert m.order_id == oid("KEY-001") and m.follow_up_kind == "tracking"


def test_the_outbox_list_asks_for_one_extra_query_however_many_rows(client):
    from sqlalchemy import event

    from app.db import engine
    for name in ("KEY-001", "HDP-001"):
        add(client, name, "tracking" if name == "KEY-001" else "where")
    counts = []

    def count(*_):
        counts[-1] += 1
    event.listen(engine, "before_cursor_execute", count)
    try:
        counts.append(0)
        client.get("/outbox")
        two = counts[-1]
        client.post("/chase/send-all")
        counts.append(0)
        client.get("/outbox")
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert counts[-1] <= two + 1  # more rows, at most the same queries (the log is read once for the whole list)


def test_a_saved_follow_up_shows_how_long_the_wait_has_left_and_remembers_its_order(client):
    add(client, "KEY-001", "tracking")
    with SessionLocal() as db:
        m = db.scalars(select(Outbox)).one()
        assert m.order_id == oid("KEY-001") and m.follow_up_kind == "tracking"
    d = text(client.get(f"/outbox/{outbox_id('Tracking for order KEY-001')}"))
    assert "2 days left" in d and "Delete" in d
    with SessionLocal() as db:
        db.scalars(select(AlertLog)).one().last_sent_at = now() - timedelta(days=3)
        db.commit()
    assert "No wait left" in text(client.get(f"/outbox/{outbox_id('Tracking for order KEY-001')}"))


def test_deleting_a_follow_up_clears_the_wait_and_the_order_is_due_again(client):
    add(client, "KEY-001", "tracking")
    mid = outbox_id("Tracking for order KEY-001")
    assert "wait for this order is cleared" in text(client.get(f"/outbox/{mid}/delete"))
    r = client.post(f"/outbox/{mid}/delete")
    assert r.status_code == 303 and r.headers["location"] == "/outbox"
    with SessionLocal() as db:
        assert not db.scalars(select(Outbox)).all() and not db.scalars(select(AlertLog)).all()
        o = db.scalars(select(Order).where(Order.name == "KEY-001")).one()
        assert o.events[-1].action == "follow-up removed" and o.events[-1].by == "Sam"
    assert "5 orders need chasing, and 5 are due a message today." in text(client.get("/chase"))
    assert add(client, "KEY-001", "tracking").status_code == 303  # it can be sent right away


def test_deleting_the_older_of_two_follow_ups_keeps_the_wait_and_the_newer_resets_it_to_the_older(client):
    add(client, "KEY-001", "tracking")
    with SessionLocal() as db:
        db.scalars(select(Outbox)).one().at = now() - timedelta(days=3)
        db.scalars(select(AlertLog)).one().last_sent_at = now() - timedelta(days=3)
        db.commit()
    add(client, "KEY-001", "tracking")
    with SessionLocal() as db:
        old, new = sorted(db.scalars(select(Outbox)), key=lambda m: m.at)
        old_id, new_id, old_at = old.id, new.id, old.at
    client.post(f"/outbox/{old_id}/delete")
    with SessionLocal() as db:
        assert db.scalars(select(AlertLog)).one().last_sent_at.date() == now().date()  # still waiting
    add_again = add(client, "KEY-001", "tracking")
    assert add_again.status_code == 400
    with SessionLocal() as db:  # put the older one back, then delete the newer
        db.add(Outbox(to="x@example.com", subject="older", body="b", at=old_at, kind="follow-up",
                      company_id=1, order_id=oid("KEY-001"), follow_up_kind="tracking"))
        db.commit()
    client.post(f"/outbox/{new_id}/delete")
    with SessionLocal() as db:
        assert db.scalars(select(AlertLog)).one().last_sent_at == old_at
    assert "5 are due a message today" in text(client.get("/chase"))  # 3 days old: due again


def test_deleting_an_alert_or_an_old_message_changes_no_order(client):
    with SessionLocal() as db:
        db.add_all([Outbox(company_id=1, to="a@example.com", subject="Test: alert", body="b", at=now(), kind="test"),
                    Outbox(company_id=1, to="nova@nova.example.com", subject="Old follow-up", body="b", at=now(), kind="follow-up")])
        db.commit()
    for subject, words in [("Test: alert", "Nothing was delivered"), ("Old follow-up", "Nothing was delivered")]:
        mid = outbox_id(subject)
        assert words in text(client.get(f"/outbox/{mid}/delete"))
        assert client.post(f"/outbox/{mid}/delete").status_code == 303
    with SessionLocal() as db:
        assert not db.scalars(select(Outbox)).all()
    assert client.post("/outbox/9999/delete").status_code == 404 and client.get("/outbox/9999/delete").status_code == 404


def test_only_staff_can_delete_outbox_messages_and_deleting_an_order_keeps_its_messages(client):
    add(client, "KEY-001", "tracking")
    mid = outbox_id("Tracking for order KEY-001")
    from tests.conftest import ACME
    supplier = make_client(ACME, fresh=False)
    assert supplier.post(f"/outbox/{mid}/delete").status_code in (302, 303, 403)
    assert supplier.get(f"/outbox/{mid}/delete").status_code in (302, 303, 403)
    with SessionLocal() as db:
        assert len(db.scalars(select(Outbox)).all()) == 1
    assert client.post(f"/orders/{oid('KEY-001')}/delete").status_code == 303
    with SessionLocal() as db:
        assert db.scalars(select(Outbox)).one().order_id is None  # the message stays, as a record


def test_deleting_an_order_clears_its_chase_log(client):
    gid = oid("MOU-002")
    add(client, "MOU-002", "confirm")
    assert client.post(f"/orders/{gid}/delete").status_code == 303
    with SessionLocal() as db:
        assert not db.scalars(select(AlertLog).where(AlertLog.order_id == gid)).all()
