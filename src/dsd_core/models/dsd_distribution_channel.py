from odoo import fields, models


class DsdDistributionChannel(models.Model):
    """SAP distribution channel (VTWEG) — how products reach the customer."""
    _name = 'dsd.distribution.channel'
    _description = 'DSD Distribution Channel'
    _order = 'code'

    code = fields.Char(required=True, index=True, help="SAP VTWEG code, e.g. 10")
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique (code)',
        'The distribution channel code must be unique!',
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} — {rec.name}'
