# [Step 8 — DEV TASK] Delivery preparation & mobile delivery readiness (`dsd_core`)

> Eighth development task. Master plan: #1 · Builds on #6 (orders on
> visits), #7 (API), #8 (monitoring). The VAN-sales draft stays ON HOLD —
> this step delivers from the WAREHOUSE (classic presales fulfilment), no
> van stock, no COCI, no money (sales collects nothing for now).
> Spec version: draft v1 (2026-11-19) — **pending approval before posting**.

## Goal

Close the physical half of the sales scenario:

1. **Back-office prepares deliveries** from the confirmed presale orders —
   grouped, checkable, assignable to a driver + vehicle + date
2. **The backend is ready for the mobile DELIVERY scenario**: a deliveryman
   downloads his delivery run, confirms each stop with GPS, handles
   partial/failed deliveries and doorstep returns — all online (D8)

## 0. Odoo-native survey (standing rule)

| Concern | Native | Verdict |
|---|---|---|
| Order → delivery | `sale_stock`: confirming a sale.order creates the outgoing picking | ✓ reuse (already in depends since step-8-draft… via `sale_stock`) |
| Grouping runs | **`stock.picking.batch`** — native batch of pickings | ✓ reuse = the delivery RUN (route+date+driver+vehicle); v1 legacy module already proved this mapping |
| Run assignment | x-fields on batch: driver (res.users), vehicle (fleet.vehicle), route (dsd.route), execution_date | ✓ light extension |
| Delivery confirm | picking `button_validate()` | ✓ reuse; app endpoint wraps it |
| Failed/partial | native: partial validate (backorder) + cancel with reason (x field) | ✓ reuse |
| Doorstep return | native return picking (customer→WH) | ✓ reuse |
| Invoicing | deferred entirely (sales collects no money — user 2026-11-19) | — |

**New dependency: `sale_stock`** (delivery flow). `depends` becomes
`base, product, stock, sale, fleet, mail, sale_stock`.

## 1. Delivery preparation (back-office)

1. **Prepare action** (on confirmed orders / per route+date): creates the
   outgoing pickings (if not auto) and groups them into a
   `stock.picking.batch` "Delivery Run" for `(route, date)`: fields
   `driver_id`, `vehicle_id` (optional — walk-in routes), `route_id`,
   `execution_date`, `state` (draft/ready/in_progress/done — native batch
   states reused).
2. **Readiness checks** before marking ready: all orders confirmed; all
   pickings assigned to the run; products available in WH (else the run
   lists shortages as warnings, not blockers).
3. **Pick list / load list view**: the warehouse sees the run's pickings
   (per customer stop) and stages goods — no van location, no loading
   document (held with van step).
4. Runs appear in the monitoring console (#8) alongside sales tours.

## 2. Mobile delivery API additions (v1.3 — extends #7)

| Endpoint | In | Effect |
|---|---|---|
| `POST /delivery/day/get` | `{date}` | the caller's delivery run: batch + stops (customer snapshot, SA, items with qty/UoM), run state |
| `POST /delivery/stop/confirm` | `{client_uuid, picking_id, gps?, delivered_qty[]?, occurred_at}` | validates the picking (full or **partial → backorder** per native flow); stamps GPS + time on the stop |
| `POST /delivery/stop/fail` | `{client_uuid, picking_id, reason, gps?, occurred_at}` | marks the stop failed — picking cancelled with reason (native cancel + x-reason), order flagged `delivery_failed` for the office |
| `POST /delivery/return/pickup` | `{client_uuid, picking_id, reference_invoice_id?, lines[]}` | doorstep return: creates the native **return picking (customer→WH)** linked to the visit's order/`dsd_reference_invoice_id`; goods receipt when WH validates |
| `POST /delivery/run/close` | `{client_uuid}` | run done: remaining stops must be terminal (delivered/failed) |

Idempotency + envelope per #7 §1.9; driver scoping per #7 §2.1 (run
`driver_id = uid`).

## 3. Behavior rules (final)

| Topic | Rule |
|---|---|
| Source of stops | ONLY confirmed presale orders of that route+date — no ad-hoc sales on the delivery app in v1 |
| Partial delivery | allowed via native backorder; the backorder picking stays on the SAME run |
| Failed stop | never deletes data — picking cancelled with reason, order flagged, office follows up |
| Returns at doorstep | reference invoice REQUIRED (ties into #7 `/returnable_invoices`); goods receipt at WH validation — credit/money untouched |
| No money | no invoice, no payment, no COCI anywhere in this step |
| GPS | every stop action stamps GPS + time (same store as #7; feeds the live map) |

## 4. Tests

1. prepare run: confirmed orders of route+date → one batch, stops ordered
   by route membership sequence; unconfirmed orders excluded
2. readiness: shortages warn but do not block; missing driver does not
   block prepare (blocks download)
3. partial stop confirm → backorder picking on same run
4. fail stop → picking cancelled + reason + order flagged
5. doorstep return with reference invoice → return picking to WH; without
   valid reference → rejected
6. run close blocked while a stop is open
7. API (HttpCase): day/get scoping (driver B gets 404 on driver A's run),
   stop confirm idempotent, GPS stamped

## 5. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–8)
- [ ] Scripted delivery day as a test: prepare → 3 stops (1 partial, 1
      failed, 1 delivered) + 1 doorstep return → close run
- [ ] `depends = base, product, stock, sale, fleet, mail, sale_stock`
- [ ] Runs visible in the monitoring console
- [ ] PR to `main` with screenshots (run form, stop list, console)

## Out of scope (held or later)

Van stock/van locations/loading/COCI/reload (held van draft), invoicing &
payments (no money for now), route optimization, time-windows, proof-of-
delivery photos/signatures, printing, empties.

## References

- User directive 2026-11-19 (no money; delivery prep + mobile delivery
  readiness) · registry `MSE_DELIVERY_HEADER/_ITEM/_COND`,
  `MSE_REFERENCE_INVOICE*` · MDSD `DeliveryManager` (GetDelivery/Create/
  Cancel-with-reason — semantics reference) · v1 legacy `dsd_tour` on
  `stock.picking.batch` (branch `dsd-v1`) — the batch mapping is REUSED
  here, this time for delivery runs
