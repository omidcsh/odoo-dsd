from odoo import fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    is_dsd_van = fields.Boolean(
        'Is DSD Van',
        help='Mark internal locations that represent a delivery van. '
             'Van sales source their delivery from these locations.',
    )
