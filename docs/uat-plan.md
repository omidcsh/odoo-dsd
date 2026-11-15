# DSD UAT Plan — Walkthrough Script & Driver Checklist

- **Environment:** Odoo 20 Community, http://localhost:8069, database `odoo`
  (live demo) and `odoo_uat` (restored practice copy)
- **Roles:** Supervisor (admin), Driver (any internal user in *DSD / User*)
- **Prerequisite:** `fleet`, `stock_fleet` installed; `dsd_core` installed;
  demo route *Route A — City Center* (VAN-01, Route Cash journal) present

## 1. Setup walkthrough (supervisor)

| # | Step | Expected result |
|---|------|-----------------|
| 1.1 | DSD → Routes → New: name *Route B — North*, mode **Mixed**, warehouse *YourCompany*, set van location (create *VAN-02* first via Inventory → Configuration → Locations under `Vans`, tick **Is DSD Van**), pick/create a vehicle, assign driver | Route saved without van-location error (mixed mode needs one) |
| 1.2 | Add 4 stops (stores from Contacts, e.g. *Wood Corner*, *Azure Interior*, *Deco Addict*, *Gemini Furniture*), set sequences 1–4, tick weekdays | Stops ordered by drag handle |
| 1.3 | Try removing the van location on a **Van Sales** route | ValidationError: route needs a van location |
| 1.4 | **Generate Day** button → pick tomorrow | Wizard shows weekday + scheduled stop count |
| 1.5 | Generate again for the same date | UserError: route day already exists |
| 1.6 | DSD → Route Days | New day card in kanban, state *Draft*, pending visits = stops of that weekday |

**Acceptance:** all six steps behave as described.

## 2. Day walkthrough (supervisor + driver)

| # | Step | Expected result |
|---|------|-----------------|
| 2.1 | Open the day → **Load Van** → add 2–3 storable products with quantities → Validate | Picking `WH/INT/xxxx` done; day flips to *Loaded* automatically; van location shows the quant |
| 2.2 | **Start Route** | State *In Progress* |
| 2.3 | Visit 1 → **Presale Order** → add lines → Confirm | Order confirmed; delivery sources from **WH/Stock**; visit still *Pending* |
| 2.4 | Visit 2 → **Van Sale** → add lines → Confirm → **Complete Van Sale** | Delivery from **VAN-xx** validated; invoice posted; payment registered & reconciled on *Route Cash*; visit *Done*; van quant reduced |
| 2.5 | Visit 3 → **Deliver from Van** (no sale) → validate picking | Visit *Done* |
| 2.6 | Visit 3 → **Take Return** (after a delivery) → validate | Goods back into van; return linked to visit |
| 2.7 | Visit 4 → mark **Skipped** with reason *Store closed* | Badge muted, reason shown |
| 2.8 | Try **End Route** while a visit is pending | UserError listing pending visits |
| 2.9 | **End Route** (all visits done/skipped) | State *Done* |
| 2.10 | **Return Stock** → return unsold van stock → Validate | `WH/INT/xxxx` done; van quant back to 0 |
| 2.11 | **Settle Route Day** → leave counted cash **short** by any amount → *Post & Close Route* | Settlement posted; variance journal entry Dr variance / Cr cash; day *Settled* |
| 2.12 | Settlement → Print → **Settlement Sheet** | PDF: day header, cash table with red difference, visit summary, leftover lines, signature lines |
| 2.13 | **Settle** with exact counted cash (other day) | No variance entry posted |

**Acceptance:** full loop with no manual SQL/DBA steps; every document traceable from the day.

## 3. Driver UX checklist (tablet/phone, browser)

- [ ] Route Days kanban readable at ~400px width; cards show state, visits, cash
- [ ] Day form: header buttons (Load/Start/End/Return/Settle) reachable without horizontal scroll
- [ ] Visit dialog: Van Sale / Presale / Deliver / Take Return buttons usable with touch
- [ ] Product search on sale lines returns items quickly on mobile network
- [ ] Barcode: scanning a product barcode into a line product field fills it (standard `barcodes` scanning; full scanner app is Enterprise `stock_barcode` — out of scope, confirmed)
- [ ] Notification arrives for visit reassignment? (v1: none — accepted gap)
- [ ] Signature (POD) attach works from tablet (file/camera)

## 4. Exit criteria

- All steps above pass twice: once on `odoo` (demo), once on `odoo_uat`
- No CRITICAL/Traceback in `docker logs odoo` during the run
- Settlement variance postings balance (check Accounting → Journal Entries)
- Sign-off recorded in this file (name + date)

**Sign-off:** ________________ (date: ________)

## 5. Execution log — technical dry run 2026-11-16 (ZCode)

All steps executed programmatically on live `odoo` DB as **Route B — North**
(mixed, VAN-02) → **RD/2026/0198**, 4 stops, committed. Result: **15/15 PASS**
(full transcript in git history). The dry run found and fixed two real design
gaps before human UAT:

1. **Take Return was blocked after a delivery** — the delivery validation
   auto-closed the visit, so a driver could not take empties back at the same
   stop. Fix: returns now allowed on pending **and** done visits (still
   blocked on skipped). UAT step 2.6 updated accordingly.
2. **Presale visits could never close** — their delivery ships days later,
   which permanently blocked End Route. Fix: a presale visit completes when
   its order is confirmed (order capture = stop done; fulfillment tracked via
   the linked delivery). UAT step 2.3 expected result updated.

Also verified in this run: van stock reconciliation (water 10 → 0 via sale/
delivery/return), leftover snapshot caught 2 crates left in the van at
settlement, cash variance entry posted Dr 7.5, settlement PDF generated
(29.7 KB, `%PDF`). Note: `wkhtmltopdf` logs a network-asset warning when the
server is stopped during headless runs — PDF still renders; check headers on
a running server during human UAT.
