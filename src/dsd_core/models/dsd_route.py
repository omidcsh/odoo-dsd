from odoo import fields, models


class DsdRoute(models.Model):
    """DSD customer-visit route — an Odoo-side grouping/ordering master.

    Deliberately NOT SAP TVRO (that is transport routing: transit/distance/
    weight — live-checked 2026-11-18) and not Solico's ZSLC_DSD_ROUTES
    (masir→sales-office mapping). Weekday patterns do NOT live here (D10):
    they belong to the visit plan header. This model answers: which
    customers, in which order, optionally scoped to one sales area and one
    departure warehouse, with permitted drivers.
    """
    _name = 'dsd.route'
    _description = 'DSD Route'
    _order = 'code'
    _rec_names_search = ['code', 'name']

    code = fields.Char(required=True, index=True, help="Route code (SAP masir codes migrate here)")
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sales_area_id = fields.Many2one(
        'dsd.sales.area', string='Sales Area',
        help="Optional scope: memberships must use this sales area")
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Departure Warehouse',
        help="Shipping point this route departs from")
    driver_ids = fields.Many2many(
        'res.users', string='Permitted Drivers',
        help="Who may ever run this route (permissions) — daily assignment "
             "lives on the visit list/tour, not here")
    customer_sequence_ids = fields.One2many(
        'dsd.route.customer', 'route_id', string='Customers')

    _code_uniq = models.Constraint(
        'unique (code)',
        'The route code must be unique!',
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} — {rec.name}'
