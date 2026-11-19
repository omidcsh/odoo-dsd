# [Step 8 — DEV TASK] Distribution & van sales — material side (`dsd_core`)

> Eighth development task (renumbered 2026-11-19: the monitoring console became step 7). Master plan: #1 · Builds on #5 (partner
> geo/SA), #6 (presales day: tour/visit/orders), #7 (API v1.1).
> Spec version: draft v1 (2026-11-19) — **pending approval before posting**.

## Scope decision (the cut)

Distribution splits cleanly along M05/M08 lines: **this step = MATERIAL**
(van stock, loading, van-sale delivery, FINAL return fulfilment, reload,
check-out/in counts); **money (cash float, cheques, settlement run) = step
9**. The M05 `CASH/` location joins step 9 with the float it carries.

- Odoo 20, Community-compatible, LGPL-3. **New dependency: `sale_stock`**
  (native delivery flow; pulls `account` for credit notes). `depends`
  becomes `base, product, stock, sale, fleet, mail, sale_stock`.

## 0. Odoo-native survey (standing rule)

| Concern | Odoo 20 native | Verdict |
|---|---|---|
| Van stock | `stock.location`/`quant` — the whole logistics backbone | ✓ reuse; van = internal location tree per vehicle |
| Load/reload/unload | `stock.picking` warehouse↔van | ✓ reuse (picking types seeded) |
| Van-sale delivery | `sale_stock` delivery picking, source overridden to the van location | ✓ reuse |
| Returns FINAL | native return picking + refund credit note (`account.move` reversal) | ✓ reuse — this IS the final design step 6 deferred |
| Stock types (free/reserved/blocked/…) | none native | sub-locations per M05 §3.1 (device contract "1".."5") |
| COCI counts | none native (`/DSD/ME_COCI_HD`: tour, check_direct, checker, date/time, plant) | custom light `dsd.coci` — material side only |
| Batch/lot | `stock.lot` + product tracking | ✓ reuse |

## 1. Business rules — FINAL (D12)

| Topic | Rule |
|---|---|
| Van location | created automatically when a `fleet.vehicle` gets `is_dsd_van`; tree `WH/VAN/{code}/{FREE,RESERVED,BLOCKED,EMPTY,LOSS}/` (M05 §3.1; `CASH/` joins step 8) — exact names, `allow_negative=False` on every node |
| Stock type | determined ONLY by sub-location — never a field on quant/line |
| Negative van stock | forbidden — no force flag, at location level |
| Loading | picking `VanLoad` (wh STOCK → van FREE) before/at tour start; tour may not `run` without a load |
| Delivery | from the VAN of the visit's tour only (source override on the sale.order delivery) — availability checked on van stock |
| Return fulfilment (FINAL) | `dsd_is_return` orders (from step 6) get: return picking customer→van (BLOCKED if damaged) → at check-in unload van→wh → **refund credit note** via native reversal; the interim flag becomes fully realised |
| Reload | mid-day picking `VanReload` (wh STOCK → van FREE) — v1 same flow as load; the mirrored device state machine is NOT built (API concern later) |
| Check-out/in (COCI material) | count document per tour+direction (`/DSD/ME_COCI_HD` shape); lines = system qty vs counted qty vs difference + reason; differences generate DRAFT inventory adjustments (loss location) — never auto-validate |
| Money | NOTHING financial in this step (cash float, payments, settlement = step 8) |

## 2. Data model

- `fleet.vehicle` (extends step 5): `is_dsd_van` now also builds/maintains
  the location tree (`van_location_id` m2o stock.location stored).
- **Picking types (seed data, per company):** `VanLoad`, `VanDelivery`,
  `VanReturn`, `VanUnload` (van→wh STOCK), `VanReload` (alias flow of load
  in v1).
- `dsd.tour` extensions: `load_picking_id`, `coci_out_id`/`coci_in_id`,
  `van_location_id` (related via vehicle).
- **`dsd.coci`**: `tour_id`, `direction` sel out/in, `checker_id`
  (res.users), `checked_at`, `warehouse_id` (=PLANT), `state`
  draft/confirmed; **`dsd.coci.line`**: `coci_id`, `product_id`, `lot_id`
  (per tracking), `system_qty`, `counted_qty`, `difference` (computed),
  `reason` (required when difference ≠ 0), `adjustment_id` (draft
  `stock.inventory`-equivalent — Odoo 20: inventory adjustment via
  `stock.quant` inventory mode; spec: draft quant adjustments).
- `sale.order` (extends step 6): `dsd_is_return` orders gain
  `return_picking_ids`; refund credit note created at check-in confirm via
  standard reversal wizard programmatically.

## 3. Lifecycle

```
load (VanLoad confirmed) → tour running
   ├─ deliveries (van→customer) + returns (customer→van)
   ├─ reload (mid-day, optional)
   └─ check-in: COCI-in count → differences → draft adjustments
        → unload (van→wh) → tour done → refund credit notes issued
```

COCI-out (start count) optional in v1 (`COCI_METHOD` customizing arrives
with the API step); COCI-in mandatory before `done`.

## 4. Mobile API additions (v1.2 — extends #7)

| Endpoint | Effect |
|---|---|
| `POST /tour/load/confirm` | validates the VanLoad picking (idempotent) |
| `POST /delivery/confirm` | validates the order's van delivery (+ GPS optional) |
| `POST /return/confirm` | validates the return picking into van |
| `POST /reload/confirm` | validates VanReload |
| `POST /tour/checkin` | submits COCI-in lines; server computes differences, creates DRAFT adjustments + unload picking + credit notes on confirm |

## 5. Tests (`TransactionCase` unless HTTP noted)

1. flagging a vehicle `is_dsd_van` builds the exact M05 tree (names,
   allow_negative False); unflag archives it
2. tour cannot `run` without a confirmed load
3. delivery source = the tour's van; van stock decremented, customer
   delivered; delivery from another van impossible
4. negative van stock rejected at location level
5. return order → picking into van BLOCKED/… → check-in → unload →
   **refund credit note exists and links the order** (final return path)
6. COCI-in: counted < system → difference line + reason required → draft
   adjustment created, NOT validated; zero-difference needs no reason
7. reload adds van stock mid-day
8. API (HttpCase): load/delivery/return/checkin endpoints idempotent;
   checkin computes differences server-side

## 6. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–7)
- [ ] Scripted distribution day: load → 2 deliveries + 1 return → reload →
      check-in with one difference → unload → credit note — as a test
- [ ] `depends = base, product, stock, sale, fleet, mail, sale_stock`
- [ ] D12 rules each covered by a test
- [ ] PR to `main` with screenshots (van tree, COCI form, return refund)

## Out of scope (do NOT build)

Cash float + `CASH/` location, payments/cheques, settlement run (step 8),
empties balances beyond the EMPTY/ location, HANDOVER transit location,
mirrored reload state machine, ATP/quota on van, promotions/deal engine,
API GPS/OTP additions beyond the above.

## References

- Package M05 §3.1 (location tree — authoritative names), §3.4–3.7 · M08
  §3.1 (COCI field tables — material subset adopted) · 11-IMPL §2.5
- SAP live check 2026-11-19: `/DSD/ME_COCI_HD` (tour/check_direct/checker/
  date/time/plant) — header shape matched
- MDSD: agent-notes 06 (van stock model, stock types "1".."5")
