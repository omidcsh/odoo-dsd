# [Step 6 — DEV TASK] Mobile API v1 — sales scenario (`dsd_core`)

> Sixth development task. Master plan: #1 · Builds on step 5 (presales day
> models: visit list → on-demand tour → visits → orders). Implements
> decision **D8** (native mobile app + clean Odoo JSON API, online-first).
> Spec version: v1.1 (2026-11-19) — expanded with the MDSD feature set
> (login, GPS/geofence, item proposal, capture-on-hand, deal conditions).

## Goal — the app can run the whole sales day against Odoo

A native Android/iOS app (built separately, against this API) must be able
to: **log in with username/password**, download its day (tour, visits,
customers, products, configs, customizing, prices), work the visits, and
send back orders, returns, visit statuses, **GPS location, geo-fence
validation, item proposals, capture-on-hand and deal conditions** — plus
**cancel & copy** on orders. **Everything online (D8):** every read AND
write is a live server call — including pricing (the app asks Odoo and
displays the returned price; it never computes). The server is the single
source of truth; no offline mode is designed in v1 (if the app caches for
UX, that is its own concern and never authoritative).

- Lives in `dsd_core/controllers/` (split to its own module at publish time
  if the suite needs it). `depends` unchanged by this step (controllers are
  part of dsd_core; `sale` arrives with step 5).
- Versioned prefix: **`/dsd/api/v1/`** — the app team can freeze against v1.

### 0.1 Login & user provisioning (username + password)

Login uses Odoo's own credentials — no parallel user store:

1. The app calls the standard `POST /web/session/authenticate` with
   `{login, password, db}` and keeps the session cookie. Wrong credentials
   → Odoo's standard 401-ish error; nothing DSD-specific.
2. **Provisioning (configuration task, not code):** for each preseller,
   create an Odoo user (login = employee code / phone), set the password,
   and add groups `dsd_core.group_dsd_driver` (+ `base.group_user`). The
   user IS the mobile identity everywhere (D8).
3. Tests must NOT contain literal credentials — test users are created in
   the test setup with generated passwords; any demo credentials come from
   environment variables only.
4. Password reset/lockout = standard Odoo. API-key login → later step with
   device registration (unchanged decision).

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
| `POST /dsd/api/v1/prices` | `{visit_id, items: [{product_id, qty, uom_id?}], date?}` | **server-computed prices in the VISIT's SA context** (D9 — SA, hence pricelist/company/currency, comes from the visit; optional date & uom overrides). Returns per-item price, discount, taxes. The app never computes prices. *Why this endpoint exists in online mode:* it is the live replacement of the old app's local pricing engine — the preseller builds a cart and must SEE the price before submitting (qty-dependent pricelists make any snapshot stale); the order endpoint prices again server-side with the same engine. If the team prefers, it can be merged into an `order` dry-run verb — same contract, different shape. |
| `POST /dsd/api/v1/visit/detail` | `{visit_id}` | everything the app needs to WORK the visit in one call: customer snapshot + SA flags (blocks, permissions), **item proposal** (1.6), **deal conditions** (1.7), resolved customizing for this SA, partner geo (for client-side geofence UX) |
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
  policy, `MANUAL_DISCOUNTS`, reason-mandatory flags for skip/cancel,
  `CANCEL_ALLOWED`, `COPY_ENABLED`, `ITEMS_PROPOSAL` (MDSD SA flag +
  `PROPOSAL_HISTORY_DAYS`), `GEOFENCE_ENABLED` (MDSD per-SA GeoFence flag),
  `GEOFENCE_RADIUS_M`, `GEOFENCE_MODE` (soft/strict), `LOCATION_RETENTION_DAYS`.
  The rest of the ~75-key catalog joins step by step as features need it —
  never invent keys without an MDSD counterpart.
- The `config` payload of the day package = resolved key/value map for the
  driver's context (their SAs + company country).

### 1.3 Uploads (mutations — all online)

| Endpoint | In | Effect |
|---|---|---|
| `POST /dsd/api/v1/visit/status` | `{client_uuid, visit_id, state, reason?, gps?, occurred_at}` | planned/arrived/done/skipped (reason mandatory on skip); stamps times; on `arrived`, the server runs the **geo-fence check** (1.8) and stamps `geofence_ok`; **idempotent on `client_uuid`** (upsert) |
| `POST /dsd/api/v1/visit/capture_on_hand` | `{client_uuid, visit_id, items: [{product_id, qty, uom_id, zero_count?}], not_taken?}` | records shelf-stock capture (1.4 `dsd.coh`); **idempotent on `client_uuid`** |
| `POST /dsd/api/v1/location` | `{lat, lng, accuracy?, occurred_at}` | driver GPS ping (1.5) — app sends periodically during an open tour; lightweight, no response payload beyond the envelope |
| `POST /dsd/api/v1/order` | `{client_uuid, visit_id, type: "order"\|"return", lines: [{product_id, qty, discount?}]}` | creates `sale.order` on the visit. **Return = POSITIVE quantities + `dsd_is_return=True`** (review 6.5 — no negative-qty hack). **EXPLICITLY INTERIM (MVP carrier)**: this is not the final return model — step 7 (distribution) delivers the real design: return delivery → goods receipt into stock → credit note/refund, connected to these flagged orders. Prices computed server-side; **idempotent on `client_uuid`** |
| `POST /dsd/api/v1/order/cancel` | `{client_uuid, reason}` | `action_cancel` with guards (not delivered/invoiced); reason logged |
| `POST /dsd/api/v1/order/copy` | `{source_client_uuid, new_client_uuid}` | copies lines to a NEW draft order on the same visit |

### 1.4 `dsd.coh` — capture on hand (shelf stock; MDSD `CaptureOnHandBO/ItemBO`, wire `MSE_COH_INVENTORY_HD/_ITM`)

| Field | Type | Notes |
|---|---|---|
| `visit_id` / `partner_sales_area_id` | m2o | capture belongs to a visit (or standalone header with customer+SA — v1: visit-linked only) |
| `executed_at` | Datetime | EXEC_DATE/TIME |
| `not_taken` | Boolean | the "inventory not taken" marker (INV_NOT_TAKEN) |
| `line_ids` | o2m `dsd.coh.line` | `product_id`, `qty` (sales UoM), `qty_base` optional, `uom_id`, `zero_count` Boolean |

Back-office list/form only (admin UI) — this is data capture, no logic in
v1. History feeds item proposals later.

### 1.5 `dsd.driver.location` — GPS ping store (registry topic DRIVER_LOCATION)

`user_id` (m2o res.users, indexed), `tour_id` (optional), `latitude`,
`longitude`, `accuracy_m` (Float), `occurred_at` (Datetime). Write-only from
the API; last-known location shown on the tour form; **retention: purge
older than N days via cron — N from customizing `LOCATION_RETENTION_DAYS`**
(privacy; default 90).

### 1.6 Item proposal (MDSD: SA flag `ItemsProposal` + `CUST_MAT_LIST/CUST_MAT_GROUP` customizing)

`visit/detail` returns `proposal: [{product_id, qty, source}]` when the
visit's SA has `ITEMS_PROPOSAL` enabled (per-SA customizing). v1 source:
the customer's own order history in that SA — top products by quantity over
the last `PROPOSAL_HISTORY_DAYS` (customizing, default 90), usual qty =
median of past lines. No new model: computed read from `sale.order.line`.

### 1.7 `dsd.deal.condition` — deal conditions (MDSD: 9 DealCondition BOs, wire `MSE_DEALCOND_*`)

| Field | Type | Notes |
|---|---|---|
| `code` | Char, required, unique | DealConditionID |
| `type` | Char | DealConditionType |
| `date_from/date_to` | Date | BegDate/EndDate |
| `is_mandatory` | Boolean | MDSD forces proposing it |
| `text` | Text | DealConditionText |
| `line_ids` | o2m `dsd.deal.condition.line` | `product_id`, `target_qty`, `uom_id`, `result_kind` sel discount/free_goods, `result_value` |
| `assignment_ids` | o2m `dsd.deal.condition.assignment` | `partner_id`+`sales_area_id` (optional = all), `payment_term_id` optional (wire `MSE_DEALCOND_ASGN`: PRONR/KUNNR/SA/ZTERM) |

v1: back-office master data + `visit/detail` returns the deals valid for
that customer+SA+date. **Pricing EFFECT of deals is NOT computed in v1**
(D5: prices come from the Odoo pricelist; deal lines can be copied into the
order manually). The deal engine (feedback/discount/free-goods results,
proportional allocation) is deferred to the promotions step — flagged, not
forgotten.

### 1.8 Geo-fence validation (configurable via customizing — MDSD agent-notes 04 §5)

On `visit/status → arrived` (and available in `visit/detail` for client-side
UX): if `GEOFENCE_ENABLED` resolves true for the visit's SA:

- compare the reported `gps` with the partner's `partner_latitude/longitude`
  (step 4) at `GEOFENCE_RADIUS_M` (customizing, default 200m — haversine)
- outcome stored on the visit: `geofence_ok` Boolean + `geofence_distance_m`
- `GEOFENCE_MODE` = `soft` (flag only, default) | `strict` (arrival outside
  the fence rejected with error code `geofence_violation`)

Partner without coordinates ⇒ check skipped, `geofence_ok = null`.

### 1.9 Cross-cutting contract

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
12. login: valid credentials (test user, generated password — never literal)
    → session works; wrong password → auth error
13. capture-on-hand: idempotent on client_uuid; `not_taken` header without
    items accepted
14. item proposal: with `ITEMS_PROPOSAL` on + order history → proposal
    present in `visit/detail`; flag off → absent
15. geo-fence: soft mode flags `geofence_ok` false outside radius; strict
    mode rejects with `geofence_violation`; no partner coords → skipped
16. location ping stored; tour shows last-known; retention cron purges old
    rows per `LOCATION_RETENTION_DAYS`
17. deal conditions: valid-for-customer+SA deals returned in `visit/detail`;
    expired/other-SA deals excluded

## 4. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–6)
- [ ] `docs/mobile-api-v1.md` written and reviewed (app team contract)
- [ ] Scripted sales day passes over HTTP: login → download → prices →
      2 orders + 1 return → cancel one → copy one → visit statuses →
      capture-on-hand → location ping
- [ ] Idempotency + error contract verified by tests
- [ ] Geo-fence soft/strict modes covered by tests
- [ ] User-provisioning runbook (create preseller user + driver group) in
      the API doc
- [ ] PR to `main` with the API doc attached

## Out of scope (later steps — do NOT build)

Distribution scenario (van stock/deliveries/COCI/reload — API grows then),
offline queue/sync, push notifications, photos/signatures, OTP
verification, the deal-condition PRICING ENGINE (feedback/discount/free
goods — promotions step; v1 ships the data + payload only), promotions
beyond native pricelist, multi-language payloads, pagination of the day
package (catalog is paginated), rate limiting.

## 5. MDSD coverage map (audited 2026-11-19 against the app's 37 managers)

Covered by v1.1: Tour, Visit (+GPS/geofence), Order (create/cancel/copy/
interim return), Pricing (server-side), ProposeOrder (item proposal),
CaptureOnHand, DealCondition (data only), Material (/catalog), Customer
(read), ReasonCode, DocumentNumber (Odoo sequences), Authorization
(geofence part).

Deferred BY DESIGN to their roadmap steps: COCI/Delivery/Inventory/Reload/
Questions/Empties (step 7) · Collection (step 8) · Pdf/print (step 9) ·
CRMActivity/CRMActivityJournal/TradeAsset/Expense/Message/Signature/OTP/
Region/CPD-customer-creation (later) · BackupTableData/GenericDataTransport
(meaningless under online-first D8) · ReferenceInvoice (with the final
return design, step 7).

**Known gaps — NOT in v1.1, registered so they are not lost (do NOT add
without a scope decision):**

| MDSD manager | Meaning | Disposition |
|---|---|---|
| `CreditLimit` + online open-items | preseller sees customer debt/credit before ordering | small future item after step 5 wires accounting; needs `account` data |
| `ListingExclusion` | per-customer product listing (what may be sold to whom) | future filter on `/catalog`; needs listing master data first |
| `Quota` (ZQUO conditions) | purchase quota per customer | future; depends on condition data we have not modeled |

## References

- Decisions D5/D7/D8 (issue #1 log) · step 5 entities · PRESELLER-SCENARIO
  §4–7 (business semantics — reference only, no wire formats)
