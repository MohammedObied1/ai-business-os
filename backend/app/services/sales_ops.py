"""Sales operations shared by the Sales API, the point of sale, field sales and the online shop."""
import secrets
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.inventory import _warehouse, apply_stock
from app.core.deps import branch_scope, has_permission
from app.models import (
    Cheque, CreditNote, CreditNoteItem, Customer, Invoice, Payment, SalesOrder, SalesOrderItem, User,
)
from app.schemas.sales import ChequeIn, OrderIn, ReturnIn
from app.services import currency as fx
from app.services import webhooks
from app.services.money import account_currency, get_account, post
from app.services.numbering import next_number
from app.services.pricing import price_cart

PAY_METHODS = ("cash", "bank", "card", "cheque")
ACTIVE = ("confirmed", "delivered")


def customer(db: Session, cid: int, customer_id: int) -> Customer:
    c = db.get(Customer, customer_id)
    if not c or c.company_id != cid:
        raise HTTPException(404, "Customer not found")
    return c


def create_order(db: Session, user: User, payload: OrderIn, source: str = "manual") -> SalesOrder:
    cid = user.company_id
    cust = customer(db, cid, payload.customer_id)
    if not [i for i in payload.items if i.product_id]:
        raise HTTPException(400, "Order needs at least one item")
    wh = _warehouse(db, cid, payload.warehouse_id, user) if payload.warehouse_id else None
    if (payload.discount_pct or any(i.discount_pct for i in payload.items)) and not has_permission(user, "sales.discount"):
        raise HTTPException(403, "You are not allowed to give discounts")
    scope = branch_scope(user)
    if scope and wh and wh.branch_id and wh.branch_id != scope:
        raise HTTPException(403, "This warehouse belongs to another branch")
    cur = fx.normalize(db, cid, payload.currency)
    rate = fx.rate(db, cid, cur)
    priced = price_cart(db, cid, payload.items, cust, payload.discount_pct, rate)
    status = payload.status
    from app.services import approvals
    # below-cost lines only count when that approval rule is on (it is by default)
    reasons = [r for r in priced.approval_reasons if not r.startswith("Price below cost") or approvals.rule(db, cid, "below_cost")[0]]
    needs_approval = bool(reasons) and status in ACTIVE and not has_permission(user, "approvals.approve")
    if needs_approval:
        status = "pending_approval"
    prefix = "QT" if status == "quotation" else "SO"
    order = SalesOrder(company_id=cid, number=next_number(db, SalesOrder, cid, prefix), customer_id=cust.id, warehouse_id=payload.warehouse_id,
                       status=status, order_date=payload.order_date or date.today(), discount_pct=payload.discount_pct, salesperson_id=user.id,
                       tax_rate=_tax_rate(db, cid),
                       branch_id=(wh.branch_id if wh and wh.branch_id else scope), source=source, notes=payload.notes,
                       currency=cur, exchange_rate=rate, client_ref=getattr(payload, "client_ref", None),
                       approval_reason="; ".join(reasons)[:200] if needs_approval else None)
    db.add(order)
    db.flush()
    for ln in priced.lines:
        db.add(SalesOrderItem(company_id=cid, order_id=order.id, product_id=ln.product.id, quantity=ln.base_qty,
                              unit_price=round(ln.price / ln.factor, 4), unit_cost=ln.product.cost_price, discount_pct=ln.discount_pct,
                              line_total=ln.line_total, uom_label=ln.uom_label, uom_qty=ln.uom_qty, uom_price=ln.price if ln.uom_label else None))
    order.subtotal, order.tax_amount, order.total, order.cost_total = priced.lines_total, priced.tax, priced.total, priced.cost
    db.flush()  # the session doesn't autoflush; the lines must exist before stock is moved
    if status in ACTIVE and payload.warehouse_id:
        _move_stock(db, cid, order, -1)
    db.flush()
    if needs_approval:
        kind = "below_cost" if any(r.startswith("Price below cost") for r in reasons) else "sales_discount"
        approvals.request(db, user, kind, "sales_orders", order.id, order.number, order.total, "; ".join(reasons))
    webhooks.emit(db, cid, "order.created", {"id": order.id, "number": order.number, "customer_id": cust.id, "total": order.total,
                                             "currency": cur or fx.base(db, cid), "status": order.status, "source": source})
    return order


def _tax_rate(db: Session, cid: int) -> float:
    from app.models import Company
    return db.get(Company, cid).tax_rate or 0


def _move_stock(db: Session, cid: int, order: SalesOrder, sign: int, movement: str = "sale") -> None:
    """Sale (sign -1): stock leaves and each line records its real cost (FIFO / average), which becomes the order's COGS.
    Cancel (sign +1): the stock comes back at the cost it left with."""
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
    for it in items:
        if sign < 0:
            cost = apply_stock(db, cid, it.product_id, order.warehouse_id, -it.quantity, movement, order.number)
            if it.quantity:
                it.unit_cost = round(cost / it.quantity, 4)
        else:
            apply_stock(db, cid, it.product_id, order.warehouse_id, it.quantity, "adjustment", f"cancel {order.number}", unit_cost=it.unit_cost)
    if sign < 0:
        order.cost_total = round(sum(i.quantity * (i.unit_cost or 0) for i in items), 2)


def approve_order(db: Session, user: User, order: SalesOrder) -> SalesOrder:
    if order.status != "pending_approval":
        raise HTTPException(400, "This order is not waiting for approval")
    if order.warehouse_id:
        _move_stock(db, user.company_id, order, -1)
    order.status = "confirmed"
    order.approved_by = user.full_name
    from app.services import approvals
    approvals.resolve_for(db, "sales_orders", order.id, "APPROVED", user)
    return order


def invoice_for_order(db: Session, cid: int, order: SalesOrder, due_days: int = 30) -> Invoice:
    if db.scalar(select(Invoice.id).where(Invoice.order_id == order.id, Invoice.status != "cancelled")):
        raise HTTPException(400, "This order already has an invoice")
    if order.status not in ACTIVE:
        raise HTTPException(400, "Only confirmed or delivered orders can be invoiced")
    inv = Invoice(company_id=cid, number=next_number(db, Invoice, cid, "INV"), customer_id=order.customer_id, order_id=order.id,
                  issue_date=date.today(), due_date=date.today() + timedelta(days=due_days), total=order.total,
                  tax_amount=order.tax_amount or 0, subtotal=round(order.total - (order.tax_amount or 0), 2),
                  currency=order.currency, exchange_rate=order.exchange_rate or 1, branch_id=order.branch_id)
    db.add(inv)
    db.flush()
    webhooks.emit(db, cid, "invoice.created", {"id": inv.id, "number": inv.number, "customer_id": inv.customer_id, "total": inv.total,
                                               "currency": inv.currency or fx.base(db, cid), "due_date": inv.due_date.isoformat()})
    return inv


def refresh_invoice_status(inv: Invoice) -> None:
    if inv.status == "cancelled":
        return
    if inv.balance <= 0.009:
        inv.status = "paid"
    elif inv.paid_amount > 0 or (inv.credited_amount or 0) > 0:
        inv.status = "overdue" if inv.due_date < date.today() else "partial"
    else:
        inv.status = "overdue" if inv.due_date < date.today() else "open"


def _check_method(method: str, cheque: ChequeIn | None, have_cheque_row: bool = False) -> None:
    if method not in PAY_METHODS:
        raise HTTPException(400, f"Unknown payment method {method}")
    if method == "cheque" and not have_cheque_row and (not cheque or not cheque.number or not cheque.due_date):
        raise HTTPException(400, "Cheque number and due date are required")


def pay_invoice(db: Session, user: User, inv: Invoice, amount: float, method: str, reference: str | None = None,
                account_id: int | None = None, cheque: ChequeIn | None = None, number: str | None = None,
                cheque_row: Cheque | None = None, pay_currency: str | None = None) -> Payment:
    """Money received against one invoice. `amount` is in the paying currency (default: the invoice currency).
    Cash/bank/card land in an account now; cheques wait in the cheque box until cleared."""
    cid = user.company_id
    _check_method(method, cheque, cheque_row is not None)
    if inv.status == "cancelled":
        raise HTTPException(400, "Invoice is cancelled")
    inv_cur = inv.currency
    pay_cur = fx.normalize(db, cid, pay_currency) if pay_currency else inv_cur
    inv_rate_now, pay_rate_now = fx.rate(db, cid, inv_cur), fx.rate(db, cid, pay_cur)
    amount_inv = round(amount * pay_rate_now / inv_rate_now, 2)
    if pay_cur != inv_cur:  # paying in another currency: a rounding cent (in the paying currency) settles the invoice exactly
        tol = max(0.01, pay_rate_now / inv_rate_now * 0.006)
        if abs(amount_inv - inv.balance) <= tol:
            amount_inv = round(inv.balance, 2)
    if amount <= 0 or amount_inv > inv.balance + 0.01:
        raise HTTPException(400, f"Amount must be between 0 and {inv.balance}")
    pay = Payment(company_id=cid, invoice_id=inv.id, customer_id=inv.customer_id, amount=amount_inv, method=method, reference=reference,
                  paid_at=datetime.utcnow(), number=number or next_number(db, Payment, cid, "RV"), exchange_rate=inv_rate_now,
                  account_amount=round(amount, 2))
    db.add(pay)
    db.flush()
    cust = db.get(Customer, inv.customer_id)
    if method == "cheque":
        if cheque_row is None:
            cheque_row = Cheque(company_id=cid, direction="in", number=cheque.number, bank=cheque.bank, amount=round(amount, 2),
                                due_date=cheque.due_date, customer_id=inv.customer_id, payment_id=pay.id, currency=pay_cur)
            db.add(cheque_row)
            db.flush()
        pay.reference = pay.reference or f"Cheque {cheque_row.number}"
    else:
        acc = get_account(db, cid, account_id, pay_cur)
        acc_cur = fx.normalize(db, cid, account_currency(db, acc))
        acc_amount = round(amount * pay_rate_now / fx.rate(db, cid, acc_cur), 2) if acc_cur != pay_cur else round(amount, 2)
        pay.account_id, pay.account_amount = acc.id, acc_amount
        post(db, cid, acc.id, acc_amount, "customer_payment", number=pay.number, description=f"{inv.number}", reference=reference,
             customer_id=inv.customer_id, payment_id=pay.id, party_name=cust.name if cust else None, user_id=user.id)
    inv.paid_amount = round(inv.paid_amount + amount_inv, 2)
    was_open = inv.status != "paid"
    refresh_invoice_status(inv)
    webhooks.emit(db, cid, "payment.received", {"number": pay.number, "invoice": inv.number, "customer_id": inv.customer_id,
                                                "amount": amount, "currency": pay_cur or fx.base(db, cid), "method": method})
    webhooks.emit(db, cid, "payment.created", {"number": pay.number, "invoice": inv.number, "customer_id": inv.customer_id,
                                               "amount": amount, "currency": pay_cur or fx.base(db, cid), "method": method})
    if was_open and inv.status == "paid":
        webhooks.emit(db, cid, "invoice.paid", {"id": inv.id, "number": inv.number, "customer_id": inv.customer_id, "total": inv.total})
    return pay


def receive_from_customer(db: Session, user: User, customer_id: int, amount: float, method: str, reference: str | None,
                          account_id: int | None, cheque: ChequeIn | None, pay_currency: str | None = None) -> list[Payment]:
    """Spread one receipt over the customer's oldest open invoices (one voucher number for all of it), across currencies."""
    cid = user.company_id
    cust = customer(db, cid, customer_id)
    _check_method(method, cheque)
    pay_cur = fx.normalize(db, cid, pay_currency)
    pay_rate = fx.rate(db, cid, pay_cur)
    invoices = db.scalars(select(Invoice).where(Invoice.company_id == cid, Invoice.customer_id == customer_id,
                                                Invoice.status.in_(("open", "partial", "overdue"))).order_by(Invoice.due_date, Invoice.id)).all()
    owed_base = round(sum(i.balance * fx.rate(db, cid, i.currency) for i in invoices), 2)
    if amount <= 0 or amount * pay_rate > owed_base + 0.01:
        raise HTTPException(400, f"Amount must be between 0 and {round(owed_base / pay_rate, 2)}")
    number = next_number(db, Payment, cid, "RV")
    cheque_row = None
    if method == "cheque":
        cheque_row = Cheque(company_id=cid, direction="in", number=cheque.number, bank=cheque.bank, amount=round(amount, 2),
                            due_date=cheque.due_date, customer_id=cust.id, currency=pay_cur)
        db.add(cheque_row)
        db.flush()
    payments, remaining_base = [], round(amount * pay_rate, 2)
    for inv in invoices:
        if remaining_base <= 0.009:
            break
        part_base = min(inv.balance * fx.rate(db, cid, inv.currency), remaining_base)
        part_pay = round(part_base / pay_rate, 2)
        if part_pay <= 0:
            continue
        payments.append(pay_invoice(db, user, inv, part_pay, method, reference, account_id, cheque, number=number, cheque_row=cheque_row,
                                    pay_currency=pay_cur))
        remaining_base = round(remaining_base - part_base, 2)
    if cheque_row and payments:
        cheque_row.payment_id = payments[0].id
    return payments


def create_return(db: Session, user: User, payload: ReturnIn) -> CreditNote:
    cid = user.company_id
    order = db.get(SalesOrder, payload.order_id)
    if not order or order.company_id != cid:
        raise HTTPException(404, "Order not found")
    inv = db.scalar(select(Invoice).where(Invoice.order_id == order.id, Invoice.status != "cancelled"))
    if not inv:
        raise HTTPException(400, "Invoice the order first, or cancel it instead of returning")
    wid = payload.warehouse_id or order.warehouse_id
    if wid:
        _warehouse(db, cid, wid)
    lines = {i.id: i for i in db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()}
    already = dict(db.execute(select(CreditNoteItem.order_item_id, func.sum(CreditNoteItem.quantity))
                              .join(CreditNote, CreditNote.id == CreditNoteItem.credit_note_id)
                              .where(CreditNote.order_id == order.id).group_by(CreditNoteItem.order_item_id)).all())
    cn = CreditNote(company_id=cid, number=next_number(db, CreditNote, cid, "CN"), customer_id=order.customer_id, invoice_id=inv.id,
                    order_id=order.id, warehouse_id=wid, reason=payload.reason, currency=order.currency, exchange_rate=order.exchange_rate or 1)
    db.add(cn)
    db.flush()
    basis = cost = 0.0
    for r in payload.items:
        if r.quantity <= 0:
            continue
        line = lines.get(r.order_item_id)
        if not line:
            raise HTTPException(404, "Order line not found")
        left = line.quantity - float(already.get(line.id, 0))
        if r.quantity > left + 1e-9:
            raise HTTPException(400, f"You can return at most {left:g} of this item")
        value = round(line.line_total * r.quantity / line.quantity, 2)
        condition = (r.condition or "good").lower()
        if condition not in ("good", "damaged", "expired"):
            raise HTTPException(400, "Condition must be good, damaged or expired")
        db.add(CreditNoteItem(company_id=cid, credit_note_id=cn.id, product_id=line.product_id, order_item_id=line.id, quantity=r.quantity,
                              unit_price=round(value / r.quantity, 4), unit_cost=line.unit_cost, line_total=value, condition=condition))
        basis += value
        cost += r.quantity * line.unit_cost
        if wid:  # back at the cost it left with
            apply_stock(db, cid, line.product_id, wid, r.quantity, "return", cn.number, unit_cost=line.unit_cost)
            if condition != "good":  # can't be sold again: straight into damaged / expired stock (written off)
                from app.services import stock_states
                stock_states.mark(db, cid, line.product_id, wid, r.quantity, condition, cn.number, batch="")
    if basis <= 0:
        raise HTTPException(400, "Choose at least one item to return")
    # value the return at the same prices, discount and VAT as the original sale
    ratio = basis / order.subtotal if order.subtotal else 0
    cn.total = round(order.total * ratio, 2)
    cn.tax_amount = round((order.tax_amount or 0) * ratio, 2)
    cn.subtotal = round(cn.total - cn.tax_amount, 2)
    cn.cost_total = round(cost, 2)
    applied = round(min(cn.total, max(inv.balance, 0)), 2)
    inv.credited_amount = round((inv.credited_amount or 0) + applied, 2)
    cn.applied_to_invoice = applied
    refresh_invoice_status(inv)
    refund = round(cn.total - applied, 2)
    if refund > 0.009:
        cust = db.get(Customer, order.customer_id)
        acc = get_account(db, cid, payload.refund_account_id, order.currency)
        acc_amount = round(refund * (order.exchange_rate or 1) / fx.rate(db, cid, acc.currency), 2)
        post(db, cid, acc.id, -acc_amount, "refund", prefix="PV", description=f"{cn.number} / {inv.number}",
             customer_id=order.customer_id, party_name=cust.name if cust else None, user_id=user.id)
        cn.refunded = refund
    db.flush()
    webhooks.emit(db, cid, "return.created", {"number": cn.number, "invoice": inv.number, "total": cn.total, "refunded": cn.refunded})
    return cn


def ensure_public_token(inv: Invoice) -> str:
    if not inv.public_token:
        inv.public_token = secrets.token_urlsafe(24)
    return inv.public_token
