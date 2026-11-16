from odoo import _, fields, models


class DsdReason(models.Model):
    """Reason codes across the DSD process (SAP: Define Reasons for Differences /
    for Changing Deliveries and Orders / Customer Visit Reasons).
    """
    _name = 'dsd.reason'
    _description = 'DSD Reason Code'
    _order = 'scope, sequence, code'
    _rec_names_search = ['name', 'code']

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    scope = fields.Selection([
        ('checkout_diff', 'Check-out difference'),
        ('checkin_diff', 'Check-in difference'),
        ('delivery_change', 'Delivery change'),
        ('order_change', 'Order change'),
        ('visit_outcome', 'Visit outcome'),
        ('stock_adjust', 'Van stock adjustment'),
        ('return', 'Return'),
    ], required=True)
    blocks_settlement = fields.Boolean(
        help='If set, using this reason marks the related tour difference as blocking '
             'for the final settlement run until resolved.')
    needs_reschedule = fields.Boolean(
        help='Visit outcome only: the visit should be rescheduled to a later date (status RS).')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company')  # empty = shared

    _code_scope_unique = models.Constraint(
        'unique(code, scope)',
        'The reason code must be unique within its scope.',
    )
