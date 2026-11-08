"""Permission catalogue.

Two vocabularies live side by side:
- the original coarse permissions (`sales:read`, `inventory:write`…) that every existing role and route uses;
- granular permissions (`sales.discount`, `reports.view_profit`, `inventory.adjust`…) for finer roles.

They are kept equivalent so nothing breaks: a legacy permission grants all the granular ones it used to cover, and
a granular permission grants access to the routes guarded by its legacy parent. Routes that need finer control check
the granular permission directly (e.g. `accounting.close_period`, `reports.view_profit`).
"""

# group → [(permission, English label)]; Arabic labels live in the frontend dictionary (perm.<name>)
CATALOG: list[tuple[str, list[tuple[str, str]]]] = [
    ("Sales", [("sales.view", "View sales"), ("sales.create", "Create sales"), ("sales.edit", "Edit / confirm sales"), ("sales.delete", "Cancel sales"),
               ("sales.discount", "Give discounts"), ("sales.approve_discount", "Approve big discounts / below cost"), ("pos.use", "Use the cashier"),
               ("invoices.create", "Create invoices"), ("invoices.cancel", "Cancel invoices"), ("returns.create", "Customer returns")]),
    ("Customers", [("customers.view", "View customers"), ("customers.create", "Add customers"), ("customers.edit", "Edit customers"),
                   ("customers.delete", "Delete customers")]),
    ("Inventory", [("inventory.view", "View stock"), ("inventory.edit", "Edit products & warehouses"), ("inventory.adjust", "Adjust stock"),
                   ("inventory.transfer", "Transfer between warehouses"), ("inventory.count", "Stock counts"),
                   ("inventory.approve_adjustment", "Approve stock adjustments"), ("products.view_cost", "See cost prices"),
                   ("warehouses.all", "All warehouses (ignore warehouse limits)")]),
    ("Purchasing", [("purchasing.view", "View purchases"), ("purchasing.create", "Create purchases"), ("purchasing.approve", "Approve purchases")]),
    ("Finance", [("finance.view", "View expenses & money"), ("finance.create_payment", "Record payments"), ("finance.create_expense", "Record expenses"),
                 ("finance.approve_expense", "Approve expenses"), ("accounts.view", "View cash & banks"), ("accounts.edit", "Vouchers, transfers & cheques")]),
    ("Accounting", [("accounting.view", "View accounting"), ("accounting.create_entry", "Create journal entries"), ("accounting.edit_entry", "Edit / delete entries"),
                    ("accounting.close_period", "Close / reopen periods")]),
    ("Reports", [("reports.view", "View reports & dashboards"), ("reports.view_profit", "See profit & margins"), ("reports.view_salary", "See salaries"),
                 ("reports.export", "Export data")]),
    ("Employees", [("employees.view", "View employees"), ("employees.create", "Add employees"), ("employees.edit", "Edit employees & payroll"),
                   ("employees.delete", "Delete employees")]),
    ("Delivery & field", [("deliveries.view", "See all deliveries"), ("deliveries.driver", "Driver: my deliveries"), ("field.rep", "Sales rep: my route"),
                          ("field.track_location", "Record location on visits"), ("field.collect_payment", "Collect payments on visits")]),
    ("Administration", [("users.manage", "Users & roles"), ("settings.manage", "Company settings"), ("approvals.approve", "Approve requests"),
                        ("approvals.rules", "Edit approval rules"), ("automation.manage", "Automation rules"), ("audit.view", "Activity log"),
                        ("documents.manage", "Company documents"), ("integrations.manage", "API keys & webhooks"), ("branches.all", "All branches"),
                        ("ai.use", "AI assistant"), ("ai.actions", "Let the AI prepare drafts")]),
]

ALL_GRANULAR = [p for _, perms in CATALOG for p, _ in perms]

# legacy permission → granular permissions it has always covered
LEGACY: dict[str, list[str]] = {
    "sales:read": ["sales.view"],
    "sales:write": ["sales.create", "sales.edit", "sales.delete", "sales.discount"],
    "invoices:create": ["invoices.create", "invoices.cancel"],
    "returns:create": ["returns.create"],
    "pos:use": ["pos.use"],
    "customers:read": ["customers.view"],
    "customers:write": ["customers.create", "customers.edit"],
    "customers:delete": ["customers.delete"],
    "inventory:read": ["inventory.view"],
    "inventory:write": ["inventory.edit", "inventory.adjust", "inventory.transfer", "inventory.count", "products.view_cost"],
    "purchasing:read": ["purchasing.view", "products.view_cost"],
    "purchasing:write": ["purchasing.create"],
    "purchasing:approve": ["purchasing.approve"],
    "finance:read": ["finance.view"],
    "finance:write": ["finance.create_expense"],
    "payments:write": ["finance.create_payment", "field.collect_payment"],
    "accounts:read": ["accounts.view"],
    "accounts:write": ["accounts.edit"],
    "accounting:read": ["accounting.view", "products.view_cost"],
    "accounting:write": ["accounting.create_entry", "accounting.edit_entry"],
    "reports:read": ["reports.view", "reports.view_profit", "reports.export", "products.view_cost"],
    "hr:read": ["employees.view", "reports.view_salary"],
    "hr:write": ["employees.create", "employees.edit", "employees.delete"],
    "users:write": ["users.manage"],
    "settings:write": ["settings.manage", "integrations.manage", "approvals.rules"],
    "approvals:approve": ["approvals.approve", "sales.approve_discount", "finance.approve_expense", "inventory.approve_adjustment"],
    "automation:write": ["automation.manage"],
    "audit:read": ["audit.view"],
    "documents:write": ["documents.manage"],
    "branches:all": ["branches.all"],
    "ai:use": ["ai.use"],
}

# granular permission → the legacy permission guarding the routes it needs
# (cross-cutting ones like products.view_cost grant nothing else: holding them must not open whole screens)
_NO_PARENT = {"products.view_cost", "reports.view_salary", "reports.export"}
_PARENT: dict[str, str] = {}
for _legacy, _grans in LEGACY.items():
    for _g in _grans:
        if _g not in _NO_PARENT:
            _PARENT.setdefault(_g, _legacy)
_PARENT.update({"deliveries.view": "sales:read", "field.rep": "customers:read", "ai.actions": "ai:use"})


def effective(held: list[str] | None) -> set[str]:
    """Every permission a role really has, in both vocabularies."""
    out = set(held or [])
    if "*" in out:
        return out
    for p in list(out):
        out.update(LEGACY.get(p, []))
        if p in _PARENT:
            out.add(_PARENT[p])
    return out


def catalog_for_ui() -> list[dict]:
    return [{"group": g, "permissions": [{"name": p, "label": label} for p, label in perms]} for g, perms in CATALOG]
