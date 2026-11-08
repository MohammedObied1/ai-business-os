"""Phase 2 — multi-tenant attack suite.

Company B is filled with one of (almost) everything, every name carrying the marker ZZB. Company A then attacks:
every route that takes an id in its path (with B's ids), ids in request bodies, ids in query parameters, search,
files, exports, reports, AI tools, API keys, public links, webhooks and background jobs.
A leak = a 2xx answer on B's record, or the marker showing up anywhere in A's responses.
At the end the whole database is scanned: no row of one company may point (by foreign key) at a row of another.
"""
import re
from datetime import date, timedelta

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

MARK = "ZZB"


def _admin(client):
    tok = client.post("/api/auth/login", data={"username": "root@platform.test", "password": "rootpass1"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _ok(r, what):
    assert r.status_code in (200, 201), f"seed failed: {what}: {r.status_code} {r.text[:300]}"
    return r.json() if r.content else None


def _company(client, admin, name, email, mark=""):
    _ok(client.post("/api/platform/companies", headers=admin, json={"name": f"{name} {mark}".strip(), "tax_rate": 0, "owner_name": f"Owner {mark}".strip(),
                                                                    "owner_email": email, "owner_password": "secret12"}), "company")
    tok = client.post("/api/auth/login", data={"username": email, "password": "secret12"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _seed(client, h, m):
    """One record of every kind, all names containing the marker `m`. Returns the ids."""
    ids = {}
    ids["branch"] = _ok(client.post("/api/branches", headers=h, json={"name": f"Branch {m}"}), "branch")["id"]
    ids["warehouse"] = _ok(client.post("/api/inventory/warehouses", headers=h, json={"name": f"WH {m}"}), "warehouse")["id"]
    ids["product"] = _ok(client.post("/api/inventory/products", headers=h, json={
        "name": f"Product {m}", "cost_price": 4, "sale_price": 10, "barcode": f"BC{m}", "opening_stock": 50, "warehouse_id": ids["warehouse"]}), "product")["id"]
    ids["product2"] = _ok(client.post("/api/inventory/products", headers=h, json={"name": f"Made {m}", "sale_price": 20}), "product2")["id"]
    ids["price_list"] = _ok(client.post("/api/price-lists", headers=h, json={"name": f"PL {m}", "items": [{"product_id": ids["product"], "price": 7.77}]}), "pl")["id"]
    ids["promo"] = _ok(client.post("/api/promotions", headers=h, json={"name": f"Promo {m}", "kind": "percent", "percent": 5, "product_id": ids["product"]}), "promo")["id"]
    ids["customer"] = _ok(client.post("/api/customers", headers=h, json={"name": f"Customer {m}", "phone": "0599123456", "email": "c@zzb.ps"}), "customer")["id"]
    ids["supplier"] = _ok(client.post("/api/purchasing/suppliers", headers=h, json={"name": f"Supplier {m}"}), "supplier")["id"]
    accounts = _ok(client.get("/api/accounts", headers=h), "accounts")
    ids["account"] = accounts[0]["id"]
    order = _ok(client.post("/api/sales/orders", headers=h, json={"customer_id": ids["customer"], "warehouse_id": ids["warehouse"], "notes": f"note {m}",
                                                                  "items": [{"product_id": ids["product"], "quantity": 2}]}), "order")
    ids["order"] = order["id"]
    inv = _ok(client.post("/api/sales/invoices", headers=h, json={"customer_id": ids["customer"], "order_id": ids["order"]}), "invoice")
    ids["invoice"] = inv["id"]
    pay = _ok(client.post("/api/sales/payments", headers=h, json={"invoice_id": ids["invoice"], "amount": 5, "method": "cash", "reference": f"ref {m}"}), "payment")
    ids["voucher"] = pay["number"]
    _ok(client.post("/api/sales/payments", headers=h, json={"invoice_id": ids["invoice"], "amount": 5, "method": "cheque",
                                                           "cheque": {"number": f"CH{m}", "bank": f"Bank {m}", "due_date": str(date.today() + timedelta(days=9))}}), "cheque pay")
    ids["cheque"] = _ok(client.get("/api/cheques", headers=h), "cheques")[0]["id"]
    ret = _ok(client.post("/api/sales/returns", headers=h, json={"order_id": ids["order"], "reason": f"ret {m}",
                                                                 "items": [{"order_item_id": order["items"][0]["id"], "quantity": 1}]}), "return")
    ids["return"] = ret["id"]
    inv2 = _ok(client.post("/api/sales/invoices", headers=h, json={"customer_id": ids["customer"], "total": 300, "description": f"Service {m}"}), "invoice2")
    ids["invoice2"] = inv2["id"]
    _ok(client.post(f"/api/sales/invoices/{ids['invoice2']}/installments", headers=h, json={"count": 3, "first_due": str(date.today())}), "installments")
    ids["recurring"] = _ok(client.post("/api/sales/recurring", headers=h, json={"customer_id": ids["customer"], "description": f"Rent {m}", "amount": 50,
                                                                               "next_date": str(date.today() + timedelta(days=30))}), "recurring")["id"]
    po = _ok(client.post("/api/purchasing/orders", headers=h, json={"supplier_id": ids["supplier"], "warehouse_id": ids["warehouse"], "notes": f"po {m}",
                                                                    "items": [{"product_id": ids["product"], "quantity": 3, "unit_cost": 4}]}), "po")
    ids["po"] = po["id"]
    ids["expense"] = _ok(client.post("/api/finance/expenses", headers=h, json={"category": "Rent", "description": f"Rent {m}", "amount": 20}), "expense")["id"]
    ids["gl"] = _ok(client.post("/api/accounting/accounts", headers=h, json={"code": "1799", "name": f"GL {m}", "type": "asset"}), "gl")["id"]
    chart = _ok(client.get("/api/accounting/accounts", headers=h), "chart")
    cash_gl = next(a["id"] for a in chart if a["type"] == "asset" and a["id"] != ids["gl"])
    ids["journal"] = _ok(client.post("/api/accounting/journal", headers=h, json={"entry_date": str(date.today()), "memo": f"JV {m}", "lines": [
        {"account_id": ids["gl"], "debit": 10}, {"account_id": cash_gl, "credit": 10}]}), "journal")["id"]
    ids["employee"] = _ok(client.post("/api/hr/employees", headers=h, json={"full_name": f"Employee {m}", "base_salary": 3000}), "employee")["id"]
    run = _ok(client.post("/api/hr/payroll?month=" + date.today().strftime("%Y-%m"), headers=h), "payroll")
    ids["payroll"] = run["id"]
    detail = _ok(client.get(f"/api/hr/payroll/{ids['payroll']}", headers=h), "payroll detail")
    ids["payslip"] = detail["slips"][0]["id"]
    roles = _ok(client.get("/api/users/roles", headers=h), "roles")
    ids["role"] = _ok(client.post("/api/users/roles", headers=h, json={"name": f"Role {m}", "permissions": ["sales:read"]}), "role")["id"]
    cashier = next(r["id"] for r in roles if r["name"] == "Cashier")
    ids["user"] = _ok(client.post("/api/users", headers=h, json={"email": f"staff{m.lower() or 'a'}@t.ps", "full_name": f"Staff {m}", "password": "secret12",
                                                                "role_id": cashier}), "user")["id"]
    ids["task"] = _ok(client.post("/api/tasks", headers=h, json={"title": f"Task {m}"}), "task")["id"]
    ids["rule"] = _ok(client.post("/api/automation/rules", headers=h, json={"name": f"Rule {m}", "condition_type": "low_stock"}), "rule")["id"]
    ids["document"] = _ok(client.post("/api/documents/text", headers=h, json={"title": f"Policy {m}", "doc_type": "policy",
                                                                                "content": f"Secret discount policy {m} for wholesale."}), "doc")["id"]
    ids["attachment"] = _ok(client.post(f"/api/attachments?entity=customer&entity_id={ids['customer']}", headers=h,
                                        files={"file": (f"contract-{m}.txt", f"contract {m}".encode(), "text/plain")}), "attachment")["id"]
    ids["count"] = _ok(client.post(f"/api/stock-counts?warehouse_id={ids['warehouse']}&note=count%20{m}", headers=h), "count")["id"]
    ids["bom"] = _ok(client.post("/api/manufacturing/boms", headers=h, json={"product_id": ids["product2"], "output_qty": 1, "note": f"bom {m}",
                                                                            "lines": [{"product_id": ids["product"], "quantity": 1}]}), "bom")["id"]
    ids["delivery"] = _ok(client.post("/api/deliveries", headers=h, json={"order_id": ids["order"], "address": f"Street {m}"}), "delivery")["id"]
    _ok(client.post("/api/field/visits", headers=h, json={"customer_id": ids["customer"], "note": f"visit {m}"}), "visit")
    ids["key"] = _ok(client.post("/api/integrations/keys", headers=h, json={"name": f"Key {m}"}), "key")
    ids["hook"] = _ok(client.post("/api/integrations/webhooks", headers=h, json={"url": "http://127.0.0.1:9/hook", "events": ["*"]}), "hook")["id"]
    ids["portal"] = _ok(client.post(f"/api/customers/{ids['customer']}/portal-link", headers=h), "portal")["token"]
    ids["share"] = _ok(client.post(f"/api/sales/invoices/{ids['invoice']}/share", headers=h), "share")["token"]
    _ok(client.post(f"/api/public/portal/{ids['portal']}/payment-proof", data={"amount": "5", "reference": f"TRX {m}"}), "proof")
    ids["proof"] = _ok(client.get("/api/customers/payment-proofs/pending", headers=h), "proofs")[0]["id"]
    _ok(client.post("/api/automation/run", headers=h), "automation")
    alerts = _ok(client.get("/api/alerts", headers=h), "alerts")
    ids["alert"] = alerts[0]["id"] if alerts else 0
    target = _ok(client.post("/api/inventory/warehouses", headers=h, json={"name": f"Destination {m}"}), "destination")
    ids["transfer"] = _ok(client.post("/api/inventory/transfers", headers=h, json={
        "from_warehouse_id": ids["warehouse"], "to_warehouse_id": target["id"], "submit": False,
        "lines": [{"product_id": ids["product"], "quantity": 1}],
    }), "stock transfer")["id"]
    ids["saved_report"] = _ok(client.post("/api/reports/saved", headers=h, json={"name": f"Report {m}", "report": "pnl"}), "saved report")["id"]
    # Pending resources have no direct creation API; seed valid tenant-owned rows.
    from app.core.database import SessionLocal
    from app.models import User
    from app.models.comms import Notification
    from app.models.control import AiDraft
    from app.models.ext import ImportBatch
    owner_id = _ok(client.get("/api/auth/me", headers=h), "owner")["id"]
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        notice = Notification(company_id=owner.company_id, user_id=owner_id, kind="low_stock", title=f"Notice {m}")
        draft = AiDraft(company_id=owner.company_id, user_id=owner_id, tool="create_task", args={"title": f"Draft {m}"}, summary=f"Draft {m}")
        batch = ImportBatch(company_id=owner.company_id, user_id=owner_id, entity="products", filename=f"import-{m}.csv")
        db.add_all([notice, draft, batch])
        db.commit()
        ids.update(notification=notice.id, draft=draft.id, import_batch=batch.id)
    return ids


@pytest.fixture(scope="module")
def world(client):
    admin = _admin(client)
    ha = _company(client, admin, "Tenant A", "owner@tenant-a.ps")
    hb = _company(client, admin, "Tenant", "owner@tenant-b.ps", MARK)
    a = _seed(client, ha, "")
    b = _seed(client, hb, MARK)
    return {"ha": ha, "hb": hb, "a": a, "b": b, "admin": admin}


# path parameter → which of B's ids to use
def _param_value(path: str, name: str, b: dict):
    if name == "account_id":
        return b["gl"] if path.startswith("/api/accounting") else b["account"]
    table = {"alert_id": "alert", "att_id": "attachment", "branch_id": "branch", "cheque_id": "cheque", "count_id": "count", "customer_id": "customer",
             "delivery_id": "delivery", "doc_id": "document", "eid": "employee", "entry_id": "journal", "expense_id": "expense", "hook_id": "hook",
             "invoice_id": "invoice", "key_id": "key", "order_id": "order", "pl_id": "price_list", "po_id": "po", "product_id": "product",
             "promo_id": "promo", "proof_id": "proof", "rid": "recurring", "role_id": "role", "rule_id": "rule", "run_id": "payroll",
             "slip_id": "payslip", "supplier_id": "supplier", "task_id": "task", "user_id": "user", "warehouse_id": "warehouse", "number": "voucher"}
    table.update(nid="notification", tid="transfer", report_id="saved_report", draft_id="draft", batch_id="import_batch")
    key = table.get(name)
    if key == "key":
        return b["key"]["id"]
    return b[key] if key else None


# bodies that pass validation, so the handler really runs (a 422 alone would prove nothing)
def _body(method: str, path: str, b: dict):
    samples = {
        "PATCH /api/customers/{customer_id}": {"name": "hacked"},
        "PATCH /api/inventory/products/{product_id}": {"name": "hacked"},
        "PATCH /api/inventory/warehouses/{warehouse_id}": {"name": "hacked"},
        "PATCH /api/purchasing/suppliers/{supplier_id}": {"name": "hacked"},
        "PATCH /api/hr/employees/{eid}": {"full_name": "hacked"},
        "PATCH /api/branches/{branch_id}": {"name": "hacked"},
        "PATCH /api/users/{user_id}": {"full_name": "hacked"},
        "PUT /api/users/roles/{role_id}": {"name": "hacked", "permissions": ["*"]},
        "PATCH /api/accounting/accounts/{account_id}": {"code": "9", "name": "hacked", "type": "asset"},
        "PATCH /api/accounts/{account_id}": {"name": "hacked"},
        "PUT /api/price-lists/{pl_id}": {"name": "hacked"},
        "PUT /api/promotions/{promo_id}": {"name": "hacked", "kind": "percent", "percent": 50, "product_id": b["product"]},
        "PATCH /api/sales/recurring/{rid}": {"customer_id": b["customer"], "description": "hacked", "amount": 1, "next_date": str(date.today())},
        "PATCH /api/automation/rules/{rule_id}": {"name": "hacked", "condition_type": "low_stock"},
        "POST /api/sales/invoices/{invoice_id}/installments": {"count": 2, "first_due": str(date.today())},
        "POST /api/sales/invoices/{invoice_id}/email": {"to": "attacker@evil.ps"},
        "POST /api/deliveries/{delivery_id}/status": {"status": "delivered", "cash_collected": 1},
        "PUT /api/stock-counts/{count_id}/lines": [{"product_id": b["product"], "counted": 0}],
        "PATCH /api/hr/payroll/{run_id}/slips/{slip_id}": {"bonus": 1000},
        "POST /api/customers/payment-proofs/{proof_id}": {"approve": True},
        "POST /api/purchasing/orders/{po_id}/receive": {"warehouse_id": b["warehouse"]},
        "POST /api/hr/payroll/{run_id}/pay": {},
        "POST /api/customers/{customer_id}/interactions": {"kind": "note", "summary": "hacked"},
        "PATCH /api/finance/expenses/{expense_id}": {"category": "Rent", "amount": 1},
    }
    return samples.get(f"{method} {path}", {})


# required query parameters, so the request reaches the handler
QUERY = {"/api/sales/orders/{order_id}/status": "?status=cancelled", "/api/purchasing/orders/{po_id}/status": "?status=cancelled",
         "/api/purchasing/orders/{po_id}/pay": "?amount=1", "/api/tasks/{task_id}/status": "?status=done"}

# Period/provider are company-local natural keys, not foreign record IDs. Their
# isolation is exercised separately with the same key in both companies below.
SKIP_PARAMS = {"entity", "report", "code", "name", "slug", "token", "company_id", "cid", "plan_id", "number", "period", "provider"}


def test_path_ids_of_another_company_are_rejected(client, world):
    from app.main import app
    ha, b = world["ha"], world["b"]
    leaks, weak = [], []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path.startswith(("/api/platform", "/api/public")):
            continue
        params = re.findall(r"{(\w+)}", route.path)
        if not params or set(params) & SKIP_PARAMS:
            continue
        values = {p: _param_value(route.path, p, b) for p in params}
        if None in values.values():
            leaks.append(f"no test value for {route.path}")
            continue
        url = route.path.format(**values) + QUERY.get(route.path, "")
        for method in route.methods:
            body = _body(method, route.path, b)
            r = client.request(method, url, headers=ha, json=body if method in ("POST", "PUT", "PATCH") else None)
            if r.status_code < 300 or r.status_code >= 500 or MARK in r.text:
                leaks.append(f"{method} {route.path} → {r.status_code} {r.text[:120]}")
            elif r.status_code == 422:
                weak.append(f"{method} {route.path}")
    assert not leaks, "cross-tenant access:\n" + "\n".join(leaks)
    assert not weak, "these were only stopped by body validation, the ownership check never ran:\n" + "\n".join(weak)


def test_ids_of_another_company_in_request_bodies_are_rejected(client, world):
    ha, a, b = world["ha"], world["a"], world["b"]
    today = str(date.today())
    attacks = [
        ("POST", "/api/customers", {"name": "x", "price_list_id": b["price_list"]}),
        ("POST", "/api/customers", {"name": "x", "assigned_user_id": b["user"]}),
        ("POST", "/api/customers", {"name": "x", "branch_id": b["branch"]}),
        ("PATCH", f"/api/customers/{a['customer']}", {"price_list_id": b["price_list"]}),
        ("PATCH", f"/api/customers/{a['customer']}", {"assigned_user_id": b["user"]}),
        ("POST", "/api/sales/orders", {"customer_id": b["customer"], "items": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/sales/orders", {"customer_id": a["customer"], "items": [{"product_id": b["product"], "quantity": 1}]}),
        ("POST", "/api/sales/orders", {"customer_id": a["customer"], "warehouse_id": b["warehouse"], "items": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/sales/quote", {"customer_id": b["customer"], "items": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/sales/invoices", {"customer_id": b["customer"], "total": 10}),
        ("POST", "/api/sales/invoices", {"customer_id": a["customer"], "order_id": b["order"]}),
        ("POST", "/api/sales/payments", {"invoice_id": b["invoice"], "amount": 1}),
        ("POST", "/api/sales/payments", {"invoice_id": a["invoice2"], "amount": 1, "account_id": b["account"]}),
        ("POST", "/api/sales/receipts", {"customer_id": b["customer"], "amount": 1}),
        ("POST", "/api/sales/returns", {"order_id": b["order"], "items": [{"order_item_id": 1, "quantity": 1}]}),
        ("POST", "/api/sales/recurring", {"customer_id": b["customer"], "description": "x", "amount": 1, "next_date": today}),
        ("POST", "/api/pos/sale", {"customer_id": b["customer"], "items": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/pos/sale", {"items": [{"product_id": b["product"], "quantity": 1}]}),
        ("POST", "/api/pos/sale", {"warehouse_id": b["warehouse"], "items": [{"product_id": a["product"], "quantity": 1}], "payments": [{"amount": 10}]}),
        ("POST", "/api/pos/sale", {"items": [{"product_id": a["product"], "quantity": 1}], "payments": [{"amount": 10, "account_id": b["account"]}]}),
        ("POST", "/api/pos/shift/open", {"opening_float": 1, "account_id": b["account"]}),
        ("POST", "/api/purchasing/orders", {"supplier_id": b["supplier"], "items": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/purchasing/orders", {"supplier_id": a["supplier"], "items": [{"product_id": b["product"], "quantity": 1}]}),
        ("POST", "/api/purchasing/orders", {"supplier_id": a["supplier"], "warehouse_id": b["warehouse"], "items": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/purchasing/payments", {"supplier_id": b["supplier"], "amount": 1}),
        ("POST", "/api/purchasing/payments", {"supplier_id": a["supplier"], "amount": 1, "po_id": b["po"]}),
        ("POST", "/api/purchasing/payments", {"supplier_id": a["supplier"], "amount": 1, "account_id": b["account"]}),
        ("POST", "/api/finance/expenses", {"category": "Rent", "amount": 1, "account_id": b["account"]}),
        ("POST", "/api/finance/expenses", {"category": "Rent", "amount": 1, "supplier_id": b["supplier"]}),
        ("POST", "/api/finance/expenses", {"category": "Rent", "amount": 1, "branch_id": b["branch"]}),
        ("POST", "/api/vouchers", {"direction": "in", "amount": 1, "account_id": b["account"]}),
        ("POST", "/api/vouchers", {"direction": "in", "amount": 1, "account_id": a["account"], "gl_account_id": b["gl"]}),
        ("POST", "/api/transfers", {"from_account_id": a["account"], "to_account_id": b["account"], "amount": 1}),
        ("POST", "/api/transfers", {"from_account_id": b["account"], "to_account_id": a["account"], "amount": 1}),
        ("POST", "/api/accounting/journal", {"entry_date": today, "memo": "x", "lines": [{"account_id": b["gl"], "debit": 1}, {"account_id": a["gl"], "credit": 1}]}),
        ("POST", "/api/inventory/stock/adjust", {"product_id": b["product"], "warehouse_id": a["warehouse"], "quantity": 1}),
        ("POST", "/api/inventory/stock/adjust", {"product_id": a["product"], "warehouse_id": b["warehouse"], "quantity": 1}),
        ("POST", "/api/inventory/stock/transfer", {"product_id": a["product"], "from_warehouse_id": a["warehouse"], "to_warehouse_id": b["warehouse"], "quantity": 1}),
        ("POST", "/api/inventory/warehouses", {"name": "x", "branch_id": b["branch"]}),
        ("PATCH", f"/api/inventory/warehouses/{a['warehouse']}", {"name": "x", "branch_id": b["branch"]}),
        ("POST", "/api/users", {"email": "x1@t.ps", "full_name": "x", "password": "secret12", "role_id": b["role"]}),
        ("POST", "/api/users", {"email": "x2@t.ps", "full_name": "x", "password": "secret12", "branch_id": b["branch"]}),
        ("PATCH", f"/api/users/{a['user']}", {"branch_id": b["branch"]}),
        ("POST", "/api/hr/employees", {"full_name": "x", "branch_id": b["branch"]}),
        ("POST", "/api/hr/employees", {"full_name": "x", "user_id": b["user"]}),
        ("POST", "/api/hr/attendance", {"employee_id": b["employee"], "day": today}),
        ("POST", "/api/hr/advances", {"employee_id": b["employee"], "amount": 1, "monthly_deduction": 1}),
        ("POST", "/api/hr/advances", {"employee_id": a["employee"], "amount": 1, "monthly_deduction": 1, "account_id": b["account"]}),
        ("POST", "/api/tasks", {"title": "x", "assigned_to_id": b["user"]}),
        ("POST", "/api/tasks", {"title": "x", "related_customer_id": b["customer"]}),
        ("POST", "/api/price-lists", {"name": "x", "items": [{"product_id": b["product"], "price": 1}]}),
        ("POST", "/api/promotions", {"name": "x", "kind": "percent", "percent": 5, "product_id": b["product"]}),
        ("POST", f"/api/stock-counts?warehouse_id={b['warehouse']}", None),
        ("PUT", f"/api/stock-counts/{a['count']}/lines", [{"product_id": b["product"], "counted": 1}]),
        ("POST", "/api/manufacturing/boms", {"product_id": b["product2"], "lines": [{"product_id": a["product"], "quantity": 1}]}),
        ("POST", "/api/manufacturing/boms", {"product_id": a["product2"], "lines": [{"product_id": b["product"], "quantity": 1}]}),
        ("POST", f"/api/manufacturing/orders?bom_id={b['bom']}&quantity=1&warehouse_id={a['warehouse']}", None),
        ("POST", f"/api/manufacturing/orders?bom_id={a['bom']}&quantity=1&warehouse_id={b['warehouse']}", None),
        ("POST", "/api/deliveries", {"order_id": b["order"]}),
        ("POST", "/api/deliveries", {"order_id": a["order"], "driver_id": b["user"]}),
        ("POST", "/api/field/visits", {"customer_id": b["customer"]}),
        ("POST", "/api/field/visits", {"customer_id": a["customer"], "order_id": b["order"]}),
        ("POST", f"/api/attachments?entity=customer&entity_id={b['customer']}", "file"),
        ("POST", f"/api/attachments?entity=expense&entity_id={b['expense']}", "file"),
    ]
    leaks = []
    for method, url, body in attacks:
        if body == "file":
            r = client.request(method, url, headers=ha, files={"file": ("x.txt", b"x", "text/plain")})
        else:
            r = client.request(method, url, headers=ha, json=body)
        if r.status_code < 300 or r.status_code >= 500 or MARK in r.text:
            leaks.append(f"{method} {url} {body} → {r.status_code} {r.text[:150]}")
    assert not leaks, "foreign ids accepted:\n" + "\n".join(leaks)
    # an order has no branch_id input: a smuggled one is ignored, the branch comes from the warehouse / the user
    o = client.post("/api/sales/orders", headers=ha, json={"customer_id": a["customer"], "branch_id": b["branch"],
                                                          "items": [{"product_id": a["product"], "quantity": 1}]}).json()
    assert o["branch_id"] != b["branch"]


def test_query_params_and_search_do_not_leak(client, world):
    from app.main import app
    ha, b = world["ha"], world["b"]
    leaks = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods or "{" in route.path or route.path.startswith(("/api/platform", "/api/public")):
            continue
        query = {}
        for p in route.dependant.query_params:
            if p.name == "q":
                query[p.name] = MARK
            elif p.name.endswith("_id"):
                query[p.name] = _param_value(route.path, p.name, b) or b.get(p.name[:-3], 1)
        r = client.get(route.path, headers=ha, params=query)
        if r.status_code >= 500 or MARK in r.text:
            leaks.append(f"GET {route.path} {query} → {r.status_code} {r.text[:150]}")
    assert not leaks, "\n".join(leaks)


def test_files_exports_reports_and_documents_do_not_leak(client, world):
    ha, b = world["ha"], world["b"]
    checks = [f"/api/vouchers/{b['voucher']}", f"/api/sales/receipts/{b['voucher']}", f"/api/inventory/barcode/BC{MARK}", f"/api/attachments/{b['attachment']}", f"/api/documents/{b['document']}", f"/api/documents/search?q={MARK}",
              f"/api/attachments?entity=customer&entity_id={b['customer']}"]
    for entity in ("products", "customers", "suppliers", "expenses", "invoices", "sales"):
        checks.append(f"/api/data/export/{entity}?lang=en")
    for report in ("pnl", "vat", "aging", "sales-by-user", "sales-by-product", "sales-by-customer", "daily-sales", "finance"):
        checks.append(f"/api/reports/{report}")
    checks += ["/api/accounting/trial-balance", "/api/accounting/balance-sheet", "/api/accounting/journal", "/api/insights/risk",
               "/api/insights/pricing", "/api/insights/daily", "/api/command-center?lang=en", "/api/dashboard", "/api/security/logins"]
    leaks = []
    for url in checks:
        r = client.get(url, headers=ha)
        body = r.content.decode("latin-1")  # xlsx/zip bytes too
        if r.status_code >= 500 or MARK in r.text or MARK in body or (url.startswith(("/api/attachments/", "/api/documents/")) and "?" not in url and r.status_code < 300):
            leaks.append(f"GET {url} → {r.status_code}")
    # Excel files are zipped: unzip and look inside
    import io
    import zipfile
    for entity in ("products", "customers", "suppliers", "expenses", "invoices", "sales"):
        data = client.get(f"/api/data/export/{entity}?lang=en", headers=ha).content
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if any(MARK.encode() in z.read(n) for n in z.namelist()):
                leaks.append(f"export {entity} contains another company's rows")
    assert not leaks, "\n".join(leaks)


def test_ai_tools_only_see_own_company(client, world):
    from app.core.database import SessionLocal
    from app.models import User
    from app.services.ai_agent import ToolBox
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == "owner@tenant-a.ps"))
        tb = ToolBox(db, owner.company_id, owner.full_name, owner)
        outputs = [tb.query_sales(group_by=g, period="this_year") for g in ("summary", "customer", "product", "warehouse", "category", "month")]
        outputs += [tb.query_profit("this_year"), tb.query_inventory("low_stock"), tb.query_inventory("forecast"),
                    tb.query_customers("owing", threshold=0), tb.query_customers("top", period="this_year"), tb.query_customers("inactive"),
                    tb.query_finance("summary"), tb.query_finance("overdue"), tb.query_finance("cashflow"), tb.analyze_business("en"),
                    tb.search_documents(f"discount policy {MARK}"), tb.create_report("management", "this_year")]
        assert MARK not in str(outputs)
    for q in ("who owes us money", "top customers this year", "profit this year", "low stock", f"discount policy {MARK}", "why did sales drop"):
        r = client.post("/api/ai/ask", headers=world["ha"], json={"question": q, "history": []})
        assert r.status_code == 200 and MARK not in r.text, q


def test_ai_tools_respect_permissions(client, world):
    """A user allowed to use the assistant but not to see profits or create customers can't do it through the AI."""
    h = world["ha"]
    role = client.post("/api/users/roles", headers=h, json={"name": "AI only", "permissions": ["ai:use"]}).json()
    client.post("/api/users", headers=h, json={"email": "aionly@tenant-a.ps", "full_name": "AI only", "password": "secret12", "role_id": role["id"]})
    tok = client.post("/api/auth/login", data={"username": "aionly@tenant-a.ps", "password": "secret12"}).json()["access_token"]
    hu = {"Authorization": f"Bearer {tok}"}
    for q in ("profit this year", "who owes us money", "cash flow", "top customers this year"):
        r = client.post("/api/ai/ask", headers=hu, json={"question": q, "history": []})
        assert r.status_code == 200
        assert r.json()["data"] == {} or all("error" in v for v in r.json()["data"].values()), (q, r.json())
    from app.core.database import SessionLocal
    from app.models import Customer, User
    from app.services.ai_agent import ToolBox
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "aionly@tenant-a.ps"))
        tb = ToolBox(db, u.company_id, u.full_name, u)
        assert "error" in tb.create_customer("Sneaky")
        assert "error" in tb.create_purchase_request([{"product_id": world["a"]["product"], "quantity": 1}])
        assert not db.scalar(select(Customer).where(Customer.name == "Sneaky"))
        # the model may only call the listed tools, never other methods of the toolbox
        from app.services.ai_agent import run_tool
        assert "error" in run_tool(tb, "__init__", {})
        assert "error" in run_tool(tb, "_check", {})


def test_api_keys_and_public_links_stay_in_their_company(client, world):
    b = world["b"]
    key_a = client.post("/api/integrations/keys", headers=world["ha"], json={"name": "A key"}).json()["key"]
    ka = {"X-API-Key": key_a}
    assert MARK not in client.get("/api/customers", headers=ka).text
    assert client.get(f"/api/customers/{b['customer']}", headers=ka).status_code == 404
    assert client.get(f"/api/sales/invoices/{b['invoice']}", headers=ka).status_code == 404
    # A's portal shows only A; B's portal token works only for B's own customer
    portal_a = client.get(f"/api/public/portal/{world['a']['portal']}")
    assert portal_a.status_code == 200 and MARK not in portal_a.text
    assert client.get("/api/public/portal/" + "x" * 32).status_code == 404
    assert client.get("/api/public/invoices/" + "x" * 32).status_code == 404
    # a payment proof sent through A's portal can't be confirmed by B, and vice versa
    assert client.post(f"/api/customers/payment-proofs/{b['proof']}", headers=world["ha"], json={"approve": True}).status_code == 404


def test_webhooks_and_background_jobs_stay_in_their_company(client, world):
    from app.core.database import SessionLocal
    from app.models import Alert, Company, WebhookDelivery
    from app.services import webhooks
    from app.services.automation import run_all_companies
    with SessionLocal() as db:
        a_id = db.scalar(select(Company.id).where(Company.name == "Tenant A"))
        b_id = db.scalar(select(Company.id).where(Company.name == f"Tenant {MARK}"))
        before = db.query(WebhookDelivery).filter_by(company_id=a_id).count()
        webhooks.emit(db, b_id, "customer.created", {"name": f"Customer {MARK}"})
        db.commit()
        assert db.query(WebhookDelivery).filter_by(company_id=a_id).count() == before
        assert all(MARK not in str(d.payload) for d in db.query(WebhookDelivery).filter_by(company_id=a_id))
    run_all_companies()
    from app.services.recurring import run_all as run_recurring
    run_recurring()
    with SessionLocal() as db:
        for al in db.query(Alert).filter_by(company_id=a_id):
            assert MARK not in f"{al.title} {al.message}"
    assert MARK not in client.get("/api/alerts", headers=world["ha"]).text
    assert MARK not in client.get("/api/tasks", headers=world["ha"]).text


def test_company_local_period_and_provider_keys_do_not_modify_other_tenants(client, world, monkeypatch):
    from app.core.database import SessionLocal
    from app.models import User
    from app.models.control import AccountingPeriod, Connection
    from app.api import ops
    ha, hb = world["ha"], world["hb"]
    period = date.today().strftime("%Y-%m")
    assert client.post(f"/api/accounting/periods/{period}/close", headers=hb, json={}).status_code == 200
    assert client.post(f"/api/accounting/periods/{period}/close", headers=ha, json={}).status_code == 200
    assert client.post(f"/api/accounting/periods/{period}/reopen", headers=ha, json={"note": "Tenant A correction"}).status_code == 200
    assert client.put("/api/integrations/connections/whatsapp", headers=hb, json={
        "provider": "whatsapp", "config": {"label": MARK}, "secret": "synthetic-tenant-b-secret",
    }).status_code == 200
    assert client.put("/api/integrations/connections/whatsapp", headers=ha, json={
        "provider": "whatsapp", "config": {"label": "Tenant A"}, "secret": "synthetic-tenant-a-secret",
    }).status_code == 200
    aid = client.get("/api/auth/me", headers=ha).json()["id"]
    bid = client.get("/api/auth/me", headers=hb).json()["id"]
    with SessionLocal() as db:
        acid, bcid = db.get(User, aid).company_id, db.get(User, bid).company_id
    calls = []
    def fake_send(db, cid, phone, text):
        calls.append(cid)
        return False
    monkeypatch.setattr(ops.integrations_svc, "whatsapp_send", fake_send)
    assert client.post("/api/integrations/connections/whatsapp/test?phone=test-recipient", headers=ha).status_code == 200
    assert calls == [acid]  # No external message is sent by this test.
    assert client.delete("/api/integrations/connections/whatsapp", headers=ha).status_code == 204
    with SessionLocal() as db:
        statuses = dict(db.execute(select(AccountingPeriod.company_id, AccountingPeriod.status).where(AccountingPeriod.period == period)).all())
        assert statuses[acid] == "OPEN" and statuses[bcid] == "CLOSED"
        other = db.scalar(select(Connection).where(Connection.company_id == bcid, Connection.provider == "whatsapp"))
        assert other.secret == "synthetic-tenant-b-secret" and other.config == {"label": MARK}
        assert db.scalar(select(Connection).where(Connection.company_id == acid, Connection.provider == "whatsapp")) is None


def test_no_row_points_to_another_company(client, world):
    """Database-wide integrity scan: every foreign key of a tenant row must point to a row of the same company."""
    from app.core.database import Base, SessionLocal
    import app.models  # noqa: F401
    bad = []
    with SessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            if "company_id" not in table.c:
                continue
            for col in table.c:
                for fk in col.foreign_keys:
                    target = fk.column.table
                    if "company_id" not in target.c or col.name == "company_id":
                        continue
                    rows = db.execute(select(table.c.id, col, table.c.company_id, target.c.company_id)
                                      .join(target, fk.column == col).where(table.c.company_id != target.c.company_id)).all()
                    bad += [f"{table.name}.{col.name} row {r[0]}: company {r[2]} → {target.name} of company {r[3]}" for r in rows]
    assert not bad, "\n".join(bad[:50])
