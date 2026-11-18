# [Step 5 — DEV TASK] Presales day: visit list → on-demand tour → visits → orders

> Fifth development task. Master plan: #1 · Builds on #2 (SA), #3 (routes),
> #4 (visit plans), #5 (partner panel). Implements decision **D7**.
> Spec version: draft v1 (2026-11-18) — **pending approval before posting**.

## Goal — the first operational vertical slice

Run the **presales scenario** in the Odoo back-office, end to end:

1. Operator creates a **visit list** for a date (populated from a route's
   membership or a visit plan's weekday lines)
2. "Download" materializes the **tour** from the list — once (1:1, locked)
3. Driver's day on the tour: open → visits → **presale order per visit**
   (`sale.order`, native pricing via D5) → close
4. Admin can **unlock** a wrongly downloaded list by logically deleting the
   tour (guarded), then download again

D7 rules implemented verbatim: tour born from list at download; no second
tour while one is live; snapshot of the list into the tour (later list edits
don't touch an existing tour); admin unlock with guards.

- Odoo 20, Community-compatible, LGPL-3. **First new dependency: `sale`**
  (justified: presale orders ARE `sale.order`; pricelist already flows from
  the customer's primary SA per D5). `depends` becomes
  `base, product, stock, sale`.

## 0. Odoo-native survey (standing rule)

| Concept | Odoo 20 native | Verdict |
|---|---|---|
| Vehicle / van | **`fleet.vehicle`** (Community: plate, model, driver partner) | ✓ reuse + `is_dsd_van` flag — replaces package's custom `dsd.vehicle` (native-first correction; the van stock-location tree arrives with van-stock step) |
| Day plan of stops | nothing native (calendar/appointments are single slots) | custom light `dsd.visit.list` |
| Tour (day record) | nothing native | custom light `dsd.tour` — **NOT** on `stock.picking.batch`: presales has no stock moves; batch rides along at the van-stock step |
| Order | **`sale.order`** | ✓ reuse — add `dsd_visit_id`; state stays draft→sale standard |
| Driver | `res.users` (device-login users) / `fleet.vehicle.driver_id` (partner) | reuse `res.users` on tour (package parity) |

## 1. Data model

### 1.1 `dsd.visit.list` — the day's planning unit

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | Char | — | computed `{date} {route or plan}` |
| `execution_date` | Date | yes | |
| `route_id` | m2o `dsd.route` | no | populate source #1 |
| `plan_id` | m2o `dsd.visit.plan` | no | populate source #2 |
| `driver_id` | m2o `res.users` | yes | |
| `state` | sel draft/downloaded/closed | yes | draft — per D7 collapsed ladder |
| `line_ids` | o2m `dsd.visit.list.line` | — | |
| `tour_ids` | o2m `dsd.tour` | — | live = exactly 0 or 1 (guard, not DB) |

Partial SQL unique (active lists): `unique (execution_date, route_id)` where
`route_id` is set — obvious duplicate protection; manual lists (no route)
unconstrained. (Divergence from package's `unique(plan, date)` + code-300
machinery — consciously dropped per D7.)

### 1.2 `dsd.visit.list.line`

`list_id` (cascade), `partner_sales_area_id` m2o `dsd.partner.sales.area`
(required), `partner_id` related stored, `sequence` int (handle),
`planned_from/planned_to` optional Time/Char — keep Datetime optional.
`unique (list_id, partner_sales_area_id)`.

### 1.3 `dsd.tour` — materialized at download (D7)

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | Char | — | sequence `dsd.tour` (`T00001`…) — NEW id each materialization (guard 2) |
| `list_id` | m2o `dsd.visit.list` | yes | the birth list |
| `execution_date` / `driver_id` / `route_id` | copied from list | yes | frozen copies |
| `vehicle_id` | m2o `fleet.vehicle` | yes | domain `is_dsd_van` |
| `state` | sel draft/running/done/cancelled | yes | draft — light ladder; SAP's 23 codes arrive with the gateway step |
| `visit_ids` | o2m `dsd.visit` | — | |
| `dsd_reset_reason` | Text | — | filled by admin unlock (audit) |

### 1.4 `dsd.visit` — snapshot rows (owned by the tour)

`tour_id` (cascade), `visit_id` Integer (**unique per tour**, 1..n at
materialization), `sequence`, `partner_id` + `sales_area_id` (copied),
`snapshot_name/address/city` Char (frozen from partner at creation —
package 11-IMPL §2.2 semantics), `state` sel planned/arrived/done/skipped +
`skip_reason`, `order_ids` o2m sale.order.

### 1.5 Extensions

- `fleet.vehicle`: `is_dsd_van` Boolean (default False)
- `sale.order`: `dsd_visit_id` m2o `dsd.visit` (readonly), `dsd_tour_id`
  related stored

## 2. Behavior (must implement)

1. **Populate from route** (server action on draft list): for
   `execution_date`'s weekday, take `route.customer_sequence_ids` rows whose
   validity covers the date → lines in membership sequence order.
2. **Populate from plan**: plan lines whose `weekday_mask` has the date's
   bit and window covers it → lines in `sequence`.
3. **Download = materialize** (`action_download` on list, draft only):
   guard — a live (unarchived) tour already exists for this list →
   `UserError`. Create tour (state draft) + copy lines to `dsd.visit` rows
   (`visit_id` 1..n, sequence, partner, SA, snapshot chars) → list state
   `downloaded`.
4. **Snapshot isolation**: after materialization, editing/deleting list
   lines does NOT touch the tour's visits (they are copies).
5. **Admin unlock** (`action_reset_download` on tour, admin group only):
   guard — any visit has linked `sale.order` → `UserError` (nothing may be
   orphaned); else archive tour (`active=False`, store `dsd_reset_reason`,
   state cancelled) → list back to `draft`. A later download creates a NEW
   tour (new sequence name); the archived one stays as history.
6. **Day flow**: tour `draft → running` (open action, stamps nothing fancy),
   per visit: `action_create_order` → `sale.order` draft with partner, SA's
   pricelist (via partner property), `dsd_visit_id`; visit state
   `done` when an order exists (or `skipped` + reason manually); all visits
   terminal → tour closable (`done`).

## 3. Views

- DSD → **Operations** (new menu): Visit Lists, Tours.
- List form: header (date, driver, route/plan, state statusbar), buttons
  *Populate from Route / from Plan* (draft only), **Download Tour**;
  lines tab (handle, PSA, times).
- Tour form: statusbar, list/driver/vehicle (readonly copies), visits tab
  (state badges, per-visit **New Order** button, order smart-link),
  *Open Tour / Close Tour*, admin **Reset Download** (with reason prompt).
- Visit Kanban/list optional — keep form-in-tour only (minimal).

## 4. Security — extend `ir.access.csv`

Operations data: `dsd.visit.list`, `dsd.visit.list.line`, `dsd.tour`,
`dsd.visit` → user `r`, officer `ru`, system `crud`. Reset action gated by
`base.group_system` in code (button invisible for non-admins).

## 5. Tests (`TransactionCase`, `@tagged('standard')`)

1. populate-from-route: weekday filter + membership validity + sequence
2. populate-from-plan: weekday_mask bit + window
3. download materializes: visits 1..n with snapshot; **editing list lines
   afterwards leaves tour visits unchanged** (snapshot isolation)
4. second download blocked while live tour exists (UserError)
5. unlock: resets list to draft, archives tour with reason; re-download →
   NEW tour name, old one archived; unlock blocked when a visit has an order
6. partial unique (date, route) on duplicate active lists
7. presale order from visit: `dsd_visit_id` set, partner/pricelist defaults,
   visible on visit; visit auto-`done`
8. tour close only when all visits terminal

## 6. Definition of done

- [ ] Fresh-DB install clean; full suite green (steps 1–5, `--test-tags /dsd_core`)
- [ ] The scripted presales day passes as a test: list → download → open →
      2 visits with orders + 1 skipped → close (test 7/8 cover it)
- [ ] `depends = base, product, stock, sale` — nothing else
- [ ] D7 rules each covered by a test (3/4/5)
- [ ] PR to `main` with screenshots: list form, tour form with visits+orders

## Out of scope (later steps — do NOT build)

Van stock / loading / COCI / reload (van-sales step), check-out & check-in
wizard content (odometer, cash float, signatures), SAP 23-state tour codes +
`tour_id ≥ 9,000,000` + sequence-block numbering (gateway step), GPS
geofence/OTP on visits, activities/surveys, visit appointments, mid-day OCS
sync, `stock.picking.batch` integration.

## References

- Decision D7 (issue #1 log) · M01 §3.5/§3.7 (1:1, copy-lines, snapshot
  semantics — our ladder collapsed per D7) · 11-IMPL §2.1–2.2 (full tour/
  visit wire model — deliberately deferred) · PRESELLER-SCENARIO §4–7
- Prior art: v1 monorepo `dsd_tour` on `stock.picking.batch` (branch
  `dsd-v1`) — batch link consciously NOT adopted here (presales has no
  stock moves)
