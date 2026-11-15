# ADR-004: Van sales via sale.order + instant picking/invoice/payment, not POS

- **Status:** Proposed
- **Date:** 2026-11-15
- **Parent:** ADR-001, ADR-002

## Context

At a store stop the driver may sell directly from the van: hand over goods, print/
show an invoice, take cash. Two mechanisms:

1. **`sale.order` + one-click completion**: a sale order with `warehouse = WH`
   whose delivery sources from the van location; a single "Complete Van Sale"
   button validates the outgoing picking from the van, creates and posts the
   invoice, registers the cash payment, all in one transaction.
2. **POS session per van**: orders taken in a POS configured on the van location
   with a cash payment method.

## Decision

**Option 1.** Van sale = `sale.order` (flagged `is_van_sale`, source location =
van location) completed by a single server action. Per-visit documents remain
first-class and settle cleanly: invoice → payment → picking all reference the
order and the visit.

## Consequences

**Positive**
- Invoice semantics per store visit (price lists, taxes, customer terms) come from
  the Sales app unchanged — retail cash-register semantics of POS (sessions,
  cash-in/out, POS categories) are the wrong fit.
- Settlement reconciliation reads ordinary `account.payment` records for the
  route day; no POS session import step.
- Works on the standard responsive web client.

**Negative**
- Slower per-transaction UX than POS (a few clicks); mitigated by the one-click
  wizard, canned "van sale" products/pricelist, and later barcode entry
  (`barcodes` framework is available in Community; `stock_barcode` mobile UX is
  Enterprise-only — v1 uses plain web forms).
- If a future requirement is anonymous street selling (no customer record), POS
  would be the better tool; revisit then.
