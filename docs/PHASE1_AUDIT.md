# Phase 1 — Project Audit & Gap Analysis

Date: 2026-09-27 · Scope: the whole repository (backend, frontend, infra, tests). No code was changed in this phase.

## 1. Architecture as it is today

| Layer | What exists |
|---|---|
| Backend | FastAPI, SQLAlchemy 2, 21 routers, 23 services, ~10k lines. Entry `app/main.py`, routes in `app/api/*`, business logic in `app/services/*`. |
| Database | **64 tables** (earlier reports said 84 — that count was wrong). SQLite locally (`%LOCALAPPDATA%\BizOS`), PostgreSQL in Docker. Schema kept in sync by `core/migrate.py` (adds missing tables/columns) + one Alembic baseline (`migrations/versions/d4c0b9ab6342`). |
| Tenant model | Every business table has an indexed `company_id` (only `companies`, `plans`, `platform_admins`, `password_reset_tokens` do not — by design). |
| Auth | JWT with `sub`, `cid`, `tv` (token version), `imp` (impersonation), `scope` (company / platform). API keys via `X-API-Key` act as the user who created them. 2FA (TOTP), lockout (5 tries / 15 min), logout-all, login history. |
| Tenant resolution | `core/deps.get_current_user`: user loaded from the token, `user.company_id` must equal the token's `cid`; company suspended → 403, subscription expired → 402. Every route uses `user.company_id`; **no route reads a company id from the request**. |
| Authorization | Role = list of permission strings (`sales:read`, `accounting:write`, …, `*`). `require_permission()` dependency. `branch_scope()` limits branch-bound users. 9 default roles, custom roles supported. |
| Audit | `core/audit.py`: SQLAlchemy `after_flush` hook writes old→new values for 23 tracked tables. |
| Jobs | APScheduler inside the API process: automation (15 min), email outbox (1 min), webhooks (1 min), recurring invoices (1 h), backup (daily), platform billing (06:00), daily summary (07:00). |
| AI | `services/ai_agent.py`: Claude tool-use loop with 12 tenant-scoped tools (8 read, 4 write) + offline intent router; receipt/invoice reading; RAG over company documents. |
| Frontend | Next.js 14 app router, 47 pages, Arabic/English (`lib/i18n.tsx` + `lib/i18n-en.ts`), RTL, PWA, offline POS. Token stored in `localStorage`. |
| Infra | Dockerfiles, `docker-compose.yml` (+prod with Caddy, HTTPS, on-demand TLS for tenant domains), GitHub Actions CI, daily backups (SQLite copy / `pg_dump`, keep 30). |
| Tests | 29 backend tests (pytest, one SQLite DB per session). No frontend tests. |

## 2. Status by area

Legend: ✅ works · 🟡 works, needs hardening · 🟠 partial · ❌ missing

| Area (phase) | Status | Notes |
|---|---|---|
| Tenant isolation (P1) | 🟡 | Reads are filtered by `company_id` everywhere checked. **Writes accept foreign ids from the request body without checking their company in several places** (see §3). Only 2 small isolation tests exist. |
| RBAC (P2) | 🟠 | Coarse permissions (`sales:read` also exposes cost/profit to cashiers). No warehouse restriction. Custom roles exist; no permission catalogue UI beyond checkboxes. |
| Approvals (P3) | 🟠 | Sales discount / below cost and large expenses only; no generic approval entity, no rules UI, no rejection reason. |
| Audit log (P4) | 🟡 | Old→new values recorded, but no IP/device, 40+ newer tables not tracked (journal, price lists, deliveries, API keys, webhooks, currencies…), impersonation start not logged. |
| Period lock (P5) | ❌ | |
| Inventory costing (P6) | 🟠 | Weighted average cost on product + FEFO batches for quantities; no FIFO cost layers, no costing method setting. |
| Warehouse transfers (P7) | 🟠 | Instant transfer only; no workflow, no in-transit/reserved/damaged/expired stock. |
| Returns & damaged (P8) | 🟠 | Customer returns only (always back to stock); no supplier returns, no condition. |
| Notification center (P9) | 🟠 | Alerts + email outbox; no per-user preferences, no push/WhatsApp channel. |
| Automation engine (P10) | 🟠 | Fixed rule types with parameters; no generic IF/THEN builder. |
| Dashboard builder (P11) | ❌ | Fixed dashboards. |
| SaaS billing (P12) | 🟠 | Plans with limits, monthly invoices, paid → extend. No yearly/trial/grace/coupons/add-ons/usage. |
| Platform admin (P13) | 🟡 | Companies, plans, billing, backups, outbox, security, impersonation. Impersonation start not audited. |
| Tenant health (P14) | ❌ | |
| Observability (P15) | 🟠 | `/health`, optional Sentry, Python logging. No metrics, no structured logs, no slow-query tracking. |
| Customer portal (P16) | 🟡 | Balance, invoices, statement, payment proof. Token never expires; no orders/instalments view. |
| Online store (P17) | 🟡 | Uses the real products/stock; orders always become quotations (not configurable). |
| Delivery (P18) | 🟡 | Statuses assigned/out/delivered/failed; no RETURNED; cash → payment automatically. |
| Field sales (P19) | 🟡 | Route, visits with location, quick order; location is always requested (no company opt-in). |
| Reporting (P20) | 🟠 | Many reports; no saved reports, no CSV/PDF export per report, no branch/warehouse breakdown for all. |
| AI analyst (P21) | 🟡 | Real tenant data through tools. **Tools ignore the user's permissions** (see §3). |
| AI voice (P22) | 🟡 | Browser speech-to-text → same endpoint. |
| Anomaly detection (P23) | 🟠 | Per-employee flags vs fixed thresholds, not vs the employee's own history. |
| Forecasting (P24) | 🟡 | Stock-out forecast per product; no confidence, no cash-flow forecast. |
| Recommendations (P25) | 🟡 | Pricing ideas, alerts; reasoning partly shown. |
| AI actions (P26) | 🟠 | Write tools execute immediately (task, customer, purchase request, alert) — no draft/confirm step. |
| Integrations (P27) | 🟠 | API keys + webhooks only; no integration framework. |
| Webhooks (P28) | 🟡 | HMAC-signed, retries, delivery log. Some events of the spec missing (order.updated, invoice.paid, stock.updated, delivery.completed). |
| Public API (P29) | 🟠 | Any endpoint via API key; no scopes, no rate limit, no expiry, no usage tracking. |
| Backups (P30) | 🟠 | Daily + retention; no weekly/monthly tiers, no encryption, **restore never tested automatically**. |
| Security hardening (P31) | 🟡 | 2FA, lockout, logout-all, hashed passwords. Missing: password policy (min 6 only), rate limiting, security headers, SECRET_KEY guard, token in localStorage. |
| Custom domains (P32) | 🟡 | Set only by the platform admin (a tenant cannot claim one); no DNS verification step. |
| Localization (P33) | 🟡 | Arabic/English, RTL; currency per company; no per-company timezone/date format. |
| Import/export (P34) | 🟠 | Excel import with preview for 4 entities, fixed column names (no mapping step); export Excel only; exports ignore branch scope. |
| Accounting integrity (P35) | 🟡 | Double-entry ledger rebuilt from documents; trial balance & balance sheet balance in tests. |

## 3. Security findings (ordered by severity)

1. **Cross-tenant foreign keys on write (HIGH).** Several create/update endpoints store ids from the request body without checking they belong to the caller's company:
   - customers: `price_list_id`, `assigned_user_id`, `branch_id` → with another company's price list id, `/api/sales/quote` returns that company's prices (**data leak**);
   - purchase orders: `warehouse_id` (an unknown id even crashes with 500);
   - users, warehouses, expenses, employees, sales orders: `branch_id`;
   - other nested ids not yet exercised (driver, BOM lines, visits…).
   A missed check in any future endpoint would repeat the problem → needs a central guard, not only point fixes.
2. **AI tools bypass permissions (HIGH).** Anyone with `ai:use` can read profit/finance through the assistant and let it create customers/purchase requests without holding those permissions.
3. **Cost/profit visible with `sales:read` (MEDIUM).** Order payloads include `cost_total`; the cashier role holds `sales:read`.
4. **Insecure defaults (MEDIUM).** `SECRET_KEY=change-me-in-production` and admin `admin1234` are accepted in production; no startup refusal.
5. **API keys (MEDIUM).** No scopes, expiry or rate limit; a key has all powers of its creator.
6. **No rate limiting (MEDIUM)** except login lockout and public portal/shop limits.
7. **Portal links never expire (LOW/MEDIUM).**
8. **Token in localStorage (LOW)** — acceptable with no XSS, but an httpOnly cookie is safer.
9. **Excel export formula injection (LOW).** Cells starting with `=`, `+`, `-`, `@` are written as-is.
10. **Impersonation start not audited (LOW).** Actions during it are labelled "(platform admin)", but the entry itself is not logged.

## 4. Architectural issues

- **Scheduler inside the web process**: with more than one worker every job runs N times. Needs a single scheduler (separate process or a DB lock) before scaling.
- **Two schema mechanisms** (`migrate.sync_schema` + Alembic). From now on schema changes go through Alembic migrations; `sync_schema` stays as a safety net for local SQLite.
- **Ledger is rebuilt from documents** (auto entries regenerated). Correct and simple, but period locking (P5) must lock the source documents, not only journal lines.
- Permission strings are coarse and colon-style (`sales:read`); the spec wants dot-style granular ones → add new ones and map old → new, never rename in place (backward compatibility).

## 5. Required changes (overview, per phase — detailed when each phase starts)

| | Database | API | Frontend |
|---|---|---|---|
| P2 tenant | none | central FK-ownership guard; point fixes | none |
| RBAC | permission catalogue, role scopes (warehouse) | granular checks, hide cost fields | permission-aware UI, role editor |
| Approvals | `approval_requests`, `approval_rules` | generic approve/reject | rules page, approval center |
| Audit | `ip`, `user_agent`, `reason` on `audit_logs` | filters | filters UI |
| Period lock | `accounting_periods` | close/reopen, write guard | periods page |
| Costing / transfers / returns | cost layers, transfer docs, stock states | workflows | screens |
| Billing / health / observability | subscriptions, usage records, job runs | admin endpoints | admin pages |

## 6. Tests

Existing (29): business flow, permissions (1 test), tenant isolation (2 tests), ERP flows, platform admin, advanced features.
Missing: systematic cross-tenant attack tests (every route, body ids, files, exports, AI), permission matrix tests, period lock, costing, backup restore, frontend tests.

## 7. Plan for Phase 2 (multi-tenant security)

1. Automated attack suite: two companies with a full data set each; every route with a path id is called with the other company's ids; body ids, query ids, files, exports, reports, AI tools, public links and API keys are attacked explicitly.
2. **Central guard (design change, explained):** a SQLAlchemy `before_flush` check that every foreign key on a tenant row points to a row of the same company. It closes finding #1 for all current and future endpoints at once. No schema change, no API change; a violation returns 404 "not found" (same as an unknown id, so it reveals nothing).
3. Point fixes where the guard alone is not enough (the purchase-order 500, AI tool permissions).
4. Run all tests + build; report.

---

# Phase 2 — Multi-tenant security: results (2026-09-27)

**Attack suite** `backend/tests/test_tenant_security.py` (9 tests): company B holds one of almost every record type (names marked `ZZB`); company A attacks every route with an id in its path (41 routes), 64 request bodies carrying B's ids, every GET route with B's ids in its query parameters and `q=ZZB`, files, Excel exports (unzipped), reports, accounting statements, AI tools and `/ai/ask`, API keys, portal/invoice links, webhooks and background jobs. A final scan checks that no row in the whole database points at another company's row.

**Found**
- Reads by id, search, exports, reports, files, AI tools, API keys, public links, webhooks, jobs: no leak.
- 19 create/update requests stored another company's ids (customer price list / sales rep / branch, expense supplier / branch, user / warehouse / employee branch, employee user, task assignee / customer, visit order, attachments on another company's record). The price-list case leaked the other company's prices through `/sales/quote`.
- AI tools ignored the user's permissions; the model could invoke any method of the toolbox.

**Fixed**
- `app/core/tenant_guard.py` (new): before every flush, every id on a tenant row must point to a row of the same company (declared FKs + 6 undeclared id columns). Violation → 404 "… not found". Registered in `app/main.py` (+ exception handler) and `scripts/seed.py`.
- `app/api/ops.py`: attachments require the target record to exist in the caller's company.
- `app/services/ai_agent.py`, `app/api/ai.py`: each tool requires the same permission as its screen; only listed tools can run (`run_tool`); denied tools answer with an error message.
- `tests/conftest.py`: the suite refuses to run (and drop tables) unless the database is `./test_bizos.db`.

**Database changes:** none. **API changes:** requests with another company's ids now get 404 instead of being accepted.

**Tests:** 38 passed (29 existing + 9 new). A mutation run with the guard switched off made the new body/scan tests fail, so they do detect the problem.

**Not verified:** frontend production build (no frontend file changed; `tsc` passes), manual API checks against the live local server (the server is stopped — see incident below).

**Incident:** while verifying the tests, a helper script loaded the app before the test settings, so the suite's `drop_all` ran against the local database `%LOCALAPPDATA%\BizOS\data\bizos.db`. Its tables are gone. A copy of the emptied file is at `bizos-DAMAGED-20260927.db`. The intact copy `backend/bizos-OLD-moved-to-AppData.db` (2026-09-26 22:42, 727 orders, integrity ok) holds all business data; differences found are regenerated system data (ledger, alerts, login events) plus three demo settings made today. The conftest guard above prevents a repeat.
