"""AI Business Analyst agent.

Tools are executed server-side with tenant scoping. If ANTHROPIC_API_KEY is configured the agent
runs a Claude tool-use loop; otherwise a deterministic intent router answers common questions so
the product stays usable offline / in tests.
"""
import json
import re
from datetime import date, datetime, timedelta

import os
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AIConversation, AiDraft, Customer, PurchaseOrder, PurchaseOrderItem, Product, Supplier, Task, Alert
from app.services import analytics, rag
from app.services.forecasting import forecast_all
from app.services.insights import build_command_center
from app.services.numbering import next_number


# ---------------------------------------------------------------- tools
def _period(period: str) -> tuple[date, date]:
    today = date.today()
    if period == "last_month":
        s, _ = analytics.month_bounds(today)
        return analytics.month_bounds(s - timedelta(days=1))
    if period == "this_year":
        return date(today.year, 1, 1), today
    if period == "last_90_days":
        return today - timedelta(days=90), today
    return analytics.month_bounds(today)  # this_month


# what the signed-in user must be allowed to do (same permissions as the matching screens) before the AI may run a tool
TOOL_PERMISSIONS = {
    "query_sales": "reports:read", "query_profit": "reports:read", "query_inventory": "inventory:read", "query_customers": "customers:read",
    "query_finance": "finance:read", "query_anomalies": "reports:read", "analyze_business": "reports:read", "search_documents": None, "create_report": "reports:read",
    "create_task": None, "create_purchase_request": "purchasing:write", "create_customer": "customers:write", "send_notification": "automation:write",
}


class ToolBox:
    """Tools the assistant can call. Always scoped to one company; with `user` also limited to that user's permissions
    (user=None is the system itself, e.g. background jobs)."""

    def __init__(self, db: Session, cid: int, user_name: str, user=None):
        self.db, self.cid, self.user_name, self.user = db, cid, user_name, user

    def allowed(self, tool: str) -> bool:
        from app.core.deps import has_permission
        perm = TOOL_PERMISSIONS.get(tool)
        return self.user is None or perm is None or has_permission(self.user, perm)

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if name in TOOL_PERMISSIONS and not object.__getattribute__(self, "allowed")(name):
            return lambda *a, **k: {"error": f"You don't have permission for this ({TOOL_PERMISSIONS[name]})."}
        return attr

    def query_sales(self, period: str = "this_month", group_by: str = "summary", limit: int = 20) -> dict:
        s, e = _period(period)
        if group_by == "customer":
            return {"period": [s.isoformat(), e.isoformat()], "top_customers": analytics.top_customers(self.db, self.cid, s, e, limit)}
        if group_by == "product":
            return {"period": [s.isoformat(), e.isoformat()], "top_products": analytics.top_products(self.db, self.cid, s, e, limit, by="revenue")}
        if group_by == "warehouse":
            return {"period": [s.isoformat(), e.isoformat()], "warehouses": analytics.sales_by_warehouse(self.db, self.cid, s, e)}
        if group_by == "category":
            return {"period": [s.isoformat(), e.isoformat()], "categories": analytics.category_margins(self.db, self.cid, s, e)}
        if group_by == "month":
            return {"monthly": analytics.monthly_series(self.db, self.cid, 12)}
        rev, cogs = analytics.revenue_between(self.db, self.cid, s, e)
        return {"period": [s.isoformat(), e.isoformat()], "revenue": round(rev, 2), "cogs": round(cogs, 2), "gross_profit": round(rev - cogs, 2)}

    def query_profit(self, period: str = "this_month", limit: int = 20) -> dict:
        s, e = _period(period)
        return {"period": [s.isoformat(), e.isoformat()], "top_products_by_profit": analytics.top_products(self.db, self.cid, s, e, limit, by="profit"),
                "categories": analytics.category_margins(self.db, self.cid, s, e)}

    def query_inventory(self, filter: str = "low_stock") -> dict:
        if filter == "forecast":
            return {"forecast": forecast_all(self.db, self.cid, only_risky=True)[:20]}
        return {"low_stock": analytics.low_stock_products(self.db, self.cid), "inventory_value": analytics.inventory_value(self.db, self.cid)}

    def query_customers(self, filter: str = "top", threshold: float = 0, period: str = "this_year", limit: int = 20) -> dict:
        if filter == "owing":
            return {"customers_owing_more_than": threshold, "customers": analytics.customers_owing_more_than(self.db, self.cid, threshold)}
        if filter == "inactive":
            return {"inactive_customers": analytics.inactive_customers(self.db, self.cid, int(threshold or 60))}
        s, e = _period(period)
        return {"period": [s.isoformat(), e.isoformat()], "top_customers": analytics.top_customers(self.db, self.cid, s, e, limit)}

    def query_finance(self, view: str = "summary") -> dict:
        if view == "cashflow":
            return {"cashflow": analytics.cashflow_series(self.db, self.cid, 6)}
        if view == "overdue":
            inv = analytics.overdue_invoices(self.db, self.cid)
            return {"overdue_invoices": [{"number": i.number, "due_date": i.due_date.isoformat(), "balance": i.balance} for i in inv]}
        return analytics.dashboard_kpis(self.db, self.cid)

    def query_anomalies(self, days: int = 14) -> dict:
        from app.services.smart import detect_anomalies
        return {"anomalies": detect_anomalies(self.db, self.cid, days)}

    def analyze_business(self, lang: str = "en") -> dict:
        cc = build_command_center(self.db, self.cid, lang)
        cc.pop("generated_at", None)
        return cc

    def search_documents(self, query: str) -> dict:
        return {"hits": rag.search(self.db, self.cid, query, k=4)}

    def create_report(self, report_type: str = "management", period: str = "this_month") -> dict:
        s, e = _period(period)
        return {
            "report_type": report_type, "period": [s.isoformat(), e.isoformat()],
            "kpis": analytics.dashboard_kpis(self.db, self.cid),
            "top_customers": analytics.top_customers(self.db, self.cid, s, e, 10),
            "top_products": analytics.top_products(self.db, self.cid, s, e, 10),
            "categories": analytics.category_margins(self.db, self.cid, s, e),
        }

    def _draft(self, tool: str, args: dict, summary: str) -> dict:
        """Nothing is written yet: the AI is only allowed to *propose* a change. It's saved as a draft the user who
        asked must explicitly confirm (or reject) — the AI never modifies data on its own."""
        if self.user is None:
            return {"error": "This action needs a signed-in user to confirm it."}
        from app.core.deps import has_permission
        if not has_permission(self.user, "ai.actions"):
            return {"error": "You don't have permission to let the AI prepare drafts (ask your manager for 'ai.actions')."}
        d = AiDraft(company_id=self.cid, user_id=self.user.id, tool=tool, args=args, summary=summary)
        self.db.add(d)
        self.db.commit()
        return {"draft_id": d.id, "status": "awaiting your confirmation", "summary": summary,
                "note": "Nothing was created yet. Show this to the user and ask them to confirm it (Confirm/Reject) before it happens."}

    def create_task(self, title: str, description: str = "", customer_id: int | None = None) -> dict:
        return self._draft("create_task", {"title": title, "description": description, "customer_id": customer_id},
                           f"Create task: {title}" + (f" — {description}" if description else ""))

    def create_purchase_request(self, items: list[dict], supplier_id: int | None = None, notes: str = "") -> dict:
        supplier = self.db.get(Supplier, supplier_id) if supplier_id else self.db.query(Supplier).filter_by(company_id=self.cid).first()
        if not supplier or supplier.company_id != self.cid:
            return {"error": "No supplier found. Create a supplier first."}
        names = []
        total = 0.0
        for it in items:
            p = self.db.get(Product, int(it.get("product_id", 0)))
            if not p or p.company_id != self.cid:
                continue
            names.append(f"{p.name} x{it['quantity']}")
            total += float(it["quantity"]) * p.cost_price
        if not names:
            return {"error": "None of the products were found."}
        return self._draft("create_purchase_request", {"items": items, "supplier_id": supplier.id, "notes": notes},
                           f"Purchase request from {supplier.name}: {', '.join(names)} (~{round(total, 2)})")

    def create_customer(self, name: str, email: str = "", phone: str = "") -> dict:
        return self._draft("create_customer", {"name": name, "email": email, "phone": phone},
                           f"Add customer: {name}" + (f" · {phone}" if phone else ""))

    def send_notification(self, title: str, message: str, severity: str = "info") -> dict:
        return self._draft("send_notification", {"title": title, "message": message, "severity": severity}, f"Send notification: {title}")


def execute_draft(db: Session, cid: int, user_name: str, draft: AiDraft) -> dict:
    """Run the action a confirmed AiDraft describes. Called only after the user explicitly confirmed it — never by
    the AI itself. Reuses the same code the AI's tools used to run directly, now for real."""
    a = draft.args
    if draft.tool == "create_task":
        t = Task(company_id=cid, title=a["title"], description=a.get("description") or "", related_customer_id=a.get("customer_id"),
                 created_by=f"AI Agent ({user_name}), confirmed")
        db.add(t)
        db.flush()
        return {"task_id": t.id, "status": "created"}
    if draft.tool == "create_purchase_request":
        supplier = db.get(Supplier, a["supplier_id"])
        if not supplier or supplier.company_id != cid:
            return {"error": "The supplier no longer exists."}
        po = PurchaseOrder(company_id=cid, number=next_number(db, PurchaseOrder, cid, "PR"), supplier_id=supplier.id, status="request",
                           requested_by=f"AI Agent ({user_name}), confirmed", notes=a.get("notes") or "Created by AI agent, confirmed by the user.")
        db.add(po)
        db.flush()
        total = 0.0
        for it in a["items"]:
            p = db.get(Product, int(it.get("product_id", 0)))
            if not p or p.company_id != cid:
                continue
            lt = float(it["quantity"]) * p.cost_price
            db.add(PurchaseOrderItem(company_id=cid, po_id=po.id, product_id=p.id, quantity=float(it["quantity"]), unit_cost=p.cost_price, line_total=lt))
            total += lt
        po.total = round(total, 2)
        db.flush()
        return {"purchase_request": po.number, "total": po.total, "status": "request — awaiting approval"}
    if draft.tool == "create_customer":
        c = Customer(company_id=cid, name=a["name"], email=a.get("email") or None, phone=a.get("phone") or None)
        db.add(c)
        db.flush()
        return {"customer_id": c.id, "status": "created"}
    if draft.tool == "send_notification":
        db.add(Alert(company_id=cid, severity=a.get("severity", "info"), category="ai", title=a["title"], message=a.get("message", "")))
        db.flush()
        return {"status": "notification created"}
    return {"error": f"unknown draft tool {draft.tool}"}


TOOL_SPECS = [
    {"name": "query_sales", "description": "Sales revenue, grouped by summary/customer/product/warehouse/category/month.",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string", "enum": ["this_month", "last_month", "this_year", "last_90_days"]}, "group_by": {"type": "string", "enum": ["summary", "customer", "product", "warehouse", "category", "month"]}, "limit": {"type": "integer"}}}},
    {"name": "query_profit", "description": "Profit and margins by product and category.",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string", "enum": ["this_month", "last_month", "this_year", "last_90_days"]}, "limit": {"type": "integer"}}}},
    {"name": "query_inventory", "description": "Low stock products, inventory value, or demand forecast.",
     "input_schema": {"type": "object", "properties": {"filter": {"type": "string", "enum": ["low_stock", "forecast"]}}}},
    {"name": "query_customers", "description": "Top customers, customers owing more than a threshold, or inactive customers.",
     "input_schema": {"type": "object", "properties": {"filter": {"type": "string", "enum": ["top", "owing", "inactive"]}, "threshold": {"type": "number"}, "period": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "query_finance", "description": "KPIs, cashflow, overdue invoices.",
     "input_schema": {"type": "object", "properties": {"view": {"type": "string", "enum": ["summary", "cashflow", "overdue"]}}}},
    {"name": "query_anomalies", "description": "Days where sales or expenses jumped or dropped well outside the company's own recent baseline (statistical, not a guess).",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}}}},
    {"name": "analyze_business", "description": "Full business health analysis: risks, positives, causes and recommended actions. Use for 'why' questions.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "search_documents", "description": "Search company policies, contracts, catalogs and procedures (RAG).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "create_report", "description": "Generate a management report.",
     "input_schema": {"type": "object", "properties": {"report_type": {"type": "string"}, "period": {"type": "string"}}}},
    {"name": "create_task", "description": "Prepare a draft follow-up task (the user must confirm it before it is created).",
     "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"}, "customer_id": {"type": "integer"}}, "required": ["title"]}},
    {"name": "create_purchase_request", "description": "Prepare a draft purchase request the user must confirm (it then still needs manager approval).",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"product_id": {"type": "integer"}, "quantity": {"type": "number"}}}}, "supplier_id": {"type": "integer"}, "notes": {"type": "string"}}, "required": ["items"]}},
    {"name": "create_customer", "description": "Prepare a draft new customer (the user must confirm it before it is created).",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"}}, "required": ["name"]}},
    {"name": "send_notification", "description": "Prepare a draft in-app notification to management (the user must confirm before it is sent).",
     "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "message": {"type": "string"}, "severity": {"type": "string"}}, "required": ["title", "message"]}},
]

SYSTEM_PROMPT = """You are the AI Business Analyst inside a company's business operating system.
Answer ONLY from tool results — never invent numbers. Currency: {currency}. Today: {today}.
Be concise and managerial: lead with the answer, then the key numbers, then 1-3 recommended actions.
Answer in the same language the user writes in (Arabic, Hebrew or English).
Actions that change data (purchase requests, tasks, customers, notifications) never happen immediately: calling one of those
tools only prepares a draft. Tell the user what you prepared and that they must confirm it themselves in the app before
anything is created — never say you "created" or "sent" it; say you "prepared a draft" of it."""


# ---------------------------------------------------------------- LLM loop
def _client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def call_claude(**kwargs):
    """One Messages API call. `fallbacks: "default"` lets the API re-run a request that the model's safety
    classifiers decline on Anthropic's recommended fallback model instead of returning a refusal."""
    return _client().beta.messages.create(model=settings.AI_MODEL, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)


def run_tool(tb: ToolBox, name: str, args: dict) -> dict:
    """Run one tool the model asked for. Only the listed tools can run — never any other method of the toolbox."""
    if name not in TOOL_PERMISSIONS or not isinstance(args, dict):
        return {"error": f"unknown tool {name}"}
    try:
        out = getattr(tb, name)(**args)
        return out if isinstance(out, dict) else {"result": out}
    except Exception as ex:  # noqa: BLE001
        tb.db.rollback()
        return {"error": str(ex)}


def run_llm_agent(tb: ToolBox, question: str, history: list[dict], currency: str) -> tuple[str, list[str], dict]:
    system = SYSTEM_PROMPT.format(currency=currency, today=date.today().isoformat())
    messages: list = [*history[-8:], {"role": "user", "content": question}]
    used, data = [], {}
    for _ in range(8):
        resp = call_claude(max_tokens=16000, system=system, tools=TOOL_SPECS, messages=messages)
        if resp.stop_reason == "refusal":
            return "I can't help with that request.", used, data
        # keep the full content (thinking + tool_use blocks) so the next turn continues the same reasoning
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text, used, data
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            out = run_tool(tb, block.name, block.input or {})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str), **({"is_error": True} if "error" in out else {})})
            used.append(block.name)
            data[block.name] = out
        messages.append({"role": "user", "content": results})
    return "I could not finish the analysis within the tool budget.", used, data


# ---------------------------------------------------------------- reading supplier invoices
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": "string"},
        "supplier_invoice_no": {"type": "string"},
        "invoice_date": {"type": "string", "description": "YYYY-MM-DD, or empty if not shown"},
        "currency": {"type": "string"},
        "tax_amount": {"type": "number"},
        "total": {"type": "number"},
        "lines": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "code": {"type": "string", "description": "product code / barcode if printed, else empty"},
                "quantity": {"type": "number"},
                "unit_cost": {"type": "number", "description": "price per unit before tax"},
            },
            "required": ["name", "code", "quantity", "unit_cost"],
            "additionalProperties": False,
        }},
    },
    "required": ["supplier_name", "supplier_invoice_no", "invoice_date", "currency", "tax_amount", "total", "lines"],
    "additionalProperties": False,
}

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
        "total": {"type": "number"},
        "tax_amount": {"type": "number"},
        "category": {"type": "string", "enum": ["Rent", "Salaries", "Utilities", "Marketing", "Logistics", "Insurance", "Other"]},
        "description": {"type": "string"},
    },
    "required": ["vendor", "date", "total", "tax_amount", "category", "description"],
    "additionalProperties": False,
}


MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf"}


def extract_supplier_invoice(filename: str, content: bytes) -> dict:
    """Read a photo or PDF of a supplier invoice and return its header and lines as structured data."""
    import base64
    ext = os.path.splitext(filename.lower())[1]
    media = MEDIA.get(ext)
    if not media:
        raise ValueError("Upload a photo (JPG/PNG/WEBP) or a PDF")
    b64 = base64.standard_b64encode(content).decode("ascii")
    block = ({"type": "document", "source": {"type": "base64", "media_type": media, "data": b64}} if media == "application/pdf"
             else {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}})
    resp = call_claude(
        max_tokens=16000,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": (
            "This is a supplier invoice (it may be in Arabic, Hebrew or English). Extract the supplier name, the supplier's invoice "
            "number, the invoice date, currency, total VAT and grand total, and every product line with its quantity and unit price "
            "before tax. Copy product names exactly as printed. Use 0 or an empty string for anything that is not on the document.")}]}],
        output_config={"format": {"type": "json_schema", "schema": INVOICE_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise ValueError("The document could not be read")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


# ---------------------------------------------------------------- offline fallback
def _fmt(n: float, cur: str) -> str:
    return f"{n:,.0f} {cur}"


ANSWERS = {
    "en": {
        "owing": "{n} customers owe more than {t}:",
        "owing_none": "No customers owe more than {t}.",
        "top_customers": "Top {n} customers by revenue ({s} → {e}):",
        "top_customer_row": "{i}. {name} — {rev} ({orders} orders)",
        "profit": "Highest-profit products ({s} → {e}):",
        "profit_row": "{i}. {name} — profit {profit} (margin {margin}%)",
        "warehouses": "Sales by warehouse:",
        "warehouse_row": "• {name}: {rev} ({orders} orders)",
        "stock_none": "No products are at stock-out risk right now.",
        "stock": "Products at stock-out risk:",
        "stock_row": "• {name}: stock {stock:.0f}, 7-day demand {demand:.0f}, risk {risk} → order {qty:.0f}",
        "overdue": "{n} overdue invoices:",
        "overdue_row": "• {number} due {due} — {bal}",
        "cash": "Cashflow (last 6 months):",
        "cash_row": "• {month}: in {cin}, out {cout}, net {net}",
        "docs": "From company documents:",
        "sales": "Revenue {s} → {e}: {rev}; gross profit {gp}.",
    },
    "ar": {
        "owing": "{n} زباين عليهم أكثر من {t}:",
        "owing_none": "ما في ولا زبون عليه أكثر من {t}.",
        "top_customers": "أفضل {n} زبون حسب المبيعات ({s} ← {e}):",
        "top_customer_row": "{i}. {name} — {rev} ({orders} طلب)",
        "profit": "المنتجات اللي بتجيب أكثر ربح ({s} ← {e}):",
        "profit_row": "{i}. {name} — ربح {profit} (هامش {margin}%)",
        "warehouses": "المبيعات حسب المستودع:",
        "warehouse_row": "• {name}: {rev} ({orders} طلب)",
        "stock_none": "ما في منتجات بخطر إنها تخلص هلأ.",
        "stock": "منتجات ممكن يخلص مخزونها:",
        "stock_row": "• {name}: الموجود {stock:.0f}، المتوقع ينباع بأسبوع {demand:.0f}، الخطر {risk} ← اطلب {qty:.0f}",
        "overdue": "{n} فواتير متأخرة:",
        "overdue_row": "• {number} كان لازم تندفع {due} — {bal}",
        "cash": "حركة المصاري (آخر 6 شهور):",
        "cash_row": "• {month}: دخل {cin}، طلع {cout}، الصافي {net}",
        "docs": "من ملفات الشركة:",
        "sales": "المبيعات {s} ← {e}: {rev}؛ الربح الإجمالي {gp}.",
    },
}

RISK_AR = {"HIGH": "عالي", "MEDIUM": "متوسط", "LOW": "منخفض"}


def detect_lang(text: str) -> str:
    return "ar" if re.search(r"[؀-ۿ]", text) else "en"


def run_rule_based(tb: ToolBox, q: str, currency: str, lang: str | None = None) -> tuple[str, list[str], dict]:
    lang = lang if lang in ANSWERS else detect_lang(q)
    A = ANSWERS[lang]
    ql = q.lower()
    period = "last_month" if re.search(r"last month|الشهر الماضي|الشهر اللي فات|החודש שעבר", ql) else "this_year" if re.search(r"this year|السنة|هالسنة|هذه السنة|השנה", ql) else "this_month"
    num = re.search(r"(\d[\d,\.]*)", ql)
    threshold = float(num.group(1).replace(",", "")) if num else 5000
    top_n = int(re.search(r"top\s*(\d+)|أفضل\s*(\d+)|أعلى\s*(\d+)", ql).group(0).split()[-1]) if re.search(r"top\s*\d+|أفضل\s*\d+|أعلى\s*\d+", ql) else 20

    if re.search(r"why|لماذا|ليش|ليه|مدוע|explain|analy|وضع|حلل", ql):
        d = tb.analyze_business(lang)
        if "error" in d:
            return d["error"], ["analyze_business"], d
        return d["summary"], ["analyze_business"], d
    if re.search(r"owe|owing|balance|يدين|مديون|ديون|عليهم|عليه|חוב", ql):
        d = tb.query_customers("owing", threshold=threshold)
        if "error" in d:
            return d["error"], ["query_customers"], d
        rows = d["customers"]
        t = _fmt(threshold, currency)
        txt = A["owing"].format(n=len(rows), t=t) + "\n" + "\n".join(f"• {r['name']}: {_fmt(r['balance'], currency)}" for r in rows[:20])
        return txt if rows else A["owing_none"].format(t=t), ["query_customers"], d
    if re.search(r"customer|عميل|عملاء|زبون|زباين|زبائن|לקוח", ql) and re.search(r"top|best|أفضل|أحسن|أعلى|أكبر|revenue", ql) and not re.search(r"inactive|بطّلوا|بطلوا", ql):
        d = tb.query_customers("top", period=period, limit=top_n)
        if "error" in d:
            return d["error"], ["query_customers"], d
        rows = d["top_customers"]
        return A["top_customers"].format(n=len(rows), s=d["period"][0], e=d["period"][1]) + "\n" + "\n".join(
            A["top_customer_row"].format(i=i + 1, name=r["name"], rev=_fmt(r["revenue"], currency), orders=r["orders"]) for i, r in enumerate(rows)), ["query_customers"], d
    if re.search(r"inactive|بطّلوا|بطلوا|خامل", ql):
        d = tb.query_customers("inactive", threshold=60)
        if "error" in d:
            return d["error"], ["query_customers"], d
        rows = d["inactive_customers"]
        if not rows:
            return ("كل الزباين اشتروا خلال آخر 60 يوم." if lang == "ar" else "All customers bought something in the last 60 days."), ["query_customers"], d
        head = f"{len(rows)} زباين ما اشتروا من 60 يوم:" if lang == "ar" else f"{len(rows)} customers inactive for 60+ days:"
        return head + "\n" + "\n".join(f"• {r['name']}" for r in rows[:20]), ["query_customers"], d
    if re.search(r"profit|margin|ربح|هامش|רווח", ql):
        d = tb.query_profit(period, limit=top_n)
        if "error" in d:
            return d["error"], ["query_profit"], d
        rows = d["top_products_by_profit"]
        return A["profit"].format(s=d["period"][0], e=d["period"][1]) + "\n" + "\n".join(
            A["profit_row"].format(i=i + 1, name=r["name"], profit=_fmt(r["profit"], currency), margin=r["margin_pct"]) for i, r in enumerate(rows[:10])), ["query_profit"], d
    if re.search(r"warehouse|مستودع|مستودعات|مخزن|מחסן", ql) and re.search(r"compar|sales|قارن|مبيعات", ql):
        d = tb.query_sales(period, group_by="warehouse")
        if "error" in d:
            return d["error"], ["query_sales"], d
        return A["warehouses"] + "\n" + "\n".join(A["warehouse_row"].format(name=w["name"], rev=_fmt(w["revenue"], currency), orders=w["orders"]) for w in d["warehouses"]), ["query_sales"], d
    if re.search(r"stock|inventory|forecast|مخزون|بضاعة|يخلص|توقع|מלאי", ql):
        d = tb.query_inventory("forecast")
        if "error" in d:
            return d["error"], ["query_inventory"], d
        rows = d["forecast"]
        if not rows:
            return A["stock_none"], ["query_inventory"], d
        return A["stock"] + "\n" + "\n".join(A["stock_row"].format(
            name=r["product_name"], stock=r["current_stock"], demand=r["predicted_7d_demand"],
            risk=RISK_AR.get(r["risk"], r["risk"]) if lang == "ar" else r["risk"], qty=r["recommended_order_qty"]) for r in rows[:10]), ["query_inventory"], d
    if re.search(r"overdue|late|متأخر|متاخر|פיגור", ql):
        d = tb.query_finance("overdue")
        if "error" in d:
            return d["error"], ["query_finance"], d
        return A["overdue"].format(n=len(d["overdue_invoices"])) + "\n" + "\n".join(
            A["overdue_row"].format(number=i["number"], due=i["due_date"], bal=_fmt(i["balance"], currency)) for i in d["overdue_invoices"][:15]), ["query_finance"], d
    if re.search(r"cash|نقد|مصاري|كاش|תזרים", ql):
        d = tb.query_finance("cashflow")
        if "error" in d:
            return d["error"], ["query_finance"], d
        return A["cash"] + "\n" + "\n".join(A["cash_row"].format(
            month=c["month"], cin=_fmt(c["cash_in"], currency), cout=_fmt(c["cash_out"], currency), net=_fmt(c["net"], currency)) for c in d["cashflow"]), ["query_finance"], d
    if re.search(r"policy|contract|procedure|catalog|discount|سياسة|عقد|إجراء|نهج|خصم|خصومات", ql):
        d = tb.search_documents(q)
        if "error" in d:
            return d["error"], ["search_documents"], d
        if d["hits"]:
            return A["docs"] + "\n" + "\n\n".join(f"[{h['document_title']}] {h['content'][:400]}" for h in d["hits"][:3]), ["search_documents"], d
    if re.search(r"sales|revenue|مبيعات|إيراد|بيع|מכירות", ql):
        d = tb.query_sales(period, group_by="summary")
        if "error" in d:
            return d["error"], ["query_sales"], d
        return A["sales"].format(s=d["period"][0], e=d["period"][1], rev=_fmt(d["revenue"], currency), gp=_fmt(d["gross_profit"], currency)), ["query_sales"], d
    d = tb.analyze_business(lang)
    if "error" in d:
        return d["error"], ["analyze_business"], d
    return d["summary"], ["analyze_business"], d


def ask(db: Session, cid: int, user_id: int, user_name: str, currency: str, question: str, history: list[dict], lang: str | None = None,
        user=None) -> dict:
    tb = ToolBox(db, cid, user_name, user)
    docs_used: list[str] = []
    if settings.ANTHROPIC_API_KEY:
        try:
            answer, used, data = run_llm_agent(tb, question, history, currency)
        except Exception as ex:  # noqa: BLE001
            from app.core.observability import log_error
            log_error("ai", f"Claude request failed: {type(ex).__name__}: {ex}", company_id=cid, level="warning")
            answer, used, data = run_rule_based(tb, question, currency, lang)
            data = {used[0]: data} if used else data
            answer += f"\n\n(LLM unavailable: {ex}; answered with built-in analytics.)"
    else:
        answer, used, data = run_rule_based(tb, question, currency, lang)
        data = {used[0]: data} if used else data
    if "search_documents" in data:
        docs_used = sorted({h["document_title"] for h in data["search_documents"].get("hits", [])})
    db.add(AIConversation(company_id=cid, user_id=user_id, question=question, answer=answer, tools_used=used))
    db.commit()
    return {"answer": answer, "tools_used": used, "data": json.loads(json.dumps(data, default=str)), "grounded_on_documents": docs_used}


def extract_receipt(filename: str, content: bytes) -> dict:
    """Read a photo/PDF of an expense receipt (fuel, electricity bill, restaurant...) into an expense."""
    import base64
    ext = os.path.splitext(filename.lower())[1]
    media = MEDIA.get(ext)
    if not media:
        raise ValueError("Upload a photo (JPG/PNG/WEBP) or a PDF")
    b64 = base64.standard_b64encode(content).decode("ascii")
    block = ({"type": "document", "source": {"type": "base64", "media_type": media, "data": b64}} if media == "application/pdf"
             else {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}})
    resp = call_claude(
        max_tokens=4000,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": (
            "This is a receipt or bill for a business expense (Arabic, Hebrew or English). Extract who was paid, the date, the total paid, "
            "the VAT included in it (0 if not shown), pick the closest category, and write a short description in the receipt's language.")}]}],
        output_config={"format": {"type": "json_schema", "schema": RECEIPT_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise ValueError("The document could not be read")
    return json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))
