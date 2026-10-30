from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    """A buying company. It owns its products, suppliers, orders, arrivals, settings and Outbox, and nobody else sees them."""
    __tablename__ = "company"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    created_at: Mapped[datetime]


class Tenant:
    """Marks a table whose rows belong to one company. app/tenancy.py filters every query on company_id."""
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)


class Supplier(Tenant, Base):
    __tablename__ = "supplier"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]


class Product(Tenant, Base):
    __tablename__ = "product"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    code: Mapped[str] = mapped_column(String(8))
    identifiers: Mapped[list] = mapped_column(JSON, default=list)  # SKUs/titles that match sales to this product
    bundle_map: Mapped[dict] = mapped_column(JSON, default=dict)  # variant -> units per sale, e.g. {"Buy 2 Get 2": 4}
    stock: Mapped[int] = mapped_column(default=0)
    unshipped: Mapped[int] = mapped_column(default=0)
    # per-product overrides; None falls back to Settings
    lead_time: Mapped[int | None]
    safety_days: Mapped[int | None]
    target_days: Mapped[int | None]
    sales: Mapped[list["DailySale"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="product")


class DailySale(Base):
    __tablename__ = "daily_sale"
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    units: Mapped[int]
    product: Mapped[Product] = relationship(back_populates="sales")


class Order(Tenant, Base):
    __tablename__ = "order"
    __table_args__ = (UniqueConstraint("company_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]  # product code + number, e.g. MOU-002
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    units: Mapped[int]
    notes: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime]
    confirmed_at: Mapped[datetime | None]
    closed: Mapped[bool] = mapped_column(default=False)
    cancelled: Mapped[bool] = mapped_column(default=False)
    product: Mapped[Product] = relationship(back_populates="orders")
    supplier: Mapped[Supplier] = relationship()
    trackings: Mapped[list["Tracking"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="order")
    events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderEvent.at")


class Tracking(Base):
    __tablename__ = "tracking"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    number: Mapped[str]
    carrier: Mapped[str] = mapped_column(default="")
    units: Mapped[int]
    shipped_at: Mapped[datetime | None]
    order: Mapped[Order] = relationship(back_populates="trackings")


class Arrival(Tenant, Base):
    __tablename__ = "arrival"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    units: Mapped[int]
    day: Mapped[date]
    note: Mapped[str] = mapped_column(default="")
    by: Mapped[str] = mapped_column(default="")
    edited: Mapped[bool] = mapped_column(default=False)  # the match was changed by hand
    product: Mapped[Product] = relationship()
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="arrival", cascade="all, delete-orphan")


class Allocation(Base):
    """Units of an arrival matched to an order. order_id NULL means 'not from an order'."""
    __tablename__ = "allocation"
    id: Mapped[int] = mapped_column(primary_key=True)
    arrival_id: Mapped[int] = mapped_column(ForeignKey("arrival.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("order.id"))
    units: Mapped[int]
    arrival: Mapped[Arrival] = relationship(back_populates="allocations")
    order: Mapped[Order | None] = relationship(back_populates="allocations")


class StockMovement(Tenant, Base):
    __tablename__ = "stock_movement"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    kind: Mapped[str]  # arrival | sale | adjustment | reallocation
    delta: Mapped[int]
    note: Mapped[str] = mapped_column(default="")
    at: Mapped[datetime]
    by: Mapped[str] = mapped_column(default="")


class OrderEvent(Base):
    __tablename__ = "order_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    action: Mapped[str]
    detail: Mapped[str] = mapped_column(default="")
    by: Mapped[str] = mapped_column(default="")
    at: Mapped[datetime]
    order: Mapped[Order] = relationship(back_populates="events")


class AlertLog(Tenant, Base):
    __tablename__ = "alert_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    kind: Mapped[str]
    last_sent_at: Mapped[datetime]


class Outbox(Tenant, Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    to: Mapped[str]
    subject: Mapped[str]
    body: Mapped[str]
    at: Mapped[datetime]
    kind: Mapped[str] = mapped_column(default="")  # follow-up | alert | test


class Settings(Tenant, Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_time: Mapped[int] = mapped_column(default=45)
    safety_days: Mapped[int] = mapped_column(default=14)
    target_days: Mapped[int] = mapped_column(default=60)
    alerts_enabled: Mapped[bool] = mapped_column(default=False)
    recipients: Mapped[str] = mapped_column(default="")
    data_updated_at: Mapped[datetime | None]


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role: Mapped[str]  # staff | supplier
    name: Mapped[str | None]  # a supplier's company name; staff are shown by the first part of their email
    # A staff user belongs to one company. A supplier has none: it sees the orders of every company whose
    # Supplier row carries the same email address.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id"))
    created_at: Mapped[datetime | None]
    company: Mapped["Company | None"] = relationship()
