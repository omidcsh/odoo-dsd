from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdToleranceType(models.Model):
    """Tolerance type assigned to a product (SAP: material master tolerance type)."""
    _name = 'dsd.tolerance.type'
    _description = 'DSD Tolerance Type'
    _order = 'name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    description = fields.Text()
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'unique(code)',
        'The tolerance type code must be unique.',
    )


class DsdToleranceGroup(models.Model):
    """Tolerance group (SAP: Route Settlement -> Tolerances).

    Determines whether a quantity or cash difference is auto-posted (warn)
    or must be resolved manually (block) during difference determination.
    Determination: product tolerance type x partner (partner-specific group wins).
    """
    _name = 'dsd.tolerance.group'
    _description = 'DSD Tolerance Group'
    _order = 'partner_id, sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    tolerance_type_id = fields.Many2one(
        'dsd.tolerance.type', string='Product Tolerance Type', index='btree_not_null',
        help='Products carrying this tolerance type are checked against this group.')
    partner_id = fields.Many2one(
        'res.partner', string='Customer (optional)',
        help='Empty = applies to every customer; a customer-specific group takes priority.')
    line_ids = fields.One2many('dsd.tolerance.group.line', 'group_id')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company')

    @api.constrains('line_ids')
    def _check_lines(self):
        for group in self:
            kinds = [line.check_kind for line in group.line_ids]
            if len(kinds) != len(set(kinds)):
                raise ValidationError(self.env._(
                    'Tolerance group %s has duplicate check kinds; keep one line per kind.',
                    group.name))


class DsdToleranceGroupLine(models.Model):
    _name = 'dsd.tolerance.group.line'
    _description = 'DSD Tolerance Group Threshold'
    _order = 'group_id, check_kind'

    group_id = fields.Many2one('dsd.tolerance.group', required=True, ondelete='cascade')
    check_kind = fields.Selection([
        ('qty_abs', 'Quantity difference (absolute)'),
        ('qty_pct', 'Quantity difference (%)'),
        ('value_abs', 'Value difference (absolute)'),
        ('value_pct', 'Value difference (%)'),
    ], required=True, string='Check')
    threshold = fields.Float(
        required=True,
        help='Maximum accepted difference. Percentages are expressed 0-100. '
             'Differences within the threshold follow the severity policy below.')
    severity = fields.Selection([
        ('warn', 'Auto-post and continue'),
        ('block', 'Require manual resolution'),
    ], required=True, default='warn')
