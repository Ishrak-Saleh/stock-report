from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.forecast import LEVEL_RANK, Flag, Forecast, Option, Params, compute, main_flag, order_options
from app.domain.orders import expected_arrival
from app.domain.runway import Gap, Landing, Runway, gap_of, landing_day, project
from app.models import Order, Product, Settings
from app.services.orders import is_open, order_stages

SPARK_DAYS = 40


@dataclass
class ProductRow:
    product: Product
    forecast: Forecast
    params: Params
    placed: int
    in_production: int
    on_the_way: int
    flag: Flag
    spark: list[int]  # daily sales, oldest to newest, ending yesterday
    runway: Runway | None = None  # stock over the lead time on the current orders; None with no sales
    gap: Gap | None = None        # empty days before a new order placed today could land (the lead time); None when none
    gap_lands_on: date | None = None  # the day the first order after the gap starts is expected (an estimate)

    @property
    def ordered(self) -> int:
        return self.placed + self.in_production + self.on_the_way

    @property
    def rank(self) -> tuple[int, float]:
        d = self.forecast.days_of_stock
        return LEVEL_RANK[self.flag.level], float("inf") if d is None else d

    @property
    def reorder_line(self) -> int:
        return self.params.lead_time + self.params.safety_days

    def options(self) -> list[Option]:
        return order_options(self.product.stock, self.ordered, self.forecast, self.params)


def get_settings(db: Session, company_id: int | None = None) -> Settings:
    """The company's settings. A staff session has exactly one row in view; a supplier, who can see several companies'
    rows, says which company it means."""
    q = select(Settings)
    if company_id is not None:
        q = q.where(Settings.company_id == company_id)
    return db.scalars(q).one()


def params_for(p: Product, s: Settings) -> Params:
    return Params(
        lead_time=p.lead_time if p.lead_time is not None else s.lead_time,
        safety_days=p.safety_days if p.safety_days is not None else s.safety_days,
        target_days=p.target_days if p.target_days is not None else s.target_days,
    )


def open_landings(p: Product, lead_time: int, today: date) -> list[Landing]:
    """When each open order is expected to land (order date plus lead time: an assumption) and how many units are to come."""
    out = []
    for o in p.orders:
        st = order_stages(o)
        if is_open(o) and st.to_come > 0:
            out.append(Landing(landing_day(expected_arrival(o.created_at.date(), lead_time), today), st.to_come, o.name))
    return out


def product_row(db: Session, p: Product, s: Settings, today: date) -> ProductRow:
    daily = {d.day: d.units for d in p.sales}
    st = [order_stages(o) for o in p.orders]
    placed, prod, way = (sum(getattr(x, k) for x in st) for k in ("placed", "in_production", "on_the_way"))
    params = params_for(p, s)
    f = compute(daily, p.stock, placed + prod + way, today, params)
    spark = [daily.get(today - timedelta(days=i), 0) for i in range(SPARK_DAYS, 0, -1)]
    runway = gap = None
    if f.adjusted_burn > 0:
        landings = open_landings(p, params.lead_time, today)
        window = max(1, params.lead_time)  # an order placed today lands then, so only empty days before it are unavoidable
        runway = project(p.stock, f.adjusted_burn, landings, window)
        gap = gap_of(runway, landings, window)
    lands_on = today + timedelta(days=gap.first_landing.day) if gap and gap.first_landing else None
    return ProductRow(p, f, params, placed, prod, way, main_flag(f), spark, runway, gap, lands_on)


def gap_risk(rows: list[ProductRow]) -> dict[int, tuple[Runway, int]]:
    """product id -> (stock projection, lead time) for the products that sell: what list_orders needs to say how many
    empty days open up before each order lands. Staff only: a supplier session cannot see the other orders."""
    return {r.product.id: (r.runway, r.params.lead_time) for r in rows if r.runway is not None}


def report(db: Session, today: date) -> list[ProductRow]:
    """Every product, most urgent first."""
    s = get_settings(db)
    # One query each for the sales, orders, tracking and arrivals of every product, instead of four per product.
    load = (selectinload(Product.sales), selectinload(Product.orders).selectinload(Order.trackings),
            selectinload(Product.orders).selectinload(Order.allocations))
    rows = [product_row(db, p, s, today) for p in db.scalars(select(Product).options(*load))]
    return sorted(rows, key=lambda r: (r.rank, r.product.name))


@dataclass
class Headline:
    text: str
    sub: str
    top: ProductRow | None  # the most urgent product that needs a reorder


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def stock_headline(rows: list[ProductRow]) -> Headline:
    if not rows:
        return Headline("No products yet.", "Add your first product to see what to reorder.", None)
    need = [r for r in rows if r.forecast.reorder_now]
    out = [r.product.name for r in rows if r.forecast.out_of_stock]
    if need:
        text = f"{len(need)} product{'s' if len(need) != 1 else ''} need{'s' if len(need) == 1 else ''} a reorder"
        if out:
            text += f", and {_join(out)} {'is' if len(out) == 1 else 'are'} out"
        text += "."
    else:
        text = "No product needs a reorder."
        if out:
            text += f" {_join(out)} {'is' if len(out) == 1 else 'are'} out of stock."
    total = sum(r.forecast.suggested_order for r in need)
    empty = sum(1 for r in rows if r.gap)  # products that will have days with no stock before a new order could land
    sub = " ".join(x for x in (f"Suggested order: {total:,} units." if need else "",
                               f"{empty} will have days with no stock." if empty else "") if x)
    return Headline(text, sub, need[0] if need else None)


def counts(rows: list[ProductRow]) -> dict[str, int]:
    return {
        "all": len(rows),
        "critical": sum(r.flag.level == "crit" for r in rows),
        "reorder": sum(r.flag.level == "serious" for r in rows),
        "healthy": sum(r.flag.level == "good" for r in rows),
    }


FILTERS = {"critical": "crit", "reorder": "serious", "healthy": "good"}
