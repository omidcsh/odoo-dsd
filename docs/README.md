# Odoo DSD Project Docs

Direct Store Delivery on Odoo 20 Community (Docker at `~/odoo-docker`, database `odoo`).
**Status: PLAN v2 — Phase 0 delivered (2026-11-16)** — new module `src/dsd` installed
on the dev DB with demo data, 22/22 tests green on clean install. The old `dsd_core`
prototype is fully removed (DB uninstall + code delete). Next: Phase 1 (Visit Control).

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

Module: **`src/dsd`** — Phase 0 scope delivered: DSD master data (routes with capacity
limits, drivers on hr.employee, vans with auto-managed stock locations, counting groups,
aggregation categories, tolerance types/groups, reason catalogs, license categories,
lock periods), security groups (user/dispatcher/driver/supervisor/settlement/manager),
company settings incl. settlement accounts, demo dataset. Phase 1 adds visit plans,
lists and appointments. Deployed through the `~/odoo-docker/addons` volume
(`/mnt/extra-addons`).

