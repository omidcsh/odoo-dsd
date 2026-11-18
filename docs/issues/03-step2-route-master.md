# [Step 2 — DEV TASK] Route master & customer membership (`dsd_core`)

> Second development task of the DSD-on-Odoo project. Master plan: #1 ·
> Builds directly on step 1 (#2, sales-area entities).
> Spec version: draft v1 (2026-11-18) — **pending approval before posting**.

## Roadmap note (requires maintainer OK)

Issue #1 bundled "Route & visit plans" as step 2. This task splits them:
**step 2 = route master + membership only**; visit plans/lists (with their
generation machinery, M01 §3.4/§3.6) become their own step 3 — they are
considerably heavier (plan types, auth groups, parity message codes) and
depend on nothing here beyond the membership ordering this task provides.
Steps 3–8 of #1 shift by one.

## Goal

Model the DSD **route** — the strategic template that groups customers into
an ordered visiting sequence for a departure warehouse — and each customer's
**membership** in it. Later steps consume this: visit planning (step 3) and
tour generation (tours step) walk the membership sequence.

- Same constraints as #2: Odoo 20, Community-compatible, module `dsd_core`,
  `depends` stays `base, product, stock` (nothing new needed), LGPL-3.

## 0. Odoo-native survey (standing rule: standard first)

| Odoo 20 native | What it is | Fits a customer-visit route? | Verdict |
|---|---|---|---|
| `stock.rule` / stock routes | internal replenishment routing WH→WH | ✗ not customer visits | no |
| `fleet` | vehicles, not itineraries | ✗ (useful later, tours step) | no |
| `resource.calendar` (+attendance dayofweek) | working hours calendars | ✗ serving-*days* pattern ≠ working hours; also tz gotchas | no — simple weekday booleans instead |
| `calendar.event` / appointment | single meetings/slots | ✗ not ordered sequences | no |
| nothing else in Community touches visit routes | | | **custom model** (confirms package M01 §3.3) |

Native reuse in this step: `stock.warehouse` (departure/shipping point),
`res.users` (permitted drivers — they are the device login users),
`dsd.sales.area` from step 1 (route scoping).

## 1. Data model

### 1.1 `dsd.route` — route master

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `code` | Char(10) | yes | | route code (SAP TVRO-style / masir codes), **unique** |
| `name` | Char | yes | | translatable |
| `active` | Boolean | — | True | |
| `sales_area_id` | m2o `dsd.sales.area` | no | | optional scoping to one sales-area combo (package had trio chars; we have the combo from step 1) |
| `warehouse_id` | m2o `stock.warehouse` | no | | departure/shipping point (`shipping_point` in M01 §3.3) |
| `driver_ids` | m2m `res.users` | no | | permitted drivers (package: replaces ZDSD_DRV_CUST permission layer together with membership) |
| `customer_sequence_ids` | o2m `dsd.route.customer` | — | | ordered membership (1.2), context default route |

**D10 FINAL (2026-11-18): no weekday fields on the route** — weekday
patterns live on the visit plan (step 3 header mask + optional line
override), matching standard `/DSD/VC_VPH`. The route is purely a
grouping/ordering master.

- `display_name`: `"{code} — {name}"`; `_order = 'code'`
- No chatter yet (`mail` stays out of depends — same policy as #2).

### 1.2 `dsd.route.customer` — ordered membership

| Field | Type | Required | Notes |
|---|---|---|---|
| `route_id` | m2o `dsd.route` | yes | `ondelete='cascade'` |
| `partner_id` | m2o `res.partner` | yes | `ondelete='cascade'` |
| `sales_area_id` | m2o `dsd.sales.area` | yes | the visit identity triple disambiguates multi-SA customers |
| `sequence` | Integer | yes | visit order within the route (`widget="handle"` in list) |
| `valid_from` / `valid_to` | Date | no | membership validity window |

- `_order = 'sequence, id'`

**Behavior rules (must implement):**

1. **Membership history** (review 2.2): the plain unique triple is REPLACED
   by a python constraint — for one (route, partner, sales_area), validity
   windows must **not overlap**. A customer may leave a route and re-join
   later as a NEW row with a later window (history preserved). One open
   window (`valid_to` empty) per triple at a time.
2. **Sales-area compatibility** (review 2.1): when `route.sales_area_id` is
   set, every membership's `sales_area_id` must equal it (`ValidationError`
   otherwise). A route without SA scope accepts any SA.
3. Membership ordering is the `sequence` field; no implicit re-sorting.
4. `driver_ids` = **permitted drivers** (who may ever run this route) —
   daily driver assignment is NOT stored here; it lives on the visit
   list/tour (step 5), which may also be validated against this permission.

## 2. Views

- Route form: sheet with code/name/sales area/warehouse/drivers; notebook
  page **"Customers"** with an **editable** `<list>`: handle (sequence),
  partner, sales area, valid_from, valid_to.
- Route list + search (by sales area, warehouse, driver, archived).
- Membership standalone list/form not required (managed from the route) —
  but keep the model searchable for later steps.
- Menus: DSD → Configuration → **Routes**.
- Odoo 20 syntax reminders from #2 apply (`<list>`, `column_invisible`,
  no `<tree>`).

## 3. Security — add rows to `security/ir.access.csv` (same format as #2)

- `dsd.route`: `r` for `group_dsd_user` and `group_dsd_officer`, `crud` for
  `base.group_system` (route master is configuration)
- `dsd.route.customer`: `r` user, **`ru` officer** (operators maintain
  memberships), `crud` system

## 4. Tests (`TransactionCase`, `@tagged('standard')`)

1. duplicate route `code` raises `psycopg2.IntegrityError`
2. overlapping validity windows for the same (route, partner, sales_area)
   raise `ValidationError`; sequential re-join windows are allowed
3. same partner on **two different routes** → allowed
4. same partner, same route, **different sales areas** → allowed (the
   disambiguation rule)
5. membership order: create out of order, `_order`/search returns by
   `sequence` then id
6. SA compatibility: membership with an SA differing from the route's
   scoped SA raises; route without SA scope accepts any SA

## 5. Definition of done

- [ ] Installs clean on fresh Odoo 20 DB (`-u/-i dsd_core`, zero errors)
- [ ] All tests green (`--test-tags /dsd_core` — includes step-1 suite)
- [ ] Both unique constraints enforced; disambiguation cases covered
- [ ] `depends` unchanged (`base, product, stock`)
- [ ] Odoo 20 syntax throughout; no new security formats beyond #2 patterns
- [ ] PR to `main` with screenshot of route form + Customers tab

## Out of scope (do NOT build — later steps)

- Visit plans, visit lists and their generation machinery (next step;
  M01 §3.4/§3.6: plan types, auth groups, parity message codes 300–316)
- Capacity checks (weight/volume/stops/duration — tours step; prior art in
  legacy v1 `dsd.route`)
- `dsd.calendar` model (M01 FLOW-003) — weekday booleans stand in
- Route determination config (FLOW-014 — orders step)
- Partner-form route display (Customer-360 step)
- Demo data, chatter, app icon

## References

- Package `odoo/modules/M01-SD-FOUNDATION.en.md` §3.3 (route master +
  membership), FLOW-014 note
- Prior art: legacy module `src/dsd/models/dsd_route.py` (monorepo branch
  `dsd-v1`) — weekday pattern + capacity fields; capacities consciously
  deferred here
- Step 1 (#2) supplies `dsd.sales.area`
- **SAP live-system check (2026-11-18):** standard SAP has NO customer-visit
  route master — `TVRO` is transport routing (transit/distance/weight);
  Solico's `ZSLC_DSD_ROUTES` is a masir→sales-office/preseller mapping with
  NO weekdays; weekday patterns live on the visit plan
  (`/DSD/VC_VPH` MON..SUN — standard). ⇒ our `dsd.route` is an Odoo-side
  grouping/ordering concept; the weekday booleans were dropped (D10 final) —
  populate-from-plan is the canonical weekday source, matching SAP.
  Migration mapping: MASIR→route
  code, VKBUR→Odoo sales-office TBD, PRESELLER/PHONESELLER→permitted
  drivers.
