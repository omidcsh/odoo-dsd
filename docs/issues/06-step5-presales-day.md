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

- Odoo 20, Community-compatible, LGPL-3. **New dependencies: `sale`,
  `fleet`, `mail`** (sale = presale orders ARE `sale.order`; fleet =
  `fleet.vehicle` for the van flag; mail = chatter/tracking = the Odoo-native
  audit trail for skips/cancels/resets — review 4.4). `depends` becomes
  `base, product, stock, sale, fleet, mail`. Pricing reads the **visit's
  SA pricelist** (D9), never the partner-level property.

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
| `source_type` | sel route/plan/manual | yes | exactly one source (review 5a); drives which populate button applies |
| `route_id` | m2o `dsd.route` | if source=route | populate source |
| `plan_id` | m2o `dsd.visit.plan` | if source=plan | populate source |
| `driver_id` | m2o `res.users` | yes | |
| `company_id` | m2o `res.company` | — | env company (D11 multi-company anchor) |
| `state` | sel draft/downloaded/closed | yes | draft — per D7 collapsed ladder; **lines lock on downloaded (D11)** |
| `line_ids` | o2m `dsd.visit.list.line` | — | |
| `tour_ids` | o2m `dsd.tour` | — | live = exactly 0 or 1 (guard, not DB) |

Partial SQL unique (active lists): `unique (execution_date, route_id)` where
`route_id` is set — duplicate protection; manual lists unconstrained.
(Divergence from package's `unique(plan, date)` + code-300 machinery —
consciously dropped per D7.)

**DB-level 1:1 lock (review 5.4):** a PARTIAL UNIQUE INDEX enforces at most
one *live* tour per list — created in the model's `init()`:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS dsd_tour_live_per_list
  ON dsd_tour (list_id) WHERE active = TRUE;
```

Concurrent downloads cannot race past business logic alone.

### 1.2 `dsd.visit.list.line`

`list_id` (cascade), `partner_sales_area_id` m2o `dsd.partner.sales.area`
(required), `partner_id` related stored, `sequence` int (handle),
`planned_from/planned_to` — **final: optional Datetime** (planned slot;
actual arrival/departure are separate fields on the visit — review 5b).
`unique (list_id, partner_sales_area_id)`.

### 1.3 `dsd.tour` — materialized at download (D7)

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | Char | — | sequence `dsd.tour` (`T00001`…) — NEW id each materialization (guard 2) |
| `list_id` | m2o `dsd.visit.list` | yes | the birth list |
| `execution_date` / `driver_id` / `route_id` | copied from list | yes | frozen copies |
| `vehicle_id` | m2o `fleet.vehicle` | no | **optional in presales** (review 5.1 — presellers carry no goods); domain `is_dsd_van`; becomes required when the van-stock step lands |
| `state` | sel draft/running/done/cancelled | yes | draft — light ladder; SAP's 23 codes arrive with the gateway step |
| `visit_ids` | o2m `dsd.visit` | — | |
| `company_id` | m2o `res.company` | — | copied from list (D11) |
| `active` | Boolean | — | True; False = logically deleted (admin unlock) |
| `dsd_reset_reason` | Text | — | **required** on unlock (audit) |

### 1.4 `dsd.visit` — snapshot rows (owned by the tour)

`tour_id` (cascade), `visit_id` Integer (**unique per tour**, 1..n at
materialization), `sequence`, `partner_id` + `sales_area_id` (copied),
`company_id` (from tour), `snapshot_name/address/city/phone` Char (frozen from partner at creation —
package 11-IMPL §2.2 semantics), `state` sel planned/arrived/done/skipped +
`skip_reason`, `order_ids` o2m sale.order.

### 1.5 Extensions

- `fleet.vehicle`: `is_dsd_van` Boolean (default False)
- `sale.order`: `dsd_visit_id` m2o `dsd.visit` (readonly), `dsd_tour_id`
  related stored

## 2. Behavior (must implement)

**0. Business Rules — FINAL (D11, adopted 2026-11-19 after critical review
of the external 7-phase program — full table):**

| Topic | Rule |
|---|---|
| Visit vs Tour | independent entities, separate lifecycles |
| Visit without an order | allowed — a done visit with zero orders is valid |
| Orders per visit | many (o2m); order lifecycle is standard sale.order |
| Same customer twice in one tour | allowed ONLY via different sales areas (list-line uniqueness); no other duplicate visits in one tour |
| Re-download | returns the EXISTING tour (idempotent — D7/D9) |
| Re-populate | draft lists only; rebuild = replace all lines in one write |
| Pricing | ONLY from the visit's SA pricelist — **no automatic fallback** to partner property or company default (D11: silent fallback could pick ANOTHER SA's pricelist) |
| Missing pricelist on SA | order creation BLOCKED with a clear error (`no_pricelist`) — never silently priced |
| Empty list | download blocked (`empty_list`) — a tour must have ≥1 visit |
| Cancel tour | explicit transition (draft/running → cancelled) with MANDATORY reason |
| Multi-company | list/tour/visit are company-aware (`company_id`); cross-company data access is out of scope for v1 UI but the fields anchor the P1 record rules |

1. **Populate from route** (server action on draft list): for
   `execution_date`'s weekday, take `route.customer_sequence_ids` rows whose
   validity covers the date → lines in membership sequence order.
2. **Populate from plan**: plan lines whose `weekday_mask` has the date's
   bit and window covers it → lines in `sequence`.
3. **Download = materialize** (`action_download` on list, draft only):
   guarded by the DB partial-unique index above (concurrency-safe) and the
   D11 empty-list rule (`empty_list` error on zero lines). **ATOMIC (D11):**
   tour + all visits are created in ONE transaction — a failure anywhere
   leaves no partial tour. Create tour (state draft, chatter on) + copy
   lines to `dsd.visit` rows (`visit_id` 1..n, sequence, partner, SA,
   snapshot chars incl. phone) → list state `downloaded` and the **list
   becomes READ-ONLY** (lines locked; D11). **Idempotent at the API layer
   (step 6):** a repeated download returns the EXISTING tour's package, it
   does not error.
4. **Snapshot isolation**: after materialization, the tour is independent
   of later changes to the LIST (locked anyway), the ROUTE (reordering,
   membership edits) and the CUSTOMER master (snapshot chars frozen);
   partner/SA links remain live references for reporting only.
5. **Admin unlock** (`action_reset_download` on tour, admin group only):
   guards — (a) any visit has a linked `sale.order` → block; (b) any visit
   has operational activity (state ≠ planned, or GPS/timestamps recorded)
   → block unless the operator confirms an explicit force with full audit
   (chatter message; review 5.5); `dsd_reset_reason` **required**. On
   success: archive tour (`active=False`, state cancelled) → list back to
   `draft` and editable again; a later download creates a NEW tour (new
   sequence); the archived one remains as history.
6. **Day flow**: tour `draft → running` (open action) → `done` when all
   visits are terminal; `draft/running → cancelled` with mandatory reason.
   **Visit lifecycle is independent of orders** (review 5.2) with an
   explicit transition matrix (D11): `planned → arrived`, `planned →
   skipped` (reason mandatory), `arrived → done`, `arrived → skipped`
   (reason); `done`/`skipped` are terminal. Status changes are never
   implied by order existence.
7. **Order creation** (`action_create_order`): `sale.order` with partner +
   **pricelist read STRICTLY from the visit's
   `partner_sales_area_id.pricelist_id`** — **NO automatic fallback (D11
   corrects D9's earlier chain)**: if that SA has no pricelist, creation
   is blocked with error `no_pricelist`. Additional D11 guards: the SA's
   `sale_block` blocks creation (`customer_blocked`); products must be
   active/sale-ok. `dsd_visit_id` set; a visit may carry many orders.

**Audit (review 4.4, deepened round 2):** `mail.thread` + activity mixin on
list/tour/visit; `tracking=True` captures **old value → new value, user,
timestamp** on the sensitive fields: visit states & skip reasons, tour
state / reset reason / unlock (incl. the force flag), blocks, driver/vehicle
on the list, and order cancel reasons. Because every write — UI or API —
goes through the ORM, `mail.tracking.value` covers API-originated events
too; the API layer must NOT bypass the ORM (no raw-SQL writes). Partner
geo fields (step 4) gain tracking when the `mail` dependency lands here.
Full immutable event log (append-only, beyond chatter) → P2.

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
4. concurrent materialization: second insert of a live tour for the same
   list hits the partial unique index (IntegrityError) — DB-enforced
5. unlock: resets list to draft, archives tour with required reason;
   re-download → NEW tour name, old one archived; blocked when any visit
   has an order; force path with activity recorded
6. partial unique (date, route) on duplicate active lists
7. presale order from visit: `dsd_visit_id` set, partner set, **pricelist
   = visit SA's pricelist**; visible on visit; visit state does NOT
   auto-change (independence rule 6)
8. tour close only when all visits terminal; a done visit with zero orders
   is valid
9. **D11 — no-fallback pricing**: visit's SA without pricelist → order
   creation raises `no_pricelist`; the partner property is NEVER consulted
10. **D11 — empty list**: zero lines → download raises `empty_list`
11. **D11 — list lock**: after download, line create/write/delete raises;
    unlock restores editability
12. **D11 — route-change isolation**: reorder/alter route memberships
    after download → tour visits unchanged (copied at materialization)
13. **D11 — blocks guard**: visit SA with `sale_block` → order creation
    raises `customer_blocked`
14. **D11 — cancel tour**: with mandatory reason; cancelled tour keeps
    history; list re-download allowed only via admin unlock path
15. **D11 — visit transitions**: invalid transitions (done → arrived,
    planned → done) raise

## 6. Definition of done

- [ ] Fresh-DB install clean; full suite green (steps 1–5, `--test-tags /dsd_core`)
- [ ] The scripted presales day passes as a test: list → download → open →
      2 visits with orders + 1 skipped → close (test 7/8 cover it)
- [ ] `depends = base, product, stock, sale, fleet, mail` — nothing else
- [ ] D7 rules each covered by a test (3/4/5); D9 pricing rule covered (7);
      **D11 rules each covered (9–15)**
- [ ] chatter/tracking present on list/tour/visit (audit)
- [ ] `company_id` present on list/tour/visit (multi-company anchors)
- [ ] PR to `main` with screenshots: list form, tour form with visits+orders

## Out of scope (later steps — do NOT build)

Van stock / loading / COCI / reload (van-sales step), check-out & check-in
wizard content (odometer, cash float, signatures), SAP 23-state tour codes +
`tour_id ≥ 9,000,000` + sequence-block numbering (gateway step), GPS
geofence/OTP on visits, activities/surveys, visit appointments, mid-day OCS
sync, `stock.picking.batch` integration.

## References

- Decision D7 + **D11** (issue #1 log — business-rules finalization from
  the critical review of the external 7-phase program, 2026-11-19) · M01
  §3.5/§3.7 (1:1, copy-lines, snapshot semantics — our ladder collapsed
  per D7) · 11-IMPL §2.1–2.2 (full tour/visit wire model — deliberately
  deferred) · PRESELLER-SCENARIO §4–7
- Prior art: v1 monorepo `dsd_tour` on `stock.picking.batch` (branch
  `dsd-v1`) — batch link consciously NOT adopted here (presales has no
  stock moves)
