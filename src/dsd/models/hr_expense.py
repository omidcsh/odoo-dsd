from odoo import fields, models


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    dsd_tour_id = fields.Many2one(
        'stock.picking.batch', string='DSD Tour',
        help='Tour the expense was incurred on (fuel, tolls, parking).')
