from datetime import date, datetime

from pydantic import BaseModel, EmailStr

from app.schemas.common import ORMModel


class RegisterCompany(BaseModel):
    company_name: str
    currency: str = "ILS"
    industry: str | None = None
    owner_name: str
    owner_email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    kind: str = "company"  # company / platform


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class RoleOut(ORMModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[str]
    granted: list[str] = []  # granular permissions this role really has (legacy ones expanded)


class RoleIn(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    department: str | None = None
    is_active: bool
    role: RoleOut | None = None
    company_id: int
    branch_id: int | None = None
    phone: str | None = None
    totp_enabled: bool = False
    last_login_at: datetime | None = None
    impersonated: bool = False
    must_setup_2fa: bool = False
    allowed_warehouse_ids: list[int] | None = None
    effective_permissions: list[str] = []  # filled by /auth/me: every permission the role grants, both vocabularies


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    department: str | None = None
    role_id: int | None = None
    branch_id: int | None = None
    phone: str | None = None
    allowed_warehouse_ids: list[int] | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    department: str | None = None
    role_id: int | None = None
    is_active: bool | None = None
    password: str | None = None  # admin reset
    branch_id: int | None = None
    phone: str | None = None
    allowed_warehouse_ids: list[int] | None = None


class CompanyOut(ORMModel):
    id: int
    name: str
    currency: str
    industry: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tax_number: str | None = None
    is_active: bool = True
    tax_rate: float = 0
    prices_include_tax: bool = False
    logo_path: str | None = None
    invoice_footer: str | None = None
    plan_id: int | None = None
    subscription_ends_at: date | None = None
    slug: str | None = None
    custom_domain: str | None = None
    domain_verified_at: datetime | None = None
    brand_color: str | None = None
    catalog_enabled: bool = False
    portal_orders_enabled: bool = True
    online_order_status: str = "quotation"
    payment_instructions: str | None = None
    approval_discount_pct: float = 0
    approval_expense_amount: float = 0
    require_2fa: bool = False
    timezone: str = "Asia/Hebron"
    costing_method: str = "average"


class CompanyUpdate(BaseModel):
    name: str | None = None
    currency: str | None = None
    industry: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tax_number: str | None = None
    tax_rate: float | None = None
    prices_include_tax: bool | None = None
    invoice_footer: str | None = None
    slug: str | None = None
    brand_color: str | None = None
    catalog_enabled: bool | None = None
    portal_orders_enabled: bool | None = None
    online_order_status: str | None = None
    payment_instructions: str | None = None
    approval_discount_pct: float | None = None
    approval_expense_amount: float | None = None
    require_2fa: bool | None = None
    costing_method: str | None = None
    timezone: str | None = None


# ---------------------------------------------------------------- platform admin
class PlatformCompanyIn(BaseModel):
    name: str
    currency: str = "ILS"
    industry: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tax_number: str | None = None
    notes: str | None = None
    tax_rate: float = 16
    plan_id: int | None = None
    subscription_ends_at: date | None = None
    owner_name: str
    owner_email: EmailStr
    owner_password: str


class PlatformCompanyUpdate(CompanyUpdate):
    custom_domain: str | None = None
    is_active: bool | None = None
    notes: str | None = None
    plan_id: int | None = None
    subscription_ends_at: date | None = None


class CompanyStats(BaseModel):
    users: int
    customers: int
    products: int
    orders: int
    invoices: int
    revenue: float
    last_order: date | None = None


class PlatformCompanyOut(CompanyOut):
    notes: str | None = None
    created_at: datetime
    owner_name: str | None = None
    owner_email: str | None = None
    stats: CompanyStats


class PlatformAdminOut(ORMModel):
    id: int
    email: str
    full_name: str


class OwnerPasswordReset(BaseModel):
    new_password: str
