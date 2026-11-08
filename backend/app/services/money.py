"""Shared money helpers: VAT maths, cash/bank ledger postings and account balances (accounts can be in any currency)."""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Company, Transaction
from app.services import currency as fx
from app.services.numbering import next_number

CASH_METHODS = ("cash", "bank", "card")  # money lands in an account immediately; "cheque" waits until cleared


def split_tax(amount: float, rate: float, inclusive: bool) -> tuple[float, float, float]:
    """(net, tax, gross) for an amount that is either before tax or already includes it."""
    rate = rate or 0
    if inclusive:
        gross = round(amount, 2)
        net = round(gross / (1 + rate / 100), 2) if rate else gross
        return net, round(gross - net, 2), gross
    net = round(amount, 2)
    tax = round(net * rate / 100, 2)
    return net, tax, round(net + tax, 2)


def company_tax(db: Session, cid: int) -> tuple[float, bool]:
    c = db.get(Company, cid)
    return (c.tax_rate or 0, bool(c.prices_include_tax)) if c else (0, False)


def account_currency(db: Session, acc: Account) -> str:
    return acc.currency or fx.base(db, acc.company_id)


def default_cash_account(db: Session, cid: int, currency: str | None = None) -> Account:
    """The first cash box in that currency (created on first use, e.g. "صندوق USD")."""
    cur = fx.normalize(db, cid, currency)
    stmt = select(Account).where(Account.company_id == cid, Account.kind == "cash", Account.is_active.is_(True))
    stmt = stmt.where(Account.currency.is_(None) if cur is None else Account.currency == cur)
    acc = db.scalar(stmt.order_by(Account.id))
    if not acc:
        acc = Account(company_id=cid, name="الصندوق الرئيسي" if cur is None else f"صندوق {cur}", kind="cash", currency=cur)
        db.add(acc)
        db.flush()
    return acc


def get_account(db: Session, cid: int, account_id: int | None, currency: str | None = None) -> Account:
    if not account_id:
        return default_cash_account(db, cid, currency)
    acc = db.get(Account, account_id)
    if not acc or acc.company_id != cid:
        raise HTTPException(404, "Account not found")
    return acc


def post(db: Session, cid: int, account_id: int | None, amount: float, kind: str, *, prefix: str | None = None,
         tx_date: date | None = None, currency: str | None = None, **fields) -> Transaction:
    """Record money moving in (+) or out (−) of an account, in the account's own currency.
    prefix gives the row a voucher number (RV / PV / TR)."""
    acc = get_account(db, cid, account_id, currency)
    rate = fx.rate(db, cid, acc.currency)
    tx = Transaction(company_id=cid, account_id=acc.id, amount=round(amount, 2), kind=kind, tx_date=tx_date or date.today(),
                     base_amount=round(amount * rate, 2), **fields)
    if prefix:
        tx.number = next_number(db, Transaction, cid, prefix)
    db.add(tx)
    db.flush()
    return tx


def account_balance(db: Session, acc: Account, until: date | None = None) -> float:
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.account_id == acc.id)
    if until:
        stmt = stmt.where(Transaction.tx_date <= until)
    return round((acc.opening_balance or 0) + float(db.scalar(stmt)), 2)
