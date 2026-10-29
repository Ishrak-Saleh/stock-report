from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.forecast import LEVEL_RANK, Flag, Forecast, Option, Params, compute, main_flag, order_options
from app.models import DailySale, Product, Settings
from app.services.orders import order_stages

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


def get_settings(db: Session) -> Settings:
    return db.scalars(select(Settings)).one()


def params_for(p: Product, s: Settings) -> Params:
    return Params(
        lead_time=p.lead_time if p.lead_time is not None else s.lead_time,
        safety_days=p.safety_days if p.safety_days is not None else s.safety_days,
        target_days=p.target_days if p.target_days is not None else s.target_days,
    )


def product_row(db: Session, p: Product, s: Settings, today: date) -> ProductRow:
    daily = {d.day: d.units for d in db.scalars(select(DailySale).where(DailySale.product_id == p.id))}
    st = [order_stages(o) for o in p.orders]
    placed, prod, way = (sum(getattr(x, k) for x in st) for k in ("placed", "in_production", "on_the_way"))
    params = params_for(p, s)
    f = compute(daily, p.stock, placed + prod + way, today, params)
    spark = [daily.get(today - timedelta(days=i), 0) for i in range(SPARK_DAYS, 0, -1)]
    return ProductRow(p, f, params, placed, prod, way, main_flag(f), spark)


def report(db: Session, today: date) -> list[ProductRow]:
    """Every product, most urgent first."""
    s = get_settings(db)
    rows = [product_row(db, p, s, today) for p in db.scalars(select(Product))]
    return sorted(rows, key=lambda r: (r.rank, r.product.name))


@dataclass
class Headline:
    text: str
    sub: str
    top: ProductRow | None  # the most urgent product that needs a reorder


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def stock_headline(rows: list[ProductRow]) -> Headline:
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
    return Headline(text, f"Suggested order: {total:,} units." if need else "", need[0] if need else None)


def counts(rows: list[ProductRow]) -> dict[str, int]:
    return {
        "all": len(rows),
        "critical": sum(r.flag.level == "crit" for r in rows),
        "reorder": sum(r.flag.level == "serious" for r in rows),
        "healthy": sum(r.flag.level == "good" for r in rows),
    }


FILTERS = {"critical": "crit", "reorder": "serious", "healthy": "good"}
