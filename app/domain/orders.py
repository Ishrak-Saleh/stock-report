"""Order stages and overall status (section 4). Pure functions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Stages:
    placed: int
    in_production: int
    on_the_way: int
    arrived: int
    confirmed: bool
    status: str

    @property
    def to_come(self) -> int:
        return self.placed + self.in_production + self.on_the_way


def stages(units: int, *, marked_confirmed: bool, tracking_units: int, arrived: int,
           closed: bool, cancelled: bool) -> Stages:
    arrived = min(arrived, units)
    remaining = units - arrived
    on_the_way = min(tracking_units, remaining)
    rest = remaining - on_the_way
    confirmed = marked_confirmed or tracking_units > 0 or arrived > 0
    placed, in_production = (0, rest) if confirmed else (rest, 0)

    if cancelled:
        status = "cancelled"
    elif closed:
        status = "closed"
    elif remaining == 0:
        status = "received"
    elif arrived > 0:
        status = "partial"
    elif on_the_way > 0:
        status = "on the way"
    elif confirmed:
        status = "in production"
    else:
        status = "placed"

    open_order = not (cancelled or closed)  # only open orders count toward stock numbers
    return Stages(
        placed=placed if open_order else 0,
        in_production=in_production if open_order else 0,
        on_the_way=on_the_way if open_order else 0,
        arrived=arrived,
        confirmed=confirmed,
        status=status,
    )


def tracking_fits(order_units: int, existing: int, new: int) -> bool:
    return new > 0 and existing + new <= order_units
