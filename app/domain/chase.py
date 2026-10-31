"""Chase rules (SOP section 4). Pure functions: the caller works out the day counts, so `today` never appears here."""
from dataclasses import dataclass

CONFIRM_AFTER = 2    # not confirmed 2 or more days after ordering
TRACKING_AFTER = 10  # confirmed 10 or more days ago, with units still without tracking
WHERE_AFTER = 10     # on the way MORE than 10 days
REPEAT_EVERY = 2     # an alert repeats at most every 2 days while its reason still applies


@dataclass(frozen=True)
class Chase:
    kind: str       # confirm | tracking | where
    days: int       # how long it has waited
    threshold: int  # the SOP limit for this rule
    over: int       # days past the limit, used to rank the list


def chase_of(*, is_open: bool, remaining: int, confirmed: bool, created_days: int, confirmed_days: int | None,
             untracked: int, on_the_way: int, oldest_shipped_days: int) -> Chase | None:
    """The most overdue reason to chase an order, or None."""
    if not is_open or remaining <= 0:
        return None
    best: Chase | None = None

    def consider(kind: str, days: int, threshold: int, applies: bool, strict: bool = False) -> None:
        nonlocal best
        hit = days > threshold if strict else days >= threshold
        if applies and hit and (best is None or days - threshold > best.over):
            best = Chase(kind, days, threshold, days - threshold)

    consider("confirm", created_days, CONFIRM_AFTER, not confirmed)
    consider("tracking", confirmed_days or 0, TRACKING_AFTER, confirmed and confirmed_days is not None and untracked > 0)
    consider("where", oldest_shipped_days, WHERE_AFTER, on_the_way > 0, strict=True)
    return best


def due_again(last_sent_days_ago: int | None) -> bool:
    """True when a follow-up for this reason may be sent (or shown as due) again."""
    return last_sent_days_ago is None or last_sent_days_ago >= REPEAT_EVERY


def days_until_again(last_sent_days_ago: int) -> int:
    """Days left on the wait: 2 the day it was sent, 1 the next day, 0 once it may be sent again."""
    return max(0, REPEAT_EVERY - last_sent_days_ago)
