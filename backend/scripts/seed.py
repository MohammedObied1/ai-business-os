"""Seed a demo company with 6 months of realistic data.

Run:  python -m scripts.seed
Login: owner@demo.com / demo1234
"""
import random
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 and choke on "→" / "—"

from sqlalchemy import select  # noqa: E402

from app.api.auth import create_default_roles  # noqa: E402
from app.core import tenant_guard  # noqa: E402,F401  (same write guard as the API)
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    Company, Customer, CustomerInteraction, Expense, Invoice, Payment, Product, PurchaseOrder, PurchaseOrderItem, SalesOrder,
    SalesOrderItem, StockLevel, Supplier, User, Warehouse,
)
from app.services.automation import ensure_default_rules, run_company  # noqa: E402
from app.services.rag import index_document  # noqa: E402
from app.services.scoring import rescore_all  # noqa: E402

random.seed(42)

PRODUCTS = [
    ("BEV-001", "Coca-Cola 330ml", "Beverages", 2.1, 4.0, 300, 5),
    ("BEV-002", "Mineral Water 1.5L", "Beverages", 1.2, 3.0, 400, 5),
    ("BEV-003", "Orange Juice 1L", "Beverages", 4.5, 8.5, 150, 7),
    ("SNK-001", "Potato Chips 150g", "Snacks", 3.0, 6.5, 200, 7),
    ("SNK-002", "Chocolate Bar 100g", "Snacks", 2.8, 6.0, 200, 7),
    ("ELC-001", "USB-C Charger 20W", "Electronics", 28.0, 39.0, 40, 14),
    ("ELC-002", "Wireless Earbuds", "Electronics", 95.0, 129.0, 20, 21),
    ("ELC-003", "Phone Case", "Electronics", 9.0, 19.0, 60, 14),
    ("HOM-001", "Dish Soap 750ml", "Household", 5.5, 11.0, 120, 10),
    ("HOM-002", "Paper Towels 6-pack", "Household", 12.0, 22.0, 80, 10),
    ("HOM-003", "Laundry Detergent 3L", "Household", 24.0, 45.0, 50, 10),
    ("FRS-001", "Fresh Milk 1L", "Dairy", 4.2, 6.9, 200, 2),
    ("FRS-002", "Yogurt 500g", "Dairy", 3.5, 6.5, 150, 2),
    ("FRS-003", "White Cheese 250g", "Dairy", 8.0, 14.0, 80, 3),
]

CUSTOMERS = [
    "Al-Noor Supermarket", "Jerusalem Mini Market", "Haifa Grocery Co.", "Nazareth Trading", "Ramallah Foods",
    "Golden Basket Stores", "Tel Aviv Corner Shop", "Bethlehem Market", "Nablus Wholesale", "Akko Fresh",
    "Sunrise Kiosk", "Green Valley Market", "Eilat Beach Store", "City Center Mart", "Family Grocery",
    "Hebron Distributors", "Tiberias Lakeside Shop", "Jaffa Deli", "Northern Supplies", "Desert Oasis Store",
]

POLICY_DOC = """Discount Policy — Demo Trading Co.
1. Standard trade discount for wholesale customers is 5%.
2. Sales employees may grant discounts up to 10% without approval.
3. Discounts between 10% and 20% require Sales Manager approval.
4. Discounts above 20% require General Manager approval and must be documented with a business justification.
5. Discounts are never combined with promotional pricing on the same line item.

Credit & Collections Policy
- Standard payment terms are Net 30 days.
- Customers with an overdue balance above 30 days are placed on credit hold; new orders require Finance Manager approval.
- Finance sends a reminder at 7, 14 and 30 days after the due date.
- Balances above 60 days overdue are escalated to the General Manager.

Returns Procedure
- Dairy and fresh products cannot be returned after delivery.
- Packaged goods may be returned within 14 days in original condition; a restocking fee of 3% applies.
- Electronics are covered by a 12-month supplier warranty; defective units are replaced, not refunded.
"""

SUPPLIER_DOC = """Supplier Agreement — Northern Beverages Ltd.
Products covered: Coca-Cola 330ml, Mineral Water 1.5L, Orange Juice 1L.
Lead time: 5 working days from purchase order confirmation.
Minimum order: 200 units per SKU. Volume rebate of 2% on monthly purchases above 50,000 ILS.
Payment terms: 45 days. Late payment interest: 1% per month.
Delivery: supplier delivers to Main Warehouse (Haifa) on Mondays and Thursdays.
"""


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.scalar(select(Company.id)):
        print("Database already seeded.")
        return
    co = Company(name="Demo Trading Co.", currency="ILS", industry="Wholesale & Distribution")
    db.add(co)
    db.flush()
    roles = create_default_roles(db, co.id)
    users = {
        "owner": User(company_id=co.id, email="owner@demo.com", full_name="Sami Haddad", hashed_password=hash_password("demo1234"), role_id=roles["Company Owner"].id, department="Management"),
        "sales_mgr": User(company_id=co.id, email="sales@demo.com", full_name="Layla Mansour", hashed_password=hash_password("demo1234"), role_id=roles["Sales Manager"].id, department="Sales"),
        "finance": User(company_id=co.id, email="finance@demo.com", full_name="Yousef Khoury", hashed_password=hash_password("demo1234"), role_id=roles["Finance Manager"].id, department="Finance"),
        "sales_emp": User(company_id=co.id, email="rep@demo.com", full_name="Dana Saleh", hashed_password=hash_password("demo1234"), role_id=roles["Sales Employee"].id, department="Sales"),
        "warehouse": User(company_id=co.id, email="warehouse@demo.com", full_name="Omar Nasser", hashed_password=hash_password("demo1234"), role_id=roles["Warehouse Employee"].id, department="Operations"),
    }
    db.add_all(users.values())
    db.flush()

    whs = [Warehouse(company_id=co.id, name="Main Warehouse (Haifa)", location="Haifa"),
           Warehouse(company_id=co.id, name="Jerusalem Depot", location="Jerusalem"),
           Warehouse(company_id=co.id, name="South Hub (Beersheba)", location="Beersheba")]
    db.add_all(whs)
    db.flush()

    products = []
    for sku, name, cat, cost, price, min_stock, lt in PRODUCTS:
        p = Product(company_id=co.id, sku=sku, name=name, category=cat, cost_price=cost, sale_price=price, min_stock=min_stock,
                    supplier_lead_time_days=lt, track_batches=cat == "Dairy")
        products.append(p)
    db.add_all(products)
    db.flush()

    customers = [Customer(company_id=co.id, name=n, email=f"orders@{n.lower().replace(' ', '').replace('.', '').replace('-', '')}.com",
                          phone=f"05{random.randint(10000000, 99999999)}", credit_limit=random.choice([10000, 20000, 50000]),
                          customer_type="business", address=random.choice(["Haifa", "Jerusalem", "Nazareth", "Tel Aviv", "Beersheba"]))
                 for n in CUSTOMERS]
    db.add_all(customers)
    db.flush()

    suppliers = [Supplier(company_id=co.id, name="Northern Beverages Ltd.", email="sales@nbev.com", lead_time_days=5, payment_terms_days=45),
                 Supplier(company_id=co.id, name="TechSource Import", email="orders@techsource.com", lead_time_days=21, payment_terms_days=30),
                 Supplier(company_id=co.id, name="Galilee Dairy Farms", email="hello@galileedairy.com", lead_time_days=2, payment_terms_days=14)]
    db.add_all(suppliers)
    db.flush()

    # initial stock (deliberately low for some products to trigger alerts)
    for p in products:
        base = p.min_stock * random.uniform(1.5, 4)
        if p.sku in ("BEV-001", "FRS-001", "ELC-002"):
            base = p.min_stock * 0.6
        for i, w in enumerate(whs):
            share = [0.55, 0.3, 0.15][i]
            db.add(StockLevel(company_id=co.id, product_id=p.id, warehouse_id=w.id, quantity=round(base * share),
                              batch=f"B{date.today().strftime('%y%m')}" if p.track_batches else "",
                              expiry_date=date.today() + timedelta(days=random.randint(10, 40)) if p.track_batches else None))

    # 6 months of orders. Last month = strong, this month = weaker + higher expenses + high discounts (to make insights interesting)
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=170)).replace(day=1)
    so_n = inv_n = 0
    d = start
    customer_weights = [random.uniform(0.3, 3.0) for _ in customers]
    while d <= today:
        month_factor = 1.0
        months_ago = (today.year - d.year) * 12 + today.month - d.month
        if months_ago == 1:
            month_factor = 1.25
        elif months_ago == 0:
            month_factor = 1.1
        n_orders = max(1, int(random.gauss(4, 1.5) * month_factor))
        if d.weekday() in (4,):
            n_orders = max(1, n_orders // 2)
        for _ in range(n_orders):
            cust = random.choices(customers, weights=customer_weights)[0]
            wh = random.choices(whs, weights=[0.55, 0.3, 0.15])[0]
            so_n += 1
            disc = 0.0
            if months_ago == 0 and cust.name in ("Al-Noor Supermarket", "Nablus Wholesale") and random.random() < 0.5:
                disc = random.choice([18, 22, 25])
            elif random.random() < 0.15:
                disc = 5
            order = SalesOrder(company_id=co.id, number=f"SO-{d.year}-{so_n:04d}", customer_id=cust.id, warehouse_id=wh.id, status="delivered",
                               order_date=d, discount_pct=disc, salesperson_id=random.choice([users["sales_emp"].id, users["sales_mgr"].id]))
            db.add(order)
            db.flush()
            subtotal = cost = 0.0
            for p in random.sample(products, k=random.randint(2, 5)):
                qty = random.randint(5, 60) if p.category != "Electronics" else random.randint(1, 6)
                if p.sku == "BEV-001":
                    qty = random.randint(40, 120)
                price = p.sale_price
                if months_ago == 0 and p.category == "Electronics":
                    price = round(p.sale_price * 0.85, 2)  # margin squeeze on electronics this month
                line = qty * price
                db.add(SalesOrderItem(company_id=co.id, order_id=order.id, product_id=p.id, quantity=qty, unit_price=price, unit_cost=p.cost_price, line_total=round(line, 2)))
                subtotal += line
                cost += qty * p.cost_price
            order.subtotal = round(subtotal, 2)
            order.total = round(subtotal * (1 - disc / 100), 2)
            order.cost_total = round(cost, 2)
            inv_n += 1
            inv = Invoice(company_id=co.id, number=f"INV-{d.year}-{inv_n:04d}", customer_id=cust.id, order_id=order.id, issue_date=d, due_date=d + timedelta(days=30), total=order.total)
            age = (today - d).days
            if age > 45 and random.random() < 0.94 or (30 < age <= 45 and random.random() < 0.6):
                inv.paid_amount = inv.total
                inv.status = "paid"
                db.add(inv)
                db.flush()
                db.add(Payment(company_id=co.id, invoice_id=inv.id, customer_id=cust.id, amount=inv.total, method=random.choice(["bank", "cheque", "cash"]),
                               paid_at=datetime.combine(d + timedelta(days=random.randint(10, 40)), datetime.min.time())))
            elif age > 60:
                inv.status = "overdue"
                db.add(inv)
            else:
                db.add(inv)
        d += timedelta(days=1)

    # expenses: this month +12%
    cats = {"Rent": 18000, "Salaries": 62000, "Utilities": 4200, "Marketing": 6500, "Logistics": 9800, "Insurance": 2100}
    m = start
    while m <= today:
        months_ago = (today.year - m.year) * 12 + today.month - m.month
        for c, amt in cats.items():
            factor = 1.12 if months_ago == 0 and c in ("Logistics", "Marketing", "Salaries") else 1.0
            db.add(Expense(company_id=co.id, category=c, description=f"{c} — {m.strftime('%B %Y')}", amount=round(amt * factor * random.uniform(0.95, 1.05), 2), expense_date=m.replace(day=min(5, 28))))
        m = (m + timedelta(days=32)).replace(day=1)

    # purchase orders
    for i, (sup, prods) in enumerate([(suppliers[0], products[0:3]), (suppliers[1], products[5:8]), (suppliers[2], products[11:14])]):
        po = PurchaseOrder(company_id=co.id, number=f"PO-{today.year}-{i + 1:04d}", supplier_id=sup.id, warehouse_id=whs[0].id, status="ordered",
                           order_date=today - timedelta(days=random.randint(3, 20)), expected_date=today + timedelta(days=sup.lead_time_days), requested_by="Omar Nasser")
        db.add(po)
        db.flush()
        total = 0
        for p in prods:
            q = p.min_stock * 2
            db.add(PurchaseOrderItem(company_id=co.id, po_id=po.id, product_id=p.id, quantity=q, unit_cost=p.cost_price, line_total=q * p.cost_price))
            total += q * p.cost_price
        po.total = round(total, 2)
        po.paid_amount = round(total * 0.5, 2) if i == 0 else 0

    # interactions
    kinds = ["call", "whatsapp", "email", "visit", "complaint"]
    for c in random.sample(customers, 12):
        for _ in range(random.randint(1, 3)):
            k = random.choice(kinds)
            db.add(CustomerInteraction(company_id=co.id, customer_id=c.id, user_id=users["sales_emp"].id, kind=k,
                                       summary=random.choice(["Discussed next month's order volume.", "Complained about late delivery on Thursday.", "Requested updated price list.",
                                                              "Asked about credit limit increase.", "Confirmed receipt of goods."]),
                                       occurred_at=datetime.utcnow() - timedelta(days=random.randint(1, 80))))

    db.commit()
    index_document(db, co.id, "Company Policies (Discounts, Credit, Returns)", "policy", POLICY_DOC)
    index_document(db, co.id, "Supplier Agreement — Northern Beverages", "contract", SUPPLIER_DOC)
    ensure_default_rules(db, co.id)
    rescore_all(db, co.id)
    created = run_company(db, co.id)
    print("Seeded Demo Trading Co.")
    print("Automation run:", created)
    print("Login: owner@demo.com / demo1234  (also sales@, finance@, rep@, warehouse@ — same password)")
    db.close()


if __name__ == "__main__":
    seed()
