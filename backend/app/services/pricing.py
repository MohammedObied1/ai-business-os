"""Pricing a cart: price lists, promotions, pack units, currency, VAT and approval checks.

Used by order creation and by /sales/quote (so the POS and the sale form show exactly what will be saved).
"""
from dataclasses import dataclass, field
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Customer, PriceList, PriceListItem, Product, Promotion


@dataclass
class Line:
    product: Product
    base_qty: float  # in base units
    price: float  # per entered unit, in document currency
    discount_pct: float
    line_total: float
    uom_label: str | None = None
    uom_qty: float | None = None
    factor: float = 1
    promo: str | None = None
    free: bool = False


@dataclass
class Priced:
    lines: list[Line] = field(default_factory=list)
    lines_total: float = 0
    after_discount: float = 0
    net: float = 0
    tax: float = 0
    total: float = 0
    cost: float = 0  # base currency
    approval_reasons: list[str] = field(default_factory=list)


def _list_price(db: Session, customer: Customer | None, product: Product) -> float:
    """Base-unit price in base currency for this customer (their price list if any)."""
    if customer and customer.price_list_id:
        pl = db.get(PriceList, customer.price_list_id)
        if pl and pl.is_active:
            item = db.scalar(select(PriceListItem).where(PriceListItem.price_list_id == pl.id, PriceListItem.product_id == product.id))
            if item:
                return item.price
            if pl.discount_pct:
                return round(product.sale_price * (1 - pl.discount_pct / 100), 4)
    return product.sale_price


def active_promotions(db: Session, cid: int) -> list[Promotion]:
    today = date.today()
    return [p for p in db.scalars(select(Promotion).where(Promotion.company_id == cid, Promotion.is_active.is_(True))).all()
            if (not p.starts_on or p.starts_on <= today) and (not p.ends_on or p.ends_on >= today)]


def _promo_for(promos: list[Promotion], product: Product, kind: str) -> Promotion | None:
    for p in promos:
        if p.kind == kind and ((p.product_id and p.product_id == product.id) or (not p.product_id and p.category and p.category == product.category)):
            return p
    return None


def price_cart(db: Session, cid: int, items, customer: Customer | None, order_discount_pct: float = 0, rate: float = 1.0,
               apply_promotions: bool = True) -> Priced:
    """items: objects with product_id, quantity, unit ("unit"/"pack"), unit_price (optional, document currency), discount_pct."""
    company = db.get(Company, cid)
    promos = active_promotions(db, cid) if apply_promotions else []
    out = Priced()
    for it in items:
        if not it.product_id:
            continue
        if it.quantity <= 0:
            raise HTTPException(400, "Quantities must be greater than zero")
        p = db.get(Product, it.product_id)
        if not p or p.company_id != cid:
            raise HTTPException(404, f"Product {it.product_id} not found")
        factor, label = 1.0, None
        if getattr(it, "unit", "unit") == "pack":
            if not p.pack_size:
                raise HTTPException(400, f"{p.name} has no pack unit")
            factor, label = p.pack_size, p.pack_unit or "pack"
        base_price = _list_price(db, customer, p)
        default_price = (p.pack_price if (label and p.pack_price) else base_price * factor) / rate
        price = it.unit_price if it.unit_price is not None else round(default_price, 4)
        disc = it.discount_pct or 0
        promo_name = None
        pct = _promo_for(promos, p, "percent")
        if pct and pct.percent > disc and it.unit_price is None:
            disc, promo_name = pct.percent, pct.name
        line_total = round(it.quantity * price * (1 - disc / 100), 2)
        line = Line(p, it.quantity * factor, price, disc, line_total, label, it.quantity if label else None, factor, promo_name)
        out.lines.append(line)
        # buy X get Y free → an extra free line of the same product
        bx = _promo_for(promos, p, "bxgy")
        if bx and bx.buy_qty > 0 and bx.free_qty > 0:
            free_units = int(line.base_qty // bx.buy_qty) * bx.free_qty
            if free_units > 0:
                out.lines.append(Line(p, free_units, 0, 0, 0, None, None, 1, bx.name, True))
        # approval checks
        unit_price_base = price * rate / factor * (1 - disc / 100)
        if unit_price_base + 1e-6 < p.cost_price and not getattr(it, "free", False):
            out.approval_reasons.append(f"Price below cost: {p.name}")
        if company.approval_discount_pct and disc > company.approval_discount_pct and not promo_name:
            out.approval_reasons.append(f"Discount {disc:g}% on {p.name}")
    if company.approval_discount_pct and order_discount_pct > company.approval_discount_pct:
        out.approval_reasons.append(f"Order discount {order_discount_pct:g}%")
    out.lines_total = round(sum(ln.line_total for ln in out.lines), 2)
    out.after_discount = out.lines_total * (1 - order_discount_pct / 100)
    r, inclusive = company.tax_rate or 0, bool(company.prices_include_tax)
    if inclusive:
        out.total = round(out.after_discount, 2)
        out.net = round(out.total / (1 + r / 100), 2) if r else out.total
        out.tax = round(out.total - out.net, 2)
    else:
        out.net = round(out.after_discount, 2)
        out.tax = round(out.net * r / 100, 2)
        out.total = round(out.net + out.tax, 2)
    out.cost = round(sum(ln.base_qty * ln.product.cost_price for ln in out.lines), 2)
    return out
