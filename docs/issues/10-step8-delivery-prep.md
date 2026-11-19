# [Step 8 — DEV TASK] Delivery preparation & mobile delivery readiness (`dsd_core`)

> Eighth development task. Master plan: #1 · Builds on #6 (orders on
> visits), #7 (API), #8 (monitoring). Van-sales stays ON HOLD; no money,
> no invoicing, no COCI in this step.
> Spec v2 (2026-11-19) — **rewritten after external review round 3**
> (verdicts: all critical findings accepted; two of my factual claims
> corrected against the Odoo source). **Pending approval.**

## Architecture decisions (final — the three that shape everything)

1. **`stock.picking.batch` = warehouse transfer grouping ONLY.** The DSD
   operational concepts are first-class: **`dsd.delivery.run`** (may link a
   batch for warehouse processing) and **`dsd.delivery.stop`**. Delivery
   lifecycle never rides the batch state.
2. **Delivery attempt ≠ stock cancellation.** A failed stop records an
   ATTEMPT (reason, GPS, times) and touches no picking — the office decides
   the picking's fate. Partial delivery records quantities + leaves the
   backorder decision explicit.
3. **Returns chain to the ORIGINAL DELIVERED PICKING** (native `return_id`
   chain); the reference invoice is the COMMERCIAL anchor
   (`dsd_reference_invoice_id`, mandatory) — server resolves
   invoice → order → delivered picking(s).

## 0. Odoo-native survey (verified in source, 2026-11-19 — incl. round-3 corrections)

| Concern | Verdict |
|---|---|
| Order→picking | ✓ `sale_stock`, but an order yields **0..N pickings** (routes/product/warehouse dependent) — prepare works from EXISTING pickings, never assumes 1:1 |
| Batch lifecycle | ✓ native `draft/in_progress/done/cancel`, **computed + readonly** — never redefined; DSD readiness is a separate flag on the run |
| **Automatic batches** | ✓ **EXISTS in core** (review corrected my earlier claim): `stock.picking.type.auto_batch` groups by contact/destination-country/src-dest-location/waves (product/category/location/date). Criteria do NOT cover route/driver/DSD-date → **DSD Run orchestration stays custom**; native auto-batch may coexist for WH waves |
| Batch membership | pickings must be compatible (company + operation type) → run grouping key = **(company, warehouse/op-type, route, date)**; driver assigned after grouping |
| Bulk WH ops | `action_assign`/`action_done` = warehouse batch processing (bulk) — DISTINCT from mobile per-stop confirms; both tested separately |
| Partial/backorder | ✓ native backorder on partial validate; **membership of the backorder picking in the run is an explicit field/decision, not an assumption** |
| Returns | ✓ native return picking from the original (chain via `return_id/return_ids`) |

## 1. Data model (core of the rewrite)

### `dsd.delivery.run`
`route_id`, `execution_date`, `company_id`, `warehouse_id` +
`picking_type_id` (grouping key), `driver_id`, `vehicle_id` (optional),
`batch_id` (m2o stock.picking.batch, optional — created/linked for WH
processing), `dsd_ready` Boolean (operational readiness — NOT the batch
state), `state` sel draft/ready/running/closed/cancelled (DSD lifecycle),
`stop_ids` o2m. Chatter (audit).

### `dsd.delivery.stop` — the physical customer visit of the deliveryman
`run_id`, `partner_id` + `sales_area_id` + **snapshot chars** (name/
address/phone — from the order/visit data, not live master),
`sequence` (order derived from route membership), `picking_ids` m2m
(multiple orders → multiple pickings per stop), `state` sel
open/delivered/partial/failed/closed, `attempt_ids` o2m, gps/timestamps
of last attempt. **Source of route/date (D14):** route = the presales
TOUR's route (snapshot); delivery date = the order's
`commitment_date` — NEVER recomputed from the customer's current master.

### `dsd.delivery.attempt` — one physical knock on the door
`stop_id`, `result` sel full/partial/failed, `reason_id` (required when
failed), `gps` + `occurred_at` (client) + `received_at` (server),
`line_ids` (for partial: picking, product, qty, uom, **lot/serial ids**),
`client_uuid` (idempotent).

### `dsd.delivery.prepare.request` — volume-safe orchestration
`date`, `warehouse_ids`, `state`, `job_ids` o2m `dsd.delivery.prepare.job`
(`slice` = route×warehouse, own transaction per job, `state`
pending/running/done/error + error text). **No manual commits inside
business methods** (review 3.3) — each job is an independent transaction;
re-run picks up only orders NOT yet in a run/stop (per-order idempotency,
not per-batch existence). v1: jobs processed by cron + UI trigger.

## 2. Business rules (final)

| Topic | Rule |
|---|---|
| Stop formation | all confirmed orders' pickings for the same (partner, SA, address) on a route+date run → ONE stop, ordered by route membership sequence |
| Readiness | `dsd_ready` when every stop has ≥1 picking assigned+reserved; shortages WARN (listed on run), never block silently |
| Full delivery | attempt(full) → all stop pickings validated |
| Partial | attempt(partial) with per-line qty (lots where tracked) → validated pickings create native backorders; **backorder membership: explicit `dsd_run_keep` decision — default stays on the SAME run for retry, office may move it to a later run** |
| Failed | attempt(failed) + mandatory reason → **picking untouched**; stop state=failed; office picks: retry (reopen stop), cancel picking/order, or reschedule |
| Return | reference invoice MANDATORY (no `?` — API fixed); server validates chain invoice→order→delivered picking(s); qty ≤ delivered − already-returned; duplicate return of the same picking lines rejected; receiving location default WH/STOCK (damaged-goods location choice arrives with the van step) |
| Money | none — no invoice issuance, no payment, no COCI (unchanged) |
| Multi-run | a driver may have several runs per day (multi-WH/multi-route) — API returns a list |

## 3. Mobile API v1.3 (stop-centric — revised)

| Endpoint | In | Effect |
|---|---|---|
| `POST /delivery/day/get` | `{date}` | ALL runs of the caller: runs[] → stops[] (snapshot, state, sequence) → pickings[] (id, order, products w/ qty, uom, tracking needs) |
| `POST /delivery/stop/confirm` | `{client_uuid, stop_id, result: full\|partial, lines?[{picking_id, product_id, qty, uom_id, lot_ids?}], gps?, occurred_at}` | full → validate all stop pickings; partial → validate given qtys (native backorders per explicit rule); stamps GPS+times on the attempt |
| `POST /delivery/stop/fail` | `{client_uuid, stop_id, reason, gps?, occurred_at}` | records failed attempt — **no picking side-effects** |
| `POST /delivery/return/pickup` | `{client_uuid, stop_id, reference_invoice_id, lines[]}` | builds native return picking(s) chained to the ORIGINAL delivered picking(s); commercial ref stored on the return order |
| `POST /delivery/run/close` | `{client_uuid, run_id}` | run closed when all stops terminal; open backorders listed for the office |

Cross-cutting: idempotent `client_uuid` on every verb; envelope per #7
§1.9; driver scoping per #7 §2.1 (stop must belong to a run of
`driver_id = uid`); client `occurred_at` + server `received_at` stored;
UoM validated server-side (conversion where needed); lot/serial required
per product tracking.

## 4. Volume & performance (D13, revised per review)

- prepare = request + per-slice jobs (own transactions, re-runnable,
  per-order idempotency) — **no raw commits**; cron-driven in v1
- native `auto_batch`/waves may handle WH-internal grouping where the
  criteria suffice — runs stay the DSD layer
- tests: 100 orders across **3 routes × 2 warehouses** (compatibility
  key exercised); **multiple pickings per customer** (2 orders → 1 stop ×
  2 pickings); multi-run per driver; re-run adds 0 duplicates; bulk WH
  validation via `action_assign/action_done` tested SEPARATELY from
  mobile per-stop confirms

## 5. Tests (revised set)

1. grouping key: same route+date across 2 warehouses → 2 runs; same
   warehouse different routes → 2 runs; incompatible pickings never share
   a run/batch
2. stop formation: customer with 2 confirmed orders → 1 stop, 2 pickings;
   sequence follows route membership
3. readiness warnings on shortage; `dsd_ready` gate
4. full confirm validates all pickings; idempotent replay
5. partial confirm → backorder picking; `dsd_run_keep` default keeps it
   on the run; moving it to another run is an explicit office action
6. fail → attempt recorded, picking state UNCHANGED; office retry reopens
7. return: chain to original picking; over-return and double-return
   rejected; reference invoice mandatory
8. run/close blocked with open stops; open backorders reported
9. API (HttpCase): multi-run day/get; driver scoping; lot-tracked
   partial confirm carries lot ids; timestamps (client+server) stored
10. volume smoke: 100 orders / 3 routes / 2 WH via prepare request+jobs;
    re-run clean

## 6. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–8)
- [ ] Scripted delivery day as a test: prepare → 3 stops (full / partial
      with backorder kept / failed then retried) + 1 doorstep return →
      close run
- [ ] `depends = base, product, stock, sale, fleet, mail, sale_stock`
- [ ] Runs/stops visible in the monitoring console (#8)
- [ ] PR to `main` with screenshots (run form, stops, attempts, console)

## Out of scope (unchanged — review agreed)

Van stock/van locations/loading/COCI/reload (held), invoicing & payments,
route optimization, time-windows, POD photos/signatures, printing,
empties. GPS + event timestamps REMAIN in scope.

## References

- External review round 3 (2026-11-19) — all critical findings adopted;
  two factual corrections verified in source: batch state
  (`draft/in_progress/done/cancel`, computed+readonly) and **native
  auto-batch exists** (`stock.picking.type.auto_batch` + grouping
  criteria — insufficient for route/driver/DSD-date, hence custom runs)
- SAP live check 2026-11-19: `LIPS` structure (VGBEL/VGPOS, tolerances,
  partial control, POD flags, `SHKZG`), `TVLK` 15+ delivery types,
  `LIPS.ZZVGBEL_VF` custom reference-invoice field — indicates the
  business importance of invoice-referenced returns in Solico (claim
  scoped: it does NOT by itself validate the Odoo return design; the
  chain mapping in §2 does). Reproducible queries recorded in
  `docs/reviews/sap-verification-2026-11-18.md`
- v1 legacy batch mapping (branch `dsd-v1`) reused for WH processing
