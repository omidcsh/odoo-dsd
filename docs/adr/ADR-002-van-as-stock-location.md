# ADR-002: Model each van as an internal stock location with a fleet vehicle

- **Status:** Proposed
- **Date:** 2026-11-15
- **Parent:** ADR-001

## Context

Van stock must be tracked: loaded at the warehouse, decremented by each store
delivery/van sale, incremented by returns, and reconciled at end of day. Two natural
modelings in Odoo:

1. **Van = internal `stock.location`** (child of the warehouse, e.g. `WH/VAN/01`),
   paired with a `fleet.vehicle` record.
2. **Van = separate warehouse** (`stock.warehouse`) per vehicle.

## Decision

**Option 1 — internal location + fleet vehicle.** Install the Community modules
`fleet` and `stock_fleet`. Each van is:

- `stock.location`, usage `internal`, child of `WH/Stock`'s warehouse
  (e.g. `YourCompany / Vans / VAN-01`), and
- a `fleet.vehicle`; `stock_fleet` already relates vehicles to warehouses and
  lets batches/pickings carry the vehicle.

Load-out is an internal transfer `WH/Stock → WH/VAN-01`; a store delivery sources
from `WH/VAN-01`; unsold stock returns at settlement via the reverse transfer.
Returnable empties (crates, kegs, bottles) are tracked as storable products on the
same locations with lots where needed.

## Consequences

**Positive**
- One warehouse = one valuation/ledger; van stock and warehouse stock reconcile in
  a single view; no per-van accounting noise.
- Reuses `stock_fleet` instead of writing our own vehicle model (Odoo guideline:
  leverage built-ins).
- Internal transfers already give us the load-out/return documents — no new
  document types to invent.

**Negative / trade-offs**
- A separate-warehouse model would give each van its own operation types and
  numbering; we forgo that isolation deliberately — per-van views are built with
  domain filters on the location instead (cheaper, one valuation pool).
- Vehicle capacity/planning (what fits in the van) is out of scope for v1.
