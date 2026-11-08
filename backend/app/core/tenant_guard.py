"""Central tenant guard for writes.

Endpoints check the ids they load, but a create/update can also carry ids in its body (customer.price_list_id,
user.branch_id, expense.supplier_id…). Before every flush this guard checks that each id stored on a tenant row
points to a row of the SAME company (or to nothing that exists). It covers every endpoint, service and background
job at once, including ones written later. A violation raises TenantViolation, which the API turns into a plain
404 "not found" — the same answer as an id that doesn't exist, so it reveals nothing about the other company.
"""
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.core.database import Base

# id columns that are not declared as foreign keys but still point at tenant rows
UNDECLARED = {
    ("visits", "order_id"): "sales_orders",
    ("journal_entries", "branch_id"): "branches",
    ("stock_counts", "user_id"): "users",
    ("recurring_invoices", "last_invoice_id"): "invoices",
    ("invoices", "recurring_id"): "recurring_invoices",
    ("payment_proofs", "attachment_id"): "attachments",
}


class TenantViolation(Exception):
    def __init__(self, table: str, column: str):
        self.table, self.column = table, column
        label = column[:-3].replace("_", " ").capitalize() if column.endswith("_id") else "Record"
        super().__init__(f"{label} not found")


def _references(table) -> list[tuple[str, object]]:
    """(column name, target table) for every id column of `table` that points at a tenant table."""
    cache = _references.__dict__.setdefault("cache", {})
    if table.name not in cache:
        refs = []
        for col in table.c:
            if col.name == "company_id":
                continue
            targets = [fk.column.table for fk in col.foreign_keys]
            if not targets and (table.name, col.name) in UNDECLARED:
                targets = [Base.metadata.tables[UNDECLARED[(table.name, col.name)]]]
            refs += [(col.name, t) for t in targets if "company_id" in t.c]
        cache[table.name] = refs
    return cache[table.name]


def _owner(session: Session, target, value, memo: dict):
    """company_id of the target row, or None if the row doesn't exist (yet)."""
    key = (target.name, value)
    if key not in memo:
        with session.no_autoflush:
            memo[key] = session.execute(select(target.c.company_id).where(target.c.id == value)).scalar()
        if memo[key] is None:  # created earlier in this same flush?
            for obj in session.new:
                if getattr(obj, "__tablename__", None) == target.name and getattr(obj, "id", None) == value:
                    memo[key] = getattr(obj, "company_id", None)
    return memo[key]


@event.listens_for(Session, "before_flush")
def _check_tenant_references(session: Session, _ctx, _instances) -> None:
    memo: dict = {}
    for obj in list(session.new) + list(session.dirty):
        table = getattr(obj, "__table__", None)
        if table is None or "company_id" not in table.c:
            continue
        cid = getattr(obj, "company_id", None)
        if cid is None:
            continue
        state = inspect(obj)
        for col, target in _references(table):
            value = getattr(obj, col, None)
            if value is None:
                continue
            if obj not in session.new and not state.attrs[col].history.has_changes():
                continue  # unchanged on an existing row
            owner = _owner(session, target, value, memo)
            if owner != cid:  # another company's row, or a row that doesn't exist
                raise TenantViolation(table.name, col)
