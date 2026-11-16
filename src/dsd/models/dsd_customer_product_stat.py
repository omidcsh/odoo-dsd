from datetime import date, timedelta

from odoo import _, api, fields, models


class DsdCustomerProductStat(models.Model):
    """Customer sales statistics (SAP mobile statistics /DSD/GS_QU):
    90-day quantities per customer x product, powering the console
    statistics panel and speculative-load proposals. Refreshed nightly
    from sale orders (ORM aggregates only — no raw SQL)."""
    _name = 'dsd.customer.product.stat'
    _description = 'DSD Customer Product Statistics'
    _order = 'partner_id, qty_90d desc'

    partner_id = fields.Many2one('res.partner', required=True, index='btree')
    product_id = fields.Many2one('product.product', required=True, index='btree')
    orders_90d = fields.Integer(readonly=True)
    qty_90d = fields.Float(readonly=True)
    avg_qty_per_week = fields.Float(readonly=True)
    last_order_date = fields.Date(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    _partner_product_unique = models.Constraint(
        'unique(partner_id, product_id)',
        'Only one statistics row per customer and product.',
    )

    @api.model
    def refresh_statistics(self):
        """Rebuild the 90-day aggregates from confirmed sale orders (ORM
        read_group; keeps everything parameter-free)."""
        self.search([]).unlink()
        cutoff = fields.Date.context_today(self) - timedelta(days=90)
        orders = self.env['sale.order'].search([
            ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', fields.Datetime.to_datetime(cutoff)),
        ])
        grouped = self.env['sale.order.line']._read_group(
            [('order_id', 'in', orders.ids)],
            ['order_id', 'product_id'],
            ['product_uom_qty:sum', 'order_id:count_distinct'],
        )
        # merge to one row per (customer, product): several orders of the
        # same pair must aggregate, not collide on the unique constraint
        per_pair = {}
        for order, product, qty_sum, order_count in grouped:
            key = (order.partner_id.id, product.id)
            agg = per_pair.setdefault(
                key, {'qty': 0.0, 'orders': 0, 'last': None,
                      'company': order.company_id.id})
            agg['qty'] += qty_sum
            agg['orders'] += order_count
            order_day = order.date_order.date()
            if not agg['last'] or order_day > agg['last']:
                agg['last'] = order_day
        for (partner_id, product_id), agg in per_pair.items():
            if not agg['qty']:
                continue
            self.create({
                'partner_id': partner_id,
                'product_id': product_id,
                'orders_90d': agg['orders'],
                'qty_90d': agg['qty'],
                'avg_qty_per_week': agg['qty'] / 13.0,  # ~90 days = ~13 weeks
                'last_order_date': agg['last'],
                'company_id': agg['company'],
            })
        return True
