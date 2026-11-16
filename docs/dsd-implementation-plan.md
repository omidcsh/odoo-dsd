# DSD (Direct Store Delivery) on Odoo 20 — Comprehensive Implementation Plan (v2, from scratch)

- **Date:** 2026-11-16 · **Status:** IN DELIVERY — Phases 0–2 complete (2026-11-16).
  Supersedes all prior plans and the `dsd_core` prototype.
  Phase 0 done: master data, security, settings, menus (62-test base).
  Phase 1 done: visit control — plan types (role matrix), plans (weekly/rrule,
  holiday policies, exceptions), lists with SAP visit statuses, appointment time
  stream + cron, generation wizard (dry-run/watermark), sale-order proposals.
  Phase 2 done: tours on stock.picking.batch (lifecycle, route/list links, co-driver,
  trailer, seals), SAP shipment validations incl. licenses/locks, van load-out
  aggregation picking with van-location isolation, speculative load wizard, dynamic
  tour generation (capacity order weight→volume→stops→duration→LU, attempts,
  include-new-customers), materials overview, tour kanban/list/search.
  **62/62 tests green** on clean install; live smoke: candidate selection → tour
  generated with clean log.
  Pending AC: manual browser pass over tour screens (§4.4 headless caveat).
- **Target stack:** Odoo 20.0 Community (docker: `~/odoo-docker`, Postgres 16), local git only
- **Built from:** full analysis of `sap-dsd/` reference set —
  SAP Help *Direct Store Delivery* (EHP8 SP25), *SAP DSD Configuration* guide + SP01/SP02/SP03 deltas,
  *SD Practical Guide*, *Basic Functions & Master Data in SD*, and
  `sap-dsd/Planning/sap-dsd-sd-capability-priorities.md`.
- **Everything below is a fresh design.** The previous `src/dsd_core` module is discarded
  (see §19.3 Removal of the previous prototype). A few of its environment lessons are kept (§4.4).

---

## 1. Executive summary

Direct Store Delivery is the consumer-goods distribution model where the producer delivers
straight to the retail outlet, bypassing the retailer's distribution centers. The SAP reference
decomposes it into four pillars; this plan implements each natively on Odoo 20 Community:

| SAP DSD pillar | Odoo 20 implementation |
|---|---|
| **DSD-specific master data** | Extensions of `res.partner`, `product.template`, `fleet.vehicle`, `hr.employee` + new `dsd.*` config models |
| **Tour preparation** (Visit Control + Transportation Planning + Output Control) | `dsd.visit.plan` → `dsd.visit.list` generation; tours built on **`stock.picking.batch`** (with `stock_fleet` vehicle/driver/capacity) + new `dsd.route` master; QWeb tour documents |
| **Tour execution** (loading, check-out/in, reload, van stock, driver activities) | Van = internal **stock location** per vehicle; loading confirmation, check-out/check-in, reload documents; **driver console** — a mobile-first web UI on top of Odoo (online; offline-capable API later) |
| **Route accounting** (difference determination, final settlement run, collection clearing) | `dsd.settlement` per tour with tolerance-based variance engine, one-shot settlement run creating invoices / payments / journal entries / goods movements, and reconciliation of collections |

All four SAP driver roles are first-class in the data model from day one
(**preseller, delivery driver, van seller, mixed driver** — §2.2), even though operational
workflows are phased.

**Delivery approach:** 8 phases (§21), each ending demo-able and tested. Estimated ~46–60 focused
engineering days for the full scope in §3 (P0+P1); §3.3 lists what is deliberately deferred.

---

## 2. Scope and operating decisions

### 2.1 Business process in scope (target picture)

One DSD cycle:

```
Strategic:  visit plans (recurring customer visit patterns per route/role)
              │  (cron / wizard, execution date)
Operational: visit lists ──┬─> orders from presellers ──> confirmed sale orders
                          │        (next-visit-date & route proposal at order entry)
Load-out:   deliveries due → tour (stock.picking.batch) per route/date/driver/vehicle
              → pick & load WH→Van → loading confirmation (counting groups, seals)
              → CHECK-OUT (van stock + opening cash)
On tour:    driver console per stop: arrival → delivery actuals / van sale /
              returns / empties / new order / invoice / collection / expenses /
              odometer / inventory adjustments / unplanned visits / resequencing
              (mid-tour RELOAD supported)
Return:     CHECK-IN (van stock + cash count) → unload Van→WH
Settlement: tour data review → DIFFERENCE DETERMINATION (qty + cash, tolerances)
              → release → FINAL SETTLEMENT RUN (docs, invoices, payments, GI,
              interim postings, collection clearing) → settlement document + log
```

### 2.2 Driver roles (SAP "Use of Roles in the DSD Process")

| Role | Delivers pre-sold? | Sells from van? | Defining document | Load model |
|---|---|---|---|---|
| Preseller | No (takes orders) | No | Visit list | none |
| Delivery driver | Yes | No | Tour (shipment) | per-order deliveries loaded |
| Van seller | No | Yes (speculative load) | Visit list | speculative load owned by driver |
| Mixed driver | Yes | Yes | Visit list + tour | both |

The role is a property of the **visit plan type** (`dsd.visit.plan.type`, §8.1) and drives:
which activities the driver console offers per stop, whether a tour/shipment is required,
how settlement bases its reconciliation, and how the load is picked (§6 Tour types).

### 2.3 Operating decisions (boundaries fixed now to prevent drift)

1. **Online-first execution.** SAP supports an offline mobile client (download/upload at tour
   boundaries). We run an **always-online mobile web console** inside Odoo; all "download/upload"
   concerns collapse into normal ORM transactions. A versioned JSON API (§18) is designed so an
   offline PWA/native shell can be added later without schema changes.
2. **Paper fallback = same cockpit.** SAP's "paper-based" variant is covered by letting the
   back office enter identical data on the settlement screens after the tour (§13.4), plus
   printable tour documents (§15).
3. **Van sales without POS.** POS is a cash-register paradigm (anonymous retail). DSD van sales
   are B2B: `sale.order` → delivery from van → `account.move` invoice → `account.payment`
   collection against receivables. (Keeps credit, returns, and settlement semantics intact.)
4. **Goods issue timing.** SAP offers "late GI at settlement" for van sales. We validate the
   physical stock move **at visit confirmation** (real-time van stock truth) and keep the
   *financial* postings (invoice/payment/GI-accounting) for settlement. Rationale in ADR-107.
5. **Single company / single warehouse first**, multi-company-safe field definitions throughout
   (`company_id` on every new model), since Odoo handles record rules cheaply when fields exist
   from day one.
6. **Fiscal localization:** rely on standard Odoo `account` taxes/fiscal positions per country;
   DSD adds nothing country-specific (per priorities-doc §7: keep country config out of logic).

---

## 3. Capability inventory & dispositions (the "forget nothing" ledger)

Every capability found in the SAP reference docs is listed with a disposition:
**[B]**uild now · **[S]**implify now (explicit Odoo-native re-design) · **[D]**efer (phase-gated) ·
**[X]** exclude (with reason).

### 3.1 Basic settings & activation (SAP "Basic Settings in the DSD Process")

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Activate DSD / EA-SCM switch | [B] | `res.config.settings` DSD block (§7.1): enable DSD, enable van-stock visibility, default warehouse, tour-doc triggers |
| Activate "Single Sales Area Processes" | [S] | Simplification: one `sales.team`-based sales area per route; check "driver's team == order team" at tour build (ADR-109) |
| Activate Vehicle Space Optimization | [X] | Third-party packing optimizer integration; Odoo `product.packaging` carries carton/pallet dims for a future hook (§3.4) |

### 3.2 DSD master data (SAP "DSD-Specific Master Data")

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Customer: DSD "Additional Data" — visit info | [B] | `res.partner` DSD tab (§7.2): route, geocode, receiving hours, unloading point/contact, payment collection profile |
| Customer geocoding (lat/lng, report, map) | [B] | `base_geolocalize` (`partner_latitude/longitude`) + bulk geocode wizard + Google-Maps link on visit lines |
| Enhanced terms of payment (payment behavior, permitted payment types, invalid bank data, document transfer) | [B] | Partner fields: `dsd_collection_type` (none/on-delivery), `dsd_accepted_payment_methods` (m2m journal), `dsd_pod_or_invoice` (POD/Invoice), `dsd_invoice_generation` (auto/manual/consolidated), `dsd_cash_only` |
| Driver master (in customer master, account group, license categories, lock times, planning-point access, single company) | [B→S] | Driver = **`hr.employee`** extension `dsd.driver` (§7.3) — NOT a partner; optional auto-created settlement partner for cash custody postings; `license_category_ids`; lock periods via `hr.leave` on DSD absence type |
| Driver's license categories customizing | [B] | `dsd.license.category` model; required categories on vehicle; tour validation |
| Vehicle master (equipment/fleet): trailer load, own/external, variable capacity, VSO type, planning points, license categories, lock periods | [B→S] | `fleet.vehicle` extension (§7.4) + `fleet.vehicle.model.category` (payload, volume — used by `stock_fleet` capacity %); `van_location_id` auto-created internal location (ADR-102); trailer = second vehicle of type trailer |
| Vehicle lock periods | [B] | `dsd.lock.period` generic (resource on vehicle or driver: date from/to + reason); excluded from tour defaults |
| Tour master data (header: route × visit-plan-type uniqueness, planning point, capacity limits stops/duration; individual tour: driver1/driver2/vehicle/trailer/sequence, drag-sequence) | [B→S] | Split: `dsd.route` (strategic route template + stop pattern defaults + capacities, §7.5) and operational tour = `stock.picking.batch` extension (§9). Co-driver field `dsd_driver2_id`. Sequence = picking `batch_sequence` (stock_fleet) |
| Material DSD data: DSD grouping (calendar type), counting group, tolerance type | [B] | `product.template` DSD tab (§7.6): `dsd_group_id`, `counting_group_id`, `tolerance_type_id` |
| Aggregation categories (4 totals categories, e.g. crates; computed on order/delivery/tour) | [S] | `dsd.aggregation` config (≤4 categories, name+uom) + `dsd_aggregation_ids` on product; **computed totals on tour** only (SAP computes on order+delivery+tour; we show on tour & visit list — decisions need it at load time) |
| Loading units (independent UoM, conversion factor, divisor; LU groups) | [S] | Use `product.packaging` (qty per package) + product `uom` conversions; tour capacity in LU computed from packaging (§9.4) |
| Counting groups + UoM hierarchy for counting (count pallets then crates) | [B] | `dsd.counting.group` with ordered `uom_ids` (hierarchy) + factor checks (§7.7); used in loading confirmation and check-out/in |
| Empties BOM (tied empties explosion on orders/deliveries/invoices; untied empties as normal materials) | [B/D] | Tied empties via `mrp.bom` type *empties* on the full product (e.g. case → 24 bottles + 1 crate); explosion displayed on visit lines & delivery as sub-lines; **deposit pricing + returns in Phase 6** (§14) |
| Trade assets (SP01: equipment placed at customer, notification types) | [D] | Phase 8: `dsd.trade.asset` (product × serial × partner, placement/pickup moves, issue notification) |
| Statistical data on device (sales history, avg qty/week) | [B] | Driver console "customer statistics" panel from `sale.order.line` history aggregated per customer×product (SQL view `dsd_customer_product_stat`, §12.7) |

### 3.3 Visit Control (strategic + operational planning)

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Visit plan (strategic): validity, plan type/group, sales area, shipment defaults (driver/vehicle/route), header appointment rule (e.g. every 2 weeks Tue), calendar + non-working-day policy, texts | [B] | `dsd.visit.plan` (§8.2): recurrence = weekday set + interval weeks (the 98% DSD case) **or** full `dateutil.rrule` string for exotic cycles; non-working-day policy (skip/previous/next) using `resource.calendar.leaves` |
| Plan items: customer worklist + drag&drop itinerary, waiting time, travel duration, unloading point/contact person defaults, receiving-hours display, inactive flag, item-level non-appointments, customer texts | [B] | `dsd.visit.plan.line` ordered (`sequence`), handle='sequence' drag; defaults from plan type; `inactive`; `exception_ids` (dates to skip) (§8.3) |
| Change protection when future lists exist (dialog "lists already generated") | [B] | `write()` guard counts generated lists → confirmation wizard (§8.6) |
| Visit list (operational): generated per execution date, editable (driver/vehicle/trailer, add/remove customers, resequence, postpone, inactive), texts | [B] | `dsd.visit.list` + `dsd.visit.list.line` (§8.4); statuses draft→confirmed→started→done→cancelled |
| List generation: simulation (no write), log of errors, no double generation for same date, "valid-from empty = day after last generated" | [B] | Wizard `dsd.visit.list.generate` with `dry_run`; per-plan generation watermark `last_execution_date`; generation log (`mail.thread` message) |
| Reference documents on lists: header (speculative load, shipment lock) & item (sample orders for presellers); post-tour refs (SD activity for failed visit) | [B→S] | Header refs: `speculative_load_picking_id`, `tour_id` (once set, list locked); line refs: order/delivery/invoice/payment links; failed visit = `dsd.visit.outcome` reason + optional CRM lead/note (§13.2) |
| Time stream / customer visit calendar (calendar types; order-entry next-visit-date + route determination; fill report/cron; customer-master calendar display) | [B→S] | Materialized `dsd.visit.appointment` (customer, date, visit_list_id?, route_id, kind=visit/delivery) generated N days ahead by cron + on-demand; `sale.order` DSD fields: proposed `commitment_date` = next appointment ≥ lead time, proposed `dsd_route_id` (§10.2); partner "upcoming visits" calendar view |
| DSD-relevant order types / allowed sales doc types / transaction types | [S] | Not needed as config: every `sale.order` from the DSD flow gets route/date proposals; the console restricts types |
| Sales-activity for unsuccessful visit + outcome→status mapping | [B] | `dsd.visit.reason` catalog + `crm` optional linkage |
| Visit plan type (role; relevant documents matrix per SAP table; "make delivery" indicator; visit-times source unloading-point vs contact; number of attempts; default waiting/travel) | [B] | `dsd.visit.plan.type` encodes the SAP matrix verbatim (§8.1) |
| BAPIs for plan/list + route-optimization tool | [S] | Public ORM methods + JSON API endpoints (§18); optimization hook `prepare_optimization_payload()` |
| Maps for plans/lists (GIS) | [S] | Google-Maps directions link per list (stop chain); embedded map deferred |

### 3.4 Transportation planning

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Shipment (V7) as tour document; DSD fields driver1/2, vehicle, trailer, sequence, route; checks (license, co-driver, trailer type, same planning point, tour exists on route) | [B] | **Tour = `stock.picking.batch`** extended (`dsd.*` fields, §9.1); `stock_fleet` already gives vehicle/driver/category capacity%/dock; add trailer, co-driver, route, checks (§9.5) |
| Shipment list | [B] | Tours kanban (status board) + tree filters (date/route/driver/vehicle/status) |
| Individual shipment processing (manual delivery assignment, planning screen, delivery/materials overview, cap-utilization columns, same-ship-to move warning) | [B] | Batch transfer UI + "Tour" smart views: drag pickings between tours; materials overview dialog (aggregated per product across pickings of the tour) |
| Dynamic Transportation Planning (collective: selection variant; group by route+date+visit-list; visit-list-based stop sequence; speculative loads; explicitly assigned deliveries; capacity-limit sequence checks; number-of-attempts skipping; distribute remainder to next shipment; include-new-customers by route; one shipment per route option; foreground/background; log) | [B] | Wizard `dsd.tour.generate` (§10.3): input date range/route(s); algorithm below; runs sync or via `ir.cron` queue; produces tours + logs; sets `tour_id` back on visit lists |
| Capacity limits: usable load, volume, stops, variable capacity, max duration, loading units; activation per planning point | [B→S] | `dsd.route.capacity` flags (§7.5): weight & volume (from `fleet.vehicle.model.category`), stops & duration (route), loading units (packaging calc); checked in tour generation in SAP's fixed order (§10.3 step 6) |
| Allowed delivery types for planning | [S] | Only outgoing `stock.picking` of type DSD-delivery (picking-type filter) |
| Route definition & determination (zones, shipping conditions, weight groups, loading groups…) | [B→S] | Collapsed into `dsd.route` assigned directly on partner (determination = partner's route, overridable per order); route = departure warehouse + planned day pattern + capacities. No zone/weight-group machinery |
| Valuated delivery note | [B] | QWeb report `dsd.report.valuated.delivery` — delivery note + price columns computed from order/pricelist (§15.3) |
| VSO (packing proposals, loading chart, HU follow-on, WM picking control) | [X] | Requires 3rd-party optimizer in SAP itself; excluded. Hook: tour payload export (JSON) documented (§18.3) |

### 3.5 Output control & documents

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Message control (condition technique, min shipping status, spool grouping, different printer, IDoc for device) | [S] | Odoo prints by action; **tour document bundle**: one click prints manifest + valuated delivery notes + check slips (grouped PDF, §15.1); optional `ir.cron` "auto-print bundles for tomorrow's confirmed tours" |
| Logistics-oriented (shipment controlling, status-gated) | [B] | Print available when tour state ≥ confirmed |
| Sales-oriented (visit-list controlling, execution-date gated) | [B] | Preseller lists printable from date X (default: today+1) |
| Driver texts (visit-plan/list header+item texts, text types) | [B] | `note`/driver-instruction fields on plan, list, line; printed on manifest |
| Invoice print at customer; reprint-as-copy | [B] | Console "print invoice"; reprints flagged *COPY* (report context flag) |

### 3.6 Tour execution

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Loading confirmation (material or counting-group level, target vs actual, show/hide target, differences → correct load or reason → interim postings, seals, delta-only on reload, authorization object) | [B] | `dsd.loading.confirmation` (+ lines) on tour (§11.2); differences either adjust the load picking or post reason-coded variance; seal numbers on tour |
| Check-out / check-in / reload check (materials **and** payment methods, checker confirmation, signatures) | [B] | `dsd.check.record` type out/in (+ `is_reload`), lines per product (counting-group aware) & per payment method; checker = any `dsd_dispatcher`/supervisor user; optional signature attachment (§11.3) |
| Stock visibility on truck (special truck stock, blocked from ATP, final unloading document, release before settlement, manual DSD goods movements, negative allowed) | [B→S] | Van internal location + `stock.quant`; ATP exclusion by using **location-restricted availability**: warehouse replenishment checks WH locations only (Odoo `_get_locations_to_unreserve`/route config); van availability only via console (checks van quants). Final unload = internal picking Van→WH `dsd.unloading` released at check-in (§11.5) |
| Reload (mid-tour stop-off, up to 99, reload document + material list, mobile stock update, debited to driver until settlement) | [B] | `dsd.reload` on running tour → internal picking WH→Van (delta), console refresh; goods stay in van location (driver custody = location itself, §11.4) |
| Tour status (cross-component status profile, follow-up activity triggers, restart, log) | [B→S] | Tour `state` + **status timeline** = chatter messages tagged `dsd.status`; status-triggered automation via `base_automation` (e.g. at state `loaded` → create check-out record; at `checked_in` → notify settlement team) (§11.6) |
| Odometer readings (start/end/per visit) | [B] | `fleet.vehicle.odometer` entries from console start-of-day / visit screens |
| Driver expenses (fuel, toll, parking types) | [B] | `hr.expense` with DSD product expense categories, tagged to tour; flows into settlement cash reconciliation (§12.5) |
| Inventory adjustments on van (breakage; normal vs damaged stock) | [B] | Console "adjust van stock" → `stock.quant` inventory adjustment on van location with reason code; damaged stock moved to van sub-location `VD` (damaged) |
| Barcode: customer identification + waiting-time capture | [B] | `barcode` on partner (GLN/EAN or Odoo id) printed as barcode on manifest; console scan → open stop; arrival/departure timestamps captured anyway (§12.2) |
| Electronic signature (per document, repository, print with doc) | [D] | Phase 7: signature pad capture → `ir.attachment` linked to visit line/POD/invoice; non-legally-binding note as in SAP |
| DEX (UCS direct exchange with customer systems) | [X] | EDI of the future; excluded |
| Occasionally-connected ATP/pricing calls | [X] | We are online; console uses live `_product_available` & pricelist |
| One-time customers | [B] | Console "quick customer" → minimal `res.partner` (name/address/phone, `dsd_is_one_time`) per stop |
| Vehicle checks catalog (questionnaire at start; catalog determination) | [D] | Phase 8: `dsd.vehicle.check` questionnaire (catalog of questions per tour scenario) |

### 3.7 Mobile-specific commercial functions

| SAP capability | Disposition | Odoo design |
|---|---|---|
| Deal condition (sales action: material or money rebate; header/assignments (AND: sales org/channel/division/plant; OR: customer/customer group/parent), conditions (material/merch-cat/material-group, must/total-qty thresholds), results (fixed/proportional; free goods or value/% discount; obligatory or driver-optional), validity, status, hierarchy types) | [B] | `dsd.deal.condition` with assignment/condition/result sub-models (§12.4); applied at visit invoicing; free goods added as $0 lines; discounts as line/global discounts; obligatory ones auto-applied |
| Manual discount by driver (condition types per sales area; authorization-gated; header & item) | [B] | Console allows discount within `dsd_max_discount_pct` on driver (0 = none); beyond → needs backoffice approval (activity); recorded per line (reason) |
| Listing & exclusion (customer-group × material-group condition tables; enforced on order entry & delivery) | [B] | `dsd.assortment` rules (partner tag/category × product category or product; allow/deny), checked in console order/delivery lines and backoffice sale order lines (§12.3) |
| Statistics: sales history (avg qty/week) per customer | [B] | §3.2 stat view + console panel |
| Credit limit check at invoicing on device | [B] | Partner `dsd_credit_limit` + `credit` (receivable) computed; console warns/blocks per policy (§16.3) |
| Open items on device (downloaded FI open items; payments against them; partial payments; final matching in backend) | [B] | Console collections screen lists open `account.move` receivables; partial `account.payment`; reconciliation happens at settlement (§13.5) |

### 3.8 Route accounting

| SAP capability | Disposition | Odoo design |
|---|---|---|
| RADB staging (tour data uploaded before settlement) | [X] | Online entry writes straight to business objects; settlement reads them. (Offline future: API writes same objects — same guarantee) |
| Tour Data Entry (paper; tabs: general, check-out/in itemization, distances & times, customer visits, delivery execution, invoices, collections, orders) | [B→S] | Equivalent data lives on: tour, checks, visit lines (orders/pickings/invoices/payments links), `dsd.tour.log` (distances/times), and is **editable from the settlement cockpit** (back-office corrections = paper entry) (§13.4) |
| Settlement cockpit (worklist, release gating, edit, difference determination run/re-run, reject delivery with reason, delete documentless visits, time types & distance types customizing, collections editing) | [B] | `dsd.settlement` kanban+form (§13): worklist filter by status/date/route; statuses mapped below; actions: *Determine differences*, *Release*, *Run settlement*, *Reject delivery*, *Remove stop* |
| Cockpit statuses (0 not relevant … 3 completed; release=20, settled=30) | [B] | `dsd.settlement.state`: `pending → data_entry → differences_ok → released → settling → settled / on_hold`; plus per-step progress grid (§13.6) |
| Difference determination (formulas qty & cash; with/without tolerances; re-runnable until settlement; needs successful run before final settlement) | [B] | Engine §13.3 with exact SAP formulas; tolerance groups decide block vs auto-post |
| Tolerances (types: value/qty abs+pct; groups; determination search; per material/customer) | [B] | `dsd.tolerance.group` (§7.9): lines with qty/value thresholds, applied by product tolerance-type & partner |
| Difference reasons (check-out/in, delivery/order change, visit) | [B] | `dsd.reason` catalogs per scope |
| Final settlement run (steps: customer docs create/process → driver docs → FI payments → goods movements → collection clearing; triggers: auto after diff-determination / auto if no diffs / manual / background job; exclusions) | [B] | `dsd.settlement.action_run_settlement()` (§13.7); trigger policy on settings; auto exclusions (e.g. differences above hard limit, missing invoices) |
| Driver documents & receipts/expenditures posting (post to driver account; payment-method→posting-action mapping) | [B] | Settlement journals driver cash custody via per-driver settlement partner (auto-created, `supplier`+`customer` minimal) and cash journal; expenses from `hr.expense` posted vs driver |
| Interim accounts (special/generic driver & customer accounts; ±differences; final differences) | [B] | Company-level config (§16.4): inventory-difference gain/loss accounts, cash-difference accounts, driver-clearing account; used by variance postings |
| Collection clearing (assign receipts→invoices, auto/manual, clearing status, log; prerequisites: settled, billed, released to FI) | [B] | §13.5: collections recorded on tour carry invoice m2o (chosen in console); settlement reconciles payment↔invoice (`js_assign_outstanding_line` equivalent) and posts cash journal→bank/handover |
| Settlement document (header status grid, cash differences, quantity differences) | [B] | `dsd.settlement` report (§15.5) |
| Application log | [B→S] | Chatter on settlement + `ir.logging`-style structured log lines stored on `dsd.settlement.log` (per run, step, message, severity) |
| Document flow (001 shipment, 002 load delivery, 003 return load, 004 visit list, 010 delivery, 012 order, 014 invoice, 015 accounting doc, 016 contact, 998 settlement doc) | [B] | Settlement smart-buttons + a flow popover listing every linked record type (§13.8) — same categories as SAP |
| Settlement office / settlement types determination | [S] | Dropped as org unit: settlement team = security group `dsd_group_settlement` + optional sales-team partitioning. Determination of *what to settle* = per tour/visit-list (role-driven) |

### 3.9 Deliberately out of scope (recorded)

- Vehicle Space Optimization & VSO-driven picking (needs 3rd-party optimizer even in SAP)
- DEX/UCS, CRM-CIC integration, SAP Mobile Engine/DOE replication (no offline client yet)
- Advanced route optimization engine (hook only), fleet telematics/fuel, merchandising surveys
- Full SAP-style condition-technique customizing engine, scheduling agreements, rebates
  (Odoo pricelists + deal conditions + `sale_loyalty` cover the DSD cases)

---

## 4. Odoo platform mapping

### 4.1 Standard apps we build on (all present in the docker image — verified)

| App | Used for |
|---|---|
| `sale`, `sale_stock`, `sale_management`, `sale_margin` | orders, delivery generation, margins |
| `stock`, `stock_account`, `stock_fleet` | pickings, batches=tours, van locations, valuation; `stock_fleet` gives vehicle/driver/category-capacity on batches |
| `fleet` (+`fleet_maintenance`) | vehicles, odometer, services |
| `hr`, `hr_expense`, `hr_holidays`, `hr_attendance` | drivers, tour expenses, availability |
| `account`, `account_payment` | invoices, journals, payments, reconciliation |
| `product`, `uom` (fractional factors = sub-base UoM), `product.packaging`, `product_expiry` | catalog, units, loading units, FEFO info |
| `mrp` | BOMs reused for empties explosion |
| `barcodes`, `barcodes_gs1_nomenclature` | barcode nomenclature, GS1 |
| `base_geolocalize` | partner lat/lng |
| `sale_loyalty` | optional consumer promos (not core DSD; deal conditions are custom) |
| `website`/`portal` (optional driver portal hosting), `mail` (chatter/log), `base_automation`, `ir.cron`, `digest`/`board` | console hosting, audit, automation, KPIs |

### 4.2 Module strategy

Single new addon **`dsd`** (`src/dsd`, synced into `~/odoo-docker/addons`), `application: True`,
depends: `sale_stock`, `stock_fleet`, `hr_expense`, `account_payment`, `base_geolocalize`, `barcodes`.
Rationale: the domains are tightly coupled (tour→visit→settlement); Odoo crosses module
boundaries via inheritance anyway; a second `dsd_portal` split is allowed later if console
assets grow. The old `dsd_core` is removed (§19.3).

### 4.3 Environment facts (verified 2026-11-16)

- Image `odoo:20.0`, PG 16, addons mount `~/odoo-docker/addons`.
- `stock_fleet` = "Stock Transport": batches get `vehicle_id`, `vehicle_category_id`
  (weight/volume capacity + used-%), `driver_id`, `dock_id`, `order_on_zip()`, `batch_sequence`.
- Community has **no** `stock_barcode` app, no `dispatch`/FSM — console implements its own scan UX.

### 4.4 Odoo-20 environment facts & gotchas (binding for v2)

**Setup:** PG ≥ 16 (satisfied); symlink `src/dsd` → `~/odoo-docker/addons/dsd`;
`docker compose run --rm odoo odoo -d odoo -u dsd --stop-after-init` after model changes.

**Framework/API facts (confirmed on image `odoo:20.0-20261112`):**
1. Kanban templates must use `<t t-name="card">` — `kanban-box` is removed in 20.
2. View modifiers (`required/invisible/domain`) must NOT traverse many2one chains
   (`['a_id.b','x']` crashes rendering — web client only loads fields declared in the view);
   declare server-side related/computed fields instead.
3. Access CSVs target `ir.access` (not `ir.model.access`): columns
   `id,name,model_id,group_id/id,operation,domain` with operations like `crud`/`ru`.
4. `res.groups` categories: `privilege_id` on `res.groups.privilege` (not `category_id`).
5. Search views: bare `<group>` elements (no `string`/`expand` attributes).
6. Translations: `self.env._()` when interpolating; module-level `_` for static strings only.
7. `account.payment`: `ref` → `memo`; lines via `payment.move_id.line_ids`; journals book
   payments on outstanding accounts — to reconcile with an invoice, the counterpart line must
   be moved onto the invoice's receivable account (settlement clearing must respect this).
8. `stock.move`: `line_ids` → `move_line_ids`, and the line UoM field is `uom_id`.
9. `stock.picking.state` is **computed** — state-sync hooks must wrap `button_validate()`,
   not `write()`.
10. `account.account` is company-shared (no `company_id` field) — account config in settings
    must filter by chart, not company.
11. Quants exist only for storable products — van visibility & counting require
    `is_storable=True` on products.
12. Headless `--test-enable` misses client-side rendering bugs entirely: every view-heavy phase
    gate includes a manual browser pass (Phase ACs assume this).
13. `_sql_constraints` removed → use `models.Constraint('unique(...)', 'message')` class
    attributes (unique constraint violations surface as `psycopg2.IntegrityError`, not
    an Odoo exception).
14. `product.template`: `detailed_type` and `uom_po_id` removed — use `type` plus
    `is_storable`; the purchase UoM is gone. The `product.packaging` model is also removed
    (packaging is expressed as extra units via `uom_ids`); loading-unit math in Phase 2
    converts through UoM, not packaging records.
15. `res.partner.company_type` is not settable at create (use `is_company`); `stock.location`
    has no `comment` field; the sales-team model is `crm.team` (never `sales.team`).
16. `mrp.bom` requires the whole `mrp` app — Phase 6 must decide between depending on `mrp`
    or a dedicated `dsd` BOM model for empties (see product DSD tab note).
17. Demo-load failures are **warning-only** ("installed without demo data") and fresh
    `createdb` databases skip demo by default in this image — grep install logs for the
    phrase; do not rely on demo presence in tests.
18. Fleet vehicle license plates carry a DB unique constraint — demo collisions from
    leftover vehicles surface at install time.
19. `ir.rule` is REMOVED. Record rules are now domain-carrying `ir.access` rows:
    a group-scoped row is a domain-limited *permission* (users of that group may only
    operate on matching records; permissions OR-ed across groups); a group-less row is
    a *restriction* applying to every user. "Drivers see only own lists" =
    `group_dsd_driver` permission with domain `[('driver_id.user_id','=',user.id)]`.
20. `ir.cron` lost the `numbercall` field; follow the `mail` module's cron XML shape
    (`forcecreate`, `user_id` base.user_root, no numbercall).
21. Kanban/form arch forbids `t-esc` — use `t-out`.
22. The view validator rejects button `context` referencing `active_id` ("field does
    not exist in model") — use object-method buttons with a domain instead.
23. `resource.calendar` lost `tz` (interval tz comes from arguments/resources) and
    attendance lost `name`; `dayofweek` is a labeled selection `'0'..'6'` with one row
    per day-half. `_work_intervals_batch(start, end)` requires TZ-AWARE datetimes and
    returns `{key: Intervals}` (empty Intervals = non-working day; we evaluate UTC
    day boundaries).
24. Transient many2many writes enforce the field domain: linking a record outside the
    field's `domain` raises "Cannot link inaccessible records" — tests must set fields
    the domain filters on (e.g. plan state) before selecting records.
25. Manifest order is load order: views referencing another file's action/xmlid must
    come after it.
26. `res.users` groups field renamed `groups_id` → `group_ids`.
27. `stock.picking.batch.driver_id` (stock_fleet) is a **res.partner** (fleet driver
    contact for consignment docs) — the operational tour driver is our
    `dsd_driver_id` (hr.employee); don't write employees into batch driver_id.
28. `stock.move` lost `name` (don't set it at create); `product_uom` → `uom_id`
    (`product_uom_qty` still exists); move `quantity` is written via `write()`
    (no `_set_quantities`); `stock.picking` has no `warehouse_id` — use
    `picking_type_id.warehouse_id`.
29. Lazily created `stock.picking.type` needs an explicit `sequence_id` — picking
    create fails with a cache KeyError on 'name' otherwise.
30. Batch kanban is a `card_id` template reference — inherit by replacing the whole
    kanban in a dedicated action view, not by xpath; view-validators reject
    domains on non-stored computes unless a `search=` method is provided.
31. Reservation search includes location DESCENDANTS — van locations must be
    siblings of `warehouse.lot_stock_id` (under a "Van Fleet" view area), never
    children, or van stock leaks into warehouse availability.


---

## 5. Architecture decisions (ADR v2 log)

> Numbered 101+ to coexist with historical ADRs 1–4 in `docs/adr/` (which remain readable but
> are superseded where they conflict).

| ADR | Decision | Rationale / rejected alternative |
|---|---|---|
| 101 | One addon `dsd`, Odoo-native UI (no separate frontend app) | smallest surface; Odoo OWL + portal is enough for a phone-friendly console |
| 102 | **Van = internal stock location per vehicle** (auto-managed `stock.location`, usage=internal, `vehicle_id` link, sub-locations `VD` damaged) | enables quants/moves/audit for free; rejected: quant-less custom ledger (rebuilds stock), or van-as-warehouse (N warehouses, heavy) |
| 103 | **Tour = `stock.picking.batch`** extended | batches already group deliveries, have state, printing, `stock_fleet` capacity; rejected: standalone `dsd.tour` model (would duplicate picking linkage and shipment semantics) |
| 104 | Driver = `hr.employee` (+ auto optional settlement partner) | HR owns availability & expenses; a partner-based driver (SAP style) pollutes AR with employees |
| 105 | Visit plan/list are new `dsd.*` models, decoupled from tours for presellers | SAP parity: list is defining doc for preseller/van/mixed; tours link to lists |
| 106 | Online console; offline via future JSON API using the same endpoints | avoids replication layer until a real offline requirement lands |
| 107 | Goods issue at visit confirmation (real time); financial postings at settlement | real-time van truth for sellers; SAP's late-GI exists only because of offline devices |
| 108 | Van sales via `sale.order` → picking from van → invoice → payment (no POS) | B2B receivables, credit, returns; POS is anonymous cash-register paradigm |
| 109 | Sales-area checks simplified to sales-team consistency | Odoo sales areas are not hard partitions; full single-SA machinery adds config without value here |
| 110 | Settlement is a controlled multi-step process, not a status flip | auditability is a core DSD value (priorities doc §6.6) |
| 111 | Empties modeled via BOM + returnable products with deposit prices; returns as return-pickings customer→van | reuses stock truth; SAP tied/untied semantics preserved in display |
| 112 | Difference/interim postings through standard journals & configurable accounts | keeps accountants in control; no custom GL |

---

## 6. Model overview diagram

```
dsd.license.category ─┐
fleet.vehicle ────────┼─ dsd.route (template: day pattern, capacities)
   └ van stock.location│        │
hr.employee(dsd.driver)        │
   │                            ▼
   │   dsd.visit.plan.type ── dsd.visit.plan ── dsd.visit.plan.line
   │                                │ (generate, per date)
   │                                ▼
   │                          dsd.visit.list ── dsd.visit.list.line ─┬─ sale.order
   │                                │                               ├─ stock.picking
dsd.deal.condition                │ tour_id                        ├─ account.move
dsd.assortment                    ▼                                └─ account.payment
dsd.tolerance.group       stock.picking.batch (=TOUR) ── pickings(deliveries)
                                   │
                    dsd.loading.confirmation · dsd.check.record(out/in)
                    dsd.reload · dsd.unload(picking Van→WH)
                                   │
                                   ▼
                          dsd.settlement ── dsd.settlement.log / differences
                                   │ run
                                   ▼
                 invoices · payments · journal entries · reconcile · report
```

---

## 7. Master data & configuration — detailed spec

### 7.1 `res.config.settings` (DSD block, stored on company)

- `dsd_enabled` (boolean; gates console/menu)
- `dsd_default_warehouse_id`, `dsd_default_planning_horizon_days` (appointment horizon, default 21)
- `dsd_stock_visibility` (van-location ATP isolation toggle, default True)
- `dsd_loading_confirmation_required`, `dsd_checkout_required`, `dsd_checkin_required` (default True)
- `dsd_auto_release_when_clean` (auto-release settlement when differences within tolerance)
- `dsd_settlement_trigger`: `manual` | `auto_clean` (auto run when no blocking diffs)
- Accounts (§16.4): `dsd_inv_diff_gain_account_id`, `dsd_inv_diff_loss_account_id`,
  `dsd_cash_diff_account_id`, `dsd_driver_clearing_account_id`, `dsd_cash_journal_id`
- `dsd_driver_user_group` default driver group for console access

### 7.2 `res.partner` extensions (customer)

**DSD tab:**
- `dsd_route_id` → `dsd.route` (required to appear on plans; warning if empty when added)
- `dsd_visit_required` boolean (auto-suggest into plans)
- `dsd_receiving_hours` (char/json: per-day windows; freeform first version)
- `dsd_unloading_point_id` (m2o child partner/address, optional), `dsd_contact_id` (m2o res.partner, contact)
- Geocode: reuse `partner_latitude/longitude` (base_geolocalize) + button *Geocode*; list/map links
- `dsd_driver_notes` (text, printed on manifest)

**Payments & documents (Enhanced Terms of Payment):**
- `dsd_collection_type`: `none` | `on_delivery` (default none)
- `dsd_accepted_journal_ids` m2m `account.journal` (cash/check/card → payment methods)
- `dsd_pod_or_invoice`: `pod` | `invoice` (what the driver prints at stop)
- `dsd_invoice_generation`: `auto` | `manual` | `consolidated` (per-stop / on demand / combine per day)
- `dsd_cash_only` boolean (driver may not take other instruments)
- `dsd_credit_limit` (monetary) — console block policy `warn|block` company-level
- `dsd_customer_group_id` → `res.partner.category` usage for assortment & deal assignment

**Identity:** `dsd_barcode` (char; GLN/EAN recommended) + `dsd_is_one_time` boolean.

### 7.3 `dsd.driver` (= `hr.employee` inheritance)

- `dsd_code` (sequence `dsd.driver`), `dsd_active_driver` boolean
- `license_category_ids` m2m `dsd.license.category`
- `default_vehicle_id` m2o, `default_route_ids` m2m
- `dsd_sales_team_id` m2o `sales.team` (ADR-109 checks)
- `dsd_max_discount_pct` float (manual-discount authority; 0 = none)
- `dsd_cash_journal_id` m2o (personal custody journal; default = company DSD cash journal)
- `dsd_settlement_partner_id` m2o res.partner (auto-created lazy on first settlement: named
  `Cash custody — <employee>`, `customer=True,supplier=True`, property accounts → driver clearing)
- Lock/availability: `dsd_lock_ids` o2m `dsd.lock.period` (or hr leaves); tour defaults skip locked
  drivers; console shows replacement-driver swap
- `user_id` m2o res.users (console login; portal or internal)

**`dsd.lock.period`**: `res_model` selection(driver/vehicle), `res_id`, `date_from`, `date_to`, `reason`.

### 7.4 `fleet.vehicle` extensions

- `dsd_is_van` boolean (creates/manages van location via `dsd_van_location_id`)
- `dsd_vehicle_type`: `truck|van|trailer`; `dsd_trailer_of_id` (self m2o)
- `dsd_license_category_ids` m2m (required to drive it)
- `dsd_is_own_vehicle` boolean (own vs subcontractor)
- `dsd_max_stops_override`, `dsd_max_duration_override` (else from route)
- `variable_capacity` float (extra flexible units, e.g. roof rack crates) — counts in LU capacity
- `dsd_lock_ids` (shared model above)
- Van location auto-create on write of `dsd_is_van` (`WH/VAN/<plate>` internal + child `VD` damaged);
  archived (not deleted) when flag off. Odometer via standard `fleet.vehicle.odometer`.

### 7.5 `dsd.route` (strategic route template ≈ SAP tour master header)

- `name`, `code`, `active`, `company_id`, `warehouse_id` (departure), `visit_plan_type_id`
  (default role for tours of this route) → **unique(route, visit_plan_type)** mirrors SAP tour header
- Day pattern: `mon..sun` booleans (serves the visit-plan generation; not the plan's own frequency)
- Capacity config (flags + values): `cap_weight`, `cap_volume`, `cap_stops` (`max_stops`),
  `cap_duration` (`max_duration_hours`), `cap_loading_units` (`lu_uom_id`) — activation order fixed
  per SAP: weight → volume → stops → variable capacity → duration → LU
- `default_driver_id`, `default_vehicle_id`, `default_trailer_id`
- `max_load_attempts` int (SAP "Number of Attempts" skipping), default 2
- One-shipment-per-day flag `single_daily_tour`
- Constraints: stops>0 if cap_stops; duration>0 if cap_duration

### 7.6 `product.template` / `product.product` extensions

- `dsd_group_id` → `dsd.dsd.group` (name + calendar type: `visit|delivery`) — SAP DSD grouping
- `counting_group_id` → `dsd.counting.group`
- `tolerance_type_id` → `dsd.tolerance.type`
- `dsd_aggregation_ids` m2m `dsd.aggregation.line`-like config (category, uom, factor) —
  totals computed on tours & lists
- `dsd_empties_bom_id` → `mrp.bom` (type empties: full→containers) + `is_returnable` flag,
  `deposit_price` (on empties products)
- `dsd_loading_unit_packaging_id` → `product.packaging` for LU capacity math
- Standard fields reused: `uom_id` + `uom_ids` (fractional factor = sub-base units),
  `barcode` (EAN), `weight`, `volume`, `tracking`, `expiry_time` (product_expiry)

### 7.7 `dsd.counting.group`

- `name`, `uom_ids` o2m ordered (`dsd.counting.group.uom`: uom, factor-to-base) — hierarchy
  "count pallets then crates then pieces"; validation report action checks product conversion
  factors exist (parity with `/DSD/SV_CHECK_CG`).

### 7.8 Reasons, outcomes, catalogs

- `dsd.reason` (`scope`: `checkout_diff|checkin_diff|delivery_change|order_change|visit_outcome|
  stock_adjust`, code, name, `blocks_settlement` bool)
- `dsd.visit.reason` (outcome catalog: customer closed, no cash, refused, out of time, rescheduled…)
  — implemented as scoped `dsd.reason` to avoid model sprawl; visit outcomes get an extra
  `needs_reschedule` flag mapping to status RS.

### 7.9 `dsd.tolerance.group`

- Lines: `tolerance_type_id` (qty abs, qty %, value abs, value %), thresholds, severity
  (`warn` (auto-post, continue) | `block` (manual resolution required))
- Determination: product `tolerance_type_id` × partner (optional `partner_id` on group for
  customer-specific groups; empty = general) — mirrors SAP search criteria.

### 7.10 Number sequences (`ir.sequence` data)

`dsd.visit.plan`, `dsd.visit.list`, `dsd.tour` (batch `name` prefix `TOUR/`),
`dsd.loading.confirmation` (`LC/`), `dsd.check.record` (`CO-`,`CI-`), `dsd.reload` (`RL/`),
`dsd.settlement` (`SET/`), `dsd.driver` (`DRV-`), `dsd.deal.condition` (`DL/`).

---

## 8. Visit Control — detailed design

### 8.1 `dsd.visit.plan.type` (role matrix, SAP parity)

| Field | Values / meaning |
|---|---|
| `name`, `code` | e.g. PRESALE, VAN, MIXED, DELIVERY |
| `role` | selection `preseller|delivery|van_sales|mixed` |
| `relevant_doc` | `visit_list` \| `tour` \| both (SAP "Relevant Documents" indicator) |
| `make_delivery` | bool (delivery driver/van load semantics) |
| SAP matrix default | delivery: list=No tour=Yes make=Yes · van: Yes/Yes/No · mixed: Yes/Yes/Yes · preseller: Yes/No/No |
| `visit_times_source` | `receiving_hours` \| `contact_times` (what plan lines display) |
| `default_waiting_minutes`, `default_travel_minutes` | copied to new plan lines |
| `max_load_attempts` | inherited default from route, overridable |
| `driver_lockable` | bool: lists of this type may swap driver ad hoc |

### 8.2 `dsd.visit.plan` (strategic)

- `name` (seq), `plan_type_id` (req), `route_id` (req), `company_id`, `sales_team_id`
- `valid_from`, `valid_to`
- `driver_id`, `vehicle_id`, `trailer_id` (shipment defaults; optional)
- **Recurrence (header rule):** `frequency` = `weekly` (`weekday_ids` m2m + `interval_weeks` int,
  anchor date) **or** `rrule` (text, dateutil) — one of two modes
- `calendar_id` → `resource.calendar` (non-working policy: `skip|previous|next`)
- `driver_notes` text
- State: `draft|active|closed` (active = generator input)
- Constraints: ≥1 line to activate; lines' partner route must equal plan route (warning, allow
  cross-route manually for edge cases)

### 8.3 `dsd.visit.plan.line`

- `partner_id` (ship-to), `sequence`, `waiting_minutes`, `travel_minutes` (defaults from type)
- `unloading_point_id`/`contact_id` defaults from partner (per SAP master-data source switch)
- `inactive` bool (skip in generation while set)
- `exception_dates` o2m (`dsd.visit.plan.line.exception`: date, reason) = SAP non-appointments
- `customer_notes` text (printed)
- Compute: `next_occurrence_date` (preview)

### 8.4 `dsd.visit.list` (operational) & lines

`dsd.visit.list`:
- `name` (seq), `execution_date` (req), `plan_id` (o2o source; manual lists allowed), `plan_type_id`
  (defaults from plan), `route_id`, `driver_id`, `vehicle_id`, `trailer_id`
- `state`: `draft → confirmed → in_progress → done → cancelled` (+`inactive` flag)
- `tour_id` m2o `stock.picking.batch` (set by tour generation → **locks** list header/items
  except driver/vehicle swap, SAP parity)
- `speculative_load_picking_id` m2o (van/mixed: internal WH→Van picking for the speculative load,
  header reference doc)
- `driver_notes` aggregated from plan; editable
- Generation watermark & guard in `plan_id.last_generated_date`

`dsd.visit.list.line`:
- `partner_id`, `sequence`, planned `waiting/travel` minutes, planned arrival (cumulative from
  route start time), `unloading_point_id`, `contact_id`
- **Execution:** `status` `NP|SP|PP|UP|RS` (SAP codes), `reason_id`, `arrival`/`departure` datetimes,
  `odometer_value`, `signature_attachment_id` (ph7)
- Result refs: `order_ids` m2m, `picking_ids` m2m, `invoice_ids` m2m, `payment_ids` m2m,
  `visit_note`
- Unplanned stop: `is_unplanned` bool (created in console)
- Compute `status` auto-rollup from activity statuses (SAP visit-status table implemented verbatim)

### 8.5 `dsd.visit.appointment` (time-stream equivalent)

- `partner_id`, `date`, `kind` (`visit|delivery`), `plan_id`, `visit_list_id` (nullable),
  `route_id`, `company_id` — unique(partner, date, kind)
- Filled by: list generation, manual lists, cron `dsd.fill_appointments` (nightly, horizon from
  settings; regenerates future unbound rows only)
- Consumed by: sale-order proposal (§10.2), partner "upcoming visits" mini-calendar

### 8.6 Generation wizard `dsd.visit.list.generate`

Input: plans (multi) or route+date-range; `dry_run`.
Algorithm per plan & date d in range:
1. skip d if weekday not in rule (or rrule excludes);
2. skip public holidays per calendar & policy (skip/prev/next);
3. skip if plan line `inactive` or line exception covers d;
4. create list (execution_date=d, defaults from plan), lines in sequence;
5. write appointments; set plan watermark; log created/skipped counts (chatter + wizard result screen).
Guard: refuse date ≤ watermark unless dry-run (SAP no-double-generation), with clear message.

### 8.7 Console maintenance of lists

Drag reorder (handle=sequence), add/remove stop, postpone (change execution_date → regenerate
appointments), set inactive, swap driver/vehicle (logs old/new; revalidates license vs vehicle).

---

## 9. Tour preparation — detailed design

### 9.1 Tour = `stock.picking.batch` extension (`dsd.tour` mixin fields on batch)

Added fields:
- `dsd_state`: `draft|confirmed|loading|loaded|checked_out|in_progress|checked_in|to_settle|settled|cancelled`
  (kept in sync with batch `state`; batch state remains source for stock ops)
- `dsd_route_id`, `dsd_visit_list_id` (m2o; nullable for pure-delivery tours), `plan_type_role`
  (related), `dsd_driver2_id` (co-driver), `dsd_trailer_id`
- `dsd_weight_usage/volume_usage` — provided by `stock_fleet` (`used_weight_percentage` etc.)
- `dsd_lu_total` + `dsd_lu_capacity` (loading units, from packaging math)
- `dsd_seal_numbers` char, `odometer_start/end`
- `dsd_settlement_id` m2o (after check-in)
- Chatter is the tour log; `dsd.status` messages on each transition (§11.6)

### 9.2 Delivery pipeline (pre-sold)

1. `sale.order` confirmed (console or back office) → standard `sale_stock` procurement creates
   outgoing picking to customer (WH stock).
2. **Tour load-out:** before loading, DSD re-routes the picking source WH→Van:
   `dsd.tour.action_load()` creates ONE internal picking `WH/Van load-out` (type `dsd.load`)
   aggregating tour pickings' reserved moves (per product/qty, counting-group aware), and flips
   customer pickings' `location_id` to Van (delivery completes Van→Customer later).
   Reservation stays on WH until load-out validates (ATP-safe, ADR on stock visibility).
3. Load-out validation = physical load; then loading confirmation (§11.2) reconciles counts.

Van-sale speculative load: same internal picking type, created from the visit list header
(speculative load reference doc) with manually chosen quantities (or replenishment proposal from
previous sales statistics).

### 9.3 Tour generation wizard `dsd.tour.generate` (≈ Dynamic Transportation Planning)

Inputs: date(s), route(s) (empty = all with due work), options `include_new_customers`
(deliveries without visit-list coverage grouped by route), `single_tour_per_route`, `assign_from_route_defaults`.

Algorithm:
1. Candidate deliveries = outgoing pickings (DSD picking types) `state not in (done,cancel)`,
   `scheduled_date` in range, route of ship-to (partner route, or picking's route) matches.
2. Candidate visit lists = `state in (draft,confirmed)` for date(s) & route(s), not inactive,
   whose plan type has tour as relevant doc; sort by plan type then route (SAP order).
3. Per (route, date):
   a. defaults: driver/vehicle/trailer from list → else route defaults; validate license, locks.
   b. build stop order = visit-list line sequence; attach customer pickings to their stop.
   c. create batch (name seq TOUR/), link pickings (`batch_id`), set `dsd_visit_list_id`.
   d. **capacity loop** (adds stops in order; first exceeded limit stops assignment — SAP order):
      weight → volume → stops → variable capacity → duration (`travel+waiting` sum incl. first/last
      legs) → loading units; on exceed: skip customer, try next (`max_load_attempts` skips before
      closing the tour), remainder → **new tour** if list allows distribution (no explicit driver,
      no speculative load; SAP prerequisites) else left unplanned with log.
   e. `include_new_customers`: route-less deliveries grouped by partner-route into extra tours.
4. Result screen: created tours, skipped customers + reasons, unplanned remainder; write-back
   `tour_id` on visit lists; log everything.

Manual tours: standard batch creation + DSD fields; same validation constraints (§9.5).

### 9.4 Capacity math

- weight/volume: sum over pickings (`stock_fleet` already computes) vs `fleet.vehicle.model.category`.
- stops: distinct ship-to parties count vs route `max_stops`.
- duration: `Σ(travel+waiting)` + first/last leg (from list line values; default travel from type).
- LU: `Σ qty(base) / packaging.qty` per product's LU packaging vs `lu_capacity` (vehicle category
  extension) + `variable_capacity`.
- Aggregation categories computed per tour for display (crates, pallets…).

### 9.5 Tour validations (constraint layer, SAP checks parity)

- driver required for `confirmed+`; co-driver only with driver1; vehicle required; trailer must
  be type trailer & attached to a tractor (vehicle `dsd_trailer_of_id` chain valid);
- driver `license_category_ids ⊇ vehicle.dsd_license_category_ids`;
- driver & vehicle not locked on tour date; driver team == route team (warn);
- all pickings same warehouse; ship-to route consistency warnings.

---

## 10. Order ↔ visit integration

### 10.1 Presale orders (console & back office)

Console order capture = `sale.order` with `dsd_visit_list_line_id`, `dsd_route_id` set; delivery
on next tour (requested date = next appointment ≥ lead time).

### 10.2 Sale-order DSD defaults (order-entry integration, SAP parity)

`onchange partner_id` (or `_compute` on create):
- `dsd_route_id` ← partner route;
- `commitment_date` proposal = earliest `dsd.visit.appointment(kind=delivery, date ≥ today+lead)`
  for partner (lead = `security_lead`-like setting `dsd_min_lead_days`);
- chatter note records proposal source. Back office may override both.

### 10.3 Listing/exclusion enforcement

`sale.order.line` & console cart lines validate against `dsd.assortment`
(deny rules win; no rule = listed) at line add; blocked lines raise UserError with the rule name.
Same check when adding van-sale items and when validating deliveries.

---

## 11. Tour execution — detailed design

### 11.1 Start-of-day & check-out

Console start-of-day: confirm/swap driver & vehicle, `odometer_start`, opening cash per payment
method (`dsd.check.record type=out` lines payment tab), optional vehicle-check questionnaire (ph8),
then `CHECK-OUT`: count loaded stock (per product or **counting group** with UoM hierarchy —
count pallets, then crates, then pieces), confirm or reason-code differences; checker (supervisor)
countersigns (any `dsd_group_supervisor` user) when differences exist; optional seal numbers;
tour → `checked_out`.

### 11.2 `dsd.loading.confirmation`

- `tour_id`, `counting_scope` (`product|counting_group`), `show_target` (from settings),
  lines: subject (product or group), target qty (from load picking), counted qty, uom (hierarchy pickable),
  difference reason.
- Resolution actions: *Adjust load* (write qty on load-out picking) or *Accept difference*
  (reason mandatory; posts to inventory-difference interim account at settlement, not now).
- Seal numbers → tour. On complete → tour `loaded`; auto `base_automation` creates check-out record.

### 11.3 `dsd.check.record` (check-out / check-in / reload checks)

- `tour_id`, `check_type` (`out|in`), `is_reload`, `checker_user_id` (supervisor), `signature_attachment_id`
- Material lines: product or counting-group, planned qty (from van quants for check-in), counted, reason
- Payment lines: journal (cash/check/card), expected amount (for check-in: opening + collected −
  expenses), counted amount, difference reason
- Check-in of a **reload stop-off** records delta only (SAP parity).

### 11.4 `dsd.reload` (mid-tour)

- Wizard on running tour: adds products/qty → internal picking WH→Van (delta only), prints
  reload material list, console van stock refresh; goods remain driver custody (van location).
  Unload-during-reload = negative lines → moves Van→WH (returns/empties drop).

### 11.5 Van stock visibility & end-of-tour unload

- Van quants = live truth (`stock.quant` filtered by van location); console header shows them.
- ATP isolation (ADR-102): warehouse sales reserve WH only (van locations are outside warehouse
  `lot_stock_id` children used for reservation) — verified in tests.
- Check-in accepted → `dsd.unload` internal picking Van→WH (unsold full goods to stock; damaged
  location VD→WH/DAMAGED; empties to empties location) released by settlement (or immediately per
  setting) — this is SAP's *final unloading document*.

### 11.6 Tour status & automations

Every `dsd_state` transition posts a chatter message tagged `dsd.status` (= SAP tour status log).
`base_automation` examples shipped: `confirmed→ create load confirmation`; `checked_in → create
settlement + notify settlement group`; failures surface on tour kanban "attention" badge.

---

## 12. Driver console (mobile-first web) — functional spec

### 12.1 Shell

- Route: `/dsd/console` (portal or internal auth; driver group). OWL app, phone-first layout,
  big targets, works ≥ 360px; dark-mode friendly; Odoo `web` assets bundle `dsd.console_assets`.
- Login lands on **Today**: my visit lists & tours (in_progress first), van stock snapshot,
  cash balance, alerts (over-credit customers, blocked assortments).
- Offline tolerance: none v1 (ADR-106); all actions optimistic with clear error toasts.

### 12.2 Stop screen (per visit line)

Header: customer, address (maps link), receiving hours, geocode, barcode scan-to-open
(scan partner barcode), statistics panel (last 6 orders, avg qty/wk per top products), open
receivables, credit-limit banner, assortment warnings, driver notes.
Buttons (role-gated by `plan_type.role`):

| Activity | Roles | What it does |
|---|---|---|
| Arrive / Depart | all | timestamps (waiting time captured = SAP barcode timing parity) |
| Deliver pre-sold | delivery, mixed | open tour picking for this customer: edit qty (+reason per line), add items (van availability check), returns & empties add, then *Confirm delivery* (validates Van→Customer GI) → POD or invoice per partner profile |
| Van sale | van, mixed | guided cart from van stock (assortment-checked): creates sale.order + picking (Van→Customer) + confirms + prices (pricelist + deal conditions) + invoice per profile |
| Take order | preseller, mixed | sale.order for next tour (route/date proposal per §10.2) |
| Collect payment | all (if partner collects) | pick open invoices (current stop first), partial ok, payment method per partner accepted set; prints receipt |
| Record return | all | return lines (product, qty, reason, normal/damaged) → return picking customer→Van (validated on confirm) |
| Expenses | all | `hr.expense` quick add (fuel/toll/parking products) tagged to tour |
| Inventory adjustment | van, mixed | adjust van quants with reason (breakage), normal/damaged |
| Not visited / reschedule | all | reason code → status UP / RS |
| Unplanned visit | all | quick partner (one-time) or existing → new line |
| Odometer | all | quick entry |
| Print | all | POD / invoice / receipt (COPY flag on reprints) |

Sequencing: drag reorder of remaining stops; start/end tour buttons with check-out/check-in flows (§11).

### 12.3 Van sale line pricing

Unit price from partner pricelist; deal conditions evaluated at cart finalize (§12.4); manual
discount within driver authority; credit-limit gate before invoice.

### 12.4 `dsd.deal.condition`

- Header: name, type (`free_goods|discount_value|discount_percent`), validity, status
  (draft/active/expired), `obligatory` bool, `calc_base` (`fixed|proportional`)
- Assignments: AND-block (sales team, company, warehouse — only filled ones apply) + OR-list
  (customers / customer groups / parent customers) — SAP semantics preserved
- Conditions: include product / product-category; min qty must-have per product or total-qty
  across listed products (target reached ⇒ counts)
- Results: free goods (product + qty), or % / fixed discount; `discount_condition` link to a
  `sale.order.line` discount section (negative line or global discount per Odoo 20 conventions)
- Application point: console cart finalize + backoffice order confirmation (server method
  `apply_deal_conditions(order)`); obligatory ones auto-apply, optional offered to driver (accept/decline).
- Lists: active deal conditions per customer (console + report).

### 12.5 Driver cash & expenses during tour

Running cash = opening + collections − expenses (computed live from tour-tagged payments and
`hr.expense` records). End-of-day cash count happens in check-in (§11.3).

### 12.6 Admin/mobile reports (SP01 parity-lite)

Saved filters + digest: stops per day, sales per route, differences per driver; optional digest KPIs.

### 12.7 `dsd_customer_product_stat` (SQL view)

`partner_id, product_id, orders_90d, qty_90d, avg_qty_per_week, last_order_date` — powers the
statistics panel & speculative-load proposals.

---

## 13. Route accounting & settlement — detailed design

### 13.1 `dsd.settlement`

- One per tour (`tour_id` unique) — preseller-only lists (no tour) get a settlement too, basis =
  visit list (`visit_list_id`, either/or required).
- `state`: `pending → data_entry → diff_ok → released → settling → settled`; `on_hold` from any
  pre-settled state (reason required). (Cockpit release=20/settled=30 map to released/settled.)
- Back-reference fields for everything created (invoice_ids, payment_ids, move_ids, journal_entry_ids).
- Worklist: kanban by state; filters date/route/driver; attention badge for blocking differences.

### 13.2 What settlement reads (inputs)

- Tour pickings (planned vs done qty per product) incl. returns/empties
- Check-out & check-in records (materials & payment methods)
- Loading confirmation differences
- Visit lines: statuses, reasons, orders taken, invoices printed, collections
- Expenses, odometer, times/distances (`dsd.tour.log`: type (`time|distance`), subtype, value, ref)
- Deal conditions & manual discounts applied

### 13.3 Difference determination (exact SAP formulas)

Per product (base UoM):
```
qty_diff = check_out_qty − delivered_qty + returned_qty − check_in_qty
```
(loading-confirmation counts form check-out basis when used)
Per payment method:
```
cash_diff = check_out_amount − expenses + collections − check_in_amount
```
Algorithm:
1. compute raw differences;
2. tolerance evaluation per product (`tolerance_type` × group; partner-specific group wins):
   within `warn` → auto-post flag; beyond or `block` → blocking difference line;
3. blocking ⇒ state stays `data_entry`/`on_hold` until corrected or force-accepted (reason +
   settlement group);
4. re-runnable until settled (button; auto on release); result stored as
   `dsd.settlement.difference` lines (`kind: qty|cash`, subject, expected, actual, diff,
   tolerance verdict, resolution state/reason/post-ref).

### 13.4 Data review & paper entry (Tour Data Entry parity)

Settlement form tabs mirror SAP: General (driver/vehicle swap log, odometer, times/distances),
Check-out/in (editable check records until release), Visits (edit outcomes, remove documentless
stops), Delivery execution (amend done qty via stock wizards: scrap/return adjust), Orders/Invoices
(created docs list + create missing), Collections (assign/reassign invoice links). All edits chatter-logged.

### 13.5 Collections & clearing

- Console collection already carries `invoice_ids` m2m (current-stop invoices listed first).
- Settlement step *collection clearing*: for each payment: reconcile with linked invoices
  (`account.move` lines via `js_assign_outstanding_line` semantics = `account.payment` reconcile);
  unassigned cash stays on driver clearing partner; hands-over (cash to office/bank) = transfer
  payment driver-cash-journal → company journal, posted in the run.

### 13.6 Settlement document & progress grid

Per-step status grid (SAP 0–3): orders processed / deliveries finalized / invoices / payments /
goods movements / differences posted / clearing — each `not_relevant|relevant|in_process|completed`,
only all-completed ⇒ `settled`. Rendered on settlement form + PDF (§15.5).

### 13.7 Final settlement run (`action_run_settlement`)

Preconditions: released; difference determination clean (or force-flag with reasons).
Steps (transactional per tour, idempotent — each step checks its own completion first):
1. **Customer documents:** create missing invoices for delivered/sold (per partner
   `dsd_invoice_generation`: per-stop already printed vs consolidated now); credit notes for
   rejected/zero deliveries (reason-coded).
2. **Driver documents:** expense report posting (`hr.expense.sheet` → journal) vs driver partner;
   cash-difference journal entries (gain/loss accounts) per §16.4.
3. **Payments:** post console collections (`account.payment` validate), reconcile with invoices
   (clearing), hands-over transfers.
4. **Goods movements:** validate any pending unload picking; scrap/adjust lines for
   damage differences; post inventory-difference interim entries (qty_diff beyond tolerance).
5. **Finalize:** write progress grid, `settled`, chatter summary, PDF auto-attach.
Trigger policy from settings (`manual | auto_clean` via cron scanning released-clean settlements;
exclusions: blocking diffs, unreleased invoices config, missing check-in).

### 13.8 Document flow & logs

- `dsd.settlement.log` (run, step, message, severity) = application log.
- Flow popover: shipments(tour), load/return-load pickings, visit list, deliveries, orders,
  invoices, accounting entries, contact notes, settlement doc — SAP categories 001–998 mapped 1:1
  (§15.6 table).

### 13.9 Reject delivery / remove stop

Reject = picking qty→0 with `reason_id` (blocks nothing else); remove stop = only when no docs
linked (SAP parity), else mark UP with reason.

---

## 14. Returns & empties

- **Product returns** (saleable / damaged / expired / wrong / quality): return picking
  customer→Van at stop (reason, damaged flag → VD location); at unload they go WH or WH/DAMAGED;
  credit note in settlement (auto for `auto` profile).
- **Untied empties** (bottles, crates as own products): same flow, deposit price credited.
- **Tied empties** (implied containers of full products): BOM explosion shown on delivery confirm
  ("24×bottle + 1×crate will be due"); driver records actual empties taken (default = implied qty,
  editable); delta = empties receivable/credit at settlement.
- Deposit ledger = plain product valuation (empties are stocked items); no separate ownership model v1.

---

## 15. Output & documents (QWeb)

| Report | Model | Notes |
|---|---|---|
| `dsd.report.tour.manifest` | tour | stop chain w/ sequence, addresses, notes, receiving hours, aggregation totals, barcode per stop; role-aware |
| `dsd.report.load.list` | load picking | picking list for warehouse, counting-group grouped |
| `dsd.report.valuated.delivery` | picking | delivery note **with prices** (pricelist-accurate at print time); footer "not an invoice" unless POD=invoice |
| `dsd.report.check.slip` | check record | out/in, materials + payment methods, signature box |
| `dsd.report.reload.list` | reload | delta material list |
| `dsd.report.collection.receipt` | payment | receipt, reprint= COPY |
| `dsd.report.invoice` | account.move | standard invoice + COPY flag; signature slot (ph7) |
| `dsd.report.settlement` | settlement | header grid, cash & qty differences, document-flow summary |

Bundle printing: tour action "Print tour documents" → manifest + valuated notes + blank check slips
in one PDF (SAP spool-bundle parity). Cron option for date-gated auto-print.

---

## 16. Financial integration

### 16.1 Journals

- Company `dsd_cash_journal_id` (Cash), per-driver custody journals optional; bank/handover journal standard.

### 16.2 Driver custody accounting

Driver settlement partner holds: collections taken (credit) vs hands-over & expenses (debit);
clearing account `dsd_driver_clearing_account_id` balances custody; report per driver.

### 16.3 Credit policy

`res.partner.dsd_credit_limit` + receivable `credit`; policy `warn|block` at console invoice step
and backoffice order confirm; over-limit activity to sales team.

### 16.4 Difference/interim accounts

`dsd_inv_diff_gain/loss_account_id` (stock differences), `dsd_cash_diff_account_id`,
`dsd_driver_clearing_account_id` — all on company settings; journal entries created only by
settlement run (never silently at data entry).

---

## 17. Security

Groups (on top of standard):
`dsd_group_user` (back-office planning), `dsd_group_dispatcher` (+ tours/loading/checks),
`dsd_group_driver` (console; record rule: only own lists/tours/settlements read, no unlink),
`dsd_group_supervisor` (check countersign, force-accept differences),
`dsd_group_settlement` (settlement run, release), `dsd_group_manager` (settings/config).

Record rules: driver → `driver_id.user_id = user.id` (multi-company rule standard). Console
controllers re-check group membership. Access CSV matrix per model (read/write/create/unlink)
reviewed per phase.

---

## 18. APIs & extension points

### 18.1 JSON API (console + future offline client)

Versioned `/api/dsd/v1/` endpoints (auth: session or API key): `tour.start|stop_data`,
`visit.arrive|depart|status`, `delivery.confirm`, `order.create`, `payment.collect`,
`expense.add`, `stock.adjust`, `check.submit`, `reload.request`. All endpoints are thin wrappers
around the same public model methods the UI calls — one business path, two clients.
Idempotency: `client_ref` unique per driver-day (future offline safety), stored on
`dsd.api.call.log`.

### 18.2 Extension hooks (methods designed for override)

`_dsd_compute_stop_sequence()`, `_dsd_capacity_checks()`, `_dsd_apply_deal_conditions()`,
`_dsd_difference_determination()`, `_dsd_settlement_steps()` (ordered list),
`prepare_optimization_payload()` (route-optimizer export), `prepare_vso_payload()` (future).

### 18.3 External integrations kept open

Route optimization (export/import stop lists), BI (SQL views), payment terminals (via
`account_payment` providers), EDI/DEX (excluded, documented boundary).

---

## 19. Data, demo, migration

### 19.1 Demo dataset (`demo/`)

1 route + 1 warehouse; 2 vans (vehicles) + drivers; 8 customers (2 with POD profile, 2 cash-collect,
1 over-credit, 1 one-time); products: beverages full goods + empties + deposits + packaging;
1 visit plan per role (4); deal condition sample; assortment deny (school × alcohol);
tolerance groups; journals & accounts (works on unlocalized DB).

### 19.2 Initial load support

Partner import with DSD fields (list view import), route/plan import templates, product DSD-tab
import; geocode bulk wizard.

### 19.3 Removal of the previous prototype

- Delete `src/dsd_core` and its docker-addons symlink; drop tables by uninstalling `dsd_core`
  from the dev DB **before** removing code (keeps demo DB clean); old ADRs stay in git history.
- This plan + new ADR set become the single source of truth; update `docs/README.md` index.

---

## 20. Test strategy

- **Unit (`TransactionCase`)** per domain: recurrence/generation matrix (weekday sets, holidays,
  exceptions, watermark), capacity loop order & attempts, difference formulas & tolerances,
  deal-condition AND/OR matching, assortment deny, credit block, LU/aggregation math, empties
  explosion, license/lock validation, sequence/numbering.
- **Integration (`HttpCase`/server flow)** per role end-to-end:
  P1 preseller plan→list→order→next-tour delivery; P2 delivery load→check-out→deliver→check-in→settlement;
  P3 van speculative→sell→returns→settlement w/ cash diff; P4 mixed + reload mid-tour + deal
  condition + manual discount; P5 paper fallback (backoffice entry only) settlement; P6 rejection
  paths (over-tolerance, missing check-in) & idempotent re-run; P7 console UI smoke (HttpCase with
  phantomjs-less runner: OWL app renders, stop actions available per role).
- **Non-functional:** van-ATP isolation; multi-user concurrent visit confirm; performance smoke
  (route with 60 stops, 300 order lines); print bundles render.
- CI: `docker compose exec odoo odoo -u dsd -d test_dsd --test-enable --stop-after-init`
  (fresh DB job nightly; target ≥ 85% line coverage of `models/`).

---

## 21. Delivery plan (phases, tasks, acceptance criteria)

> Each phase ends with: demo script passing on `odoo` dev DB, tests green, docs/README updated.
> Estimates are focused engineering days (1 dev + review).

### Phase 0 — Skeleton & master data (≈5d)
Module scaffold, settings, sequences, security groups, all master-data extensions
(driver/vehicle+van location/route/product tabs/partner DSD tab), lock periods, license categories,
counting groups, aggregation, tolerance groups, reason catalogs, demo data v0, CI harness.
**AC:** install on clean DB; master data CRUD + constraint tests; van location auto-create test.

### Phase 1 — Visit Control (≈7d)
Plan types (role matrix), visit plans & lines (recurrence engines), appointment materialization +
cron, list generation wizard (dry-run/log/watermark), list maintenance UI (drag/add/postpone),
partner upcoming-visits view, sale-order proposal (route/date).
**AC:** 4 plans (one per role) generate a week of lists correctly incl. holiday/exception cases;
order-entry proposal test; P1 integration test green.

### Phase 2 — Tour preparation (≈7d)
Tour batch extension + validations, load-out aggregation picking, picking re-routing to van,
speculative load doc, tour generation wizard (capacity order, attempts, distribution,
new-customers), tours kanban + shipment-list views, aggregation/LU computations, materials overview.
**AC:** wizard builds tours for mixed scenario with capacity split logged; validations block
unlicensed driver; P2 prep tests green (no execution yet).

### Phase 3 — Loading & tour execution core (≈9d)
Loading confirmation (counting groups/UoM hierarchy/seals/diff resolution), check-out/in records
(+payment lines, supervisor countersign), reload + unload pickings, tour status automations,
van stock views/ATP isolation, odometer/expenses hooks, van inventory adjustments.
**AC:** full logistics loop (load→confirm→checkout→[reload]→checkin→unload) with differences
reason-coded; stock visibility tests; status timeline on chatter.

### Phase 4 — Driver console v1 (≈10d)
OWL shell + today view; stop screen with all activities gated by role; delivery confirm with
actuals/returns; van sale cart with pricing/deal conditions/manual discount/assortment/credit;
collections with invoice assignment + receipt print; unplanned visits, resequencing, not-visited;
statistics panel; print POD/invoice; barcode scan-open; start/end tour flows calling Phase-3 tools.
**AC:** phone-viewport usable (360px); P1–P4 integration tests pass **through console methods**;
paper-fallback screens (settlement editing) cover the same fields.

### Phase 5 — Settlement engine (≈9d)
Settlement model + worklist, difference determination + tolerances, data-review tabs, final
settlement run (all steps, idempotent, progress grid), clearing & hands-over, difference/interim
postings, settlement PDF + logs + document-flow popover, auto-trigger cron & exclusions.
**AC:** P2/P3/P5/P6 scenarios settle with expected postings (reconciled invoices, driver custody
balance zero after hand-over); idempotency test re-runs run safely.

### Phase 6 — Van sales & mixed hardening + empties/deposits (≈6d)
Empties BOM explosion on confirm + empties returns + deposit credits; consolidated invoicing
profile; one-time customers; statistics-driven speculative load proposal; per-role console polish.
**AC:** empties owed/returned deltas reflected in settlement; consolidated invoice per day test.

### Phase 7 — Output bundle, signatures, polish (≈5d)
All QWeb reports + bundle printing + copy flags; signature capture attachments (POD/invoice/check);
map links; dashboards (route KPIs, differences per driver, sales per stop) + digest; i18n hooks (EN default).
**AC:** bundle PDF for a mixed tour; reprint shows COPY; dashboards populated from demo.

### Phase 8 — Ops readiness & deferred items (≈4d+)
Trade assets, vehicle-check questionnaire, runbook & UAT plan refresh, performance pass,
final security review, versioned API freeze + `dsd.api.call.log`.
**AC:** runbook drills (backup/restore, clean-install) pass; UAT script v2 executed.

**Total P0+P1 scope: ≈ 62 days** (contingency +15% ⇒ ~70). Phase 8 items can slip post-go-live
except runbook/UAT (mandatory).

---

## 22. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Console scope creep (mobile app envy) | schedule | ADR-106: online v1; API contract frozen early; no offline promises |
| Capacity algorithm edge cases (SAP attempts semantics) | wrong splits | port SAP order/attempt rules verbatim + property-based unit tests |
| Settlement correctness (money) | financial trust | idempotent steps, tolerance engine tests, reconciliation asserts, force-accept audit |
| Van-ATP leakage (van stock promised to warehouse orders) | overselling | reservation-location isolation tests in Phase 3 gate |
| Odoo 20 UI churn (kanban/OWL) | rework | stick to documented patterns already proven (`card` templates, no chained modifiers) |
| Pricing complexity vs deal conditions overlap | confusion | deal conditions own "tour promotions"; pricelists own base prices; loyalty excluded from DSD docs |
| Single-dev bus factor | continuity | this doc + ADRs + tests as spec; module boundaries per section |

---

## 23. Traceability matrix (SAP object → Odoo implementation)

| SAP | Odoo 20 / `dsd` |
|---|---|
| Customer master DSD additional data | `res.partner` DSD tab (§7.2) |
| Geocoding / `/DSD/VC_GEOCODE` | `base_geolocalize` + bulk wizard |
| Enhanced terms of payment | partner payment profile fields |
| Driver master (account group, license cats, lock times) | `dsd.driver` on `hr.employee` + `dsd.license.category` + `dsd.lock.period` |
| Vehicle/equipment master + VSO type | `fleet.vehicle` ext + `fleet.vehicle.model.category` (no VSO) |
| Tour master (header/individual, sequence, capacities) | `dsd.route` + tour fields on `stock.picking.batch` (§9.1) |
| Material DSD data / aggregation / loading units | product DSD tab + `dsd.aggregation` + `product.packaging` |
| Counting groups + UoM hierarchy | `dsd.counting.group` |
| Visit plan / plan type / appointment rules / non-appointments | `dsd.visit.plan(.line)`, `dsd.visit.plan.type`, exceptions |
| Visit list / reference documents / rescheduling | `dsd.visit.list(.line)` + refs + RS status |
| Time stream / calendar types / `/DSD/VC_CAL_FILL` | `dsd.visit.appointment` + cron |
| DSD-relevant order type date/route proposal | sale.order computes (§10.2) |
| Shipment (V7) + DSD fields + checks | tour on batch + validation layer (§9.5) |
| Dynamic transportation planning `/DSD/RP_DYNDISP` | `dsd.tour.generate` (§10.3→9.3) |
| Capacity limits (6, fixed order) | route flags + vehicle category (§9.4) |
| Shipment list | tours kanban/list |
| VSO | excluded; payload hook |
| Output control / message control / spool | report actions + bundle print + date-gated cron |
| Valuated delivery note | `dsd.report.valuated.delivery` |
| Loading confirmation `/DSD/SV_LC_*` | `dsd.loading.confirmation` |
| Check-out/in (+reload) | `dsd.check.record` |
| Reload `/DSD/SV_RELOAD` | `dsd.reload` |
| Stock visibility `/DSD/SV_*` (truck stock, unloading doc) | van location + quants + `dsd.unload` picking |
| Tour status profiles + follow-ups | state + chatter log + `base_automation` |
| Tour data entry `/DSD/DE_ENTRY` | console + settlement review tabs |
| Settlement cockpit `/DSD/SL_COCKPIT` | `dsd.settlement` worklist |
| Difference determination + tolerances | engine §13.3 + `dsd.tolerance.group` |
| Final settlement run | `action_run_settlement` §13.7 |
| Collection clearing | §13.5 |
| Settlement document / application log / document flow | settlement PDF + `dsd.settlement.log` + flow popover |
| Interim accounts (driver/customer, ±/final differences) | company account config §16.4 |
| Settlement office / types | dropped (groups + sales team) — recorded |
| MDSD download/upload, DSD connector, DOE | online now; `/api/dsd/v1` for future |
| Deal condition | `dsd.deal.condition` |
| Manual discount | driver discount authority + line reasons |
| Listing/exclusion | `dsd.assortment` |
| Statistics `/DSD/GS_QU` | SQL stat view |
| Barcodes (customer id, waiting time) | partner barcode + arrival/departure stamps |
| Electronic signature / ArchiveLink | attachments (ph7) — non-legal, as in SAP |
| DEX | excluded |
| Occasional-connect ATP/pricing | n/a online |
| One-time customers | quick partner |
| Invoice original/copy | print flags |
| Trade assets (SP01) | `dsd.trade.asset` (ph8) |
| Vehicle checks catalog | questionnaire (ph8) |
| Mobile reports (SP01) | saved filters/dashboards |

---

## 24. Glossary

**Tour** — one vehicle/driver day-run (batch of deliveries + visit list). **Visit list** — ordered
customer stops for a date. **Speculative load** — van stock without pre-sold orders. **Check-out/in** —
custody counts (goods + cash) at tour boundaries. **Loading confirmation** — count of the loaded
truck vs plan before departure. **Reload** — mid-tour depot stop. **Route settlement** — controlled
reconciliation + posting of a finished tour. **Deal condition** — limited-time tour promotion
(free goods/discount). **Empties** — returnable containers (tied = implied by full goods BOM).
**POD** — proof of delivery printed instead of invoice. **RS/UP/NP/SP/PP** — visit statuses
(rescheduled / unsuccessfully / not / successfully / partially processed).
