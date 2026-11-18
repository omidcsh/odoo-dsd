# Architecture Review — Verdicts & Application Log

**Input:** external review of the master plan + 6 step specs (2026-11-18).
**Method:** each point verified against the SAP package, the MDSD source and
Odoo 20 semantics; then applied to the specs. Verdicts: ✅ accepted · 🔶
accepted with modification · ❌ not adopted (reason given).

## P0 items (before further development)

| # | Review point | Verdict | Applied where |
|---|---|---|---|
| 1 | Pricing must come from the **visit/order's sales area**, not the partner-level property | ✅ | Step 1 §1.3 (sync rule removed), Step 5 (order creation), Step 6 (prices endpoint) — logged as **D9** |
| 2 | Vehicle mandatory for presales is wrong; `fleet` missing from depends | ✅ real bug | Step 5: vehicle optional + `fleet` in depends |
| 3 | Visit completion must be decoupled from order existence | ✅ | Step 5: explicit visit lifecycle, no auto-done |
| 4 | Visit list needs one explicit source (route/plan/manual) | ✅ | Step 5: `source_type` selection + consistency rules |
| 5 | 1-live-tour-per-list must be DB-enforced (partial unique index) | ✅ | Step 5: partial unique index via `init()` SQL |
| 6 | Mobile auth must be ONE contract | ✅ | Step 6: session-only v1 (`/web/session/authenticate`); API keys deferred with rationale |
| 7 | Return ≠ negative quantities | 🔶 adopted with modification | Step 6: return = `sale.order` flagged `dsd_is_return` with **positive** qty lines; fulfilment (goods receipt / credit note) deliberately deferred to the distribution step — an independent return *model* now would be speculative before stock flows exist |
| 8 | Roadmap/numbering contradiction | 🔶 partially stale | The reviewer read an older snapshot; master plan already had the 9-step/D8 layout — re-verified and tightened (step↔issue mapping explicit) |
| 9 | Multi-company / org context undefined | 🔶 minimal adoption | `company_id` added to `dsd.sales.area` + `dsd.partner.sales.area` now (cheap, avoids breaking change); full multi-company record rules → P1 |

## Step-level fixes (P1-flavored, applied now since cheap)

- **Step 1:** `is_primary` boolean + one-primary constraint (replaces
  "first active by id"); PF defaults also server-side (create), not only
  onchange; plant=warehouse documented as a *deployment mapping assumption*;
  partner block read-through relabeled **filtering-only, never enforcement**.
- **Step 2:** membership history — plain unique replaced by
  **no-overlapping-validity-windows** constraint (re-join later = new row);
  route↔membership SA compatibility validation; `driver_ids` clarified as
  *permissions* (daily assignment lives on the tour, step 5).
- **Step 3:** plan↔line SA consistency constraint; single default plan type
  (constraint); state transitions defined (draft editable → active lines
  locked → closed terminal, no reopen); `weekday_mask` CHECK 1..127;
  generation semantics = date in BOTH windows AND weekday bit.
- **Step 4:** `dsd_route_ids` search method now **required** (spec gap);
  geo_source values documented (incl. `debgeo` = legacy SAP
  `/DSD/RP_DEBGEO` import); city/district chars marked **interim** —
  Geographic Master Data registered in the roadmap (P1).
- **Step 5:** audit strategy answered the Odoo-native way — **`mail`
  dependency added**; `mail.thread` + tracking on tour/visit/list (who
  skipped/cancelled/reset — review point 4.4); unlock guards extended to
  *any operational activity*, reason required; `planned_from/to` finalized
  as optional Datetime.
- **Step 6:** roles — **`group_dsd_driver` added** (drivers write their own
  day: visits, orders, returns; officer = back-office; admin = reset/config);
  day package bounded (operational snapshot) + reference data via
  **`/catalog`** endpoint with pagination; **idempotency everywhere** —
  `tour/download` becomes find-or-materialize (retry returns the same
  package; `tour_already_downloaded` error removed), `visit/status` gets
  `client_uuid`; prices endpoint takes **visit/SA context** (+date, uom)
  and returns taxes; `dsd.customizing` gets `value_type` + per-scope partial
  uniques + `config_version` in the day package; API contract stated
  explicitly: **JSON over HTTP (not JSON-RPC)**, envelope
  `{ok, data}` / `{error:{code, message}}`.

## Not adopted (with reasons)

- **Independent DSD Plant entity now** (review 1.3): no evidence yet that
  `stock.warehouse` is insufficient for Solico's operations; the assumption
  is documented and revisitable at the van-stock step — building a parallel
  concept now is speculative.
- **Full independent Return business model now** (see P0-7): deferred to the
  distribution step where stock/accounting flows exist; v1 API records
  return intent cleanly (positive qty + flag).
- **Full record rules per SA/driver in ACL files now**: API-layer
  enforcement lands with steps 5–6 (driver=uid scoping); ir.access record
  rules → P1 security pass, to avoid blocking the vertical slice.

## Wording

Master plan rephrased from "SAP-style DSD" to **"SAP-inspired DSD platform"**
(business-process compatibility ≠ technical wire compatibility — D8).
