# Plan — Sales Area (first feature, new module)

**Date:** 2026-11-18 · **Branch:** `feature/new-module` · **Status:** awaiting decisions §7

Adds the SAP SD **sales area** concept (VKORG/VTWEG/SPART trio) as the first
feature of the new module. Sources: package `odoo/modules/M01-SD-FOUNDATION`
§3.1–3.2, `odoo/11-IMPL-dsd_core` §2.7, `mobile/mse-object-registry.csv`
(MSE_CUSTOMER_SA = 32 fields, MSE_CUSTOMER_PF), agent-notes 04 §6.

## 1. Odoo-native survey (rule: standard first) — verdict: **no native twin**

Surveyed Odoo 20E source (`odoo/addons`). SAP sales area is a *determination
key* (pricing/route/visit identity), not a reporting axis — nothing in core
carries it:

| Odoo 20 native | What it is | Fits sales area? | Use |
|---|---|---|---|
| `res.company` | separate ledger/sequences | ✗ too heavy; only if SAs must stay legally separate (01-FOUNDATION: multi-company **only then**) | no (single company) |
| `crm.team` (`team_id` on sale.order) | single sales-team dimension, pipeline/reporting | ✗ one flat axis, not a 3-part key | maybe later for `ZTB_DSD_SAL_TEAM` (M01 §2.5, unconfirmed) |
| `account.analytic.plan` + distribution | multi-dim reporting on accounting lines | ✗ reporting only, no document determination | no |
| `res.partner.category` | tags | ✗ no uniqueness/semantics | no |
| `stock.warehouse` | warehouse/plant | ✓ native twin of **PLANT/Werks** | reuse: `plant_id` m2o |
| `product.pricelist` (in `product` addon) | pricelist | ✓ native twin of **PRC_LIST** | reuse: `pricelist_id` m2o |
| no `sales_area`/`sales_org` model anywhere in addons | — | — | custom model required |

Matches the package's own verdict (01-FOUNDATION: "SAP areas have no Odoo
twin; keep as classification fields") — but native `stock.warehouse` and
`product.pricelist` replace two of the spec's "passthrough char" columns with
proper m2os (improvement, wire-emitter maps id→code later).

## 2. Design

### 2.1 New model `dsd.partner.sales.area` (in new module, models/)

One row per **(partner, sales_org, dist_channel, division)** — the device's
visit-identity triple (agent-notes 04, implication 4).

**Key & identity**
- `partner_id` m2o res.partner, required, ondelete cascade
- `sales_org` / `dist_channel` / `division` char(4), required (SAP codes)
- SQL unique: `(partner_id, sales_org, dist_channel, division)`
- `name` computed: `{partner} / {org}/{chn}/{div}`
- `active` boolean default True — `active=False` ⇒ row leaves the download
  entirely; **separate from blocks** (atlas requirement, M01 §3.2)

**Blocks (≠ inactive)** — suppress document *creation*, row still emitted:
- `sale_block` / `delivery_block` / `billing_block` boolean
- `sale_block_reason` / `delivery_block_reason` / `billing_block_reason` char
  (wire `SALE_BLOCK2/DELV_BLOCK2/BILL_BLOCK2`)

**Partner functions per SA** (MSE_CUSTOMER_PF):
- `payer_id` / `sold_to_id` / `ship_to_id` / `bill_to_id` m2o res.partner
  (default = parent partner via onchange, not required)

**Native-reuse columns**
- `plant_id` m2o `stock.warehouse` (wire `PLANT`)
- `pricelist_id` m2o `product.pricelist` (wire `PRC_LIST`)

**Pricing/logistics passthrough (wire columns, consumed by M03/M02 later)**
- `price_group`, `customer_group`, `customer_group2..5`, `customer_pricing_procedure`,
  `customer_proposal_id`, `pay_code`, `collect_type`, `invoice_payer` (char)
- `payment_terms1..5` char (wire TERMS_OF_PAYMT1-5; native m2o
  `account.payment.term` rejected for now — wire has 5 slots, decide at M02)
- `is_cash_payer` boolean, `pod_inv` (PodInv), `check_zterm`, `message_type`,
  `company_code`, `emse_kalks`, `emse_vsort` (char/bool passthrough)

**Online-service flags stored per SA** (11-IMPL §2.4: onlinePricing, credit
check on/offline, ATP, due-open-items on/offline → `od_op, od_cco, od_ccon,
od_atp, od_doivo, od_doivon` boolean, default from customizing later)

**M01 planning columns** — `geofence` bool now; `route_id`, `calendar_id`,
`visit_frequency` **deferred** to the route/visit-plan feature (their models
don't exist yet).

### 2.2 `res.partner` extensions

- `sales_area_ids` o2m dsd.partner.sales.area
- `sales_area_count` computed, with **Sales Areas** tab on the partner form
  (Customer 360, M01 §3.6) — editable list/tree, form view for detail
- `x_sales_org/x_dist_channel/x_division` computed from **primary** (first
  active) SA — classification fields the compatibility filters will query
  (01-FOUNDATION mapping). Name prefix: see decision §7-D3.
- `sale_block_sales/delivery/billing` related from primary SA (list filtering)

### 2.3 Views & menu

- Partner form: new **Sales Areas** page (notebook) with the o2m
- Standalone list+form+search for SA (menu: DSD → Master Data → Sales Areas;
  top menu only if user wants an app icon)
- Search filters: blocked-for-sale / inactive / by sales org

### 2.4 Security (Odoo 20 format!)

- `security/ir.access.csv` — new header `id,name,model_id,group_id/id,operation,domain`,
  `model_id` = model **name** (`dsd.partner.sales.area`), operation codes
  (`crud` admin / `ru` officer / `r` user). No separate ir.rule files.
- Groups: `group_dsd_user` (read), `group_dsd_officer` (create/write), admin
  via base.group_system (revisit at M12 for the full role model).

### 2.5 Tests (OdooTransactionCase)

1. unique-trio constraint raises on duplicate row
2. blocks ≠ inactive semantics (block keeps row, inactive hides it — test on
   `search` domain helper used later by the emitter)
3. primary-SA compute + related block read-through
4. PF defaults (onchange fills payer/sold_to/ship_to/bill_to with parent)
5. AT-M01-08-flavored: partner with 2 SAs → both visible on form, primary =
   first active

## 3. Module bootstrap (this is feature #1 — skeleton comes with it)

- `src/<tech_name>/` with `__manifest__.py` (version 20.0.1.0.0, LGPL-3),
  `depends`: **`base`, `product`, `stock`** only (pricelist + warehouse come
  from there; `sale` joins when order ingest lands — lean base keeps the
  module publishable)
- models/, views/, security/, tests/ structure; icon placeholder

## 4. Explicitly out of scope (later features, do not build now)

- Wire emitter `MSE_CUSTOMER_SA/PF` assembly (→ compatibility module)
- Pricing consumption of price_group/customer_pricing_procedure (→ M03)
- Route determination key usage (→ M02 / FLOW-014)
- `crm.team` mapping for ZTB_DSD_SAL_TEAM (unconfirmed candidate)
- Customizing seed values (blocked on SAP export A-7)

## 5. Build order

1. Decide §7 → module name + branch rename
2. Skeleton + security groups
3. `dsd.partner.sales.area` model + constraint + computes
4. partner extensions + views + menu
5. tests → run: `./venv/bin/python -m odoo -c odoo.conf -d odoo -i <module> --test-enable --stop-after-init` (fresh test DB if wanted)
6. commit on `feature/new-module` (→ renamed branch)

## 6. Effort

One focused session (~half day) including tests. No DB/UI verification beyond
module install + form smoke via backend.

## 7. Decisions needed (blocking build start)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Module technical name | (a) `dsd_core` per package specs · (b) fresh name for the publishable product (e.g. `dsd_sale` suite root) | **(a)** — every IMPL doc references it; rename later is cheap, doc drift is not |
| D2 | Multi-SA at go-live | model supports N; seed demo with 1 or 2 SAs per partner? | 2 in demo (exercises the machinery), production = Solico's real count |
| D3 | Partner-field naming | (a) `x_` prefix as IMPL docs do · (b) clean `dsd_`-names since this module will be published | **(b)** clean names + comment linking the IMPL `x_` name for cross-referencing |
| D4 | payment_terms1..5 | char passthrough now vs account.payment.term m2o | char now (wire has 5 slots; Odoo has 1 field — revisit at M02/M07) |
