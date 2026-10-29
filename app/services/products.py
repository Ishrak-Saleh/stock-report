from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.forecast import Forecast, Params, compute
from app.models import DailySale, Product, Settings
from app.services.orders import order_stages


@dataclass
class ProductRow:
    product: Product
    forecast: Forecast
    params: Params
    placed: int
    in_production: int
    on_the_way: int

    @property
    def ordered(self) -> int:
        return self.placed + self.in_production + self.on_the_way


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
    return ProductRow(p, compute(daily, p.stock, placed + prod + way, today, params), params, placed, prod, way)


def report(db: Session, today: date) -> list[ProductRow]:
    s = get_settings(db)
    return [product_row(db, p, s, today) for p in db.scalars(select(Product).order_by(Product.name))]
