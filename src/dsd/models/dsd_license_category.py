from odoo import _, fields, models


class DsdLicenseCategory(models.Model):
    """Driver's license category (SAP: Define Driver's License Categories).

    A driver must hold every category required by a vehicle to drive it on a tour.
    """
    _name = 'dsd.license.category'
    _description = 'DSD License Category'
    _order = 'code'
    _rec_names_search = ['name', 'code']

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company')  # empty = shared across companies

    _code_unique = models.Constraint(
        'unique(code)',
        'The license category code must be unique.',
    )
