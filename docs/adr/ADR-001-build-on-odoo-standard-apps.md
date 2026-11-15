# ADR-001: Build DSD on Odoo standard apps with custom modules

- **Status:** Proposed
- **Date:** 2026-11-15
- **Context instance:** Odoo 20.0 Community (Docker), database `odoo`, modules installed: `crm`, `sale_management`, `stock`, `account`, `purchase`, `delivery`
- **Deciders:** Project owner, development

## Context

We need Direct Store Delivery (DSD): drivers load a van at the warehouse, follow a
route of store visits, deliver/sell from the van, take returns, collect cash, and
reconcile stock and cash back at base at end of day (the classic SAP IS-Retail DSD
van-sales loop).

Options considered:

1. **Extend the running Odoo 20 Community instance with custom modules** on top of
   Sales, Inventory, Accounting (`account`), Purchase, Delivery.
2. **Point of Sale–based van sales** — run POS sessions per van.
3. **Third-party "Van Sales" marketplace app** on top of Odoo.
4. **Standalone DSD mobile app integrated via Odoo API** (external frontend,
   Odoo as backend of record).

## Decision

**Option 1.** Build DSD as our own Odoo modules layered on the already-installed
standard apps, following the official Odoo development guidelines:
standard module layout (`models/`, `views/`, `security/`, `data/`, `wizard/`,
`demo/`, `tests/`), inheritance instead of core edits, `security/ir.model.access.csv`
loaded first, least-privilege access rights, and ORM-first code.

Odoo already covers the heavy lifting that SAP DSD had to special-case:
goods issue/receipt (`stock.picking`), invoicing (`account.move`), payments
(`account.payment`), multi-location stock, lot/serial tracking, and demo data.
Community 20 additionally ships `stock_fleet` (fleet vehicle ↔ picking/batch/warehouse
linkage) and `fleet` for vehicle master data, which we adopt rather than rebuild
(ADR-002).

## Consequences

**Positive**
- One system of record; deliveries, invoices, payments, and stock stay consistent
  by construction (same ORM transactions).
- Upgrades remain possible: we inherit core models/views, never fork them.
- Works offline-tolerant at the data level (documents post when connectivity
  returns) because each visit is a normal set of Odoo documents.
- No license cost beyond existing infrastructure.

**Negative / risks**
- Development effort for route planning, visit UX, and settlement (mitigated by the
  phased implementation plan; no route *optimization* in scope — sequencing is
  manual, see ADR-003).
- Mobile UX for drivers is Odoo web on a tablet/phone; not a native app. Acceptable
  for v1; API integration (option 4) remains open as a later frontend swap.
- POS option rejected: POS optimizes cash-register retail with session-based cash
  handling; it weakens per-route/per-visit stock traceability and invoice-link
  semantics we need for DSD settlement. Revisit only if pure cash-and-carry
  (no per-visit invoicing) becomes a requirement.
- Third-party app rejected: cost, vendor lock-in, opaque data model; our core
  loop is small enough to own.
