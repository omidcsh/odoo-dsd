# Plan — Sales Area (first feature, new module)

**Date:** 2026-11-18 · **Branch:** `feature/new-module` · **Status:** scope
narrowed to v2-minimal (user: «فقط sales area») — ready to build

Adds the SAP SD **sales area** concept (VKORG/VTWEG/SPART trio) as the first
feature of the new module. Sources: package `odoo/modules/M01-SD-FOUNDATION`
§3.1–3.2, `odoo/11-IMPL-dsd_core` §2.7, `mobile/mse-object-registry.csv`
(MSE_CUSTOMER_SA = 32 fields, MSE_CUSTOMER_PF), agent-notes 04 §6.

## 0. Build scope v2.1 — ONLY sales area, nothing else

**In (the whole build):**
1. Module skeleton `src/dsd_core/` (manifest, depends `base, product, stock`,
   security groups, ir.access.csv — Odoo 20 format)
2. **Three master catalogs** (m2o targets, back-office integrity; the trio is
   the join key across dozens of wire objects — free text would rot):
   `dsd.sales.org` / `dsd.distribution.channel` / `dsd.division`
   (each: `code` char(4) unique + `name` + `active`)
3. **`dsd.sales.area` — the valid-combination entity** (SAP TVTA equivalent):
   m2o trio, all required, SQL `unique(sales_org, dist_channel, division)`,
   `name` compute, `active`. Future home of the 68-field
   `MSE_CUST_SALES_AREA` customizing flags (deferred).
4. **`dsd.partner.sales.area` — the relationship row** (customer × sales area):
   `partner_id` m2o + `sales_area_id` m2o dsd.sales.area (both required) +
   SQL `unique(partner_id, sales_area_id)` + `active` + `name` compute
5. Blocks on the relationship row: `sale/delivery/billing_block` bool + 3
   reason chars
6. Partner functions per SA: `payer_id / sold_to_id / ship_to_id / bill_to_id`
   m2o res.partner, default = parent partner (onchange)
7. Native reuse: `plant_id` m2o stock.warehouse, `pricelist_id` m2o
   product.pricelist
8. `res.partner`: `sales_area_ids` o2m + **Sales Areas** tab (tree+form),
   primary-SA computed read fields (`dsd_sales_org/dist_channel/division`,
   via primary SA → combo), related block booleans for filtering
9. Config menu: DSD → Configuration (Sales Areas, Sales Orgs, Distribution
   Channels, Divisions)
10. 6 tests (combo unique, partner-SA unique, block≠inactive, primary compute,
    PF defaults, 2-SA view)

Evidence for v2.1 (user question 2026-11-18: "are the sales org, distribution
channel, division … relationship?"): registry `MSE_CUST_SALES_AREA`
(CustomizingSalesAreaBO, NON_OCS, 68 fields keyed on the trio — order/
delivery/collection permissions, OD_* online flags, reason-mandatory flags)
and the trio as join key in `MSE_CUSTOMER_SA/PF`, `MSE_DEALCOND_ASGN`,
`MSE_EMPTIES_BALANCE`, `MSE_CRM_*`, campaigns. Char trio ⇒ no integrity, and
the combo-with-settings entity is a wire obligation anyway.

**Out — deferred (add later via module upgrade; adding columns needs no
migration, so deferring is free):**
- All wire passthroughs: payment_terms1-5, pay_code, collect_type,
  invoice_payer, is_cash_payer, pod_inv, check_zterm, message_type,
  company_code, price_group, customer_group(+2-5), emse_kalks, emse_vsort —
  join when the compatibility emitter needs them
- LORD online flags OD_*, geofence, route/calendar/visit_frequency links
- Demo data, standalone DSD menus/app icon, emitter, `crm.team` mapping
- Pricing: per D5, Odoo-native pricelist only (already minimal)

**Defaults taken (veto with one word, otherwise final):**
- D1 → module name **`dsd_core`** (package specs reference it everywhere)
- D2 → **no demo data** in this slice
- D3 → **clean field names** (no `x_` prefix; comments link IMPL names)

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

### 2.0 Master catalogs + valid-combination entity

`dsd.sales.org` / `dsd.distribution.channel` / `dsd.division`: `code` (unique,
the SAP code emitted on the wire), `name`, `active`. Simple list/form each,
Configuration menu.

`dsd.sales.area` (TVTA-equivalent combo): m2o to the three catalogs (required)
+ SQL `unique(sales_org_id, dist_channel_id, division_id)` + `name` computed
`{org.code}/{chn.code}/{div.code}` + `active`. Settings (the 68 customizing
fields of MSE_CUST_SALES_AREA) attach here when the emitter feature lands —
the entity exists now so they have a home.

### 2.1 `dsd.partner.sales.area` — the relationship row (in new module, models/)

One row per **(partner, sales-area combo)** — the device's visit-identity
triple arrives via the combo (agent-notes 04, implication 4).

**Key & identity**
- `partner_id` m2o res.partner, required, ondelete cascade
- `sales_area_id` m2o `dsd.sales.area`, required, ondelete restrict
- SQL unique: `(partner_id, sales_area_id)`
- `name` computed: `{partner} — {combo name}`
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
- `pricelist_id` m2o `product.pricelist` (wire `PRC_LIST`). Primary-SA pricelist
  syncs to `res.partner.property_product_pricelist` so Odoo-native orders price
  from it automatically (decision D5, 2026-11-18: **use Odoo pricing**).

**Deferred fields (§0) — not in this build:** pricing keys (KONDA/KVGR1-5/
KALKS/VSORT), payment_terms1-5, pay_code, collect_type, invoice_payer,
is_cash_payer, pod_inv, check_zterm, message_type, company_code, OD_* online
flags, geofence, route/calendar/visit_frequency. All join later via plain
module upgrade (new columns, no migration).

**Architecture note (recorded, D5):** the custom condition-technique parity
engine (`dsd_pricing`, Phase 6) is **not built**. Device computes offline;
uploads accepted as-priced; Odoo-native orders and LORD price answers use
`product.pricelist`. Package invariant #3 consciously relaxed to "each engine
in its own domain".

### 2.2 `res.partner` extensions

- `sales_area_ids` o2m dsd.partner.sales.area
- `sales_area_count` computed, with **Sales Areas** tab on the partner form
  (Customer 360, M01 §3.6) — editable list/tree, form view for detail
- `dsd_sales_org / dsd_dist_channel / dsd_division` computed (char codes)
  from the **primary** (first active) SA → combo → catalog code — the
  classification fields compatibility filters will query later (01-FOUNDATION
  mapping; clean names per D3)
- `dsd_sale_block / dsd_delivery_block / dsd_billing_block` related from
  primary SA (list filtering)

### 2.3 Views

- Partner form: new **Sales Areas** notebook page with the o2m (tree+form)
- Search filters on the SA list: blocked-for-sale / inactive / by sales area
- DSD → Configuration menu: Sales Areas (combo list), Sales Orgs,
  Distribution Channels, Divisions — simple list/form, admin-managed
- No top-level app/menu structure in this slice (arrives with tours etc.)

### 2.4 Security (Odoo 20 format!)

- `security/ir.access.csv` — new header `id,name,model_id,group_id/id,operation,domain`,
  `model_id` = model **name**, one row set per model (`dsd.sales.org`,
  `dsd.distribution.channel`, `dsd.division`, `dsd.sales.area`,
  `dsd.partner.sales.area`); catalogs (org/chn/div/combo) admin-only `crud`,
  relationship row `ru` officer / `r` user. No separate ir.rule files.
- Groups: `group_dsd_user` (read), `group_dsd_officer` (create/write), admin
  via base.group_system (revisit at M12 for the full role model).

### 2.5 Tests (OdooTransactionCase)

1. combo `dsd.sales.area` unique-trio constraint raises on duplicate
2. `dsd.partner.sales.area` unique(partner, sales_area) raises on duplicate
3. blocks ≠ inactive semantics (block keeps row, inactive hides it — test on
   `search` domain helper used later by the emitter)
4. primary-SA compute + related block read-through
5. PF defaults (onchange fills payer/sold_to/ship_to/bill_to with parent)
6. AT-M01-08-flavored: partner with 2 SA rows → both visible on form, primary
   = first active

## 3. Module bootstrap (this is feature #1 — skeleton comes with it)

- `src/dsd_core/` with `__manifest__.py` (version 20.0.1.0.0, LGPL-3),
  `depends`: **`base`, `product`, `stock`** only (pricelist + warehouse come
  from there; `sale` joins when order ingest lands — lean base keeps the
  module publishable)
- models/, views/, security/, tests/ structure; icon placeholder

## 4. Explicitly out of scope (later features, do not build now)

- All deferred fields of §0 (wire passthroughs, OD_* flags, planning columns)
- Wire emitter `MSE_CUSTOMER_SA/PF` assembly (→ compatibility module)
- Route determination key usage (→ M02 / FLOW-014)
- `crm.team` mapping for ZTB_DSD_SAL_TEAM (unconfirmed candidate)
- Customizing seed values (blocked on SAP export A-7)

## 5. Build order

1. Skeleton `src/dsd_core/` + security groups + ir.access.csv
2. `dsd.partner.sales.area` model + constraint + computes
3. partner extensions + partner-form tab + search views
4. tests → run: `./venv/bin/python -m odoo -c odoo.conf -d odoo -i dsd_core --test-enable --stop-after-init`
5. commit on `feature/new-module` (rename branch to `feature/dsd-core`)

## 6. Effort

One focused session (~half day) including tests. No DB/UI verification beyond
module install + form smoke via backend.

## 7. Decision log (nothing blocking — defaults final unless vetoed)

| # | Decision | Outcome |
|---|---|---|
| D1 | Module technical name | **`dsd_core`** (default taken — package docs reference it; rename before publish is the only cheap moment, flag again then) |
| D2 | Demo data | **none** in this slice |
| D3 | Partner-field naming | **clean names** (`dsd_*`), comments link IMPL `x_` names |
| D4 | payment_terms1..5 | deferred with the other wire fields (§0) |
| D5 | pricing engine | **Odoo native pricing** (user, 2026-11-18) — see §2.1 note |
| D6 | trio as chars vs master models | **models + relationships** (user question 2026-11-18): 3 catalogs + `dsd.sales.area` combo entity + `dsd.partner.sales.area` relationship row — evidenced by `MSE_CUST_SALES_AREA` 68-field customizing keyed on the trio (§0, §2.0) |
