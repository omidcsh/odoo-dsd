# DSD Operations Runbook

Operational procedures for the DSD-on-Odoo stack (Docker at `~/odoo-docker`,
code at `~/Projects/Odoo/src/dsd_core`). Performed & verified 2026-11-16.

## Daily backup

```bash
mkdir -p ~/odoo-docker/backups
docker exec odoo-db pg_dump -U odoo -Fc -d odoo \
  > ~/odoo-docker/backups/odoo_$(date +%F).dump
```

Verified: dump ≈ 6.5 MB, 637 table-data sections, DSD tables included.
Schedule it (cron/launchd) for a nightly run; keep ≥ 14 days.

## Restore drill (performed 2026-11-16 — PASS)

```bash
docker exec odoo-db createdb -U odoo odoo_uat
docker exec -i odoo-db pg_restore -U odoo -d odoo_uat --no-owner \
  < ~/odoo-docker/backups/odoo_2026-11-16.dump
# verify
docker exec odoo-db psql -U odoo -d odoo_uat -c \
  "SELECT count(*) FROM dsd_route_day"
```

Result: `odoo_uat` holds the exact live state (1 route, 1 settled day,
1 settlement, `dsd_core` installed). `odoo_uat` is kept as a UAT sandbox.

Note: pass the dump via stdin (`docker exec -i`) — container paths don't
see host files.

## Clean-install verification (performed 2026-11-16 — PASS)

```bash
docker exec odoo-db createdb -U odoo odoo_fresh
cd ~/odoo-docker && docker compose stop odoo
docker compose run --rm odoo odoo -d odoo_fresh -i dsd_core --stop-after-init
docker compose start odoo
```

Result: installs on a demo-less DB with 0 criticals; 7 `dsd.*` models;
demo data correctly skipped. Drop the DB afterwards when done checking.

## Module upgrade (after code changes)

```bash
rsync -a --delete --exclude '__pycache__' \
  ~/Projects/Odoo/src/dsd_core/ ~/odoo-docker/addons/dsd_core/
cd ~/odoo-docker && docker compose stop odoo
docker compose run --rm odoo odoo -d odoo -u dsd_core --stop-after-init
docker compose start odoo
```

With tests:

```bash
docker compose run --rm odoo odoo -d odoo -u dsd_core \
  --test-enable --test-tags /dsd_core --stop-after-init
```

## Known environment facts

- `stock_sms` was **uninstalled** (2026-11-15): its SMS-on-delivery prompt
  blocked picking validation and is noise for in-person DSD delivery.
- `postgres:16` is required (Odoo 20 minimum). Initial `postgres:15` cluster
  was discarded during bring-up — do not downgrade.
- Demo DB spans **two companies** (San Francisco + Chicago). Route cash
  journals are company-scoped; `dsd_core` validates and errors clearly on
  mismatch. `Route Cash` journal exists for the SF company (demo + live).
- Odoo 20 API notes live in commit messages and `dsd_core` code comments
  (`ir.access`, `res.groups.privilege`, `move_line_ids`, payment `memo`,
  computed picking state → hook `button_validate`).

## Go-live checklist (beyond this demo environment)

1. Company-specific chart of accounts & taxes (localization module)
2. Real master data: stores, pricelists, routes, vehicles, drivers
3. Recreate cash journals + variance account per operating company
4. Decide driver device strategy (tablet browser vs later API app)
5. Nightly backup schedule + offsite copy
6. Load test with a full route (10+ stops) on target hardware
7. Optional: `dsd_sale` / `dsd_settlement` module split when the team grows
