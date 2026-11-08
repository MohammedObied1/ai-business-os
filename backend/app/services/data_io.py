"""Excel / CSV import and export for company data.

Each entity declares its columns once; the same definition drives the downloadable template, the
header matching on import (Arabic or English headers both work) and the export.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.inventory import apply_stock, next_sku
from app.models import Customer, Expense, Invoice, Product, SalesOrder, Supplier, Warehouse
from app.services.numbering import next_number


@dataclass
class Col:
    key: str
    en: str
    ar: str
    kind: str = "text"  # text / number / int / date
    required: bool = False
    example: object = ""


ENTITIES: dict[str, dict] = {
    "products": {"title": ("Products", "المنتجات"), "cols": [
        Col("sku", "SKU / code", "الكود", example="BEV-001"),
        Col("name", "Name", "اسم المنتج", required=True, example="Coca-Cola 330ml"),
        Col("category", "Category", "الفئة", example="Beverages"),
        Col("unit", "Unit", "الوحدة", example="unit"),
        Col("cost_price", "Cost price", "سعر الشراء", "number", example=2.1),
        Col("sale_price", "Sale price", "سعر البيع", "number", example=4),
        Col("min_stock", "Minimum stock", "الحد الأدنى", "number", example=50),
        Col("supplier_lead_time_days", "Supplier delivery days", "أيام توصيل المورد", "int", example=7),
        Col("opening_stock", "Opening stock", "الكمية الحالية", "number", example=120),
        Col("warehouse", "Warehouse", "المستودع", example="Main warehouse"),
    ]},
    "customers": {"title": ("Customers", "الزباين"), "cols": [
        Col("name", "Name", "اسم الزبون", required=True, example="Al-Noor Market"),
        Col("phone", "Phone", "التلفون", example="0599000000"),
        Col("email", "Email", "الإيميل", example="info@alnoor.ps"),
        Col("address", "City / address", "المدينة / العنوان", example="Nablus"),
        Col("customer_type", "Type (business/individual)", "النوع (شركة/شخص)", example="business"),
        Col("credit_limit", "Credit limit", "سقف الدين", "number", example=5000),
        Col("opening_balance", "Opening balance (owes you)", "رصيد سابق (عليه)", "number", example=0),
        Col("notes", "Notes", "ملاحظات"),
    ]},
    "suppliers": {"title": ("Suppliers", "الموردين"), "cols": [
        Col("name", "Name", "اسم المورد", required=True, example="Central Beverages Ltd"),
        Col("phone", "Phone", "التلفون", example="022000000"),
        Col("email", "Email", "الإيميل", example="orders@central.com"),
        Col("lead_time_days", "Delivery days", "أيام التوصيل", "int", example=5),
        Col("payment_terms_days", "Payment within (days)", "الدفع خلال (أيام)", "int", example=30),
    ]},
    "expenses": {"title": ("Expenses", "المصاريف"), "cols": [
        Col("expense_date", "Date", "التاريخ", "date", required=True, example=date.today()),
        Col("category", "Type", "النوع", required=True, example="Rent"),
        Col("description", "Description", "الوصف", example="Office rent"),
        Col("amount", "Amount", "المبلغ", "number", required=True, example=3500),
    ]},
}

EXPORT_ONLY = {
    "invoices": {"title": ("Invoices", "الفواتير"), "cols": [
        Col("number", "Number", "الرقم"), Col("customer", "Customer", "الزبون"), Col("issue_date", "Issued", "التاريخ", "date"),
        Col("due_date", "Due", "آخر موعد", "date"), Col("total", "Total", "المجموع", "number"), Col("paid_amount", "Paid", "المدفوع", "number"),
        Col("balance", "Balance", "الباقي", "number"), Col("status", "Status", "الحالة"),
    ]},
    "sales": {"title": ("Sales orders", "طلبات البيع"), "cols": [
        Col("number", "Number", "الرقم"), Col("order_date", "Date", "التاريخ", "date"), Col("customer", "Customer", "الزبون"),
        Col("items", "Items", "عدد الأصناف", "int"), Col("discount_pct", "Discount %", "الخصم %", "number"), Col("total", "Total", "المجموع", "number"),
        Col("status", "Status", "الحالة"),
    ]},
}

TYPE_WORDS = {"شركة": "business", "business": "business", "company": "business", "شخص": "individual", "فرد": "individual", "individual": "individual"}


def _norm(h: object) -> str:
    return re.sub(r"[\s*_:]+", " ", str(h or "")).strip().lower()


def _header_map(cols: list[Col]) -> dict[str, str]:
    m = {}
    for c in cols:
        for alias in (c.key, c.en, c.ar):
            m[_norm(alias)] = c.key
    return m


def _to_number(v: object, integer: bool = False):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v) if integer else float(v)
    s = str(v).strip().replace(",", "").replace("٫", ".")
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    n = float(s)  # raises ValueError → reported per row
    return int(n) if integer else n


def _to_date(v: object) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):  # Excel serial
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date '{s}'")


def read_rows(filename: str, data: bytes) -> list[list[object]]:
    name = filename.lower()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    if name.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    raise HTTPException(400, "Upload an Excel (.xlsx) or CSV file")


def parse(entity: str, rows: list[list[object]], lang: str = "en") -> tuple[list[tuple[int, dict]], list[dict]]:
    """Returns ([(excel_row_number, values)], errors)."""
    cols = ENTITIES[entity]["cols"]
    hmap = _header_map(cols)
    # the header is the first row that matches at least one known column
    hdr_idx = next((i for i, r in enumerate(rows[:10]) if any(_norm(c) in hmap for c in r)), None)
    if hdr_idx is None:
        raise HTTPException(400, "Could not find the header row. Use the template columns.")
    header = [hmap.get(_norm(c)) for c in rows[hdr_idx]]
    label = (lambda c: c.ar) if lang == "ar" else (lambda c: c.en)
    missing = [label(c) for c in cols if c.required and c.key not in header]
    if missing:
        raise HTTPException(400, f"Missing required column(s): {', '.join(missing)}")
    by_key = {c.key: c for c in cols}
    out, errors = [], []
    for i, raw in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
        if not any(v not in (None, "") for v in raw):
            continue
        rec, row_err = {}, []
        for key, v in zip(header, raw):
            if not key:
                continue
            col = by_key[key]
            try:
                if col.kind == "number":
                    rec[key] = _to_number(v)
                elif col.kind == "int":
                    rec[key] = _to_number(v, integer=True)
                elif col.kind == "date":
                    rec[key] = _to_date(v)
                else:
                    rec[key] = str(v).strip() if v not in (None, "") else None
            except (ValueError, TypeError):
                row_err.append(f"{label(col)}: قيمة غير صحيحة '{v}'" if lang == "ar" else f"{label(col)}: invalid value '{v}'")
        for c in cols:
            if c.required and rec.get(c.key) in (None, ""):
                row_err.append(f"{label(c)} مطلوب" if lang == "ar" else f"{label(c)} is required")
        if row_err:
            errors.append({"row": i, "message": "; ".join(row_err)})
        else:
            out.append((i, rec))
    return out, errors


def _warehouse_by_name(db: Session, cid: int, name: str | None, cache: dict) -> Warehouse:
    key = (name or "Main warehouse").strip()
    if key.lower() in cache:
        return cache[key.lower()]
    w = db.scalar(select(Warehouse).where(Warehouse.company_id == cid, func.lower(Warehouse.name) == key.lower()))
    if not w:
        w = db.scalar(select(Warehouse).where(Warehouse.company_id == cid).order_by(Warehouse.id)) if not name else None
    if not w:
        w = Warehouse(company_id=cid, name=key)
        db.add(w)
        db.flush()
    cache[key.lower()] = w
    return w


def apply(db: Session, cid: int, entity: str, records: list[tuple[int, dict]]) -> tuple[int, int, list[dict], list[int], dict]:
    """Insert or update rows. Returns (created, updated, errors, created_ids, side_effects). Caller commits or rolls
    back. `created_ids` and `side_effects` let a later rollback undo exactly this run — never touching rows the
    import only updated (we don't know their prior values, so those are left alone)."""
    created = updated = 0
    errors: list[dict] = []
    created_ids: list[int] = []
    side_effects: dict = {"opening_stock_movement": {}, "opening_invoice": {}}
    wh_cache: dict = {}
    for row_no, r in records:
        try:
            with db.begin_nested():
                if entity == "products":
                    fields = {k: v for k, v in r.items() if k not in ("opening_stock", "warehouse") and v is not None}
                    p = db.scalar(select(Product).where(Product.company_id == cid, func.lower(Product.sku) == r["sku"].lower())) if r.get("sku") else None
                    if p is None:
                        p = db.scalar(select(Product).where(Product.company_id == cid, func.lower(Product.name) == r["name"].lower()))
                    if p:
                        for k, v in fields.items():
                            setattr(p, k, v)
                        p.is_active = True
                        updated += 1
                    else:
                        fields["sku"] = fields.get("sku") or next_sku(db, cid)
                        p = Product(company_id=cid, **fields)
                        db.add(p)
                        db.flush()
                        created += 1
                        created_ids.append(p.id)
                        if r.get("opening_stock"):
                            w = _warehouse_by_name(db, cid, r.get("warehouse"), wh_cache)
                            apply_stock(db, cid, p.id, w.id, r["opening_stock"], "adjustment", "Opening stock (import)")
                elif entity == "customers":
                    fields = {k: v for k, v in r.items() if k != "opening_balance" and v is not None}
                    if "customer_type" in fields:
                        fields["customer_type"] = TYPE_WORDS.get(fields["customer_type"].strip().lower(), "business")
                    c = db.scalar(select(Customer).where(Customer.company_id == cid, func.lower(Customer.name) == r["name"].lower()))
                    if c:
                        for k, v in fields.items():
                            setattr(c, k, v)
                        updated += 1
                    else:
                        c = Customer(company_id=cid, **fields)
                        db.add(c)
                        db.flush()
                        created += 1
                        created_ids.append(c.id)
                        if r.get("opening_balance"):
                            inv = Invoice(company_id=cid, number=next_number(db, Invoice, cid, "OB"), customer_id=c.id, issue_date=date.today(),
                                          due_date=date.today(), total=round(r["opening_balance"], 2), status="open")
                            db.add(inv)
                            db.flush()
                            side_effects["opening_invoice"][c.id] = inv.id
                elif entity == "suppliers":
                    fields = {k: v for k, v in r.items() if v is not None}
                    s = db.scalar(select(Supplier).where(Supplier.company_id == cid, func.lower(Supplier.name) == r["name"].lower()))
                    if s:
                        for k, v in fields.items():
                            setattr(s, k, v)
                        updated += 1
                    else:
                        s = Supplier(company_id=cid, **fields)
                        db.add(s)
                        db.flush()
                        created += 1
                        created_ids.append(s.id)
                elif entity == "expenses":
                    e = Expense(company_id=cid, **{k: v for k, v in r.items() if v is not None})
                    db.add(e)
                    db.flush()
                    created += 1
                    created_ids.append(e.id)
                db.flush()
        except HTTPException as ex:
            errors.append({"row": row_no, "message": str(ex.detail)})
        except Exception as ex:  # noqa: BLE001
            errors.append({"row": row_no, "message": str(ex)[:200]})
    return created, updated, errors, created_ids, side_effects


def rollback(db: Session, cid: int, batch) -> dict:
    """Undo an import batch: delete the rows it created (and their opening-stock/opening-balance side effects) —
    but only the ones nothing has touched since. A product that already sold, or a customer with a real invoice
    beyond the opening one, is left in place and reported instead."""
    entity = batch.entity
    removed, kept = [], []
    model = {"products": Product, "customers": Customer, "suppliers": Supplier, "expenses": Expense}[entity]
    for oid in batch.created_ids:
        row = db.get(model, oid)
        if not row or row.company_id != cid:
            continue  # already gone
        try:
            with db.begin_nested():
                if entity == "products":
                    from app.models import StockMovement
                    if db.scalar(select(func.count(StockMovement.id)).where(StockMovement.product_id == oid, StockMovement.movement_type != "adjustment")):
                        kept.append({"id": oid, "name": row.name, "reason": "Has stock movements beyond the opening import"})
                        continue
                    from app.models import StockLevel
                    for lvl in db.scalars(select(StockLevel).where(StockLevel.product_id == oid)).all():
                        db.delete(lvl)
                    for mv in db.scalars(select(StockMovement).where(StockMovement.product_id == oid)).all():
                        db.delete(mv)
                elif entity == "customers":
                    from app.models import SalesOrder as SO
                    real_invoices = db.scalar(select(func.count(Invoice.id)).where(
                        Invoice.customer_id == oid, Invoice.id != batch.side_effect_ids.get("opening_invoice", {}).get(str(oid))))
                    has_orders = db.scalar(select(func.count(SO.id)).where(SO.customer_id == oid))
                    if real_invoices or has_orders:
                        kept.append({"id": oid, "name": row.name, "reason": "Has invoices or orders beyond the opening balance"})
                        continue
                    inv_id = batch.side_effect_ids.get("opening_invoice", {}).get(str(oid))
                    if inv_id and (inv := db.get(Invoice, inv_id)):
                        db.delete(inv)
                elif entity == "suppliers":
                    from app.models import PurchaseOrder
                    if db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.supplier_id == oid)):
                        kept.append({"id": oid, "name": row.name, "reason": "Has purchase orders"})
                        continue
                db.delete(row)
                db.flush()
            removed.append(oid)
        except Exception as ex:  # noqa: BLE001
            kept.append({"id": oid, "name": getattr(row, "name", str(oid)), "reason": str(ex)[:150]})
    return {"removed": removed, "kept_in_use": kept}


# ---------------------------------------------------------------- workbook output
HEADER_FILL = PatternFill("solid", fgColor="0F766E")
FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(v: object) -> object:
    """Guard against CSV/Excel formula injection: a cell that starts with =, +, -, @ (or a tab/CR that can hide one)
    runs as a formula when the file is opened in Excel/Sheets/LibreOffice. Prefixing it with a quote makes every
    program treat it as plain text instead — the same trick spreadsheet apps themselves use."""
    if isinstance(v, str) and v.startswith(FORMULA_LEAD):
        return "'" + v
    return v


def _workbook(title: str, cols: list[Col], rows: list[list[object]], lang: str, note: str | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    if lang == "ar":
        ws.sheet_view.rightToLeft = True
    ws.append([(c.ar if lang == "ar" else c.en) + (" *" if c.required else "") for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append([_safe_cell(v) for v in r])
    for i, c in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(14, len(c.ar if lang == "ar" else c.en) + 6)
        if c.kind == "date":
            for cell in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                for x in cell:
                    x.number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    if note:
        info = wb.create_sheet("README")
        if lang == "ar":
            info.sheet_view.rightToLeft = True
        for line in note.split("\n"):
            info.append([line])
        info.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


TEMPLATE_NOTE = {
    "en": "How to fill this file:\n- Keep the first row (column names) as is. Columns marked * are required.\n- One row per record. You can delete the example row.\n"
          "- Existing records are updated (products by SKU or name, customers and suppliers by name).\n- Save as .xlsx and upload it from the Import page.",
    "ar": "طريقة تعبئة الملف:\n- خلّي أول سطر (أسماء الأعمدة) زي ما هو. الأعمدة اللي عليها * لازم تتعبّى.\n- كل سطر = سجل واحد. بتقدر تحذف سطر المثال.\n"
          "- إذا السجل موجود بيتحدّث (المنتجات بالكود أو الاسم، الزباين والموردين بالاسم).\n- احفظ الملف .xlsx وارفعه من صفحة الاستيراد.",
}


def template(entity: str, lang: str) -> tuple[str, bytes]:
    e = ENTITIES[entity]
    title = e["title"][1 if lang == "ar" else 0]
    return f"{entity}-template.xlsx", _workbook(title, e["cols"], [[c.example for c in e["cols"]]], lang, TEMPLATE_NOTE.get(lang, TEMPLATE_NOTE["en"]))


def _csv_bytes(cols: list[Col], rows: list[list[object]], lang: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.ar if lang == "ar" else c.en for c in cols])
    for r in rows:
        w.writerow([_safe_cell(v) for v in r])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens Arabic text correctly


def export(db: Session, cid: int, entity: str, lang: str, fmt: str = "xlsx") -> tuple[str, bytes]:
    spec = ENTITIES.get(entity) or EXPORT_ONLY.get(entity)
    if not spec:
        raise HTTPException(404, "Unknown data type")
    cols = spec["cols"]
    rows: list[list[object]] = []
    if entity == "products":
        from app.models import StockLevel
        stock = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(StockLevel.company_id == cid).group_by(StockLevel.product_id)).all())
        for p in db.scalars(select(Product).where(Product.company_id == cid, Product.is_active.is_(True)).order_by(Product.name)):
            rows.append([p.sku, p.name, p.category, p.unit, p.cost_price, p.sale_price, p.min_stock, p.supplier_lead_time_days, float(stock.get(p.id, 0)), None])
    elif entity == "customers":
        from app.services.analytics import INVOICE_BALANCE_BASE
        bal = dict(db.execute(select(Invoice.customer_id, func.sum(INVOICE_BALANCE_BASE)).where(
            Invoice.company_id == cid, Invoice.status.in_(("open", "partial", "overdue"))).group_by(Invoice.customer_id)).all())
        for c in db.scalars(select(Customer).where(Customer.company_id == cid).order_by(Customer.name)):
            rows.append([c.name, c.phone, c.email, c.address, c.customer_type, c.credit_limit, round(float(bal.get(c.id, 0)), 2), c.notes])
    elif entity == "suppliers":
        for s in db.scalars(select(Supplier).where(Supplier.company_id == cid).order_by(Supplier.name)):
            rows.append([s.name, s.phone, s.email, s.lead_time_days, s.payment_terms_days])
    elif entity == "expenses":
        for e in db.scalars(select(Expense).where(Expense.company_id == cid).order_by(Expense.expense_date.desc())):
            rows.append([e.expense_date, e.category, e.description, e.amount])
    elif entity in ("invoices", "sales"):
        names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == cid)).all())
        if entity == "invoices":
            for i in db.scalars(select(Invoice).where(Invoice.company_id == cid).order_by(Invoice.issue_date.desc())):
                rows.append([i.number, names.get(i.customer_id), i.issue_date, i.due_date, i.total, i.paid_amount, i.balance, i.status])
        else:
            for o in db.scalars(select(SalesOrder).where(SalesOrder.company_id == cid).order_by(SalesOrder.order_date.desc())):
                rows.append([o.number, o.order_date, names.get(o.customer_id), len(o.items), o.discount_pct, o.total, o.status])
    title = spec["title"][1 if lang == "ar" else 0]
    if fmt == "csv":
        return f"{entity}-{date.today().isoformat()}.csv", _csv_bytes(cols, rows, lang)
    return f"{entity}-{date.today().isoformat()}.xlsx", _workbook(title, cols, rows, lang)
