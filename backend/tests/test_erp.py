"""End-to-end checks for the accounting / POS / HR / platform features, with real numbers."""
from datetime import date, timedelta

import pytest


def _admin(client):
    tok = client.post("/api/auth/login", data={"username": "root@platform.test", "password": "rootpass1"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def shop(client):
    """A fresh company with 16% VAT, one warehouse, one product with a 24-piece carton, and a customer."""
    admin = _admin(client)
    co = client.post("/api/platform/companies", headers=admin, json={
        "name": "Shop ERP", "tax_rate": 16, "owner_name": "Owner", "owner_email": "owner@shop-erp.ps", "owner_password": "secret12"}).json()
    tok = client.post("/api/auth/login", data={"username": "owner@shop-erp.ps", "password": "secret12"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    wh = client.post("/api/inventory/warehouses", json={"name": "Main"}, headers=h).json()
    prod = client.post("/api/inventory/products", headers=h, json={
        "name": "Juice", "cost_price": 2, "sale_price": 5, "barcode": "111", "pack_unit": "carton", "pack_size": 24, "pack_barcode": "222",
        "opening_stock": 100, "warehouse_id": wh["id"]}).json()
    cust = client.post("/api/customers", json={"name": "Grocer", "phone": "0599000000"}, headers=h).json()
    return {"h": h, "admin": admin, "company": co, "wh": wh, "prod": prod, "cust": cust}


def _balance(client, h, name):
    return next(a for a in client.get("/api/accounts", headers=h).json() if a["name"] == name)["balance"]


def test_vat_units_and_invoice(client, shop):
    h = shop["h"]
    # 1 carton (24 × 5 = 120) + 6 pieces (30) = 150 net, +16% VAT = 174
    o = client.post("/api/sales/orders", headers=h, json={"customer_id": shop["cust"]["id"], "warehouse_id": shop["wh"]["id"], "items": [
        {"product_id": shop["prod"]["id"], "quantity": 1, "unit": "pack"},
        {"product_id": shop["prod"]["id"], "quantity": 6}]}).json()
    assert o["tax_amount"] == 24 and o["total"] == 174
    assert o["items"][0]["quantity"] == 24 and o["items"][0]["uom_label"] == "carton"
    inv = client.post("/api/sales/invoices", headers=h, json={"customer_id": shop["cust"]["id"], "order_id": o["id"]}).json()
    assert inv["total"] == 174 and inv["tax_amount"] == 24
    d = client.get(f"/api/sales/invoices/{inv['id']}", headers=h).json()
    assert d["items"][0]["unit"] == "carton" and d["items"][0]["quantity"] == 1 and d["items"][0]["unit_price"] == 120
    # stock went from 100 to 70
    assert client.get(f"/api/inventory/products/{shop['prod']['id']}", headers=h).json()["total_stock"] == 70
    # revenue excludes VAT
    pnl = client.get("/api/reports/pnl", headers=h).json()
    assert pnl["net_sales"] == 150 and pnl["cogs"] == 60
    vat = client.get("/api/reports/vat", headers=h).json()
    assert vat["output_tax"] == 24
    shop["inv"], shop["order"] = inv, o


def test_cheque_payment_bounce_and_clear(client, shop):
    h = shop["h"]
    inv = shop["inv"]
    # pay 100 by post-dated cheque: balance drops now, no cash yet
    client.post("/api/sales/payments", headers=h, json={"invoice_id": inv["id"], "amount": 100, "method": "cheque",
                                                        "cheque": {"number": "C-1", "bank": "Bank of Palestine", "due_date": str(date.today() + timedelta(days=20))}})
    d = client.get(f"/api/sales/invoices/{inv['id']}", headers=h).json()["invoice"]
    assert d["paid_amount"] == 100 and d["status"] == "partial"
    cheques = client.get("/api/cheques?direction=in", headers=h).json()
    ch = next(c for c in cheques if c["number"] == "C-1")
    assert ch["status"] == "pending"
    # bounced → the customer owes it again + alert
    client.post(f"/api/cheques/{ch['id']}/bounce", headers=h, json={})
    d = client.get(f"/api/sales/invoices/{inv['id']}", headers=h).json()["invoice"]
    assert d["paid_amount"] == 0 and d["status"] == "open"
    st = client.get(f"/api/customers/{shop['cust']['id']}/statement", headers=h).json()
    assert st["closing"] == 174 and any(r["kind"] == "cheque_bounced" for r in st["rows"])
    # a new cheque that clears lands in the bank account
    bank = client.post("/api/accounts", headers=h, json={"name": "Bank", "kind": "bank"}).json()
    client.post("/api/sales/payments", headers=h, json={"invoice_id": inv["id"], "amount": 74, "method": "cheque",
                                                        "cheque": {"number": "C-2", "due_date": str(date.today())}})
    ch2 = next(c for c in client.get("/api/cheques", headers=h).json() if c["number"] == "C-2")
    client.post(f"/api/cheques/{ch2['id']}/clear", headers=h, json={"account_id": bank["id"]})
    assert _balance(client, h, "Bank") == 74


def test_customer_receipt_spreads_over_invoices_and_return(client, shop):
    h = shop["h"]
    # cash receipt of 100 on account settles the rest of the first invoice (100) → invoice paid
    r = client.post("/api/sales/receipts", headers=h, json={"customer_id": shop["cust"]["id"], "amount": 100, "method": "cash"})
    assert r.status_code == 201, r.text
    assert client.get(f"/api/sales/invoices/{shop['inv']['id']}", headers=h).json()["invoice"]["status"] == "paid"
    assert _balance(client, h, "الصندوق الرئيسي") == 100
    voucher = client.get(f"/api/sales/receipts/{r.json()[0]['number']}", headers=h).json()
    assert voucher["amount"] == 100
    # return 6 pieces of the fully-paid invoice → refund from cash, stock back
    line = next(i for i in shop["order"]["items"] if i["uom_label"] is None)
    cn = client.post("/api/sales/returns", headers=h, json={"order_id": shop["order"]["id"], "items": [{"order_item_id": line["id"], "quantity": 6}]}).json()
    assert cn["total"] == 34.8 and cn["tax_amount"] == 4.8 and cn["refunded"] == 34.8
    assert _balance(client, h, "الصندوق الرئيسي") == 65.2
    assert client.get(f"/api/inventory/products/{shop['prod']['id']}", headers=h).json()["total_stock"] == 76
    # can't return more than was sold
    bad = client.post("/api/sales/returns", headers=h, json={"order_id": shop["order"]["id"], "items": [{"order_item_id": line["id"], "quantity": 1}]})
    assert bad.status_code == 400
    assert client.get("/api/reports/pnl", headers=h).json()["net_sales"] == 120


def test_pos_sale_with_barcode_and_change(client, shop):
    h = shop["h"]
    look = client.get("/api/inventory/barcode/222", headers=h).json()
    assert look["unit"] == "pack"
    setup = client.get("/api/pos/setup", headers=h).json()
    r = client.post("/api/pos/sale", headers=h, json={"warehouse_id": shop["wh"]["id"], "items": [{"product_id": shop["prod"]["id"], "quantity": 2}],
                                                       "payments": [{"method": "cash", "amount": 11.6}], "cash_received": 20})
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 11.6 and r.json()["change"] == 8.4 and r.json()["balance"] == 0
    # walk-in customers must pay in full
    r = client.post("/api/pos/sale", headers=h, json={"items": [{"product_id": shop["prod"]["id"], "quantity": 1}], "payments": []})
    assert r.status_code == 400
    assert client.get("/api/pos/today", headers=h).json()["sales_count"] == 2  # the POS sale + the order from the first test
    assert setup["walk_in_customer_id"]


def test_batches_fefo_and_expiry(client, shop):
    h = shop["h"]
    sup = client.post("/api/purchasing/suppliers", headers=h, json={"name": "Supplier"}).json()
    po = client.post("/api/purchasing/orders", headers=h, json={"supplier_id": sup["id"], "warehouse_id": shop["wh"]["id"],
                                                                 "items": [{"product_id": shop["prod"]["id"], "quantity": 10, "unit_cost": 2}]}).json()
    assert po["tax_amount"] == 3.2 and po["total"] == 23.2
    client.post(f"/api/purchasing/orders/{po['id']}/approve", headers=h)
    client.post(f"/api/purchasing/orders/{po['id']}/status?status=ordered", headers=h)
    soon = str(date.today() + timedelta(days=5))
    client.post(f"/api/purchasing/orders/{po['id']}/receive", headers=h, json={"lines": [{"item_id": po["items"][0]["id"], "batch": "B1", "expiry_date": soon}]})
    exp = client.get("/api/inventory/expiring?days=10", headers=h).json()
    assert exp[0]["batch"] == "B1" and exp[0]["quantity"] == 10
    # selling 4 takes from the expiring batch first
    client.post("/api/sales/orders", headers=h, json={"customer_id": shop["cust"]["id"], "warehouse_id": shop["wh"]["id"],
                                                      "items": [{"product_id": shop["prod"]["id"], "quantity": 4}]})
    assert client.get("/api/inventory/expiring?days=10", headers=h).json()[0]["quantity"] == 6
    # pay the supplier with an outgoing cheque, then cancel it → owed again
    client.post("/api/purchasing/payments", headers=h, json={"supplier_id": sup["id"], "po_id": po["id"], "amount": 23.2, "method": "cheque",
                                                             "cheque": {"number": "OUT-1", "due_date": soon}})
    assert client.get(f"/api/purchasing/orders/{po['id']}", headers=h).json()["paid_amount"] == 23.2
    ch = next(c for c in client.get("/api/cheques?direction=out", headers=h).json() if c["number"] == "OUT-1")
    client.post(f"/api/cheques/{ch['id']}/cancel", headers=h)
    assert client.get(f"/api/purchasing/orders/{po['id']}", headers=h).json()["paid_amount"] == 0
    st = client.get(f"/api/purchasing/suppliers/{sup['id']}/statement", headers=h).json()
    assert st["closing"] == 23.2


def test_accounts_transfer_voucher_and_expense(client, shop):
    h = shop["h"]
    before = _balance(client, h, "الصندوق الرئيسي")
    client.post("/api/vouchers", headers=h, json={"direction": "in", "amount": 1000, "party_name": "Owner capital"})
    bank = next(a for a in client.get("/api/accounts", headers=h).json() if a["name"] == "Bank")
    client.post("/api/transfers", headers=h, json={"from_account_id": next(a["id"] for a in client.get("/api/accounts", headers=h).json() if a["kind"] == "cash"),
                                                   "to_account_id": bank["id"], "amount": 500})
    client.post("/api/finance/expenses", headers=h, json={"category": "Rent", "amount": 300})
    assert _balance(client, h, "الصندوق الرئيسي") == round(before + 1000 - 500 - 300, 2)
    assert _balance(client, h, "Bank") == 574


def test_payroll_with_absence_and_advance(client, shop):
    h = shop["h"]
    e = client.post("/api/hr/employees", headers=h, json={"full_name": "Worker", "base_salary": 2600, "allowances": 200, "working_days": 26}).json()
    month = date.today().strftime("%Y-%m")
    client.post("/api/hr/attendance", headers=h, json=[{"employee_id": e["id"], "day": date.today().replace(day=1).isoformat(), "status": "absent"}])
    client.post("/api/hr/advances", headers=h, json={"employee_id": e["id"], "amount": 600, "monthly_deduction": 300})
    run = client.post(f"/api/hr/payroll?month={month}", headers=h).json()
    slip = run["slips"][0]
    assert slip["absence_deduction"] == 100 and slip["advance_deduction"] == 300 and slip["net"] == 2600 + 200 - 100 - 300
    paid = client.post(f"/api/hr/payroll/{run['id']}/pay", headers=h, json={}).json()
    assert paid["status"] == "paid"
    assert client.get("/api/hr/advances", headers=h).json()[0]["remaining"] == 300


def test_audit_log_records_changes(client, shop):
    h = shop["h"]
    client.patch(f"/api/inventory/products/{shop['prod']['id']}", headers=h, json={"sale_price": 6})
    log = client.get("/api/audit?entity=products", headers=h).json()
    change = next(a for a in log if a["action"] == "update")
    assert change["changes"]["sale_price"] == [5.0, 6.0] and change["user_name"] == "Owner"


def test_plan_limits_subscription_and_public_link(client, shop):
    admin, h = shop["admin"], shop["h"]
    plan = client.post("/api/platform/plans", headers=admin, json={"name": "Basic", "price_monthly": 100, "max_users": 1, "max_branches": 1}).json()
    client.patch(f"/api/platform/companies/{shop['company']['id']}", headers=admin, json={"plan_id": plan["id"]})
    r = client.post("/api/users", headers=h, json={"email": "second@shop-erp.ps", "full_name": "Second", "password": "secret12"})
    assert r.status_code == 403
    assert client.post("/api/branches", headers=h, json={"name": "B1"}).status_code == 201
    assert client.post("/api/branches", headers=h, json={"name": "B2"}).status_code == 403
    # shared invoice link works without login
    token = client.post(f"/api/sales/invoices/{shop['inv']['id']}/share", headers=h).json()["token"]
    assert client.get(f"/api/public/invoices/{token}").json()["invoice"]["number"] == shop["inv"]["number"]
    assert client.get("/api/public/invoices/short").status_code == 404
    # expired subscription blocks the company, renewal unblocks it
    client.patch(f"/api/platform/companies/{shop['company']['id']}", headers=admin, json={"subscription_ends_at": str(date.today() - timedelta(days=1))})
    assert client.get("/api/customers", headers=h).status_code == 402
    renewed = client.post(f"/api/platform/companies/{shop['company']['id']}/extend?months=1", headers=admin).json()
    assert renewed["subscription_ends_at"] > str(date.today())
    assert client.get("/api/customers", headers=h).status_code == 200
    assert client.get("/api/platform/overview", headers=admin).json()["mrr"] >= 100
