"""Tests for the "very strong" round: security, email, currencies, general ledger, approvals, pricing, instalments, recurring,
stock counts, attachments, manufacturing, deliveries, field sales, portal, shop, POS offline/shifts, integrations, billing."""
import io
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.security import totp_now


def _admin(client):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", data={"username": "root@platform.test", "password": "rootpass1"}).json()["access_token"]}


def _login(client, email, pw, otp=None):
    data = {"username": email, "password": pw}
    if otp:
        data["otp"] = otp
    return client.post("/api/auth/login", data=data)


@pytest.fixture(scope="module")
def co(client):
    admin = _admin(client)
    c = client.post("/api/platform/companies", headers=admin, json={"name": "Adv Co", "tax_rate": 0, "owner_name": "Boss", "owner_email": "boss@adv.ps",
                                                                   "owner_password": "secret12"}).json()
    h = {"Authorization": "Bearer " + _login(client, "boss@adv.ps", "secret12").json()["access_token"]}
    wh = client.post("/api/inventory/warehouses", json={"name": "WH"}, headers=h).json()
    p = client.post("/api/inventory/products", headers=h, json={"name": "Flour", "cost_price": 4, "sale_price": 10, "opening_stock": 100, "warehouse_id": wh["id"]}).json()
    cust = client.post("/api/customers", headers=h, json={"name": "Baker", "phone": "0599111222", "email": "baker@shop.ps"}).json()
    return {"h": h, "admin": admin, "id": c["id"], "wh": wh, "p": p, "cust": cust}


def test_login_lockout_2fa_and_logout_all(client, co):
    for _ in range(5):
        assert _login(client, "boss@adv.ps", "wrong").status_code == 401
    assert _login(client, "boss@adv.ps", "secret12").status_code == 429  # locked for 15 minutes
    from app.core.database import SessionLocal
    from app.models import User
    with SessionLocal() as db:  # unlock for the rest of the test
        u = db.scalar(select(User).where(User.email == "boss@adv.ps"))
        u.locked_until = None
        db.commit()
    h = co["h"]
    setup = client.post("/api/auth/2fa/setup", headers=h).json()
    assert client.post("/api/auth/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    client.post("/api/auth/2fa/enable", headers=h, json={"code": totp_now(setup["secret"])})
    assert _login(client, "boss@adv.ps", "secret12").json()["detail"] == "2FA code required"
    tok = _login(client, "boss@adv.ps", "secret12", totp_now(setup["secret"])).json()["access_token"]
    h2 = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/auth/me", headers=h2).status_code == 200
    client.post("/api/auth/logout-all", headers=h2)
    assert client.get("/api/auth/me", headers=h2).status_code == 401
    # fresh token for the other tests
    new = _login(client, "boss@adv.ps", "secret12", totp_now(setup["secret"])).json()["access_token"]
    co["h"]["Authorization"] = f"Bearer {new}"
    assert any(e["reason"] == "2fa_required" for e in client.get("/api/auth/login-history", headers=co["h"]).json())


def test_password_reset_via_outbox(client, co):
    client.post("/api/auth/forgot-password", json={"email": "nobody@x.ps"})  # silently ignored
    client.post("/api/auth/forgot-password", json={"email": "baker-owner@adv.ps"})
    admin = co["admin"]
    client.post("/api/platform/companies", headers=admin, json={"name": "Reset Co", "owner_name": "R", "owner_email": "reset@adv.ps", "owner_password": "secret12"})
    client.post("/api/auth/forgot-password", json={"email": "reset@adv.ps", "lang": "en"})
    mail = next(m for m in client.get("/api/platform/outbox", headers=admin).json()["items"] if m["to"] == "reset@adv.ps")
    token = mail["body_html"].split("token=")[1].split('"')[0]
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "brandnew1"}).status_code == 204
    assert _login(client, "reset@adv.ps", "brandnew1").status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "again123"}).status_code == 400


def test_currency_sale_payment_and_balanced_ledger(client, co):
    h = co["h"]
    client.put("/api/currencies", headers=h, json={"code": "USD", "rate": 3.5})
    o = client.post("/api/sales/orders", headers=h, json={"customer_id": co["cust"]["id"], "warehouse_id": co["wh"]["id"], "currency": "USD",
                                                          "items": [{"product_id": co["p"]["id"], "quantity": 7}]}).json()
    assert o["currency"] == "USD" and o["exchange_rate"] == 3.5 and o["total"] == 20  # 7 × 10 ILS ÷ 3.5
    inv = client.post("/api/sales/invoices", headers=h, json={"customer_id": co["cust"]["id"], "order_id": o["id"]}).json()
    # the rate moves; the customer pays 20 USD into a USD cash box → exchange difference goes to the ledger
    client.put("/api/currencies", headers=h, json={"code": "USD", "rate": 3.6})
    pay = client.post("/api/sales/payments", headers=h, json={"invoice_id": inv["id"], "amount": 20, "method": "cash", "currency": "USD"}).json()
    assert pay["amount"] == 20
    accounts = client.get("/api/accounts", headers=h).json()
    usd = next(a for a in accounts if a["currency"] == "USD")
    assert usd["balance"] == 20 and usd["balance_base"] == 72
    tb = client.get("/api/accounting/trial-balance", headers=h).json()
    assert tb["total_debit"] == tb["total_credit"]
    bs = client.get("/api/accounting/balance-sheet", headers=h).json()
    assert bs["balanced"]
    ist = client.get(f"/api/accounting/income-statement?start={date.today().replace(day=1)}&end={date.today()}", headers=h).json()
    assert any(r["amount"] == 70 for r in ist["revenue"])  # sales 20 USD × 3.5
    assert any(r["code"] == "4950" and r["amount"] == 2 for r in ist["revenue"])  # FX gain 20 × (3.6 − 3.5)


def test_manual_journal_and_voucher_account(client, co):
    h = co["h"]
    chart = client.get("/api/accounting/accounts", headers=h).json()
    capital = next(a for a in chart if a["system_key"] == "capital")
    cash = next(a for a in chart if a["system_key"] and a["system_key"].startswith("money:"))
    assert client.post("/api/accounting/journal", headers=h, json={"entry_date": str(date.today()), "memo": "bad",
                       "lines": [{"account_id": cash["id"], "debit": 10}, {"account_id": capital["id"], "credit": 9}]}).status_code == 400
    r = client.post("/api/accounting/journal", headers=h, json={"entry_date": str(date.today()), "memo": "Owner put money in",
                    "lines": [{"account_id": cash["id"], "debit": 500}, {"account_id": capital["id"], "credit": 500}]})
    assert r.status_code == 201
    client.post("/api/vouchers", headers=h, json={"direction": "in", "amount": 1000, "party_name": "Bank loan", "gl_account_id":
                                                  next(a for a in chart if a["system_key"] == "loans")["id"]})
    bs = client.get("/api/accounting/balance-sheet?refresh=true", headers=h).json()
    assert bs["balanced"] and any(r["name_en"] == "Loans" and r["amount"] == 1000 for r in bs["liabilities"])


def test_price_list_promotion_quote_and_approvals(client, co):
    h = co["h"]
    pl = client.post("/api/price-lists", headers=h, json={"name": "Wholesale", "items": [{"product_id": co["p"]["id"], "price": 8}]}).json()
    client.patch(f"/api/customers/{co['cust']['id']}", headers=h, json={"price_list_id": pl["id"]})
    client.post("/api/promotions", headers=h, json={"name": "Buy 10 get 1", "kind": "bxgy", "product_id": co["p"]["id"], "buy_qty": 10, "free_qty": 1})
    q = client.post("/api/sales/quote", headers=h, json={"customer_id": co["cust"]["id"], "items": [{"product_id": co["p"]["id"], "quantity": 10}]}).json()
    assert q["total"] == 80 and any(ln["free"] and ln["quantity"] == 1 for ln in q["lines"])
    # approvals: discounts above 10% by a sales employee wait for a manager
    client.patch("/api/auth/company", headers=h, json={"approval_discount_pct": 10, "approval_expense_amount": 1000})
    roles = client.get("/api/users/roles", headers=h).json()
    emp_role = next(r for r in roles if r["name"] == "Sales Employee")
    client.post("/api/users", headers=h, json={"email": "emp@adv.ps", "full_name": "Emp", "password": "secret12", "role_id": emp_role["id"]})
    he = {"Authorization": "Bearer " + _login(client, "emp@adv.ps", "secret12").json()["access_token"]}
    o = client.post("/api/sales/orders", headers=he, json={"customer_id": co["cust"]["id"], "warehouse_id": co["wh"]["id"], "discount_pct": 20,
                                                           "items": [{"product_id": co["p"]["id"], "quantity": 1}]}).json()
    assert o["status"] == "pending_approval"
    stock_before = client.get(f"/api/inventory/products/{co['p']['id']}", headers=h).json()["total_stock"]
    assert client.post(f"/api/sales/orders/{o['id']}/approve", headers=he).status_code == 403
    assert client.post(f"/api/sales/orders/{o['id']}/approve", headers=h).json()["status"] == "confirmed"
    assert client.get(f"/api/inventory/products/{co['p']['id']}", headers=h).json()["total_stock"] == stock_before - 1
    e = client.post("/api/finance/expenses", headers=he, json={"category": "Marketing", "amount": 5000})
    assert e.status_code == 403  # sales employees can't add expenses at all
    # an accountant's big expense waits
    acc_role = next(r for r in roles if r["name"] == "Accountant")
    client.post("/api/users", headers=h, json={"email": "acc@adv.ps", "full_name": "Acc", "password": "secret12", "role_id": acc_role["id"]})
    ha = {"Authorization": "Bearer " + _login(client, "acc@adv.ps", "secret12").json()["access_token"]}
    exp = client.post("/api/finance/expenses", headers=ha, json={"category": "Marketing", "amount": 5000}).json()
    assert exp["approval_status"] == "pending"
    pending = client.get("/api/approvals", headers=h).json()
    assert any(x["id"] == exp["id"] for x in pending["expenses"])
    assert client.post(f"/api/approvals/expenses/{exp['id']}", headers=h).json()["status"] == "approved"


def test_installments_recurring_ubl_and_email(client, co):
    h = co["h"]
    inv = client.post("/api/sales/invoices", headers=h, json={"customer_id": co["cust"]["id"], "total": 300, "description": "Consulting"}).json()
    sched = client.post(f"/api/sales/invoices/{inv['id']}/installments", headers=h, json={"count": 3, "first_due": str(date.today() - timedelta(days=1))}).json()
    assert [s["amount"] for s in sched] == [100, 100, 100] and sched[0]["status"] == "late"
    client.post("/api/sales/payments", headers=h, json={"invoice_id": inv["id"], "amount": 150, "method": "cash"})
    d = client.get(f"/api/sales/invoices/{inv['id']}", headers=h).json()
    assert [s["status"] for s in d["installments"]][:2] == ["paid", "partial"]
    assert any(i["invoice_id"] == inv["id"] for i in client.get("/api/sales/installments/due?days=40", headers=h).json())
    client.post("/api/sales/recurring", headers=h, json={"customer_id": co["cust"]["id"], "description": "Monthly service", "amount": 50,
                                                         "next_date": str(date.today()), "send_email": True})
    assert client.post("/api/sales/recurring/run", headers=h).json()["created"] == 1
    assert client.post("/api/sales/recurring/run", headers=h).json()["created"] == 0  # next month now
    xml = client.get(f"/api/sales/invoices/{inv['id']}/ubl.xml", headers=h)
    assert xml.status_code == 200 and b"<cbc:ID>" in xml.content and b"Consulting" in xml.content
    assert client.post(f"/api/sales/invoices/{inv['id']}/email", headers=h, json={}).json()["to"] == "baker@shop.ps"


def test_stock_count_attachments_manufacturing(client, co):
    h = co["h"]
    sc = client.post(f"/api/stock-counts?warehouse_id={co['wh']['id']}", headers=h).json()
    line = next(ln for ln in sc["lines"] if ln["product_id"] == co["p"]["id"])
    client.put(f"/api/stock-counts/{sc['id']}/lines", headers=h, json=[{"product_id": co["p"]["id"], "counted": line["expected"] - 2}])
    applied = client.post(f"/api/stock-counts/{sc['id']}/apply", headers=h).json()
    assert applied["status"] == "applied" and applied["shortage_value"] == -8
    assert client.get(f"/api/inventory/products/{co['p']['id']}", headers=h).json()["total_stock"] == line["expected"] - 2
    up = client.post("/api/attachments?entity=customer&entity_id=%d" % co["cust"]["id"], headers=h, files={"file": ("contract.txt", b"hello", "text/plain")})
    att = up.json()["id"]
    assert client.get(f"/api/attachments/{att}", headers=h).content == b"hello"
    bread = client.post("/api/inventory/products", headers=h, json={"name": "Bread", "sale_price": 3}).json()
    bom = client.post("/api/manufacturing/boms", headers=h, json={"product_id": bread["id"], "output_qty": 10, "lines": [{"product_id": co["p"]["id"], "quantity": 2}]}).json()
    assert bom["unit_cost"] == 0.8
    mo = client.post(f"/api/manufacturing/orders?bom_id={bom['id']}&quantity=20&warehouse_id={co['wh']['id']}", headers=h).json()
    assert mo["unit_cost"] == 0.8
    assert client.get(f"/api/inventory/products/{bread['id']}", headers=h).json()["total_stock"] == 20


def test_delivery_field_portal_shop(client, co):
    h = co["h"]
    o = client.post("/api/sales/orders", headers=h, json={"customer_id": co["cust"]["id"], "warehouse_id": co["wh"]["id"], "items": [{"product_id": co["p"]["id"], "quantity": 1}]}).json()
    d = client.post("/api/deliveries", headers=h, json={"order_id": o["id"]}).json()
    done = client.post(f"/api/deliveries/{d['id']}/status", headers=h, json={"status": "delivered", "received_by": "Ali", "cash_collected": 8}).json()
    assert done["status"] == "delivered" and done["cash_collected"] == 8
    client.patch(f"/api/customers/{co['cust']['id']}", headers=h, json={"assigned_user_id": client.get("/api/auth/me", headers=h).json()["id"],
                                                                         "visit_days": str(date.today().weekday())})
    today = client.get("/api/field/today", headers=h).json()
    assert today[0]["scheduled"] and today[0]["visited"] is None
    client.post("/api/field/visits", headers=h, json={"customer_id": co["cust"]["id"], "outcome": "no_answer", "lat": 32.2, "lng": 35.2})
    assert client.get("/api/field/today", headers=h).json()[0]["visited"] == "no_answer"
    # customer portal + payment notice → confirmed payment
    link = client.post(f"/api/customers/{co['cust']['id']}/portal-link", headers=h).json()
    portal = client.get(f"/api/public/portal/{link['token']}").json()
    assert portal["balance"] > 0
    r = client.post(f"/api/public/portal/{link['token']}/payment-proof", data={"amount": "10", "reference": "TRX-1"}, files={"file": ("r.jpg", b"img", "image/jpeg")})
    assert r.status_code == 201
    proof = client.get("/api/customers/payment-proofs/pending", headers=h).json()[0]
    assert client.post(f"/api/customers/payment-proofs/{proof['id']}", headers=h, json={"approve": True}).json()["status"] == "confirmed"
    # online shop
    assert client.get("/api/public/shop/adv").status_code == 404
    client.patch("/api/auth/company", headers=h, json={"slug": "adv", "catalog_enabled": True})
    shop = client.get("/api/public/shop/adv").json()
    assert any(p["name"] == "Flour" for p in shop["products"])
    order = client.post("/api/public/shop/adv/order", json={"name": "Web Buyer", "phone": "0599000777", "items": [{"product_id": co["p"]["id"], "quantity": 2}]})
    assert order.status_code == 201
    assert any(o["number"] == order.json()["number"] and o["source"] == "online" for o in client.get("/api/sales/orders?q=" + order.json()["number"], headers=h).json())
    assert client.get("/api/public/brand?slug=adv").json()["name"] == "Adv Co"


def test_pos_offline_ref_shift_and_insights(client, co):
    h = co["h"]
    ref = "till-1-abc"
    sale = {"warehouse_id": co["wh"]["id"], "items": [{"product_id": co["p"]["id"], "quantity": 1}], "payments": [{"method": "cash", "amount": 10}], "client_ref": ref}
    client.post("/api/pos/shift/open", headers=h, json={"opening_float": 100})
    a = client.post("/api/pos/sale", headers=h, json=sale).json()
    b = client.post("/api/pos/sale", headers=h, json=sale).json()
    assert a["order_id"] == b["order_id"] and b["duplicate"]
    assert client.get("/api/pos/shift", headers=h).json()["expected_cash"] == 110
    closed = client.post("/api/pos/shift/close", headers=h, json={"counted_cash": 90}).json()
    assert closed["difference"] == -20
    assert any("Cash difference" in al["title"] for al in client.get("/api/alerts", headers=h).json())
    assert client.get("/api/insights/pricing", headers=h).status_code == 200
    assert client.get("/api/insights/risk", headers=h).status_code == 200
    assert "ملخص" in client.get("/api/insights/daily", headers=h).json()["text"]


def test_pagination_branches_api_keys_webhooks_billing(client, co):
    h = co["h"]
    r = client.get("/api/sales/orders?limit=2", headers=h)
    assert len(r.json()) == 2 and int(r.headers["X-Total-Count"]) > 2
    # a user limited to branch B doesn't see branch A's warehouse or orders
    admin = co["admin"]
    plan = client.post("/api/platform/plans", headers=admin, json={"name": "Pro", "price_monthly": 200, "max_users": 0, "max_branches": 0}).json()
    client.patch(f"/api/platform/companies/{co['id']}", headers=admin, json={"plan_id": plan["id"]})
    b1 = client.post("/api/branches", headers=h, json={"name": "North"}).json()
    b2 = client.post("/api/branches", headers=h, json={"name": "South"}).json()
    client.patch(f"/api/inventory/warehouses/{co['wh']['id']}", headers=h, json={"name": "WH", "branch_id": b1["id"]})
    roles = client.get("/api/users/roles", headers=h).json()
    cashier = next(r for r in roles if r["name"] == "Cashier")
    client.post("/api/users", headers=h, json={"email": "south@adv.ps", "full_name": "South Cashier", "password": "secret12", "role_id": cashier["id"], "branch_id": b2["id"]})
    hs = {"Authorization": "Bearer " + _login(client, "south@adv.ps", "secret12").json()["access_token"]}
    assert client.get("/api/inventory/warehouses", headers=hs).json() == []
    assert all(o["branch_id"] in (None, b2["id"]) for o in client.get("/api/sales/orders", headers=hs).json())
    # API key acts as its creator
    key = client.post("/api/integrations/keys", headers=h, json={"name": "Shop sync"}).json()["key"]
    assert client.get("/api/customers", headers={"X-API-Key": key}).status_code == 200
    assert client.get("/api/customers", headers={"X-API-Key": "bos_wrong"}).status_code == 401
    hook = client.post("/api/integrations/webhooks", headers=h, json={"url": "http://127.0.0.1:9/hook", "events": ["invoice.created"]}).json()
    client.post("/api/sales/invoices", headers=h, json={"customer_id": co["cust"]["id"], "total": 10})
    deliveries = client.get("/api/integrations", headers=h).json()["deliveries"]
    assert any(d["event"] == "invoice.created" for d in deliveries) and hook["secret"]
    # platform billing: one subscription invoice per month, paying it extends the subscription
    run = client.post("/api/platform/billing/run", headers=admin).json()
    assert run["created"] >= 1 and client.post("/api/platform/billing/run", headers=admin).json()["created"] == 0
    bill = next(i for i in client.get("/api/platform/billing", headers=admin).json()["items"] if i["company_id"] == co["id"])
    client.post(f"/api/platform/billing/{bill['id']}/paid", headers=admin)
    assert client.get("/api/billing", headers=h).json()[0]["status"] == "paid"


def test_pos_pay_in_usd_rounding_and_named_lists(client, co):
    h = co["h"]
    client.put("/api/currencies", headers=h, json={"code": "USD", "rate": 3.6})
    setup = client.get("/api/pos/setup", headers=h).json()
    assert {"code": "USD", "rate": 3.6} in setup["currencies"]
    # 30 ILS = 8.333… USD; the till asks for 8.33 USD, which must still settle the invoice exactly
    r = client.post("/api/pos/sale", headers=h, json={"warehouse_id": co["wh"]["id"], "items": [{"product_id": co["p"]["id"], "quantity": 3}],
                                                     "payments": [{"method": "cash", "amount": 8.33, "currency": "USD"}]})
    assert r.status_code == 201, r.text
    assert r.json()["balance"] == 0
    orders = client.get("/api/sales/orders?limit=5", headers=h).json()
    assert orders[0]["customer_name"] and orders[0]["invoice_id"]
    assert client.get(f"/api/sales/orders/{orders[0]['id']}", headers=h).json()["invoice_id"] == orders[0]["invoice_id"]
    assert client.get("/api/sales/invoices?limit=5", headers=h).json()[0]["customer_name"]
