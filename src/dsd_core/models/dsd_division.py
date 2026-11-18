from odoo import fields, models


class DsdDivision(models.Model):
    """SAP division (SPART) — product line broadest classification."""
    _name = 'dsd.division'
    _description = 'DSD Division'
    _order = 'code'

    code = fields.Char(required=True, index=True, help="SAP SPART code, e.g. 01")
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique (code)',
        'The division code must be unique!',
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} — {rec.name}'
