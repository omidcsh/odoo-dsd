# [Step 8 — DEV TASK] Delivery preparation — back-office only (`dsd_core`)

> Eighth development task. Master plan: #1 · Builds on #6 (presales day)
> and #8 (monitoring). **Scope per user 2026-11-19: BACK-OFFICE ONLY** —
> what the office does after the salesmen's orders arrive, to have the
> next day's deliveries READY. The mobile delivery scenario (app
> endpoints, driver execution, doorstep returns) is a SEPARATE later
> step and is deliberately NOT designed here.
> Spec v3 (2026-11-19) — mobile-execution parts of v2 moved out.
> **Pending approval.**

## Goal

The moment the sales day ends (orders arrived online from the
presellers' app), the office can — in Odoo, without any code:

1. **Prepare**: turn the day's confirmed orders into delivery documents,
   grouped into **Delivery Runs** and **Delivery Stops** (volume-safe)
2. **Assign**: driver + vehicle per run
3. **Make ready**: warehouse sees pick lists per stop, reservations
   checked, shortages flagged
4. **Watch**: runs/stops visible in the monitoring console (#8)

No app, no GPS, no returns, no money, no van stock in this step.

## 0. Odoo-native survey (verified in source, 2026-11-19)

| Concern | Verdict |
|---|---|
| Order→picking | ✓ `sale_stock`; an order yields **0..N pickings** (routes/product/warehouse dependent) — prepare works from EXISTING pickings, never assumes 1:1 |
| Grouping transfers | ✓ `stock.picking.batch` = warehouse transfer grouping (company + operation-type compatible members only); **native automatic batches exist** (`stock.picking.type.auto_batch`, criteria: contact/dest-country/src-dest-location/waves) — usable for WH-internal waves, **not** for route/driver/DSD-date runs → custom `dsd.delivery.run` rides ON a batch (optional) |
| Batch lifecycle | native `draft/in_progress/done/cancel`, computed+readonly — never redefined; DSD readiness = separate flag |
| Bulk WH ops | `action_assign`/`action_done` on the batch = warehouse-side bulk reserve/validate (reused for the pick list flow) |

**New dependency: `sale_stock`.** `depends` =
`base, product, stock, sale, fleet, mail, sale_stock`.

## 1. Data model

### `dsd.delivery.run`
`route_id`, `execution_date`, `company_id`, `warehouse_id` +
`picking_type_id` (grouping key — compatibility constraints respected),
`driver_id`, `vehicle_id` (optional), `batch_id` (m2o
stock.picking.batch — created/linked for WH processing; the run owns the
DSD meaning, the batch owns the transfers), `dsd_ready` Boolean
(operational readiness — independent of batch state), `state` sel
draft/ready/cancelled (back-office lifecycle; execution states belong to
the mobile-delivery step), `stop_ids` o2m. Chatter (audit: assignment,
readiness, prepare runs).

### `dsd.delivery.stop` — one customer address on a run
`run_id`, `partner_id` + `sales_area_id` + **snapshot chars**
(name/address/phone — frozen from the order/visit data),
`sequence` (from route membership order), `picking_ids` m2m (multiple
orders → multiple pickings per stop), `state` sel open/prepared
(back-office only; delivery outcomes arrive with the mobile step).
**Source of dimensions (D14):** route = the presales TOUR's route
(snapshot); execution date = the orders' `commitment_date` — NEVER
recomputed from the customer's current master.

### `dsd.delivery.prepare.request` + `.job` — volume-safe orchestration
`date`, `warehouse_ids`, state, `job_ids` (slice = route × warehouse,
own transaction per job, per-job state pending/running/done/error +
error text). **No manual commits** — each job is an independent
transaction; re-run admits only orders whose pickings are not yet in any
run/stop (**per-order idempotency**, never per-batch existence). v1:
jobs processed by cron + a UI trigger.

## 2. Business rules (final — back-office scope)

| Topic | Rule |
|---|---|
| Input set | confirmed presale orders of the day, via their existing pickings |
| Grouping key | (company, warehouse/op-type, route, execution date) → one run; incompatible pickings never share a run/batch |
| Stop formation | all pickings for the same (partner, SA, address) in a run → ONE stop, ordered by route membership sequence |
| Assignment | driver/vehicle per run after grouping; driver must be a permitted driver of the route (warning, not block) |
| Readiness | `dsd_ready` when every stop has ≥1 picking, all assigned+reserved; shortages WARN (listed on the run) — never silently block |
| Re-run | only NEW orders enter; nothing already prepared is duplicated or reordered |
| Backorders | partial-delivery outcomes are mobile-step territory — this step only guarantees backorder pickings are visible and assignable to runs by the same prepare flow |
| Money / returns / GPS | none in this step |

## 3. Views (back-office)

- DSD → **Operations → Delivery Runs**: list/kanban by state, filters
  (date/route/driver/warehouse), "Today" default
- Run form: header (route/date/driver/vehicle/warehouse), **Stops tab**
  (sequence, snapshot, pickings per stop, shortage badges), readiness
  panel + **Pick List / Load List** print per stop (QWeb, simple)
- Prepare wizard: date + warehouses → creates the request; jobs and their
  states visible on the request form
- Runs appear in the monitoring console (#8) next to sales tours

## 4. Tests (back-office only)

1. grouping key: same route+date across 2 warehouses → 2 runs; same
   warehouse different routes → 2 runs; incompatible pickings never merge
2. stop formation: customer with 2 confirmed orders → 1 stop with 2
   pickings; sequence follows route membership
3. prepare request+jobs: 100 orders / 3 routes / 2 warehouses — all
   admitted exactly once; re-run adds 0 duplicates; a failed job records
   its error and does not poison siblings
4. readiness: unreserved picking blocks `dsd_ready`; shortage listed as
   warning
5. dimension sources: run route = tour snapshot (changing the customer's
   current route does not move the run); date = commitment_date
6. driver-on-route warning fires for non-permitted driver (non-blocking)

## 5. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–8)
- [ ] Officer walkthrough as a scripted test: day's confirmed orders →
      prepare → assign drivers → ready (with one shortage warning)
- [ ] `depends = base, product, stock, sale, fleet, mail, sale_stock`
- [ ] Runs visible in the monitoring console
- [ ] PR to `main` with screenshots (run form + stops, prepare wizard)

## Out of scope (explicitly — later steps)

**Mobile delivery execution** (app endpoints v1.3, delivery attempts,
GPS stamps, partial/failed outcomes, doorstep returns + the
invoice→order→original-picking return chain, backorder-stays-or-moves
decision) — its own step; van sales (held), invoicing/payments, route
optimization, POD photos/signatures, printing beyond the simple pick
list, empties.

## References

- User directive 2026-11-19 (back-office only; mobile delivery is the
  NEXT-next step) · round-3 review (accepted: run/stop as DSD concepts,
  compatibility-keyed grouping, job-based prepare, native auto-batch
  correction) · v1 legacy batch mapping (branch `dsd-v1`) reused for WH
  processing · SAP live checks 2026-11-19 (LIPS/TVLK; queries recorded in
  `docs/reviews/sap-verification-2026-11-18.md`)
