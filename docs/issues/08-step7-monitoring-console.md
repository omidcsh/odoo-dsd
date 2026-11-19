# [Step 7 — DEV TASK] Back-office monitoring console — tours, salesmen, live map (`dsd_core`)

> Seventh development task. Master plan: #1 · Builds on #6 (presales day:
> tours/visits/orders) and #7 (API: GPS pings, statuses). Runs BEFORE the
> distribution step — the office must SEE the sales day before extending it.
> Spec version: draft v1 (2026-11-19) — **pending approval before posting**.

## Goal

After (and during) the salesmen's day, the back office must see — in Odoo:

1. **Tours that were downloaded** — one place, all of them, with status
2. **Tour status** at a glance (draft / running / done / cancelled) + progress
   (visits done/skipped/pending)
3. **Salesmen on a MAP** — live positions from the GPS pings the app sends
   (`dsd.driver.location`), with tour and freshness context
4. **Orders per salesman** — everything a driver created, per visit/tour

Plus the defined **post-tour backend behaviour** (what Odoo does when a
tour finishes — see rules).

- Odoo 20, Community-compatible, LGPL-3. `depends` unchanged from step 6.

## 0. Odoo-native survey (standing rule)

| Concern | Native | Verdict |
|---|---|---|
| Tours overview | kanban/list on `dsd.tour` (step 5) | ✓ extend: state columns, progress bar, filters (date/driver/state), "today" default filter |
| Status/progress | computed aggregates | native compute on tour (visits by state) |
| Orders per salesman | sale.order list grouped by `dsd_tour_id`/driver related field | ✓ native filter/group + a dedicated filtered action |
| **Map view** | `web_map` = **Enterprise-only (OEEL-1, depends web_enterprise)** — verified in source | ✗ cannot depend on it → **custom lightweight map client action**: OWL component + **Leaflet (bundled in module static/lib)** + OpenStreetMap tiles — no API key, no CDN, LGPL-compatible |
| Auto-refresh | none native (bus is overkill) | simple 30s polling in the component (configurable `MAP_REFRESH_SECONDS`) |

## 1. Business rules (final)

| Topic | Rule |
|---|---|
| Tour summary | on tour `done`, the chatter gets an automatic summary: visits done/skipped, orders count + amount, returns count + amount — no other side effects |
| Order states after the tour | orders keep their standard lifecycle; NO auto-confirmation — the officer reviews and confirms from the console (per-DSD presales practice) |
| Map data | markers = LAST-KNOWN location per driver with an OPEN (running) tour + stale-marker when older than `MAP_STALE_MINUTES` (default 30); completed tours drop off the live map, history stays in `dsd.driver.location` |
| Visibility | console = officer/admin; drivers are not console users |
| Privacy | map reads only `dsd.driver.location` (retention already governed by step 6) |

## 2. Data model (minimal — mostly reads)

- `dsd.tour` extensions: `visit_done_count` / `visit_skipped_count` /
  `visit_pending_count` (computed, for badges/progress), `order_amount_total`
  (computed sum of linked orders)
- `res.users` (drivers): `dsd_last_location_id` (computed last-known ping)
- No new business models; map is a client action over existing data.

## 3. Views

1. **DSD → Operations → Tours**: kanban grouped by state with progress bars
   + list with date/driver/state filters + "Today" default filter; tour form
   unchanged (step 5) plus the summary banner.
2. **DSD → Operations → Live Map** (client action `dsd_map`): Leaflet map,
   driver markers (name, tour, last ping age, click → tour form); optional
   toggle: today's visit markers from `dsd.visit` gps; auto-refresh 30s.
3. **DSD → Operations → Salesman Orders**: sale.order list filtered to
   `dsd_tour_id ≠ false`, groupable by driver/tour/visit, pivot-ready.

## 4. Tests (`TransactionCase` + one HttpCase smoke)

1. tour progress computes (2 done + 1 skipped + 1 pending)
2. tour done → chatter summary message contains the counts/amounts
3. `dsd_last_location_id` = newest ping per driver; stale flag logic
4. orders-per-driver domain returns only tour-linked orders of that driver
5. HttpCase: the map client action loads (route 200, marker data endpoint
   returns drivers with open tours)

## 5. Definition of done

- [ ] Fresh-DB install; full suite green (steps 1–7)
- [ ] Console demoable: today's tours kanban, one running tour on the map
      with a fresh marker, salesman orders grouped correctly
- [ ] Leaflet bundled in the module (no CDN/network dependency at runtime
      beyond tile server)
- [ ] PR to `main` with screenshots (kanban, map, orders view)

## Out of scope (do NOT build)

Route optimization/geocoding, heatmap/history replay of GPS trails, push
notifications, driver chat, KPI dashboards beyond the above (reporting
step), editing anything from the map, Enterprise web_map.

## References

- User directive 2026-11-19 (post-tour visibility before distribution) ·
  step 5 tour/visit models · step 6 `dsd.driver.location` + map-blocking
  verdict (web_map = OEEL) · MDSD tour dashboard (PRESELLER-SCENARIO §5 —
  the office-side counterpart of what the driver sees)
