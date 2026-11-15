# DSD (Direct Store Delivery) on Odoo — Implementation Plan

- **Date:** 2026-11-15 · **Target stack:** Odoo 20.0 Community, Docker (`~/odoo-docker`),
  database `odoo` (demo data on)
- **Progress:** Phase 0–5 delivered 2026-11-15 — routes/stops (1), route days,
  visits & generation wizard (2), van load-out / delivery / returns with POD (3),
  van sales + presales with cash collection (4), and end-of-day settlement with
  cash-variance posting + settlement sheet PDF (5). 18/18 tests green. Live
  smoke: `RD/2026/0004` fully settled — expected 100, counted 95, variance
  entry `RCASH/2026/00001`. Remaining: Phase 6 (responsive pass, dashboards)
  and Phase 7 (UAT/rollout).
- **Companion ADRs:** [001 build on standard apps](adr/ADR-001-build-on-odoo-standard-apps.md) ·
  [002 van = stock location](adr/ADR-002-van-as-stock-location.md) ·
  [003 route & visit models](adr/ADR-003-route-and-visit-model.md) ·
  [004 van sales without POS](adr/ADR-004-van-sales-without-pos.md)

## 1. Goal

Run the SAP-style DSD van-sales loop natively in Odoo:

**Route planning → van load-out → store visits (deliver, van-sell, returns,
cash collection) → end-of-day settlement (cash + stock reconciliation).**

### In scope (v1)
- Route templates and daily route runs with ordered stops
- Van = internal stock location + `fleet.vehicle` (`stock_fleet`)
- Load-out / end-of-day stock return as internal transfers
- Per-visit: delivery from van, one-click van sale (picking + invoice + cash
  payment), presale orders, returns/empties to van
- Settlement wizard: cash reconciliation + van stock count + variance posting
- Mobile-friendly (responsive web) stop screen; barcode input via `barcodes`

### Out of scope (v1)
- Route optimization / geo navigation (fields reserved)
- Native mobile app (Odoo API integration later if needed)
- Vehicle capacity planning, cold-chain/telemetry
- Multi-company DSD (single company: YourCompany / WH)

## 2. Reference flow mapping (SAP DSD → Odoo)

| SAP DSD (IS-Retail) | Odoo 20 implementation |
|---|---|
| Visit plan / route template | `dsd.route` + ordered `dsd.route.stop` |
| Visit list generation (`/DSD/VC_GEN`) | "Generate Route Day" wizard (`dsd.route.day`) |
| Vehicle load-out | internal transfer `stock.picking` WH/Stock → van location |
| Tour execution | `dsd.route.day` state `in_progress`; stops in sequence |
| Visit: delivery + POD | `stock.picking` (van → customer), signature attachment |
| Van sale: invoice + cash on the spot | `sale.order` (van sale) → posted `account.move` + `account.payment` |
| Presales order | standard `sale.order`, delivery from warehouse |
| Returns / empties | return `stock.picking` (customer → van); empties as storable products (lots) |
| Route settlement | `dsd.settlement` wizard: cash recon, stock count, variance posting |

## 3. Module design (Odoo guideline compliant)

One namespace, phased modules (each independently installable):

```
dsd_core/                    # phase 1–2: foundations, routes, visits
dsd_sale/                    # phase 3–4: van sales, presales, returns
dsd_settlement/              # phase 5: end-of-day reconciliation
```

Standard layout inside each module (per Building-a-Module docs):

```
dsd_core/
├── __init__.py
├── __manifest__.py          # version "20.0.1.0.0", depends: ['stock', 'stock_fleet', 'sale_management', 'account']
├── security/
│   ├── dsd_security.xml     # groups: dsd.group_dsd_user, dsd.group_dsd_manager
│   └── ir.model.access.csv  # loaded FIRST in manifest data list
├── models/
│   ├── dsd_route.py         # dsd.route, dsd.route.stop
│   ├── dsd_route_day.py     # dsd.route.day, dsd.visit
│   └── stock_location.py    # _inherit: van flag on locations
├── wizard/
│   └── dsd_route_day_generate.py
├── views/
│   ├── dsd_route_views.xml  # form/list/kanban; xpath-inherited stock/sale views
│   └── dsd_menus.xml
├── data/                    # sequences (route day ref), demo-friendly records
├── demo/                    # demo route + stops (uses existing demo partners)
└── tests/
    ├── test_dsd_route.py    # TransactionCase, @tagged('post_install','-at_install')
    └── test_dsd_visit.py
```

Guidelines applied throughout: **inherit, never modify core**; views extended via
`xpath` (no copied XML); ORM-first (no raw SQL except reporting SQL views);
snake_case fields, `field.help` strings; access rights least-privilege (drivers =
`dsd_user`, supervisor = `dsd_manager` + record rules scoping visits to own route);
`res.config.settings` for DSD defaults (cash journal, settlement variance account).

### Key model fields (summary)

- `dsd.route`: `name`, **`mode`** (`presale` / `van_sales` / `mixed` — restricts
  the actions offered on the visit screen; `mixed` allows any combination per
  stop), `warehouse_id`, `vehicle_id`, `van_location_id` (required when mode ≠
  `presale`), `driver_id` (res.users), `stop_ids` (1..n `dsd.route.stop`:
  `partner_id`, `sequence`, `mon..sun` weekday flags)
- `dsd.route.day`: `route_id`, `date`, `driver_id`, `vehicle_id`, `state`
  (draft/loaded/in_progress/done/settled), `load_picking_id`,
  `settlement_id`, `visit_ids`
- `dsd.visit`: `route_day_id`, `partner_id`, `sequence`, `state`
  (pending/done/skipped+reason), `sale_order_id`, `delivery_id`, `invoice_id`,
  `payment_ids`, `return_id`, `signature` (binary attachment)
- `dsd.settlement`: `route_day_id`, `counted_cash`, `expected_cash`,
  `cash_diff`, `counted_move_ids` (stock snapshot lines), `stock_diff_moves`,
  `variance_journal_entry_id`, `state`

## 4. Phases & estimates

| # | Phase | Deliverables | Est. |
|---|---|---|---|
| 0 | **Prereqs** | install `fleet`, `stock_fleet` (present in Community image); verify demo warehouse; create `WH/Vans/VAN-01` location + vehicle | 0.5 d |
| 1 | **dsd_core scaffold** | module skeleton, security groups, menus, van location flag, route model + views, demo route | 3 d |
| 2 | **Route day & visits** | generation wizard, route day kanban/list, stop sequencing, visit screen shell (read-only links) | 5 d |
| 3 | **Load-out & deliveries** | one-click load transfer WH→van; visit "Deliver" (picking van→customer, validate, signature attach); end-of-day stock return draft | 4 d |
| 4 | **Van sale & presale** | one-click van sale (SO → validate picking → post invoice → register cash payment); presale order from visit; returns/empties picking | 6 d |
| 5 | **Settlement** | wizard: expected vs counted cash; van stock snapshot & diff; variance journal posting; route day → `settled`; PDF settlement sheet | 5 d |
| 6 | **Mobile & reporting** | responsive pass on visit screen; barcode quick-entry on products; DSD dashboard (sales/cash/returns per route day); unit + integration tests complete | 5 d |
| 7 | **UAT & rollout** | script on demo DB (2 routes × 6 stops), driver-UX walkthrough, backup + restore drill, go-live | 4 d |

Total ≈ **7–8 weeks** single developer; phases 1–3 deliver a usable
"route + delivery" pilot (~3 weeks).

## 5. Testing & quality gates

- **Unit tests** per model (Odoo `TransactionCase`), run in CI container:
  `docker compose run --rm odoo odoo -d test_dsd -i dsd_core --test-enable --stop-after-init`
- **Integration test**: full loop — generate route day → load → 3 visits
  (delivery, van sale, return) → settle → assert stock, cash journal, AR ledger
- **Guideline checklist per PR**: no core edits (`git diff` touches only
  `dsd_*`), access csv present, demo data loads, tests tagged & green
- Acceptance per phase defined in each phase's ticket set (created at kickoff)

## 6. Deployment workflow (this environment)

1. Develop modules in `~/Projects/Odoo/src/dsd_*`; mount or copy into
   `~/odoo-docker/addons/` (already volume-mounted at `/mnt/extra-addons`).
2. Restart with update:
   `cd ~/odoo-docker && docker compose restart odoo` then
   Apps → Update Apps List (dev mode) → install/upgrade `dsd_*`; or headless:
   `docker compose run --rm odoo odoo -d odoo -u dsd_core,dsd_sale,dsd_settlement --stop-after-init`
3. DB backups before each upgrade:
   `docker exec odoo-db pg_dump -U odoo odoo > ~/odoo-docker/backups/odoo_$(date +%F).sql`

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Driver UX friction on web client | Phase 6 dedicated responsive pass; one-click actions; barcode entry |
| Cash variance disputes | Settlement sheet PDF + signature; daily reconciliation mandatory before route close |
| Lot/serial tracking overhead for empties | Start lot-free; enable lots per product only where legally required |
| Scope creep toward route optimization | Explicitly out of scope; lat/long reserved for later integration |
| Odoo upgrades breaking inherited views | xpath with minimal anchors; tests include view-inheritance smoke test |

## 8. References

- Odoo dev docs: [Building a Module](https://www.odoo.com/documentation/20.0/developer/tutorials/backend.html),
  [Module Manifests](https://www.odoo.com/documentation/20.0/developer/reference/backend/module.html)
- SAP DSD reference flow: [DSD Tour scenario (SAP Help)](https://help.sap.com/docs/SAP_ERP/c8601cd6b4574cdbb497e366b86114e2/5077b65334e6b54ce10000000a174cb4.html),
  [DSD visit planning/settlement overview](https://www.linkedin.com/posts/diyar-kalkan_sapdsd-vansales-presales-activity-7326488201731137536-jQcb)
- OCA precedent for vehicle–stock linkage: [stock_fleet_delivery_driver](https://apps.odoo-community.org/modules/stock_fleet_delivery_driver)
