# CI regression fixes

The first public CI run found five failing tests (38 passed). The fixes address
the underlying behavior and extend the test suite; no tests are skipped or
removed to obtain a green result.

- Field visits accept the documented `no_answer` outcome. The field-sales UI
  includes it with an Arabic label; invalid outcomes are still rejected.
- Stock-transfer workflows use `/api/inventory/transfers`. They previously
  shadowed the cash/bank `POST /api/transfers` route, causing valid financial
  transfers to fail validation. Cash/bank clients retain their existing route;
  warehouse-transfer API clients should use the inventory namespace.
- Branch reports aggregate tenant-scoped orders before joining branches. This
  removes an invalid forward table reference in SQLite and avoids counting an
  order multiple times when a branch has several warehouses. Explicit order
  branches take precedence over the warehouse fallback; empty branches remain.
- Assigning a paid plan to a previously unlimited/free subscription starts a
  first billable period. Repeated billing does not duplicate the invoice.
  Explicit administrator end dates and existing prepaid periods are preserved.
- The tenant attack suite now supplies real foreign-tenant notifications,
  warehouse transfers, saved reports, AI drafts and import batches. Natural keys
  such as accounting months and provider names are checked separately using the
  same key in two companies, rather than treated as globally unique record IDs.
  The provider test mocks delivery and sends no external message.

Local verification: **52 backend tests passed**, TypeScript `--noEmit` passed,
and the production frontend build passed. Regression coverage includes the full
warehouse transfer lifecycle, independent cash balances, duplicate-route
detection, branch aggregation, billing idempotency and tenant isolation.

Tests use only the dedicated disposable `test_bizos.db`; the fixture refuses the
application database. No application data, real credentials or uploads are used.
The same fixes are mirrored to the original local source without replacing its
configuration or database. GitHub Actions validates the pushed commit separately.

Existing datetime/dependency deprecation warnings remain. npm also reports a
security warning for the pinned Next.js 14.2.15 dependency; this change does not
claim a dependency security audit or change framework versions. No production
deployment is performed.
