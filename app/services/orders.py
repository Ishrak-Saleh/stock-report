from app.domain.orders import Stages, stages
from app.models import Order


def order_stages(o: Order) -> Stages:
    return stages(
        o.units,
        marked_confirmed=o.confirmed_at is not None,
        tracking_units=sum(t.units for t in o.trackings),
        arrived=sum(a.units for a in o.allocations),
        closed=o.closed,
        cancelled=o.cancelled,
    )
