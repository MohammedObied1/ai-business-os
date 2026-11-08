"""Phase 34/35: import rollback and the accounting integrity audit."""
import io
from datetime import date

import pytest

from tests.conftest import register


@pytest.fixture(scope="module")
def co(client):
    h = register(client, "Integrity Co", "owner@integrity.ps")
    wh = client.post("/api/inventory/warehouses", json={"name": "WH"}, headers=h).json()
    cust = client.post("/api/customers", headers=h, json={"name": "Client", "phone": "0599000111"}).json()
    return {"h": h, "wh": wh, "cust": cust}


# ---------------------------------------------------------------- accounting integrity
def test_integrity_clean_company_ties_out(client, co):
    h = co["h"]
    p = client.post("/api/inventory/products", headers=h, json={"name": "Widget", "cost_price": 4, "sale_price": 10,
                                                                 "opening_stock": 50, "warehouse_id": co["wh"]["id"]}).json()
    o = client.post("/api/sales/orders", headers=h, json={"customer_id": co["cust"]["id"], "warehouse_id": co["wh"]["id"],
                                                          "items": [{"product_id": p["id"], "quantity": 5}]}).json()
    inv = client.post("/api/sales/invoices", headers=h, json={"customer_id": co["cust"]["id"], "order_id": o["id"]}).json()
    client.post("/api/sales/payments", headers=h, json={"invoice_id": inv["id"], "amount": inv["total"] / 2, "method": "cash"})

    r = client.get("/api/accounting/integrity", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["healthy"] is True
    for c in body["checks"]:
        assert c["ok"], c


def test_integrity_catches_an_unbalanced_entry(client, co):
    """The API itself refuses to save an unbalanced manual entry (tested elsewhere) — this proves the audit would
    also catch one if it ever got into the database some other way (a bug, a bad migration, direct SQL)."""
    from app.core.database import SessionLocal
    from app.models import JournalEntry, JournalLine, User

    h = co["h"]
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="owner@integrity.ps").first()
        acct = db.query(JournalLine).filter_by(company_id=user.company_id).first().account_id
        entry = JournalEntry(company_id=user.company_id, entry_date=date.today(), memo="Deliberately broken for the test",
                             source="manual", source_type="test")
        db.add(entry)
        db.flush()
        db.add(JournalLine(company_id=user.company_id, entry_id=entry.id, account_id=acct, debit=100, credit=0))
        # no offsetting credit line — the entry is intentionally left unbalanced
        db.commit()

    body = client.get("/api/accounting/integrity", headers=h).json()
    assert body["healthy"] is False
    unbalanced = next(c for c in body["checks"] if c["check"].startswith("Every journal entry"))
    assert unbalanced["ok"] is False
    assert any(d["memo"] == "Deliberately broken for the test" for d in unbalanced["detail"])


# ---------------------------------------------------------------- import preview / commit / rollback
def _csv(rows: list[str]) -> io.BytesIO:
    return io.BytesIO(("\n".join(rows)).encode("utf-8"))


def test_import_dry_run_does_not_save(client, co):
    h = co["h"]
    csv = _csv(["Name,Phone,Email", "Dry Run Customer,0599123456,dryrun@x.ps"])
    r = client.post("/api/data/import/customers?dry_run=true", headers=h, files={"file": ("customers.csv", csv, "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True and body["created"] == 1 and body["batch_id"] is None
    # nothing was actually saved
    all_customers = client.get("/api/customers?limit=1000", headers=h).json()
    assert not any(c["name"] == "Dry Run Customer" for c in all_customers)


def test_import_commit_then_rollback(client, co):
    h = co["h"]
    csv = _csv(["Name,Phone,Email", "Rollback Customer,0599654321,rollback@x.ps"])
    r = client.post("/api/data/import/customers?dry_run=false", headers=h, files={"file": ("customers.csv", csv, "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1 and body["batch_id"]
    batch_id = body["batch_id"]

    customers = client.get("/api/customers?limit=1000", headers=h).json()
    created = next(c for c in customers if c["name"] == "Rollback Customer")

    batches = client.get("/api/data/import/batches", headers=h).json()
    assert any(b["id"] == batch_id and b["rolled_back_at"] is None for b in batches)

    r = client.post(f"/api/data/import/batches/{batch_id}/rollback", headers=h)
    assert r.status_code == 200
    assert r.json()["removed"] == 1

    customers = client.get("/api/customers?limit=1000", headers=h).json()
    assert not any(c["id"] == created["id"] for c in customers)

    # rolling back the same batch again is refused, not silently repeated
    assert client.post(f"/api/data/import/batches/{batch_id}/rollback", headers=h).status_code == 400


def test_import_rollback_keeps_rows_already_in_use(client, co):
    h = co["h"]
    csv = _csv(["Name,Cost price,Sale price", "Kept Product,3,9"])
    r = client.post("/api/data/import/products?dry_run=false", headers=h, files={"file": ("products.csv", csv, "text/csv")})
    body = r.json()
    batch_id = body["batch_id"]
    products = client.get("/api/inventory/products?limit=1000", headers=h).json()
    prod = next(p for p in products if p["name"] == "Kept Product")

    # sell it, so the product is now "in use"
    client.post("/api/inventory/stock/adjust", headers=h, json={"product_id": prod["id"], "warehouse_id": co["wh"]["id"], "quantity": 20})
    o = client.post("/api/sales/orders", headers=h, json={"customer_id": co["cust"]["id"], "warehouse_id": co["wh"]["id"],
                                                          "items": [{"product_id": prod["id"], "quantity": 2}]}).json()
    assert o.get("id") or o.get("pending_approval")

    r = client.post(f"/api/data/import/batches/{batch_id}/rollback", headers=h)
    result = r.json()
    assert result["removed"] == 0
    assert any(k["id"] == prod["id"] for k in result["kept_in_use"])
    # the product is still there
    products = client.get("/api/inventory/products?limit=1000", headers=h).json()
    assert any(p["id"] == prod["id"] for p in products)
