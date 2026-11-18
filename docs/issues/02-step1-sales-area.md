# [Step 1] Sales Area entities — done, review & next

Step 1 of the master plan (#1). **Status: code complete** on branch
`feature/dsd-core` (monorepo) — installed on the dev DB, 9 tests green
(0 failed / 0 errors). This issue tracks review + follow-ups.

## Delivered

| Piece | Notes |
|---|---|
| `dsd.sales.org` / `dsd.distribution.channel` / `dsd.division` | catalogs: unique code, name, active (`VKORG/VTWEG/SPART`) |
| `dsd.sales.area` | TVTA-style valid combination, `unique(org, channel, division)`; future home of the 68 `MSE_CUST_SALES_AREA` customizing fields |
| `dsd.partner.sales.area` | customer × sales-area relationship; `unique(partner, sales_area)`; document blocks (**block ≠ inactive** semantics); partner functions (payer/sold_to/ship_to/bill_to, default = customer); `plant_id → stock.warehouse`, `pricelist_id → product.pricelist` with primary-SA sync to the partner (decision D5) |
| `res.partner` | **Sales Areas** tab + stored primary read-through fields (`dsd_sales_org`, `dsd_dist_channel`, `dsd_division`, 3 block booleans) for filtering |
| Security | `res.groups.privilege` scope DSD, groups user/officer, Odoo 20 `ir.access.csv` |
| Menus | DSD → Configuration (Sales Areas, orgs, channels, divisions, customer SAs) |

## Deliberately deferred (free to add later via module upgrade)

- All wire passthrough fields (`payment_terms1..5`, `pay_code`,
  `price_group`, `customer_group1..5`, `emse_kalks`, …) — join at step 7
  when the emitter consumes them
- LORD online flags (`OD_*`), geofence, route/calendar links (steps 2+)
- Demo data, chatter (`mail` dependency), app icon

## Follow-ups

- [ ] Review the code on `feature/dsd-core`
- [ ] Decide step 2 (proposal: Route & visit plans) and open its issue
- [ ] When suite is publishable: icon, README, screenshots

## Discovered Odoo 20 port gotchas (documented in handoff §5 #10–12)

- `res.groups.category_id` removed → `res.groups.privilege`
- search-view `<group expand="0">` → plain `<group>`
- `_sql_constraints` list → `models.Constraint` class attributes
