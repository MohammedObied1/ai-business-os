import io

from openpyxl import Workbook, load_workbook

from app.core.config import settings


def _admin(client):
    r = client.post("/api/auth/login", data={"username": "root@platform.test", "password": "rootpass1"})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "platform"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _login(client, email, password):
    r = client.post("/api/auth/login", data={"username": email, "password": password})
    return r


def test_platform_admin_manages_companies(client):
    admin = _admin(client)
    r = client.post("/api/platform/companies", headers=admin, json={
        "name": "Bakery One", "currency": "ILS", "owner_name": "Mona", "owner_email": "mona@bakery.ps", "owner_password": "secret12"})
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["owner_email"] == "mona@bakery.ps" and co["stats"]["users"] == 1

    # the owner can log in and sees an empty company
    tok = _login(client, "mona@bakery.ps", "secret12").json()
    assert tok["kind"] == "company"
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get("/api/auth/company", headers=h).json()["name"] == "Bakery One"
    assert client.get("/api/customers", headers=h).json() == []

    # company tokens cannot use the admin API and vice versa
    assert client.get("/api/platform/companies", headers=h).status_code == 401
    assert client.get("/api/customers", headers=admin).status_code == 401

    # duplicate owner email rejected
    assert client.post("/api/platform/companies", headers=admin, json={
        "name": "X", "owner_name": "X", "owner_email": "mona@bakery.ps", "owner_password": "secret12"}).status_code == 400

    # enter the company as its owner
    enter = client.post(f"/api/platform/companies/{co['id']}/enter", headers=admin).json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {enter['access_token']}"}).json()
    assert me["email"] == "mona@bakery.ps" and me["impersonated"] is True

    # suspend → owner can no longer log in or use an existing token
    client.patch(f"/api/platform/companies/{co['id']}", headers=admin, json={"is_active": False})
    assert _login(client, "mona@bakery.ps", "secret12").status_code == 403
    assert client.get("/api/customers", headers=h).status_code == 403
    client.patch(f"/api/platform/companies/{co['id']}", headers=admin, json={"is_active": True})

    # reset owner password
    client.post(f"/api/platform/companies/{co['id']}/owner-password", headers=admin, json={"new_password": "newpass99"})
    assert _login(client, "mona@bakery.ps", "newpass99").status_code == 200

    # delete needs the exact name, then removes everything
    assert client.delete(f"/api/platform/companies/{co['id']}?confirm_name=wrong", headers=admin).status_code == 400
    assert client.delete(f"/api/platform/companies/{co['id']}?confirm_name=Bakery One", headers=admin).status_code == 204
    assert _login(client, "mona@bakery.ps", "newpass99").status_code == 401


def test_public_signup_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_SIGNUP", False)
    r = client.post("/api/auth/register", json={"company_name": "Nope", "owner_name": "N", "owner_email": "n@nope.ps", "password": "pass1234"})
    assert r.status_code == 403


def test_cross_company_references_are_blocked(client, company_a, company_b):
    wa = client.post("/api/inventory/warehouses", json={"name": "A-WH"}, headers=company_a).json()
    pa = client.post("/api/inventory/products", json={"name": "A-thing", "sale_price": 5}, headers=company_a).json()
    assert pa["sku"].startswith("P-")
    cb = client.post("/api/customers", json={"name": "B-cust"}, headers=company_b).json()
    pb = client.post("/api/inventory/products", json={"name": "B-thing", "sale_price": 5}, headers=company_b).json()
    # B cannot read A's product, or sell out of A's warehouse
    assert client.get(f"/api/inventory/products/{pa['id']}", headers=company_b).status_code == 404
    r = client.post("/api/sales/orders", headers=company_b, json={"customer_id": cb["id"], "warehouse_id": wa["id"], "items": [{"product_id": pb["id"], "quantity": 1}]})
    assert r.status_code == 404
    r = client.post("/api/sales/orders", headers=company_b, json={"customer_id": cb["id"], "items": [{"product_id": pa["id"], "quantity": 1}]})
    assert r.status_code == 404
    assert client.post("/api/inventory/stock/adjust", headers=company_b, json={"product_id": pb["id"], "warehouse_id": wa["id"], "quantity": 5}).status_code == 404
    assert client.get("/api/data/export/products", headers=company_b).status_code == 200
    names = [row[1] for row in load_workbook(io.BytesIO(client.get("/api/data/export/products", headers=company_b).content)).active.iter_rows(min_row=2, values_only=True)]
    assert "A-thing" not in names and "B-thing" in names


def test_excel_import_preview_and_commit(client, company_b):
    tpl = client.get("/api/data/template/products?lang=ar", headers=company_b)
    assert tpl.status_code == 200
    wb = Workbook()
    ws = wb.active
    ws.append(["الكود", "اسم المنتج *", "سعر البيع", "الكمية الحالية", "المستودع"])
    ws.append(["IMP-1", "Imported Tea", "12.5", 40, "Store B"])
    ws.append(["IMP-2", "", 3, None, None])  # missing name → error
    ws.append(["IMP-3", "Imported Sugar", "abc", None, None])  # bad number → error
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("products.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    preview = client.post("/api/data/import/products?dry_run=true", headers=company_b, files=files).json()
    assert preview["created"] == 1 and len(preview["errors"]) == 2
    assert not any(p["name"] == "Imported Tea" for p in client.get("/api/inventory/products", headers=company_b).json())

    done = client.post("/api/data/import/products?dry_run=false", headers=company_b, files=files).json()
    assert done["created"] == 1
    tea = next(p for p in client.get("/api/inventory/products", headers=company_b).json() if p["name"] == "Imported Tea")
    assert tea["total_stock"] == 40 and tea["sale_price"] == 12.5

    # re-import updates instead of duplicating
    again = client.post("/api/data/import/products?dry_run=false", headers=company_b, files=files).json()
    assert again["created"] == 0 and again["updated"] == 1

    csv_body = "Name,Phone,Opening balance (owes you)\nCSV Customer,0599,250\n".encode()
    r = client.post("/api/data/import/customers?dry_run=false", headers=company_b, files={"file": ("c.csv", csv_body, "text/csv")}).json()
    assert r["created"] == 1
    cust = next(c for c in client.get("/api/customers", headers=company_b).json() if c["name"] == "CSV Customer")
    assert client.get(f"/api/customers/{cust['id']}", headers=company_b).json()["open_balance"] == 250


def test_invoice_detail_and_edits(client, company_b):
    h = company_b
    wh = client.post("/api/inventory/warehouses", json={"name": "Detail WH"}, headers=h).json()
    p = client.post("/api/inventory/products", json={"name": "Detail item", "sale_price": 10, "opening_stock": 10, "warehouse_id": wh["id"]}, headers=h).json()
    assert p["total_stock"] == 10
    c = client.post("/api/customers", json={"name": "Detail cust"}, headers=h).json()
    o = client.post("/api/sales/orders", headers=h, json={"customer_id": c["id"], "warehouse_id": wh["id"], "items": [{"product_id": p["id"], "quantity": 2}]}).json()
    inv = client.post("/api/sales/invoices", headers=h, json={"customer_id": c["id"], "order_id": o["id"]}).json()
    d = client.get(f"/api/sales/invoices/{inv['id']}", headers=h).json()
    assert d["items"][0]["product"] == "Detail item" and d["customer"]["name"] == "Detail cust" and d["invoice"]["total"] == 20
    assert client.post(f"/api/sales/invoices/{inv['id']}/cancel", headers=h).json()["status"] == "cancelled"

    # product with history is archived, not deleted; customer with orders can't be deleted
    assert client.delete(f"/api/inventory/products/{p['id']}", headers=h).json() == {"archived": True}
    assert all(x["id"] != p["id"] for x in client.get("/api/inventory/products", headers=h).json())
    assert client.delete(f"/api/customers/{c['id']}", headers=h).status_code == 400

    # company settings + password change
    assert client.patch("/api/auth/company", headers=h, json={"tax_number": "123456789"}).json()["tax_number"] == "123456789"
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": "abcdef"}).status_code == 400
