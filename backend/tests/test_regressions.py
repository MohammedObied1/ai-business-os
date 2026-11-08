"""Regressions for the failures found by the first public CI run."""

from collections import Counter
from datetime import date, timedelta

import pytest
from fastapi.routing import APIRoute


def workspace(client, label):
    response = client.post(
        "/api/auth/register",
        json={
            "company_name": label,
            "owner_name": "Regression Owner",
            "owner_email": f"{label.lower()}@example.com",
            "password": "testpass123",
        },
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    owner = client.get("/api/auth/me", headers=headers).json()
    return headers, owner["company_id"]


def admin(client):
    response = client.post(
        "/api/auth/login",
        data={"username": "root@platform.test", "password": "rootpass1"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_routes_do_not_shadow_another_handler():
    from app.main import app

    routes = Counter(
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    )
    assert not {key: count for key, count in routes.items() if count > 1}


def test_cash_and_warehouse_transfers_use_independent_endpoints(client):
    h, _ = workspace(client, "transfer-regression")
    cash = client.get("/api/accounts", headers=h).json()[0]
    bank_response = client.post(
        "/api/accounts", headers=h, json={"name": "Regression bank", "kind": "bank"}
    )
    assert bank_response.status_code == 201, bank_response.text
    bank = bank_response.json()
    assert (
        client.post(
            "/api/vouchers",
            headers=h,
            json={"direction": "in", "account_id": cash["id"], "amount": 100},
        ).status_code
        == 201
    )
    moved = client.post(
        "/api/transfers",
        headers=h,
        json={"from_account_id": cash["id"], "to_account_id": bank["id"], "amount": 40},
    )
    assert moved.status_code == 201, moved.text
    balances = {
        row["id"]: row["balance"]
        for row in client.get("/api/accounts", headers=h).json()
    }
    assert balances[cash["id"]] == 60 and balances[bank["id"]] == 40
    source = client.post(
        "/api/inventory/warehouses", headers=h, json={"name": "Source"}
    ).json()
    target = client.post(
        "/api/inventory/warehouses", headers=h, json={"name": "Target"}
    ).json()
    product = client.post(
        "/api/inventory/products",
        headers=h,
        json={
            "name": "Transfer product",
            "opening_stock": 10,
            "warehouse_id": source["id"],
            "cost_price": 2,
            "sale_price": 5,
        },
    ).json()
    moved = client.post(
        "/api/inventory/transfers",
        headers=h,
        json={
            "from_warehouse_id": source["id"],
            "to_warehouse_id": target["id"],
            "submit": False,
            "lines": [{"product_id": product["id"], "quantity": 3}],
        },
    )
    assert moved.status_code == 201, moved.text
    assert moved.json()["status"] == "DRAFT"
    transfer_id = moved.json()["id"]
    assert (
        client.get(f"/api/inventory/transfers/{transfer_id}", headers=h).status_code
        == 200
    )
    for action, status in [
        ("submit", "REQUESTED"),
        ("approve", "APPROVED"),
        ("ship", "IN_TRANSIT"),
        ("receive", "RECEIVED"),
    ]:
        response = client.post(
            f"/api/inventory/transfers/{transfer_id}/{action}", headers=h, json={}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status
    from app.core.database import SessionLocal
    from app.models import StockLevel
    from sqlalchemy import select

    with SessionLocal() as db:
        quantities = dict(
            db.execute(
                select(StockLevel.warehouse_id, StockLevel.quantity).where(
                    StockLevel.product_id == product["id"]
                )
            ).all()
        )
        assert quantities[source["id"]] == 7 and quantities[target["id"]] == 3
    assert {
        row["id"]: row["balance"]
        for row in client.get("/api/accounts", headers=h).json()
    } == balances


def test_branch_report_counts_each_order_once_and_preserves_empty_branches(client):
    from app.core.database import SessionLocal
    from app.models import SalesOrder

    h, cid = workspace(client, "branch-regression")
    branches = [
        client.post("/api/branches", headers=h, json={"name": name}).json()["id"]
        for name in ("North", "South", "Empty")
    ]
    warehouses = [
        client.post(
            "/api/inventory/warehouses",
            headers=h,
            json={"name": f"WH-{i}", "branch_id": branches[0]},
        ).json()["id"]
        for i in (1, 2)
    ]
    customer = client.post(
        "/api/customers", headers=h, json={"name": "Report customer"}
    ).json()["id"]
    with SessionLocal() as db:
        for index, (wh, branch, total, tax, status) in enumerate(
            [
                (warehouses[0], None, 12, 2, "confirmed"),
                (warehouses[1], None, 24, 4, "delivered"),
                (warehouses[0], branches[1], 48, 8, "confirmed"),
                (warehouses[0], branches[0], 1000, 0, "quotation"),
            ]
        ):
            db.add(
                SalesOrder(
                    company_id=cid,
                    customer_id=customer,
                    number=f"REGRESSION-{index}",
                    warehouse_id=wh,
                    branch_id=branch,
                    total=total,
                    tax_amount=tax,
                    status=status,
                    order_date=date.today(),
                )
            )
        db.commit()
    response = client.get("/api/reports/branch", headers=h)
    assert response.status_code == 200, response.text
    rows = {row["branch_id"]: row for row in response.json()["by_branch"]}
    assert (rows[branches[0]]["revenue"], rows[branches[0]]["orders"]) == (30, 2)
    assert (rows[branches[1]]["revenue"], rows[branches[1]]["orders"]) == (40, 1)
    assert (rows[branches[2]]["revenue"], rows[branches[2]]["orders"]) == (0, 0)


def test_assigning_paid_plan_to_unlimited_company_starts_one_billable_period(client):
    _, cid = workspace(client, "billing-regression")
    a = admin(client)
    plan = client.post(
        "/api/platform/plans",
        headers=a,
        json={"name": "Paid regression", "price_monthly": 120},
    ).json()
    assigned = client.patch(
        f"/api/platform/companies/{cid}", headers=a, json={"plan_id": plan["id"]}
    )
    assert assigned.status_code == 200, assigned.text
    sub = client.get(f"/api/platform/companies/{cid}/subscription", headers=a).json()
    assert sub["status"] == "past_due"
    assert client.post("/api/platform/billing/run", headers=a).status_code == 200
    invoices = [
        row
        for row in client.get("/api/platform/billing", headers=a).json()["items"]
        if row["company_id"] == cid
    ]
    assert len(invoices) == 1 and invoices[0]["amount"] == 120
    assert client.post("/api/platform/billing/run", headers=a).status_code == 200
    repeated = [
        row
        for row in client.get("/api/platform/billing", headers=a).json()["items"]
        if row["company_id"] == cid
    ]
    assert [row["id"] for row in repeated] == [invoices[0]["id"]]


@pytest.mark.parametrize("unlimited", [False, True])
def test_explicit_admin_subscription_end_is_preserved(client, unlimited):
    _, cid = workspace(client, f"explicit-end-{unlimited}")
    a = admin(client)
    plan = client.post(
        "/api/platform/plans",
        headers=a,
        json={"name": "Manual period", "price_monthly": 90},
    ).json()
    end = None if unlimited else (date.today() + timedelta(days=60)).isoformat()
    response = client.patch(
        f"/api/platform/companies/{cid}",
        headers=a,
        json={"plan_id": plan["id"], "subscription_ends_at": end},
    )
    assert response.status_code == 200, response.text
    assert response.json()["subscription_ends_at"] == end
    client.post("/api/platform/billing/run", headers=a)
    invoices = client.get("/api/platform/billing", headers=a).json()["items"]
    assert not any(row["company_id"] == cid for row in invoices)


def test_no_answer_visit_is_recorded_and_unknown_outcome_is_rejected(client):
    h, _ = workspace(client, "visit-regression")
    customer = client.post(
        "/api/customers", headers=h, json={"name": "Visit customer"}
    ).json()
    response = client.post(
        "/api/field/visits",
        headers=h,
        json={"customer_id": customer["id"], "outcome": "no_answer"},
    )
    assert response.status_code == 201, response.text
    before = client.get("/api/field/visits", headers=h).json()
    assert len(before) == 1 and before[0]["outcome"] == "no_answer"
    assert (
        client.post(
            "/api/field/visits",
            headers=h,
            json={"customer_id": customer["id"], "outcome": "unknown"},
        ).status_code
        == 400
    )
    assert client.get("/api/field/visits", headers=h).json() == before


def test_changing_plan_keeps_an_existing_paid_period(client):
    _, cid = workspace(client, "prepaid-end-regression")
    a = admin(client)
    first = client.post(
        "/api/platform/plans",
        headers=a,
        json={"name": "Existing paid", "price_monthly": 90},
    ).json()
    next_plan = client.post(
        "/api/platform/plans",
        headers=a,
        json={"name": "New paid", "price_monthly": 120},
    ).json()
    end = (date.today() + timedelta(days=60)).isoformat()
    assert (
        client.patch(
            f"/api/platform/companies/{cid}",
            headers=a,
            json={"plan_id": first["id"], "subscription_ends_at": end},
        ).status_code
        == 200
    )
    response = client.patch(
        f"/api/platform/companies/{cid}", headers=a, json={"plan_id": next_plan["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["subscription_ends_at"] == end
    client.post("/api/platform/billing/run", headers=a)
    assert not any(
        row["company_id"] == cid
        for row in client.get("/api/platform/billing", headers=a).json()["items"]
    )
