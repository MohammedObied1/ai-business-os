from fastapi import APIRouter, Depends

from app.api import (
    approval_center, notifications, saas_admin, stock_ops, accounting, ai, auth, automation, customers, dashboard, data_io, finance, hr, inventory, money, ops, org, platform, pos, public, purchasing, reports, sales, users,
)
from app.core.deps import require_feature

api_router = APIRouter(prefix="/api")
# modules a plan can leave out (a plan with no feature list includes everything)
FEATURE_GATES = {"app.api.pos": "pos"}
# reports before dashboard: /reports/pnl etc. must win over the generic /reports/{report}
for r in (auth, platform, saas_admin, public, approval_center, notifications, stock_ops, accounting, users, customers, inventory, sales, pos, purchasing, finance, money, hr, org, ops, reports, dashboard, ai, automation, data_io):
    gate = FEATURE_GATES.get(r.__name__)
    api_router.include_router(r.router, dependencies=[Depends(require_feature(gate))] if gate else [])
