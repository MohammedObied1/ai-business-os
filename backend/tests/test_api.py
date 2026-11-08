def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_full_business_flow(client, company_a):
    h = company_a
    wh = client.post("/api/inventory/warehouses", json={"name": "Main"}, headers=h).json()
    prod = client.post("/api/inventory/products", json={"sku": "P1", "name": "Widget", "category": "Tools", "cost_price": 10, "sale_price": 25, "min_stock": 20, "supplier_lead_time_days": 5}, headers=h).json()
    client.post("/api/inventory/stock/adjust", json={"product_id": prod["id"], "warehouse_id": wh["id"], "quantity": 100}, headers=h)
    cust = client.post("/api/customers", json={"name": "ACME"}, headers=h).json()

    order = client.post("/api/sales/orders", json={"customer_id": cust["id"], "warehouse_id": wh["id"], "items": [{"product_id": prod["id"], "quantity": 90}]}, headers=h).json()
    assert order["total"] == 2250 and order["cost_total"] == 900

    stock = client.get(f"/api/inventory/stock?product_id={prod['id']}", headers=h).json()
    assert stock[0]["quantity"] == 10  # 100 - 90

    inv = client.post("/api/sales/invoices", json={"customer_id": cust["id"], "order_id": order["id"]}, headers=h).json()
    assert inv["total"] == 2250 and inv["status"] == "open"
    pay = client.post("/api/sales/payments", json={"invoice_id": inv["id"], "amount": 1000}, headers=h).json()
    assert pay["amount"] == 1000
    inv2 = client.get("/api/sales/invoices", headers=h).json()[0]
    assert inv2["status"] == "partial" and inv2["paid_amount"] == 1000

    # insufficient stock is rejected
    r = client.post("/api/sales/orders", json={"customer_id": cust["id"], "warehouse_id": wh["id"], "items": [{"product_id": prod["id"], "quantity": 999}]}, headers=h)
    assert r.status_code == 400

    # low stock detection + automation
    assert client.get("/api/inventory/low-stock", headers=h).json()[0]["name"] == "Widget"
    sup = client.post("/api/purchasing/suppliers", json={"name": "Supplier"}, headers=h).json()
    run = client.post("/api/automation/run", headers=h).json()["created"]
    assert run["Low stock"] == 1
    alerts = client.get("/api/alerts", headers=h).json()
    assert any("Low stock" in a["title"] for a in alerts)

    # purchase workflow with approval + receiving
    po = client.post("/api/purchasing/orders", json={"supplier_id": sup["id"], "warehouse_id": wh["id"], "items": [{"product_id": prod["id"], "quantity": 50}]}, headers=h).json()
    assert po["status"] == "request" and po["number"].startswith("PR-")
    po = client.post(f"/api/purchasing/orders/{po['id']}/approve", headers=h).json()
    assert po["status"] == "approved" and po["number"].startswith("PO-")
    client.post(f"/api/purchasing/orders/{po['id']}/status?status=ordered", headers=h)
    po = client.post(f"/api/purchasing/orders/{po['id']}/status?status=received", headers=h).json()
    assert po["status"] == "received"
    assert client.get(f"/api/inventory/stock?product_id={prod['id']}", headers=h).json()[0]["quantity"] == 60

    # forecasting
    fc = client.get(f"/api/inventory/forecast/{prod['id']}", headers=h).json()
    assert fc["risk"] in ("HIGH", "MEDIUM", "LOW", "NONE") and fc["current_stock"] == 60

    # dashboard, command center, reports
    dash = client.get("/api/dashboard", headers=h).json()
    assert dash["kpis"]["revenue"] == 2250
    cc = client.get("/api/command-center", headers=h).json()
    assert cc["health"] in ("healthy", "attention", "critical")
    assert client.get("/api/reports/management", headers=h).status_code == 200

    # AI assistant (rule based when no API key)
    ai = client.post("/api/ai/ask", json={"question": "Show me the top 20 customers by revenue this year"}, headers=h).json()
    assert "ACME" in ai["answer"] and "query_customers" in ai["tools_used"]
    ai = client.post("/api/ai/ask", json={"question": "Which customers owe us more than 500 ILS?"}, headers=h).json()
    assert "ACME" in ai["answer"]

    # RAG
    client.post("/api/documents/text", json={"title": "Discount policy", "content": "Discounts above 20 percent require General Manager approval. Standard trade discount is 5 percent."}, headers=h)
    hits = client.get("/api/documents/search?q=who approves discounts above 20 percent", headers=h).json()
    assert hits and hits[0]["document_title"] == "Discount policy"
    ai = client.post("/api/ai/ask", json={"question": "What is our discount policy?"}, headers=h).json()
    assert "search_documents" in ai["tools_used"]


def test_tenant_isolation(client, company_a, company_b):
    a_customers = client.get("/api/customers", headers=company_a).json()
    assert len(a_customers) == 1
    assert client.get("/api/customers", headers=company_b).json() == []
    # B cannot read A's customer by id
    assert client.get(f"/api/customers/{a_customers[0]['id']}", headers=company_b).status_code == 404
    assert client.get("/api/documents/search?q=discount", headers=company_b).json() == []


def test_permissions(client, company_a):
    roles = client.get("/api/users/roles", headers=company_a).json()
    sales_emp = next(r for r in roles if r["name"] == "Sales Employee")
    client.post("/api/users", json={"email": "rep@a.com", "full_name": "Rep", "password": "pass1234", "role_id": sales_emp["id"]}, headers=company_a)
    tok = client.post("/api/auth/login", data={"username": "rep@a.com", "password": "pass1234"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/customers", headers=h).status_code == 200
    cust = client.get("/api/customers", headers=h).json()[0]
    assert client.delete(f"/api/customers/{cust['id']}", headers=h).status_code == 403  # no customers:delete
    assert client.get("/api/finance/summary", headers=h).status_code == 403  # no finance access
    assert client.post("/api/sales/invoices", json={"customer_id": cust["id"], "total": 10}, headers=h).status_code == 201
