from odoo import _, fields, models


class DsdDsdGroup(models.Model):
    """DSD grouping on products (SAP material master "DSD Grouping").

    The calendar kind splits a customer's materialized appointments into
    visit streams and delivery streams (used from Phase 1 on).
    """
    _name = 'dsd.dsd.group'
    _description = 'DSD Product Grouping'
    _order = 'name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    calendar_kind = fields.Selection([
        ('visit', 'Visit calendar'),
        ('delivery', 'Delivery calendar'),
        ('none', 'No calendar'),
    ], required=True, default='none')
    description = fields.Text()
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'unique(code)',
        'The DSD grouping code must be unique.',
    )
