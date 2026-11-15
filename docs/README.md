# Odoo DSD Project Docs

Direct Store Delivery system planned on top of the running Odoo 20 Community
instance (Docker at `~/odoo-docker`, database `odoo`).

- [DSD Implementation Plan](dsd-implementation-plan.md) — scope, SAP→Odoo flow
  mapping, module design, phases, testing, deployment, risks
- ADRs:
  - [ADR-001 Build on Odoo standard apps with custom modules](adr/ADR-001-build-on-odoo-standard-apps.md)
  - [ADR-002 Van as internal stock location + fleet vehicle](adr/ADR-002-van-as-stock-location.md)
  - [ADR-003 Custom route and visit models](adr/ADR-003-route-and-visit-model.md)
  - [ADR-004 Van sales without POS](adr/ADR-004-van-sales-without-pos.md)

Custom modules will live in `src/` (`dsd_core`, `dsd_sale`, `dsd_settlement`)
and deploy through the `~/odoo-docker/addons` volume (`/mnt/extra-addons`).
