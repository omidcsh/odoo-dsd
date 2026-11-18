# Odoo 20 Dev Environment — Handoff

Complete guide to the local Odoo 20 development setup, including the OCA
Field Service modules ported from 19.0 to 20.0. Written so a new developer
(or agent) can take over without any prior context.

**Last updated:** 2026-11-18
**Machine:** macOS, Docker Desktop, Apple Silicon (arm64)

---

## 1. What this is

- **Odoo 20.0 Community Edition**, source clone (shallow, `--depth 1`) at
  `~/Documents/Programming/Python/odoo` — branch `20.0`, kept up to date with
  `origin/20.0` via `git pull`.
- **Docker dev environment** at `~/Documents/Programming/Python/odoo/docker-dev/`
  so nothing is installed on the host (no brew python, no postgres).
- **Ported OCA modules**: 5 modules from [OCA/field-service](https://github.com/OCA/field-service)
  (19.0 branch) fixed to work on Odoo 20.0, installed on the dev databases.

## 2. Directory layout

```
~/Documents/Programming/Python/odoo/          # odoo source (git, branch 20.0)
├── odoo-bin                                  # server entrypoint (runs INSIDE docker)
├── addons/                                   # core Odoo addons — NEVER edit
└── docker-dev/                               # ← everything we built lives here
    ├── docker-compose.yml                    # web + postgres:16-alpine
    ├── Dockerfile                            # python:3.12-slim + pip requirements
    ├── odoo.conf                             # server config (see gotcha §7.1!)
    ├── custom-addons/                        # mounted to /mnt/custom-addons
    │   └── field-service/                    # CLONE of OCA/field-service branch 19.0
    │   │                                     # (its own git repo — never commit/push it)
    │   ├── base_territory/                   # ← ported to 20.0
    │   ├── fieldservice/                     # ← ported to 20.0 (the app)
    │   ├── fieldservice_route/               # ← ported to 20.0
    │   ├── fieldservice_vehicle/             # ← ported to 20.0
    │   ├── fieldservice_stock/               # ← ported to 20.0
    │   └── (28 other modules)                # cloned but NOT ported/installed
    └── tools/
        └── convert_access.py                 # ir.model.access.csv → ir.access.csv converter
```

`docker-dev/` is **untracked** in the odoo git repo — a `git pull` in the odoo
source never touches it.

## 3. Run it

Requires only **Docker Desktop**.

```bash
cd ~/Documents/Programming/Python/odoo/docker-dev
docker compose up -d          # start (first time builds the image, ~5 min)
docker compose logs -f web    # follow logs
docker compose restart web    # restart (after changing addons_path etc.)
docker compose down           # stop; data volumes are kept
docker compose down -v        # ⚠️ also wipes databases and filestore
```

After a `git pull` of the odoo source: clear stale bytecode and restart:

```bash
cd ~/Documents/Programming/Python/odoo
find . -name "__pycache__" -type d -not -path "./docker-dev/*" -exec rm -rf {} +
cd docker-dev && docker compose restart web
```

Odoo is interpreted Python — there is no build/compile step beyond `__pycache__`.

## 4. Access

| What | Where | Credentials |
|---|---|---|
| Odoo web | http://localhost:8069 | `admin` / `admin` (superuser) |
| Demo user | same login page | `demo` / `demo` |
| Portal user | same login page | `portal` / `portal` |
| DB manager | http://localhost:8069/web/database/manager | master password: `admin` |
| PostgreSQL | internal only (`docker exec -it docker-dev-db-1 psql -U odoo -d dev`) | user/pass `odoo`/`odoo` |
| Longpolling/bus | port 8072 | — |

### Databases

| DB | Contents |
|---|---|
| `dev` | the working database. Demo data ON (companies, contacts, POS shops incl. Restaurant/Bar, CRM/Sales demos, FSM orders FO001–FO003). Also has the `website` app installed, so the login page is the eCommerce-styled one. |
| `dsd_test` | throwaway DB used to test the module port. Demo data ON. |

Two DBs exist, so Odoo may show a **database selector** — pick `dev`.
You can also bookmark http://localhost:8069/web/login?db=dev

## 5. The ported modules (OCA field-service 19.0 → 20.0)

Installed on **both** databases:
`base_territory`, `fieldservice`, `fieldservice_route`,
`fieldservice_vehicle`, `fieldservice_stock`

All 5 form a single app in the UI: **Field Service** (Dashboard, Operations,
Master Data, Reporting, Configuration). Territories/locations, day routes
(DR-NORTH-063026 etc.), routes, vehicles (empty), stock on orders
(Inventory tab) — demo data is in.

### 19 → 20 API breaks that were fixed (apply to ANY module port)

| # | 19.0 | 20.0 |
|---|---|---|
| 1 | `ir.model.access` model + `security/ir.model.access.csv` | `ir.access` + `security/ir.access.csv`, header `id,name,model_id,group_id/id,operation,domain`; `model_id` = **model name** (e.g. `res.territory`), NOT xmlid; perms collapse to one `operation` code (`crud`, `ru`, `r`…) |
| 2 | `ir.rule` record rules | merged into `ir.access`: no `group_id` = restriction (global), with `group_id` = permission |
| 3 | `from odoo.api import Self` | removed — drop it, use plain `dict(...)` |
| 4 | `<field name="type">calendar</field>` on ir.ui.view | removed — view type comes from arch root |
| 5 | `<calendar date_delay="...">` | attribute removed entirely |
| 6 | `t-esc` in view arch | forbidden → `t-out` |
| 7 | `report_file` field on ir.actions.report | removed |
| 8 | `resource.calendar.tz`, `two_weeks_calendar`, attendance `week_type`/`display_type` | gone — use `company_id.tz`; attendance keeps `hour_from/hour_to/dayofweek/day_period` |
| 9 | `stock.move.product_uom` | renamed `uom_id` (`product_uom_qty` stays) |

Also: domains in `ir.access` containing `company_ids` are FINE (core uses them
too); a `ValueError ... malformed node` from `ir_access.py` in the logs is a
benign debug line, not a crash.

To port another module from the same repo: it may already have its CSV
converted by `tools/convert_access.py` (it ran on all modules), then install
and fix remaining breaks iteratively:

```bash
docker compose exec web python3 /odoo/odoo-bin -c /etc/odoo.conf \
  -d dev -i <module_name> --stop-after-init
```

Read the traceback → fix → repeat. Useful debug flag: `--log-level=debug`
(view validation logs "Invalid XML: ..." with the RNG reason just before a
generic "Invalid view ... definition" ParseError).

## 6. Demo data added manually (not part of module demo)

- FO001 has 1 delivery picking (WH/OUT/00060) + 1 return (WH/IN/00008);
  FO002/FO003 have a delivery each — linked via `stock.picking.fsm_order_id`
  and `stock.move.fsm_order_id`, confirmed state.
- SR001 day route planned for tomorrow (in the Day Routes calendar).

## 7. Gotchas (read before debugging anything!)

1. **`http_interface = 0.0.0.0` in odoo.conf is MANDATORY.** Odoo 20 binds
   HTTP to `127.0.0.1` by default; inside Docker that means the port-forward
   gets "connection reset by peer" from the host while everything looks fine
   inside the container. Symptom: curl from host gets exit code 56 / HTTP 000.
2. **wkhtmltopdf does not exist** on Debian trixie — Odoo 20 uses headless
   Chromium for PDFs instead. Don't add it to the Dockerfile.
3. **Odoo 20 CLI creates DBs WITHOUT demo data by default** — use
   `--with-demo` when initializing (`-d newdb -i base --with-demo`).
4. **odoo-bin refuses to run as root** — the Dockerfile creates user `odoo`
   (uid 1000). Don't remove it.
5. After changing `odoo.conf` or `addons_path`, `docker compose restart web`.
6. The `field-service/` clone is on the **19.0 branch** with local edits and
   version bumps to `20.0.x`. `git status` inside it shows the port changes;
   **never commit or push that repo** — it's a scratch working copy.
7. To create a *new* database with the FSM stack:
   ```bash
   docker compose exec web python3 /odoo/odoo-bin -c /etc/odoo.conf \
     -d <name> -i base,base_territory,fieldservice,fieldservice_route,fieldservice_vehicle,fieldservice_stock \
     --with-demo --stop-after-init
   docker compose restart web   # then pick the DB in the selector
   ```

## 8. Verification tooling (Playwright)

Playwright 1.65.1 installed at `/tmp/odoo-pw/` (node project; browsers cached
in `~/Library/Caches/ms-playwright`). Scripts there drove the whole session:
login (`admin/admin`), apps-menu navigation, FSM screens, chatter, POS.
**`/tmp` is wiped on reboot** — copy the folder somewhere permanent if needed.
Key selector knowledge: Odoo 20 navbar sections are
`header button[data-menu-xmlid="module.xmlid"]`; dropdown items are
`a.o-dropdown-item` inside a `.o_popover` container (not `.dropdown-menu`).
Login page needs `button:has-text('Log in')` (website-styled page has several
`type=submit` buttons).

## 9. Context & next steps (the "why")

Long-term goal: a **DSD (Direct Store Delivery)** product — tour-day planning,
van stock, per-store visits, cash settlement. This Odoo setup is the
exploration platform for building it as a custom Odoo module.

Relevant findings so far:
- No native DSD in Odoo Community. POS is the usual base for van sales.
- KMEE's `van_sales` module (github.com/kmee/kmee-odoo-addons, Odoo 18)
  covers the load→sell→unload→settlement cycle — candidate to port next.
- OCA field-service covers planning/route structure (now ported, §5) but has
  no money/settlement half.
- Natural next step: a lean custom `dsd_*` module in
  `docker-dev/custom-addons/` (it's on `addons_path`), reusing the ported FSM
  stack where it fits.
- Odoo Enterprise (paid) is source-available but license dies with the
  subscription; everything above is fully Community/LGPL-AGPL legal.
