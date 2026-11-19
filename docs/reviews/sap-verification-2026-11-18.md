# SAP Verification of the DSD Specs — 2026-11-18

Live system: Solico SAP (client 100), via the vsp/mcphub MCP tools
(read-only). Every core claim of the specs was checked against real tables.

## Verified ✅ (spec claim ↔ SAP evidence)

| Spec claim | SAP evidence | Verdict |
|---|---|---|
| Catalogs org/channel/division are CLIENT-level (shared across orgs) | TVTWT/TSPAT have no VKORG — one channel/division definition reused by all orgs | ✅ matches our global catalogs + per-company combo |
| Valid-combination entity (TVTA equivalent) | TVTA holds the valid (VKORG, VTWEG, SPART) rows — **4,116 combos** | ✅ model correct; scale insight below |
| 3 document blocks per customer-SA | KNVV has `AUFSD` (order), `LIFSD` (delivery), `FAKSD` (billing) — as **reason-code chars**, block = non-empty | ✅ our bool+reason covers it; migration maps AUFSD→(block=True, reason) |
| 4 partner functions per SA | KNVP `AG/WE/RE/RG` per (customer, SA); defaults = self (DC000001→DC000001 observed) | ✅ |
| Multi-SA customers are real | customers with **up to 40 sales areas** (KNVV group-by) | ✅ validates is_primary AND D9 pricing-from-visit-SA (partner-level property would have been wrong at this scale) |
| Visit plan: type/validity/driver/route/vehicle/auth-group/SA-trio | `ZSLC_DSD_VP_H`: VPTYP, DATFR/DATTO, DRIVER1/DRIVER2, ROUTE, TRUCK/TRAIL, AUTH, SALES_ORG/DIST_CHANNEL/DIVISION | ✅ near field-by-field |
| Weekday pattern on the plan | VP_H has MONDAY…SUNDAY char flags + RULE_TYPE/WEEK_RULE (weekly patterns) | ✅ (representation differs — see D10) |
| Tour header exists with route+plan-type+stops | `/DSD/RP_TOH`: ROUTE, VPTYP, STOPS, MAXTIME | ✅ |

## Scale reality (affects specs)

- **146 sales organizations** (TVKOT, EN text rows — recounted 2026-11-19; the
  earlier "~100" was an undercount; TVKOT: Iran + all Iraq operations — Baghdad,
  Karbala, Basrah, Erbil, Mosul, Najaf, Kirkuk…)
- **52 distribution channels** (TVTWT), **26 divisions** (TSPAT, recounted
  2026-11-19 — one added since the first count), **4,116 valid sales-area
  combos** (TVTA)
- Consequences: (a) manual combo creation is impossible — the migration
  needs a **bulk import from TVKOT/TVTWT/TSPAT/TVTA**; (b) combo pickers
  must be searchable/filterable, never flat dropdowns; (c) multi-company
  is not hypothetical — the round-2 `(company, trio)` unique is mandatory;
  (d) drivers see a tiny slice — the day-package stays bounded.

## Divergences found ⚠️

1. **Weekdays live on the PLAN, not the route** — Solico's real route
   master `ZSLC_DSD_ROUTES` has no weekday fields: it is (MASIR = sales
   group code, VKBUR = sales office, PRESELLER, PHONESELLER). Weekdays are
   on `ZSLC_DSD_VP_H` (plan header). Our step-2 put weekday booleans on
   `dsd.route` AND step-3 has per-line `weekday_mask` → duplication risk.
   → **Open decision D10** (below).
2. **Route ≠ warehouse-centric** — their route ties to sales office/group
   (VKBUR/MASIR), not a shipping point. Our `warehouse_id` on route is a
   departure (defensible: Odoo-native departure point) — keep, but the
   migration mapping document must state MASIR→route, VKBUR→? explicitly.
3. **Plan extras we lack (minor)**: `LIMFR/LIMTO` (extra restriction
   window inside validity), `DRIVER2` co-driver, `STIME` default start
   time, `RULE_TYPE/WEEK_RULE` (weekly frequency patterns like
   every-2-weeks).
4. **Blocks are reason codes, not booleans** (see mapping note above) —
   compatible, just document the migration mapping.
5. Channel "B2C-Van Sales" (VTWEG 26) exists but has **no KNVV customers**
   in client 100 — which channel(s) actually run DSD presales is an open
   data question for the migration scope (check ZSLC_DSD_VP_H data).

## Standard-object verification (round 2, on user request — standard /DSD/* over Z)

Full standard table landscape enumerated (~180 TRANSP tables: VC visit
control, RP route planning, HH handheld/tour master, ME mobile entities,
SL settlement, ST status). Key structures inspected:

| Standard table | Content | Spec impact |
|---|---|---|
| `/DSD/VC_VPH` | visit plan HEADER: VPID/type/name/rule, **MON..SUN flags**, truck/trailer, start time/zone, start/dest point, DRIVER1/2, route, DATFR/DATTO + **LIMFR/LIMTO** restriction window, AUTH group, **SA trio** | weekdays-on-plan-header is STANDARD SAP (not Solico Z taste) → strengthens D10(a) |
| `/DSD/VC_VPP` | plan POSITIONS: item no + SEQU + KUNNR + **VKORG/VTWEG/SPARTE per line** + INACTIVE flag + per-customer RULEID + waiting/driving times + contact person | validates our per-line `partner_sales_area_id` + sequence + validity; per-line rule ≈ our weekday_mask |
| `/DSD/VC_VPTYPE` | plan TYPE is a config hub (real data: MW1–MW5, YW1–YW5): **VLHH** (visit-list doc) vs **TRHH** (shipment doc), SLTYP settlement type (M1/M2/YW/YZ), CALTYP calendar (ZB/ZP/ZV), PAFKT function, number ranges, output determination | our minimal type (code/name/default) needs a `mode` field (visit-list vs shipment production); settlement/calendar passthrough deferred to their steps |
| `/DSD/RP_TOH` | tour header: ROUTE, VPTYP, TPLST, STOPS, MAXTIME | tour born from route+plan-type confirmed |
| `ZSLC_DSD_*` | Z layer = enhancements of the standards (VP_H adds RULE_TYPE/WEEK_RULE; ROUTES = masir→sales-office/preseller mapping) | Z is the legacy we replace — do NOT model after it |

**Refined D10 recommendation:** standard SAP = weekdays on the plan HEADER
(+ per-line rule overrides). So: (a-refined) put the weekday pattern on
`dsd.visit.plan` header (7 flags or mask), keep the line-level mask as an
OPTIONAL override, and drop weekdays from `dsd.route` entirely (no standard
or Z route master carries them). This matches `/DSD/VC_VPH`+`/DSD/VC_VPP`
exactly.



**Where does the weekday pattern live?** Options:
(a) plan-only (SAP-faithful): drop weekdays from `dsd.route`; populate
uses plan line masks — route stays a pure grouping/ordering master.
(b) keep both (current specs): route weekdays = default convenience,
plan line mask overrides. Recommendation: **(a)** — matches the live
system, removes duplication; populate-from-route then needs no weekday
logic at all.

## Re-verification round 3 — 2026-11-19 (issues 02–10 vs live SAP + Odoo 20 source)

All SAP claims of issues 02–10 re-checked live (client 100). Field lists
pulled from DD03L (ADT cannot serve `/DSD/*` namespace tables). Verdicts:

| Claim | Evidence | Verdict |
|---|---|---|
| Catalogs client-level; TVTA combos | TVKOT 146 orgs (EN), TVTWT 52, TSPAT 26, TVTA 4,116 | ✅ |
| KNVV blocks order/delivery/billing | AUFSD/LIFSD/FAKSD (+ PLTYP/KONDA/WAERS per SA) | ✅ |
| Weekdays on plan header (D10) | `/DSD/VC_VPH`: MONDAY…SUNDAY + DATFR/DATTO + LIMFR/LIMTO + DRIVER1/2 + ROUTE + SA trio | ✅ |
| Per-line rule override | `/DSD/VC_VPP`: RULEID_CUST + SEQU + KUNNR + VKORG/VTWEG/SPARTE per line + INACTIVE | ✅ |
| Plan-type hub | `/DSD/VC_VPTYPE` rows MW1–MW5/YW1–YW5: VLHH/TRHH, SLTYP M1/M2/YW/YZ, CALTYP ZB/ZP/ZV | ✅ |
| Tour born from route+plan-type | `/DSD/RP_TOH`: ROUTE, VPTYP, TPLST, STOPS, MAXTIME | ✅ |
| Solico route master has NO weekdays | `ZSLC_DSD_ROUTES`: only MASIR, VKBUR, PRESELLER, PHONESELLER | ✅ |
| Geo provenance (step 4) | `/DSD/RP_DEBGEO`: KUNNR, LATITUDE, LONGITUDE, PRECISID; T005H: CITYC+REGIO+BEZEI | ✅ |
| COCI header shape (step 10/9) | `/DSD/ME_COCI_HD`: TOUR_ID, CHECK_ID, CHECK_DIRECT, CHECKER, CHECK_DATE/TIME, CHECK_TYPE, ME_ACTION, PLANT | ✅ |
| Reference-invoice field (issue #9/step 8) | LIPS `ZZVGBEL_VF` (Z-enhancement) | ✅ |
| Delivery types | TVLK: LF (outbound, VBTYP J), LR/NCR (returns, T), EL (inbound, 7) | ✅ |

New finding: `/DSD/VC_VPH` and `/DSD/VC_VPP` both carry `/EMSE/*` append
fields (`COL_CRM_ACT`, `CRM_ACT_MAX_DURATION`) — mobile-engine CRM-activity
flags; relevant when the CRM-activity step lands.

Odoo 20 source side (same day, pinned tree, release 20.0 FINAL): 13/16
claims verified (auto_batch + criteria, batch action_assign/action_done +
states + member compatibility, partially_available move-level, web_map =
OEEL-1, ir.access.csv format, res.groups.privilege, `<list>`/`column_invisible`,
models.Constraint, base partner lat/long, commitment_date, 0..N pickings,
stock.lot/quant inventory/fleet driver_id, dateutil). Two spec errors found
and fixed in the issues: `picking_type_entreprise_picking_type` does NOT
exist in Odoo 20 (issue #9 input domain reworded — real gating is
`stock.group_stock_picking_batch`); `type="json"` routes are a deprecated
alias of `type="jsonrpc"` since 19.0 (issue #7 transport row updated).
