# [Step 1 — DEV TASK] Sales Area entities (`dsd_core`)

> **Assigned to:** @developer — this is the **first development task** of the
> DSD-on-Odoo project. Work happens **in this repo**, on branch
> `feature/dsd-core`, one PR back to `main` when done.
> Master plan: #1 · Spec version: v2.1 (2026-11-18)

## Goal

Create an Odoo 20 module **`dsd_core`** that models the SAP SD **sales area**
structure (VKORG / VTWEG / SPART) as master data, so later DSD features
(routes, visits, tours, orders, the mobile wire gateway) can key off it.

- Odoo version: **20** (must also stay Community-compatible — no Enterprise
  modules in `depends`)
- Module path: `dsd_core/`, `version = '20.0.1.0.0'`, license **LGPL-3**
- `depends`: **`base`, `product`, `stock`** only
- Author/maintainer: Omid Shokri

## 1. Data model

### 1.1 Master catalogs (one each — same shape)

| Model | Meaning | SAP key |
|---|---|---|
| `dsd.sales.org` | sales organization | VKORG |
| `dsd.distribution.channel` | distribution channel | VTWEG |
| `dsd.division` | product division | SPART |

Fields: `code` Char (required, indexed, **unique** — SAP code, max 4 chars in
practice), `name` Char (required, translatable), `active` Boolean (default
True). `display_name` = `"{code} — {name}"`. Order by `code`.

### 1.2 `dsd.sales.area` — valid combination (SAP TVTA equivalent)

| Field | Type | Required | Notes |
|---|---|---|---|
| `sales_org_id` | m2o `dsd.sales.org` | yes | `ondelete='restrict'` |
| `dist_channel_id` | m2o `dsd.distribution.channel` | yes | `ondelete='restrict'` |
| `division_id` | m2o `dsd.division` | yes | `ondelete='restrict'` |
| `active` | Boolean | — | default True |

- SQL constraint: `unique (sales_org_id, dist_channel_id, division_id)`
- `company_id` m2o `res.company` (optional, default env company) — P0-9
- `display_name` computed: `"{org.code}/{chn.code}/{div.code}"` (e.g.
  `1000/10/01`)
- This entity is the future home of the per-area customizing flags (the 68
  fields of `MSE_CUST_SALES_AREA` in the SAP DSD mobile protocol) — **do not
  add them now**; just leave the entity.

### 1.3 `dsd.partner.sales.area` — customer × sales-area relationship

| Field | Type | Required | Notes |
|---|---|---|---|
| `partner_id` | m2o `res.partner` | yes | `ondelete='cascade'`, indexed |
| `sales_area_id` | m2o `dsd.sales.area` | yes | `ondelete='restrict'`, indexed |
| `is_primary` | Boolean | — | False | exactly one active primary per partner (constraint) — the deterministic "main" SA; replaces any first-row-by-id assumption (review P0) |
| `company_id` | m2o `res.company` | — | env company | multi-company anchor added now to avoid a breaking change later |
| `active` | Boolean | — | default True |
| `sale_block` / `delivery_block` / `billing_block` | Boolean | — | document blocks |
| `sale_block_reason` / `delivery_block_reason` / `billing_block_reason` | Char | — | shown only when the matching block is set |
| `payer_id` / `sold_to_id` / `ship_to_id` / `bill_to_id` | m2o `res.partner` | — | partner functions |
| `plant_id` | m2o `stock.warehouse` | — | wire `PLANT` |
| `pricelist_id` | m2o `product.pricelist` | — | wire `PRC_LIST` |

- SQL constraint: `unique (partner_id, sales_area_id)`
- `display_name`: `"{partner} — {sales_area}"`

**Behavior rules (must implement):**

1. **Block ≠ inactive** — a blocked row stays `active` (it is still
   downloadable/emittable); archiving (`active=False`) removes it entirely.
   Never let one imply the other.
1b. **Primary SA** — `is_primary=True` allowed on exactly ONE active row per
   partner (python constraint). The partner read-through fields (1.4) follow
   the primary row. **Plant note:** `plant_id → stock.warehouse` is a
   *deployment mapping assumption* (SAP Plant ≈ Odoo warehouse for Solico's
   operations) — documented, revisit at the van-stock step, not a hard
   equivalence baked into logic.
2. **Partner-function defaults** — filled with `partner_id` when empty,
   BOTH via `@api.onchange` (UI) AND in `create()` (API/code paths — onchange
   alone does not cover them). Each role holds exactly one partner (single
   m2o by design).
3. **Pricing is per sales area, resolved at order time (D5+D9)** — the
   pricelist is READ from the relevant `partner_sales_area_id` when an order
   or price request is created (step 5/6 do this from the *visit's* SA).
   Do NOT sync it onto `res.partner.property_product_pricelist` — a partner
   with multiple SAs has multiple pricelists and the partner property can
   hold only one.

### 1.4 `res.partner` extension (`_inherit`)

| Field | Type | Notes |
|---|---|---|
| `sales_area_ids` | o2m `dsd.partner.sales.area` | |
| `dsd_sales_org` / `dsd_dist_channel` / `dsd_division` | Char, computed, **stored** | trio codes of the **primary** (`is_primary`) SA; False when none |
| `dsd_sale_block` / `dsd_delivery_block` / `dsd_billing_block` | Boolean, computed, stored | read-through from the primary SA |

Semantics: these partner fields are **list-filtering/display aids only** —
blocks always live per sales-area row and are NEVER enforced customer-wide
(review 1.5). Compute depends on `is_primary`, `active`, blocks and combo
codes so changes recompute.

## 2. Views

- **Partner form**: inherit `base.view_partner_form`, add notebook page
  **"Sales Areas"** with the o2m — inline `<list>` (sales_area_id, plant,
  pricelist, blocks optional-hidden) + embedded `<form>` with the block
  reasons (invisible unless block set) and the 4 partner functions grouped.
- **Config lists/forms** for all five models (simple `sheet` forms;
  blocks group with conditional reason fields on the relationship form;
  search view on the relationship model with block filters + group-by).
- Use `<list>` — **not** `<tree>` (removed in Odoo 20); `column_invisible="1"`
  for hidden list columns.
- Menus: root **DSD** → **Configuration** (system admins only): Sales Areas,
  Sales Organizations, Distribution Channels, Divisions, Customer Sales
  Areas.

## 3. Security — Odoo 20 formats (careful, these changed!)

**`security/ir.access.csv`** — new format, header exactly:

```
id,name,model_id,group_id/id,operation,domain
access_dsd_sales_org_user,DSD Sales Organization user,dsd.sales.org,dsd_core.group_dsd_user,r,
access_dsd_partner_sales_area_officer,DSD Customer Sales Area officer,dsd.partner.sales.area,dsd_core.group_dsd_officer,ru,
access_dsd_partner_sales_area_system,DSD Customer Sales Area admin,dsd.partner.sales.area,base.group_system,crud,
```

- `model_id` = **model name** (not `model_` XML id), `operation` codes:
  `crud` / `ru` / `r` (one column, no per-op rows).
- Catalogs (org/chn/div/combo): `r` for user+officer, `crud` for
  `base.group_system`. Relationship row: `r` user, `ru` officer, `crud`
  system.

**`security/dsd_security.xml`** — `res.groups.category_id` is **removed in
20**. Pattern (copy of `addons/stock/security/stock_security.xml`):

```xml
<record id="module_category_dsd" model="ir.module.category">…</record>
<record model="res.groups.privilege" id="res_groups_privilege_dsd">
    <field name="name">Direct Store Delivery</field>
    <field name="category_id" ref="module_category_dsd"/>
</record>
<record id="group_dsd_user" model="res.groups">
    <field name="name">User</field>
    <field name="sequence">10</field>
    <field name="privilege_id" ref="res_groups_privilege_dsd"/>
    <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
</record>
<record id="group_dsd_officer" model="res.groups">
    <field name="name">Officer</field>
    <field name="sequence">20</field>
    <field name="privilege_id" ref="res_groups_privilege_dsd"/>
    <field name="implied_ids" eval="[(4, ref('group_dsd_user'))]"/>
</record>
```

## 4. Tests (`odoo.tests.common.TransactionCase`, `@tagged('standard')`)

1. duplicate combo (org/chn/div) raises `psycopg2.IntegrityError`
2. duplicate (partner, sales_area) raises `psycopg2.IntegrityError`
3. block keeps the row searchable; `active=False` hides it
4. primary-SA rule: `is_primary` on a second active row raises; partner
   stored fields follow the primary row; archiving the primary row with no
   replacement clears the read-through fields
5. partner-function onchange defaults to the partner (`odoo.tests.Form`)
6. two SA rows attach to one partner
7. pricing isolation: partner property pricelist is NEVER written by SA
   rows (D9) — assert it stays unchanged when rows with pricelists are
   created

## 5. Definition of done

- [ ] Module installs clean on a **fresh** Odoo 20 DB
      (`-i dsd_core --stop-after-init`, zero errors)
- [ ] All 7 tests green (`--test-enable --test-tags /dsd_core`)
- [ ] Both unique constraints enforced
- [ ] Block/inactive semantics verified in tests
- [ ] No `depends` beyond `base, product, stock`; no Enterprise modules
- [ ] Odoo 20 syntax everywhere (`<list>`, `models.Constraint`,
      `res.groups.privilege`, new `ir.access.csv`)
- [ ] PR opened to `main` with screenshots of the partner tab + config menus

## Out of scope (later steps — do NOT build)

Wire emitter fields (`payment_terms1..5`, `pay_code`, `price_group`,
`customer_group*`, `emse_kalks`, …), LORD online flags, geofence,
route/calendar links, demo data, chatter (`mail` dep), app icon.

---

**Reference implementation** exists on the source monorepo (branch
`feature/dsd-core`, `src/dsd_core/`) — 9 tests green, installed on a dev DB.
You may consult or adopt it, but this spec is authoritative; where they
diverge, flag it here instead of silently choosing.
