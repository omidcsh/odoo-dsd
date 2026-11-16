# Odoo DSD Project Docs

Direct Store Delivery on Odoo 20 Community (Docker at `~/odoo-docker`, database `odoo`).
**Status: PLAN v2 — Phases 0–4 delivered (2026-11-16)** — module `src/dsd` installed on
the dev DB with demo data, **89/89 tests green** on clean install, and the Phase 4 live
smoke passed the full driver loop as a real driver login (console → tour → stop → van
sale + auto-invoice → cash collection reconciled → paid → reload → check-in → stats).
Delivered so far: master data & security (0), visit control (1), tour preparation on
`stock.picking.batch` with van isolation (2), tour execution — loading confirmation,
check-out/in custody counts, reload, unload (3), driver console v1 — OWL UI, JSON API,
assortment + deal conditions, credit gate, customer statistics (4). Next: Phase 5
(settlement engine: difference determination, final settlement run, collection clearing).

- [DSD Implementation Plan v2](dsd-implementation-plan.md) — capability ledger (SAP→Odoo,
  build/simplify/defer/exclude), data model specs, tour/visit/settlement engines, driver
  console, phases 0–8 with acceptance criteria, traceability matrix
- [UAT Plan](uat-plan.md) — *prototype-cycle artifact; to be rewritten in Phase 8*
- [Operations Runbook](runbook.md) — backup/restore & clean-install drills still valid
  (commands reference `dsd`, not `dsd_core`, from now on); refresh in Phase 8

ADRs (historical, from the prototype cycle; superseded where they conflict with plan v2
ADR-101+ log inside the plan):
- [ADR-001 Build on Odoo standard apps with custom modules](adr/ADR-001-build-on-odoo-standard-apps.md)
- [ADR-002 Van as internal stock location + fleet vehicle](adr/ADR-002-van-as-stock-location.md)
- [ADR-003 Custom route and visit models](adr/ADR-003-route-and-visit-model.md)
- [ADR-004 Van sales without POS](adr/ADR-004-van-sales-without-pos.md)

Module: **`src/dsd`** — Phases 0–1 delivered: DSD master data (routes with capacity
limits, drivers on hr.employee, vans with auto-managed stock locations, counting groups,
aggregation categories, tolerance types/groups, reason catalogs, license categories,
lock periods), security groups (user/dispatcher/driver/supervisor/settlement/manager),
company settings incl. settlement accounts, demo dataset, plus visit control
(plan types, plans, lists, appointments, generation wizard, order proposals).
Phase 2 adds tours on `stock.picking.batch`; Phase 3 the execution loop (loading
confirmation, check-out/in, reload, unload, odometer, status timeline); Phase 4 the
driver console (OWL UI at `/dsd/console`, `/dsd/api/v1/*` JSON endpoints, assortment +
deal-condition enforcement at van sales, credit-gated auto-invoicing, cash collection
with reconciliation fallback, unplanned stops/resequencing, expenses, van adjustments,
checks, reload requests, customer×product statistics). Deployed through the
`~/odoo-docker/addons` volume (`/mnt/extra-addons`).

