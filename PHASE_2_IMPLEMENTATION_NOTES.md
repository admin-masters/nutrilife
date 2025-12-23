# Phase 2 implementation notes (updated code bundle)

This code bundle extends the existing Phase 1 platform with the missing flows for:

- **Low‑income verification** at the school before forwarding applications to SAPA
- **Grant funding** (grantors → SAPA) with optional allocation during SAPA approvals
- **Fulfillment / logistics** flows (production orders, shipments to schools, dispatch & delivery confirmation)

> Everything is implemented as normal Django apps (models, migrations, basic HTML screens) and is compatible with the existing Phase 1 flows.

## What changed

### 1) Program fixes

- **Fixed `MonthlySupply.bootstrap_for_enrollment()`** so it creates 6 monthly supplies instead of mistakenly creating milestones.
- **Milestone completion signal** now completes **DUE + OVERDUE** milestones when a screening is recorded (so suspended schools can be unsuspended).

### 2) Assist (applications)

- Added fields to `assist.Application`:
  - `trigger_screening`
  - `low_income_declared`
  - `income_verification_status` (`PENDING` | `VERIFIED` | `REJECTED`)
  - `income_verified_at`, `income_verified_by`, `income_verification_notes`
- Added school admin actions:
  - Verify income
  - Reject income
- **Forwarding to SAPA** now only forwards apps that are **low‑income declared + income verified**.

### 4) Fulfillment app

New Django app: `fulfillment`

- `ProductionOrder`
- `SchoolShipment` and `ShipmentItem` (maps to `program.MonthlySupply`)
- Screens:
  - `/fulfillment/` (Inditech/SAPA dashboard)
  - Manufacturer portal: `/fulfillment/manufacturer/production-orders`
  - Logistics portal: `/fulfillment/logistics/shipments`
  - School view: `/fulfillment/school/shipments`

## Database migrations

This bundle includes new migrations:

- `grants/migrations/0001_initial.py`
- `fulfillment/migrations/0001_initial.py`
- `assist/migrations/0003_application_income_verification_and_grants.py`

## Deploy / run instructions

1. Unzip this bundle and install backend dependencies as you already do.
2. Ensure the new apps are in `INSTALLED_APPS` (already done in this bundle):
   - `grants`
   - `fulfillment`
3. Run migrations:

```bash
cd nutrilift/backend
python manage.py migrate
```

4. (Optional) Enable grant bookkeeping by setting:

```bash
export NUTRILIFT_GRANT_COST_PER_ENROLLMENT="<amount>"   # e.g. "1500"
```

If the value is `0` or unset, approvals will not be blocked by grant funds.

5. Create organizations & memberships (via Django admin) for:

   - SAPA (`Role.SAPA_ADMIN`, optionally `Role.SAPA_PGC`)
   - Inditech (`Role.INDITECH`)
   - Manufacturer org (`Role.MANUFACTURER`)
   - Logistics org (`Role.LOGISTICS`)
   - Grantors (optional `Role.GRANTOR`)
6. Workflow recap

- Teacher screens, red‑flagged + low‑income students trigger parent link.
- Parent applies.
- School admin verifies income (required), then forwards to SAPA.
- SAPA approves in batches, optionally selecting an active grant.
- Inditech creates shipments for schools/months; logistics dispatches; logistics or school confirms delivery.
