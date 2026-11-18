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

- **~100 sales organizations** (TVKOT: Iran + all Iraq operations — Baghdad,
  Karbala, Basrah, Erbil, Mosul, Najaf, Kirkuk…)
- **52 distribution channels** (TVTWT), **25 divisions** (TSPAT),
  **4,116 valid sales-area combos** (TVTA)
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

## Open decision D10 (needs user)

**Where does the weekday pattern live?** Options:
(a) plan-only (SAP-faithful): drop weekdays from `dsd.route`; populate
uses plan line masks — route stays a pure grouping/ordering master.
(b) keep both (current specs): route weekdays = default convenience,
plan line mask overrides. Recommendation: **(a)** — matches the live
system, removes duplication; populate-from-route then needs no weekday
logic at all.
