"""Plain-text messages and the short sentences the pages show. Pure functions."""
from urllib.parse import quote

from app.domain.chase import Chase


def short_name(supplier: str) -> str:
    return supplier.split()[0] if supplier.strip() else supplier


def chase_step(chase: Chase, supplier: str) -> tuple[str, str]:
    """(what to do, why) for the Next step column and the chase list."""
    s = short_name(supplier)
    if chase.kind == "confirm":
        return f"Ask {s} to confirm", f"Placed {chase.days} days ago"
    if chase.kind == "tracking":
        return f"Ask {s} for tracking", f"Confirmed {chase.days} days ago, no tracking"
    return f"Ask {s} where it is", f"On the way {chase.days} days"


WAITING = {
    "placed": "Waiting for confirmation",
    "in production": "Waiting for tracking",
    "on the way": "Waiting for arrival",
    "partial": "Waiting for the rest",
}


def quiet_step(status: str) -> tuple[str, str, str]:
    """(tone, what, why) for an order with nothing to chase."""
    if status == "received":
        return "ok", "Complete", "All units arrived"
    if status in ("closed", "cancelled"):
        return "idle", status.capitalize(), "No longer counts as ordered"
    return "idle", WAITING[status], "Nothing to chase yet"


def takeaway(*, status: str, units: int, arrived: int, remaining: int, on_the_way: int, untracked: int,
             chase: Chase | None, supplier: str) -> str:
    """The one sentence an order page leads with."""
    s = short_name(supplier)
    if status == "cancelled":
        return "This order is cancelled. It no longer counts as ordered."
    if status == "closed":
        return f"This order is closed. The {units - arrived:,} units that never arrived no longer count as ordered."
    if status == "received":
        return f"All {units:,} units arrived. Nothing left to do."
    if chase and chase.kind == "where":
        return f"{on_the_way:,} units shipped {chase.days} days ago and haven't arrived. Ask {s} where it is."
    if chase and chase.kind == "tracking":
        return (f"Confirmed {chase.days} days ago, but {untracked:,} of {units:,} units have no tracking. "
                f"Ask {s} for tracking numbers.")
    if chase:
        return f"Placed {chase.days} days ago and still not confirmed. Ask {s} to confirm."
    return f"{remaining:,} units are still to come. Nothing to chase yet."


def supplier_takeaway(*, status: str, units: int, arrived: int, confirmed: bool, untracked: int) -> str:
    """The one sentence a supplier's order page leads with: what, if anything, the supplier owes."""
    if status in ("cancelled", "closed"):
        return f"This order is {status}. Nothing more is needed from you."
    if status == "received":
        return f"All {units:,} units arrived. Nothing more is needed from you."
    if not confirmed:
        return f"Please confirm this order of {units:,} units."
    if untracked > 0 and arrived < units:
        return f"Please add tracking for the {min(untracked, units - arrived):,} units that have none."
    return "Everything is confirmed and tracked. Nothing is waiting on you."


def order_message(*, supplier: str, order: str, product: str, code: str, units: int, notes: str, sender: str) -> str:
    lines = [f"Hi {short_name(supplier)},", "", "Please confirm this order:", "", f"Order: {order}",
             f"Product: {product} ({code})", f"Units: {units:,}"]
    if notes:
        lines.append(f"Notes: {notes}")
    lines += ["", "Please reply to confirm, and send tracking numbers when it ships.", "", "Thanks,", sender]
    return "\n".join(lines)


def order_subject(order: str) -> str:
    return f"New order {order}"


def mailto_link(to: str, subject: str, body: str) -> str:
    """A link that opens the user's own mail app with the message filled in. Nothing is sent from here.
    Spaces and new lines are percent-encoded (not '+'), because mail apps show a '+' as a plus sign."""
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject, safe='')}&body={quote(body, safe='')}"


def gmail_link(to: str, subject: str, body: str) -> str:
    """Opens a Gmail compose window in the browser with the message filled in. The user presses Send there; the app
    sends nothing and talks to no one. Every value is percent-encoded so '&', '?', '+' and new lines survive."""
    return ("https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={quote(to, safe='')}&su={quote(subject, safe='')}&body={quote(body, safe='')}")


def follow_up_subject(chase: Chase, order: str) -> str:
    return {"confirm": f"Please confirm order {order}", "tracking": f"Tracking for order {order}"}.get(
        chase.kind, f"Where is order {order}?")


def parse_follow_up_subject(subject: str) -> tuple[str, str] | None:
    """(kind, order name) read back from a subject that follow_up_subject wrote, or None. It lets follow-ups saved
    before the Outbox remembered an order be linked to theirs."""
    for kind, (start, end) in {"confirm": ("Please confirm order ", ""), "tracking": ("Tracking for order ", ""),
                               "where": ("Where is order ", "?")}.items():
        if subject.startswith(start) and subject.endswith(end) and len(subject) > len(start) + len(end):
            return kind, subject[len(start):len(subject) - len(end)]
    return None


def reorder_alert(items: list[tuple[str, float | None, int]], sender: str) -> tuple[str, str]:
    """(subject, body) for the reorder alert. items are (product, days with everything ordered, suggested units)."""
    n = len(items)
    subject = f"Reorder alert: {n} product{'s' if n != 1 else ''} need{'s' if n == 1 else ''} a reorder" if n else \
        "Reorder alert: nothing needs a reorder"
    lines = ["Hello,", ""]
    if n:
        lines.append("These products are under their reorder line, counting everything already on order:")
        lines.append("")
        lines += [f"- {name}: {'no sales' if days is None else f'{days:.1f} days'} left, suggested order {units:,} units"
                  for name, days, units in items]
    else:
        lines.append("No product is under its reorder line today.")
    return subject, "\n".join(lines + ["", "Thanks,", sender])


def follow_up(chase: Chase, *, supplier: str, order: str, product: str, units: int, untracked: int,
              tracking_number: str, created_days: int, sender: str) -> str:
    s = short_name(supplier)
    if chase.kind == "confirm":
        body = (f"Could you confirm order {order}? We placed it {created_days} days ago for {units:,} units of {product}.")
    elif chase.kind == "tracking":
        body = (f"Order {order} was confirmed {chase.days} days ago, but we have no tracking for {untracked:,} of "
                f"{units:,} units. Could you send tracking numbers?")
    else:
        body = (f"Order {order} shipped {chase.days} days ago (tracking {tracking_number}) and has not arrived. "
                "Do you know where it is?")
    return f"Hi {s},\n\n{body}\n\nThanks,\n{sender}"
