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
| Auth | session via standard `/web/session/authenticate` **or** API-key header (both satisfy `auth="user"`) | ✓ reuse — no custom token system in v1 |
| Serialization | JSON request params / `request.make_response` | ✓ |
| Verb style | Odoo routes accept any method; v1 convention: **POST + JSON body for everything** (actions are RPC-flavored) | ✓ document clearly for the app team |
| Rate limiting | none native | skip in v1 (single-tenant app traffic) |
| Config store | `ir.config_parameter` is global-only (no SA scope) | custom `dsd.customizing` with scope resolution — per-SA behavior is a DSD requirement (MDSD `CustomizingSalesAreaBO`) |

## 1. Endpoints (v1 — sales scenario)

### 1.1 Day package (downloads)

| Endpoint | In | Out |
|---|---|---|
| `POST /dsd/api/v1/day/get` | `{date}` | visit-list status for the caller (driver) + whether a tour exists; error `no_visit_list` if the operator prepared nothing (lists are prepared back-office — step 5) |
| `POST /dsd/api/v1/tour/download` | `{date}` | **D7 materialization** (guarded, once per list) + full day package in one payload: `tour`, `visits[]` (id, sequence, partner snapshot, SA, state, planned times), `customers[]` (partner data + SA rows + blocks + partner functions + geo + pricelist id), `products[]` (code, name, uom, category), `config` (feature-flag key-values, v1 minimal) |
| `POST /dsd/api/v1/tour/get` | `{date}` | re-fetch the current package (re-install/refresh) — serves the EXISTING tour, never re-materializes (D7 lock) |
| `POST /dsd/api/v1/prices` | `{partner_id, items: [{product_id, qty}]}` | **server-computed prices** (D5: the customer's SA pricelist, Odoo-native engine). The app never computes prices. |
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
| `value` | Char/Text | the `Behaviour` equivalent (string; app parses) |
| `scope` | sel global/country/sales_area | resolution order on read: **sales_area → country → global → built-in default** |
| `country_id` | m2o res.country | when scope=country |
| `sales_area_id` | m2o dsd.sales.area | when scope=sales_area |
| `description` | Char | shown in the admin UI |

- SQL unique: `(key, scope, country_id, sales_area_id)` (NULLs distinct)
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
| `POST /dsd/api/v1/visit/status` | `{visit_id, state, reason?, gps?, occurred_at}` | planned/arrived/done/skipped (reason mandatory on skip); stamps times |
| `POST /dsd/api/v1/order` | `{client_uuid, visit_id, type: "order"\|"return", lines: [{product_id, qty, discount?}]}` | creates `sale.order` on the visit; `return` = negative quantities + `dsd_is_return=True`; prices computed server-side; **idempotent on `client_uuid`** |
| `POST /dsd/api/v1/order/cancel` | `{client_uuid, reason}` | `action_cancel` with guards (not delivered/invoiced); reason logged |
| `POST /dsd/api/v1/order/copy` | `{source_client_uuid, new_client_uuid}` | copies lines to a NEW draft order on the same visit |

### 1.4 Cross-cutting contract

- **Idempotency:** `dsd_client_uuid` Char (indexed, unique) on `sale.order`;
  replaying an order returns the original (same id), never duplicates.
- **Errors:** uniform `{error: {code, message, data?}}` + proper HTTP status;
  `ValidationError/UserError` → 400 with `.message`; auth → 401; unknown →
  404. `code`s are stable strings (`no_visit_list`, `tour_already_downloaded`,
  `order_not_cancelable`, …) — the app branches on them.
- **Contract doc:** every payload field documented in
  `docs/mobile-api-v1.md` in this repo — the app team's frozen v1 contract.

## 2. Security

- All routes `auth="user"`, `type="json"` (JSON RPC — CSRF n/a for non-form
  posts). Writes require `dsd_core.group_dsd_officer`; reads
  `group_dsd_user`.
- The Odoo user IS the mobile login; driver-scoped calls enforce
  `driver_id = uid` server-side (never trusted from the payload).

## 3. Tests (`HttpCase`, `@tagged('standard')`)

1. `day/get`: prepared list → status; empty date → `no_visit_list`
2. `tour/download` materializes once; second call → `tour_already_downloaded`
3. `tour/get` after download serves the same tour/visit ids (D7)
4. `visit/status`: transitions + mandatory skip reason (400 without)
5. `order`: creates sale.order on the visit, server-priced (assert line
   price == pricelist result); **replay same client_uuid → same order**
6. `return`: negative-qty order flagged `dsd_is_return`
7. `cancel`: draft OK; blocked with delivery → `order_not_cancelable`
8. `copy`: new draft on same visit, same lines
9. cross-driver isolation: driver B cannot fetch driver A's tour
10. customizing resolution: SA override beats country beats global; day
    package embeds the resolved map

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
