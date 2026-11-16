from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdCountingGroup(models.Model):
    """Counting group (SAP: group materials with similar packaging so checks
    can count pallets first, then crates, then pieces).
    """
    _name = 'dsd.counting.group'
    _description = 'DSD Counting Group'
    _order = 'name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    uom_line_ids = fields.One2many(
        'dsd.counting.group.uom', 'counting_group_id', string='Counting UoM Hierarchy')
    product_ids = fields.One2many('product.template', 'counting_group_id')
    product_count = fields.Integer(compute='_compute_product_count')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'unique(code)',
        'The counting group code must be unique.',
    )

    @api.depends('product_ids')
    def _compute_product_count(self):
        groups = self.with_context(active_test=False)
        for group, noContext in zip(self, groups):
            group.product_count = len(noContext.product_ids)

    @api.constrains('uom_line_ids')
    def _check_hierarchy(self):
        for group in self:
            uoms = group.uom_line_ids.mapped('uom_id')
            if len(uoms) != len(group.uom_line_ids):
                raise ValidationError(self.env._(
                    'Counting group %s uses a unit of measure twice.', group.name))


class DsdCountingGroupUom(models.Model):
    """One step of the counting hierarchy, e.g. Pallet, then Case, then Unit."""
    _name = 'dsd.counting.group.uom'
    _description = 'DSD Counting Group Unit'
    _order = 'counting_group_id, sequence, id'

    counting_group_id = fields.Many2one(
        'dsd.counting.group', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict')
    factor_to_base = fields.Float(
        string='Conversion to Base Unit',
        related='uom_id.factor', readonly=True,
        help='How many base units one of this counting unit represents; shown to catch '
             'missing conversions on products (SAP check report /DSD/SV_CHECK_CG).')
