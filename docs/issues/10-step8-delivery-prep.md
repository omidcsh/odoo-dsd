# [Step 8 — DEV TASK] Delivery preparation — back-office only (`dsd_core`)

> Roadmap step **8** (GitHub issue will be **#9**). Master plan: #1 ·
> Builds on roadmap step 5 = issue #6 (presales day) and roadmap step 7 =
> issue #8 (monitoring). **BACK-OFFICE ONLY per user** — mobile delivery
> execution is roadmap step 9 (separate issue, later).
> Spec v4 (2026-11-19) — review round 4 applied (idempotency at picking
> level, readiness matrix, no action_done/PGI, job transaction guarantees,
> stop identity by address record, cancel semantics, numbering fixed).
> **Pending approval.**

**Survey baseline (pinned):** local Odoo **20.0** Enterprise build
`+e-20261109` (`odoo/release.py`; the workspace source tree). All native
behavior claims below verified against this tree. Any re-verification
must name its build.

## Goal

After the salesmen's orders arrive (online, from the presales app), the
office can — in Odoo, no code:

1. **Prepare** confirmed orders' pickings into **Delivery Runs** and
   **Delivery Stops** (volume-safe, idempotent at the PICKING level)
2. **Assign** driver + vehicle per run
3. **Make ready**: reservations checked, shortages warned, pick/load lists
4. **Watch** runs in the monitoring console

**Nothing validates a picking / posts goods (no PGI) in this step** —
reservation & staging only. No GPS, no returns, no money, no van stock.

## 0. Odoo-native survey (verified against the pinned build)

| Concern | Verdict |
|---|---|
| Order→picking | ✓ `sale_stock`; an order yields **0..N pickings** — prepare consumes EXISTING outgoing pickings (never assumes 1:1) |
| Picking states relevant here | `waiting/confirmed` → not ready · `assigned` = fully reserved · `partially_available` (move-level) surfaces as a picking shortage · `done/cancel` excluded from active preparation |
| Grouping | `stock.picking.batch` = WH transfer grouping (company + picking-type compatible members); **native automatic batches exist** (`stock.picking.type.auto_batch`; criteria: contact/dest-country/src-dest-loc/waves) — usable for WH waves, NOT for route/driver/DSD-date → custom `dsd.delivery.run` links a batch |
| Batch actions | `action_assign` = bulk RESERVATION attempt ✓ used; **`action_done` = validates transfers & moves stock — NOT used in this step (PGI is out of scope)** |
| Batch lifecycle | native computed+readonly `draft/in_progress/done/cancel` — untouched |

**New dependency: `sale_stock`.** `depends` =
`base, product, stock, sale, fleet, mail, sale_stock`.

## 1. Data model

### `dsd.delivery.run`
- `route_id` (delivery-planning route — see D14 sources), `source_tour_id`
  (m2o `dsd.tour` from step 5 — provenance snapshot), `execution_date`,
  `company_id`, `warehouse_id` + `picking_type_id` (grouping key,
  compatibility constraints respected)
- `driver_id` (m2o res.users, checked against `route.driver_ids` —
  warning, non-blocking), `vehicle_id` (m2o `fleet.vehicle`, domain
  company-match + active)
- `batch_id` m2o `stock.picking.batch` — **created automatically when the
  run's pickings are batch-compatible; if not (mixed op-types), the run
  runs WITHOUT a batch** and drives pickings directly — both paths behave
  identically at the DSD level (batch is a WH convenience, not a
  requirement)
- `state` sel draft/ready/cancelled — the BACK-OFFICE lifecycle
  (draft→ready confirmed by the operator; cancelled = office cancel)
- `readiness_status` sel not_ready/warnings/ready — **computed**, from
  the per-picking matrix below (independent of `state`; a draft run can
  show `ready`)
- `stop_ids` o2m; chatter (assignment, readiness, prepare/cancel audits)

### `dsd.delivery.stop` — one DELIVERY ADDRESS on a run
- Identity: `(run_id, delivery_partner_id, sales_area_id)` — the **address
  record** (delivery partner/contact), NOT address text; two different
  delivery addresses of one customer = two stops. Snapshot chars
  (name/address/phone) frozen for history only.
- `sequence` (route-membership order; differing memberships across a
  stop's orders → first order's membership wins, warning logged),
  `picking_ids` m2m, `state` sel open/prepared (delivery outcomes are
  step-9 territory)

### `dsd.delivery.prepare.request` + `.job`
- Request: `date`, `warehouse_ids`, state; creates jobs only.
- Job: **slice = warehouse × route** but a job MAY create several runs
  when op-type/date differ within its slice (job ≠ grouping key); own
  transaction per job, per-job state pending/running/done/error + error
  text; retry re-runs ONLY failed jobs; an advisory lock
  (`pg_try_advisory_lock` on the request) prevents concurrent prepares;
  **no manual commits**; cron picks pending jobs one per worker run.

## 2. Business rules (final)

**Input domain (exact):** pickings where — sale order state = `sale`;
picking `picking_type_id.code = 'outgoing'` AND
`picking_type_entreprise_picking_type != internal/other DSD flows`
(customer delivery op-types only); `company_id` + `warehouse_id` in the
request; `state not in (done, cancel)`; not already linked to a
non-cancelled run (via `dsd.stop.picking_ids`). Orders whose pickings are
all done/cancelled are naturally absent.

**Execution date:** `commitment_date` (Datetime) converted to Date in the
**company timezone**; **missing commitment_date → the order is NOT
silently dated otherwise** — it lands on the request's exception list
("no delivery date") for the officer to set (order stays untouched).

**Idempotency at PICKING level:** new picking → add to the existing stop
(backorder of an already-stopped order lands in ITS stop); no stop yet →
create stop; already-linked picking → skipped; done/cancelled → excluded
from active preparation.

**Readiness matrix (computed `readiness_status`):** every active picking
`assigned` → ready · any `partially_available` or shortage (demand −
reserved > 0) → **warnings (never ready)** · any `waiting/confirmed` →
not_ready · `done/cancel` excluded from the computation.

**Operator confirmation:** `dsd_ready`-style flag REMOVED — `state:
draft→ready` is the operator's confirmation action (UserError if
readiness_status ≠ ready… warnings allowed only with an explicit
override reason, logged in chatter).

**Cancel run:** sets state=cancelled, **detaches pickings (removes from
stops), cancels NOTHING in stock** (no picking/move/order cancel —
independent lifecycles); the batch, if any, is left to WH (unlinked);
stops+snapshots retained for audit; freed pickings re-enter the next
prepare normally.

**Shortage computation:** per product, demand (ordered qty) − reserved
qty on the picking's moves; listed per stop.

**Grouping key** (unchanged): (company, warehouse/op-type, route,
execution_date); two tours same day on one route ⇒ **one run** (merged by
the key — `source_tour_ids` m2m keeps both provenances).

## 3. Views (back-office)

- DSD → Operations → Delivery Runs: list/kanban by `state`, readiness
  badge from `readiness_status`, filters date/route/driver/warehouse,
  Today default
- Run form: header (route/date/driver/vehicle/warehouse, source tours),
  Stops tab (sequence, address snapshot, pickings per stop, shortage
  badges), readiness panel with the per-picking matrix, exceptions list
  (no-date orders), **Pick List / Load List = REPORTS ONLY** (QWeb print;
  no validation action attached)
- Prepare wizard (date + warehouses) → request form showing jobs and
  their states; failed jobs retryable individually
- Access: officers manage runs/stops/prepare (`ru`), warehouse users read
  + print lists (`r`), admin `crud`; drivers see nothing here (step 9
  brings them in)
- Runs appear in the monitoring console (roadmap step 7 / issue #8)

## 4. Tests

1. grouping key incl. two-tours-one-route merge (both source tours kept)
2. stop identity: two delivery addresses of one customer → two stops;
   address text edited later → snapshot unchanged
3. backorder of an already-prepared order lands in the EXISTING stop
   (picking-level idempotency); re-run adds nothing duplicated
4. concurrent prepares: advisory lock — second request waits/fails
   cleanly; no duplicate picking membership (DB uniqueness on the m2m)
5. readiness matrix: all assigned → ready; one partially_available →
   warnings and state→ready blocked without override; shortage listed
6. order without commitment_date → exception list; not silently included
7. cancel run: pickings detached & un-cancelled, stock untouched,
   re-prepare admits them again
8. prepare never validates anything: no picking reaches `done`, no stock
   move is posted (assert states unchanged)
9. volume smoke: 100 orders / 3 routes / 2 warehouses / mixed op-types
   via request+jobs; per-job isolation (one failing job doesn't poison
   siblings); retry fixes only it
10. driver-permission warning fires (non-blocking); vehicle domain
    filters inactive/other-company

## 5. Definition of done

- [ ] Fresh-DB install; full suite green (roadmap steps 1–8)
- [ ] Officer walkthrough scripted-test: day's orders → prepare → assign
      → ready (one shortage path with override + one exception order)
- [ ] `depends = base, product, stock, sale, fleet, mail, sale_stock`
- [ ] No `action_done`/PGI anywhere in the new code (assert in review)
- [ ] Runs visible in the monitoring console
- [ ] PR to `main` with screenshots (run form + stops, prepare wizard)

## Out of scope (explicitly)

Mobile delivery execution (step 9: attempts, GPS, partial/failed
outcomes, returns chained to original picking + reference invoice,
backorder disposition), van sales (step 10, held), invoicing/payments
(step 11), route optimization, POD photos/signatures, load VALIDATION
(lists are reports), empties.

## References

- Review round 4 (2026-11-19): all criticals adopted — picking-level
  idempotency, readiness matrix (partially_available ≠ ready),
  action_done/PGI exclusion, job transaction guarantees + advisory lock,
  address-record stop identity, cancel-detach semantics, state/
  readiness split, input domain exactness, commitment_date exception
  policy, numbering fixed (roadmap step 8 ↔ GitHub issue #9 ↔ builds on
  issues #6/#8), survey baseline pinned
- v1 legacy batch mapping (branch `dsd-v1`) reused for WH convenience
- SAP live checks 2026-11-19 (LIPS/TVLK; queries in
  `docs/reviews/sap-verification-2026-11-18.md`)
