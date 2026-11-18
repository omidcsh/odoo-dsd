from odoo import fields, models


class DsdSalesOrg(models.Model):
    """SAP sales organization (VKORG) — top level of the sales structure."""
    _name = 'dsd.sales.org'
    _description = 'DSD Sales Organization'
    _order = 'code'

    code = fields.Char(required=True, index=True, help="SAP VKORG code, e.g. 1000")
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique (code)',
        'The sales organization code must be unique!',
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} — {rec.name}'
