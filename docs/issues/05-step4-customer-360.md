# [Step 4 — DEV TASK] Customer 360 — DSD panel on the partner (`dsd_core`)

> Fourth development task. Master plan: #1 · Builds on #2 (SA), #3 (routes),
> #4 (visit plans).
> Spec version: draft v1 (2026-11-18) — **pending approval before posting**.

## Goal

Surface the DSD context built so far **on the customer** (the "360" view)
and complete the geo/address master block from M01 §3.1 that is consumed by
the future download emitter (`MSE_CUSTOMER_HD`): coordinates + provenance,
city/district codes. No new business logic — this step is read-through +
master fields.

- Same constraints: Odoo 20, Community-compatible, `depends` **unchanged**
  (`base, product, stock`), LGPL-3, no chatter.

## 0. Odoo-native survey (standing rule)

| Odoo 20 native | Verdict |
|---|---|
| `res.partner.partner_latitude / partner_longitude` (in **base**, no dep) | ✓ reuse — no new fields |
| `res.partner.state_id` (address province/state, native) | ✓ **region (SAP T005S) maps here — do NOT add a duplicate `dsd_region_state_id`** (native-first correction of M01 §3.1) |
| `res.partner.parent_id` (company/contact structure) | native hierarchy — SAP `KNVH` 7-level hierarchy is a *different* concept (emit-only) → deferred, not mapped to parent_id |
| `base_geolocalize` (geocoding via online APIs) | ✗ not a dependency — optional at deployment; manual/gps coordinates work without it |
| `res.partner.category` tags | ✗ not used (no semantics) |

## 1. Data model

### 1.1 `res.partner` additions (extend step-1 inherit)

| Field | Type | Stored | Notes |
|---|---|---|---|
| `dsd_route_ids` | computed Many2many `dsd.route` | no | distinct routes via `dsd.route.customer` memberships (active + validity-open rows only) |
| `dsd_geo_source` | Selection `debgeo/geocode/manual/gps` | yes | provenance: `debgeo` = imported from legacy SAP `/DSD/RP_DEBGEO` table; `geocode` = address-geocoded; `manual` = operator-entered; `gps` = captured from device GPS. Mutations audited via standard `write_uid/write_date`; richer geo audit lands with the geofence step |
| `dsd_geo_precision` | Char | yes | wire `PRECISID` passthrough (master-owned per M01 §3.1) |
| `dsd_city_code` | Char | yes | `T005H.CITYC` (Iranian city code) |
| `dsd_district` | Char | yes | wire `DISTRICT` |
| `dsd_county_code` | Char | yes | wire `COUNTY_CODE` |

Deferred (wire/CRM, join when consumed — M01 §3.1): hierarchy 1–7, legal
numbers 1–3, `stcd2/5` tax ids + branch, CPD markers, target groups,
geofence flag (per-SA in the package — arrives with LORD flags at the
gateway step).

**Interim note (review 4.1):** the free-char geo codes (`city_code`,
`district`, `county_code`) are a v1 carrier; a proper **Geographic Master
Data** model (country→province→county→city→district, translated names) is
registered in the master-plan roadmap (P1) and these fields migrate into
m2o references then — code must not branch on the raw strings meanwhile.

### 1.2 Behavior rules

1. `dsd_route_ids`: read-only, computed from `dsd.route.customer` rows
   where `route_id.active` AND membership window covers today
   (`valid_from ≤ today ≤ valid_to`, empty bounds open). Non-stored ⇒ the
   **search method is REQUIRED** (spec fix, review 4.3) — the "On a route"
   filter must work; no "optional".
2. No writes to native lat/long in this step (operators set them via the
   native Contacts form / geocoding module if installed).

## 2. Views

- Partner form, existing **Sales Areas** page (step 1): add a
  **"Routes"** group at top (the `dsd_route_ids` tags/chips, readonly) and a
  **"Geo & Address Codes"** group (lat, long readonly, geo source,
  precision, city code, district, county code). Keep page name or rename to
  "DSD" — developer's choice, keep it consistent.
- Partner search: filter "On a route" (`dsd_route_ids` search method) and
  "Geo missing" (`partner_latitude = 0 AND partner_longitude = 0`).
- No new menus.

## 3. Security

No new models — existing partner access applies; no `ir.access.csv` changes.

## 4. Tests (`TransactionCase`, `@tagged('standard')`)

1. partner with two memberships (one expired window) → `dsd_route_ids`
   shows only the active-window route
2. archived route hides from `dsd_route_ids`
3. geo fields persist (source/precision/city/district/county)
4. "On a route" search filter returns the right partners
5. "Geo missing" filter returns partners without coordinates

## 5. Definition of done

- [ ] Installs clean on fresh Odoo 20 DB; full suite green
      (`--test-tags /dsd_core`, steps 1–4 together)
- [ ] `depends` unchanged — lat/long come from base, zero new deps
- [ ] Route read-through respects validity windows + archived routes
- [ ] PR to `main` with screenshot of the partner DSD page (routes + geo)

## Out of scope (do NOT build)

Geocoding integration (`base_geolocalize` stays optional), SAP hierarchy
1–7, legal/tax wire fields, CPD markers, target groups, geofence, per-SA
LORD flags, map widgets.

## References

- Package M01 §3.1 (customer master field table — geo/city/district block,
  `PRECISID`, T005H/T005S notes)
- Steps #2/#3/#4 supply SA rows, memberships, plans
