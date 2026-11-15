# Odoo DSD Project Docs

Direct Store Delivery system built on Odoo 20 Community (Docker at
`~/odoo-docker`, database `odoo`). **Status: rollout-ready** — Phases 0–7
complete, 19/19 tests green, backup/restore and clean-install drills passed.

- [DSD Implementation Plan](dsd-implementation-plan.md) — scope, SAP→Odoo flow
  mapping, module design, phases, testing, deployment, risks
- [UAT Plan](uat-plan.md) — walkthrough script with acceptance criteria,
  driver UX checklist, exit criteria
- [Operations Runbook](runbook.md) — backup/restore drills (performed),
  clean-install verification, upgrade procedure, go-live checklist

ADRs:
- [ADR-001 Build on Odoo standard apps with custom modules](adr/ADR-001-build-on-odoo-standard-apps.md)
- [ADR-002 Van as internal stock location + fleet vehicle](adr/ADR-002-van-as-stock-location.md)
- [ADR-003 Custom route and visit models](adr/ADR-003-route-and-visit-model.md)
- [ADR-004 Van sales without POS](adr/ADR-004-van-sales-without-pos.md)

Custom modules: `src/dsd_core` (routes, route days, visits, van sales,
presales, settlement) — deployed through the `~/odoo-docker/addons` volume
(`/mnt/extra-addons`).
