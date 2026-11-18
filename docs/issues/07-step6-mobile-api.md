# [Step 6 — DEV TASK] Mobile API v1 — sales scenario (`dsd_core`)

> Sixth development task. Master plan: #1 · Builds on step 5 (presales day
> models: visit list → on-demand tour → visits → orders). Implements
> decision **D8** (native mobile app + clean Odoo JSON API, online-first).
> Spec version: draft v1 (2026-11-18) — **pending approval before posting**.

## Goal — the app can run the whole sales day against Odoo

A native Android/iOS app (built separately, against this API) must be able
to: log in, download its day (tour, visits, customers, products, configs,
customizing, prices), work the visits, and send back orders, returns, visit
statuses — plus **cancel & copy** on orders. **Everything online (D8):**
every read AND write is a live server call — including pricing (the app asks
Odoo and displays the returned price; it never computes). The server is the
single source of truth; no offline mode is designed in v1 (if the app caches
for UX, that is its own concern and never authoritative).

- Lives in `dsd_core/controllers/` (split to its own module at publish time
  if the suite needs it). `depends` unchanged by this step (controllers are
  part of dsd_core; `sale` arrives with step 5).
- Versioned prefix: **`/dsd/api/v1/`** — the app team can freeze against v1.

## 0. Odoo-native survey (standing rule)

| Concern | Odoo 20 native | Verdict |
|---|---|---|
| Transport | `odoo.http` controllers, `type="json"` routes | ✓ reuse |
| Auth | **v1 decision: session-based only** — app calls standard `/web/session/authenticate`, keeps the session cookie, all routes `auth="user"`. API-key auth deferred to a later step with device registration + revocation design (review 6.1: one contract, not two maybes) | ✓ reuse |
| Serialization | JSON request params / `request.make_response` | ✓ |
| Verb style | Odoo routes accept any method; v1 convention: **POST + JSON body for everything** (actions are RPC-flavored) | ✓ document clearly for the app team |
| Rate limiting | none native | skip in v1 (single-tenant app traffic) |
| Config store | `ir.config_parameter` is global-only (no SA scope) | custom `dsd.customizing` with scope resolution — per-SA behavior is a DSD requirement (MDSD `CustomizingSalesAreaBO`) |
| Style | Odoo ships JSON-RPC (`/jsonrpc`) and http controllers | v1 = **plain JSON over HTTP POST** (NOT JSON-RPC): predictable envelope for a mobile client — `{ok: true, data}` on 200, `{ok: false, error: {code, message}}` on 4xx/5xx (review 6.8) |

## 1. Endpoints (v1 — sales scenario)

### 1.1 Day package (downloads)

| Endpoint | In | Out |
|---|---|---|
| `POST /dsd/api/v1/day/get` | `{date}` | visit-list status for the caller (driver) + whether a tour exists; error `no_visit_list` if the operator prepared nothing (lists are prepared back-office — step 5) |
| `POST /dsd/api/v1/tour/download` | `{date}` | **find-or-materialize — IDEMPOTENT** (review 6.4): if a live tour exists for the list, its package is returned again (same tour/visit ids); materialization itself is concurrency-safe (DB lock, step 5). The `tour_already_downloaded` error does not exist. |
| `POST /dsd/api/v1/tour/get` | `{date}` | re-fetch the current package — serves the EXISTING tour, never re-materializes (D7 lock) |
| `POST /dsd/api/v1/catalog` | `{page, per_page}` | reference data (products: code/name/uom/category/active) **with pagination** — day package stays a bounded operational snapshot, not a product catalog dump (review 6.3) |
| `POST /dsd/api/v1/prices` | `{visit_id, items: [{product_id, qty, uom_id?}], date?}` | **server-computed prices in the VISIT's SA context** (D9 — SA, hence pricelist/company/currency, comes from the visit; optional date & uom overrides). Returns per-item price, discount, taxes. The app never computes prices. |
| `POST /dsd/api/v1/config` | `{}` | resolved customizing for the caller (see 1.2) — also embedded in the day package; standalone endpoint for refresh |

### 1.2 Config/customizing model — `dsd.customizing` (new in this step)

Behavior of the app must be changeable via config, not code. Semantics are
mined from the old app source (`/Users/kalleh/Source/Solico/MDSD`):
global keys (`CustomizingConstants.Key`, ~75) and per-sales-area flags
(`CustomizingSalesAreaBO` — the 68-field set, incl. doc-type permissions per
SA). Odoo model:

| Field | Type | Notes |
|---|---|---|
| `key` | Char, required, indexed | stable code, e.g. `SA_ORD_TYPE`, `MANUAL_DISCOUNTS` |
| `value` | Char/Text | raw value, validated per `value_type` (review 6.7b) |
| `value_type` | sel bool/int/decimal/string/json | typed values + validation; the app parses accordingly |
| `config_version` | Integer (computed) | global monotonic version — bumped on every write; embedded in every day package so the app knows when to refresh (review 6.7c) |
| `scope` | sel global/country/sales_area | resolution order on read: **sales_area → country → global → built-in default** |
| `country_id` | m2o res.country | when scope=country |
| `sales_area_id` | m2o dsd.sales.area | when scope=sales_area |
| `description` | Char | shown in the admin UI |

- Uniqueness per scope done right (review 6.7a): three PARTIAL unique
  indexes via `init()` — `(key) WHERE scope='global'`,
  `(key, country_id) WHERE scope='country'`,
  `(key, sales_area_id) WHERE scope='sales_area'` — no NULL-distinct holes.
- Admin UI: DSD → Configuration → Customizing (list/form + "effective value
  preview" per SA). Seed v1 with the **sales-scenario-relevant subset only**:
  per-SA doc permissions (`ORDER_ENABLED`, `RETURN_ENABLED`), pricing-date
  policy, `MANUAL_DISCOUNTS`, `ITEMS_PROPOSAL`, reason-mandatory flags for
  skip/cancel, `CANCEL_ALLOWED`, `COPY_ENABLED`. The rest of the ~75-key
  catalog joins step by step as features need it — never invent keys without
  an MDSD counterpart.
- The `config` payload of the day package = resolved key/value map for the
  driver's context (their SAs + company country).

### 1.3 Uploads (mutations — all online)

| Endpoint | In | Effect |
|---|---|---|
| `POST /dsd/api/v1/visit/status` | `{client_uuid, visit_id, state, reason?, gps?, occurred_at}` | planned/arrived/done/skipped (reason mandatory on skip); stamps times; **idempotent on `client_uuid`** (upsert) |
| `POST /dsd/api/v1/order` | `{client_uuid, visit_id, type: "order"\|"return", lines: [{product_id, qty, discount?}]}` | creates `sale.order` on the visit. **Return = POSITIVE quantities + `dsd_is_return=True`** (review 6.5 — no negative-qty hack). **EXPLICITLY INTERIM (MVP carrier)**: this is not the final return model — step 7 (distribution) delivers the real design: return delivery → goods receipt into stock → credit note/refund, connected to these flagged orders. Prices computed server-side; **idempotent on `client_uuid`** |
| `POST /dsd/api/v1/order/cancel` | `{client_uuid, reason}` | `action_cancel` with guards (not delivered/invoiced); reason logged |
| `POST /dsd/api/v1/order/copy` | `{source_client_uuid, new_client_uuid}` | copies lines to a NEW draft order on the same visit |

### 1.4 Cross-cutting contract

- **Idempotency everywhere (review 6.4):** `dsd_client_uuid` Char (indexed,
  unique) on `sale.order` AND on visit-status submissions; `tour/download`
  is find-or-materialize. Every retry-safe verb replays the original result.
- **Envelope:** success `200 {ok: true, data: {...}}`; failure
  `4xx/5xx {ok: false, error: {code, message, data?}}`;
  `ValidationError/UserError` → 400 with `.message`; auth → 401; unknown →
  404. `code`s are stable strings (`no_visit_list`, `order_not_cancelable`,
  `visit_already_terminal`, …) — the app branches on them.
- **Contract doc:** every payload field documented in
  `docs/mobile-api-v1.md` in this repo — the app team's frozen v1 contract.

## 2. Security

- All routes `auth="user"`, session-based (v1 contract). Reads:
  `group_dsd_user`. **Day operations (visit status, order, return, cancel,
  copy) require the new `group_dsd_driver`** — drivers run their own day
  (review 6.2: officers are back-office, must not gate every write).
  `group_dsd_officer` manages lists/back-office; admin = reset + config.

### 2.1 Server-side scoping (round 2 — groups alone are not authorization)

1. **Identity from session, never payload**: every driver-scoped endpoint
   resolves the tour by `(date, driver_id=uid)`; a `driver_id` or
   `company_id` in the payload is IGNORED (server-stamped). A driver
   physically cannot address another driver's tour — tested (cross-driver
   isolation).
2. **Record rules**: add `ir.access` domain rows for `group_dsd_driver` on
   `dsd.tour`/`dsd.visit` (`[('driver_id', '=', user.id)]`) — verify at
   implementation time that Odoo 20 `ir.access` domains evaluate `user`;
   if not supported, the controller-level checks above are the binding
   contract and the record rules land with the P1 security pass.
3. **Write surface**: drivers write ONLY through the API verbs (visit
   status, order, return, cancel, copy); they get no generic model-write
   route. List preparation, tour reset and customizing stay officer/admin.
4. **Multi-company**: API responses are company-scoped by the user's
   allowed companies; full multi-company record rules → P1.

## 3. Tests (`HttpCase`, `@tagged('standard')`)

1. `day/get`: prepared list → status; empty date → `no_visit_list`
2. `tour/download` materializes; **replay returns the same package
   (idempotent)**; concurrent downloads hit the DB lock (one winner)
3. `tour/get` after download serves the same tour/visit ids (D7)
4. `visit/status`: transitions + mandatory skip reason (400 without)
5. `order`: creates sale.order on the visit, **priced from the visit's SA
   pricelist (D9)**; replay same client_uuid → same order
6. `return`: order flagged `dsd_is_return` with POSITIVE quantities;
   fulfilment intentionally absent until the distribution step
7. `cancel`: draft OK; blocked with delivery → `order_not_cancelable`
8. `copy`: new draft on same visit, same lines
9. cross-driver isolation: driver B cannot fetch driver A's tour
10. customizing resolution: SA override beats country beats global; day
    package embeds the resolved map + `config_version`; value_type
    validation rejects bad values; duplicate same-scope key raises
11. envelope contract: success/error shapes on all endpoints; driver
    without `group_dsd_driver` cannot write; driver B gets 403/404 on
    driver A's tour

## 4. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–6)
- [ ] `docs/mobile-api-v1.md` written and reviewed (app team contract)
- [ ] Scripted sales day passes over HTTP: login → download → prices →
      2 orders + 1 return → cancel one → copy one → visit statuses
- [ ] Idempotency + error contract verified by tests
- [ ] PR to `main` with the API doc attached

## Out of scope (later steps — do NOT build)

Distribution scenario (van stock/deliveries/COCI/reload — API grows then),
offline queue/sync, push notifications, GPS streams, photos/signatures,
OTP/geofence, promotions beyond native pricelist, multi-language payloads,
pagination (day package is bounded), rate limiting.

## References

- Decisions D5/D7/D8 (issue #1 log) · step 5 entities · PRESELLER-SCENARIO
  §4–7 (business semantics — reference only, no wire formats)
