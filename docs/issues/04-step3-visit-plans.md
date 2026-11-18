# [Step 3 — DEV TASK] Visit plans — strategic layer (`dsd_core`)

> Third development task. Master plan: #1 · Builds on #2 (sales areas) and
> #3 (routes & membership).
> Spec version: draft v1 (2026-11-18) — **pending approval before posting**.

## Scope decision (why plans only, no lists/generation yet)

The package's visit *lists* are welded to tours (`tour_id` 1:1; "released"
means the tour + visits exist) and its generation machinery carries SAP
coexistence obligations (external ids ≥ 9,000,000, parity message codes
300–316, advisory locks — M01 §3.6). None of that is buildable before the
tours step. This task delivers the **strategic layer** only: *which
customers, which weekdays, in what order* — the call-book. Visit lists +
generation request move to the tours step (roadmap: #1).

## Goal

Model SAP Visit Control's planning half in `dsd_core`:
`dsd.visit.plan.type`, `dsd.visit.plan`, `dsd.visit.plan.line`.

- Same constraints as #2/#3: Odoo 20, Community-compatible, `depends`
  unchanged (`base, product, stock`), LGPL-3, no chatter.

## 0. Odoo-native survey (standing rule)

| Odoo 20 native | What it is | Fits a recurring visit plan? | Verdict |
|---|---|---|---|
| `calendar.event` / `appointment` | single meetings / booking slots | ✗ not recurring customer call-books | no |
| `resource.calendar` | working hours per employee | ✗ not customer-pattern | no |
| CRM recurring activities (`mail.activity`) | per-record reminders | ✗ not ordered multi-customer plans | no |
| `dateutil` (Odoo ships it) | rrule/weekday math | ✓ **use it** for weekday expansion later (prior art v1) | reuse as library |

No native twin — custom, per package M01 §3.4. Native reuse:
`res.users` (driver), `dsd.route` (#3), `dsd.partner.sales.area` (#2).

## 1. Data model

### 1.1 `dsd.visit.plan.type`

| Field | Type | Required | Notes |
|---|---|---|---|
| `code` | Char | yes | unique (e.g. `MW2`); `/DSD/VC_VPTYPET` replacement |
| `name` | Char | yes | translatable |
| `is_default` | Boolean | no | one default type is used as new-plan default |
| `active` | Boolean | — | True |

### 1.2 `dsd.visit.plan`

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | Char | yes | | manual for now (`VP{external_id}` naming joins at the gateway step) |
| `state` | Selection draft/active/closed | yes | draft | **additive vs package** (which has no plan state) — back-office usability, flagged as divergence |
| `plan_type_id` | m2o `dsd.visit.plan.type` | yes | | default = the `is_default` type |
| `date_from` / `date_to` | Date | yes / no | today | validity window; python constraint `date_from <= date_to` |
| `driver_id` | m2o `res.users` | no | | plan's driver filter |
| `route_id` | m2o `dsd.route` | no | | scoping; line sequence defaults from this route's membership when resolvable |
| `sales_area_id` | m2o `dsd.sales.area` | no | | plan-level scope (package trio → our combo) |
| `line_ids` | o2m `dsd.visit.plan.line` | — | | |

Deferred to later steps (do NOT add): `vehicle_id` (model arrives with
tours), `auth_group` (system groups suffice until M12), `is_custom_callbook`
and external `plan_id` (gateway step).

### 1.3 `dsd.visit.plan.line`

| Field | Type | Required | Notes |
|---|---|---|---|
| `plan_id` | m2o `dsd.visit.plan` | yes | `ondelete='cascade'` |
| `partner_sales_area_id` | m2o `dsd.partner.sales.area` | yes | pins customer + sales area in one reference |
| `partner_id` | m2o `res.partner` | — | related through the above, **stored**, readonly (search/group) |
| `weekday_mask` | Integer | yes | bit 0 = Mon … bit 6 = Sun; **single source of truth** |
| `mon`…`sun` | Boolean ×7 | — | computed from the mask, with inverse that writes bits (UI toggles) |
| `sequence` | Integer | yes | visit order; `widget="handle"`; default = route membership sequence when resolvable, else 10 |
| `valid_from` / `valid_to` | Date | no | line validity inside the plan window |

**Behavior rules (must implement):**

0. **Scope consistency** (review 3.1 + round 2): when `plan.sales_area_id`
   (or the plan's `route_id.sales_area_id`) is set, every line's
   `partner_sales_area_id.sales_area_id` must match (`ValidationError`).
   Additionally, if BOTH `plan.sales_area_id` and
   `plan.route_id.sales_area_id` are set, they must be EQUAL — a plan may
   not carry a route scoped to a different sales area than its own.

1. Weekday toggles ⇄ mask: setting `mon`/`tue` booleans sets/clears bits;
   writing `weekday_mask` directly updates the booleans. No dual storage.
2. Python constraint: two lines of the same plan with the same
   `partner_sales_area_id` may not share **any** weekday bit
   (`mask1 & mask2 != 0` → `ValidationError`). (Package constrains
   "plan+partner+SA+weekday" per fixed day; our bitmask line makes it an
   intersection check — divergence noted.)
3. Plan validity: `date_from <= date_to` else `ValidationError`; line dates
   (when set) must fall inside the plan window.
4. `weekday_mask` CHECK: `1 <= weekday_mask <= 127` (SQL check — no
   invalid bits); at least one weekday set per line.
5. **Generation semantics** (canonical rule for later steps): a date is
   visitable iff it lies inside BOTH the plan window and the line window
   AND its weekday bit is set.
6. **Single default type**: at most ONE active `is_default=True` plan type
   (python constraint).
7. **State transitions**: `draft` (fully editable) → `active` (lines become
   readonly; date_to may be extended) → `closed` (terminal — reopen not
   allowed; create a new plan instead). Existing generated artifacts are
   never modified by closing a plan.

## 2. Views

- Plan form: header (name, type, state ribbon/bar, dates, driver, route,
  sales area) + notebook page **"Lines"**: editable list — handle
  (sequence), partner (via `partner_sales_area_id`), the 7 weekday toggles
  (grouped), validity dates.
- Plan list + search (state filter, by driver/route/type/date window).
- Type list/form (code, name, is_default).
- Menus: DSD → **Master Data** (new section) → Visit Plans, Visit Plan
  Types. (`Configuration` stays for catalogs/routes; menu reorg lands with
  the tours step.)
- Odoo 20 syntax per #2 (`<list>`, `column_invisible`, statusbar for state).

## 3. Security — extend `security/ir.access.csv`

Planning is operational master data: `dsd.visit.plan.type` — user `r`,
officer `ru`, system `crud`; `dsd.visit.plan` and `dsd.visit.plan.line` —
same pattern (`r` / `ru` / `crud`).

## 4. Tests (`TransactionCase`, `@tagged('standard')`)

1. type `code` unique (IntegrityError); second active `is_default` type
   raises
2. weekday roundtrip: toggles → mask bits; direct mask write → toggles;
   mask 0 and mask > 127 rejected
3. overlapping-weekday python constraint raises for same plan + same
   `partner_sales_area_id`; **different** PSA same customer is allowed;
   line outside plan SA scope raises (rule 0)
4. line with `weekday_mask = 0` raises
5. plan window validation (`date_from > date_to` raises; line outside
   window raises)
6. `partner_id` related stored through `partner_sales_area_id`
7. default plan type comes from `is_default`

## 5. Definition of done

- [ ] Installs clean on fresh Odoo 20 DB; full suite green
      (`--test-tags /dsd_core` — steps 1–3 together)
- [ ] Weekday mask single-source-of-truth verified by roundtrip test
- [ ] Overlap + window constraints covered by tests
- [ ] `depends` unchanged; no chatter/`mail` dependency
- [ ] PR to `main` with screenshot of plan form + lines tab

## Out of scope (later steps — do NOT build)

- Visit **lists** + `tour_id` release ladder (tours step; M01 §3.5)
- Generation request/lines with parity message codes 300–316 (tours step;
  M01 §3.6)
- External ids ≥ 9,000,000, `auth_group`, `is_custom_callbook`,
  per-line `calendar_id` (gateway/M12 steps)
- `vehicle_id` (model arrives with tours)
- Visit appointments/exceptions (v1 had them; revisit at tours step)

## References

- Package M01 §3.4 (plan/type/line contract, incl. the note that the exact
  VPP column set is a destination contract to reconcile at cutover) and
  §3.5–3.6 (deferred here)
- Prior art: legacy v1 `src/dsd/models/dsd_visit_plan*.py` (monorepo branch
  `dsd-v1`) — state machine, weekday booleans, dateutil expansion; the
  expansion logic is deliberately NOT ported yet
