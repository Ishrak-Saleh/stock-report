"""Who may see which rows. Every database session carries a scope, and one hook adds the matching filter to every
SELECT, including lazy loads of related rows. So no route or service can forget to filter by company: a query that
asks for all products gets only the signed-in company's products.

Scopes (stored in session.info["scope"]):
  ("staff", company_id)   everything of that one company
  ("supplier", email)     only the orders addressed to Supplier rows with this email, and the rows those orders need
  ("none",)               a signed-out visitor: every company table looks empty
A session with no scope at all is only used by start-up code and tests (seed, reset), never by a request."""
from sqlalchemy import event, false, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import Arrival, AlertLog, Order, Outbox, Product, Settings, StockMovement, Supplier, Tenant

NONE = ("none",)


def scope_for(user: dict | None) -> tuple:
    """The scope a signed-in session user gets. Anything unexpected falls back to seeing nothing."""
    if not user:
        return NONE
    if user.get("role") == "staff" and user.get("company_id"):
        return ("staff", user["company_id"])
    if user.get("role") == "supplier" and user.get("email"):
        return ("supplier", user["email"])
    return NONE


def _supplier_ids(email: str):
    return select(Supplier.id).where(Supplier.email == email)


def _criteria(scope: tuple) -> list:
    kind = scope[0]
    if kind == "staff":
        cid = scope[1]
        return [with_loader_criteria(Tenant, lambda cls: cls.company_id == cid, include_aliases=True)]
    if kind == "supplier":
        email = scope[1]
        mine = _supplier_ids(email)
        rules = [
            (Supplier, lambda cls: cls.email == email),
            (Order, lambda cls: cls.supplier_id.in_(mine)),
            (Product, lambda cls: cls.id.in_(select(Order.product_id).where(Order.supplier_id.in_(mine)))),
            (Settings, lambda cls: cls.company_id.in_(select(Supplier.company_id).where(Supplier.email == email))),
            (Arrival, lambda cls: false()), (StockMovement, lambda cls: false()),
            (AlertLog, lambda cls: false()), (Outbox, lambda cls: false()),
        ]
        return [with_loader_criteria(model, rule, include_aliases=True) for model, rule in rules]
    return [with_loader_criteria(Tenant, lambda cls: false(), include_aliases=True)]


@event.listens_for(Session, "do_orm_execute")
def _filter_selects(state) -> None:
    scope = state.session.info.get("scope")
    if scope is None or not state.is_select or state.is_column_load:
        return
    state.statement = state.statement.options(*_criteria(scope))


@event.listens_for(Session, "before_flush")
def _stamp_and_guard(session: Session, *_) -> None:
    """New company rows get the session's company. A session that is not a staff session may not create them."""
    scope = session.info.get("scope")
    if scope is None:
        return
    for obj in session.new:
        if isinstance(obj, Tenant) and obj.company_id is None:
            if scope[0] != "staff":
                raise PermissionError("Only a signed-in staff user can create company data.")
            obj.company_id = scope[1]
    if scope[0] == "supplier":
        for obj in list(session.dirty) + list(session.deleted):
            if isinstance(obj, Tenant) and not isinstance(obj, Order):
                raise PermissionError("A supplier cannot change company data.")
    if scope[0] == "staff":
        for obj in list(session.dirty) + list(session.new):
            if isinstance(obj, Tenant) and obj.company_id != scope[1]:
                raise PermissionError("That row belongs to another company.")
