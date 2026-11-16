from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # --- DSD data tab (SAP material master "DSD Data") ---
    dsd_group_id = fields.Many2one(
        'dsd.dsd.group', string='DSD Grouping', index='btree_not_null',
        help='Groups materials with the same visit/delivery calendar kind.')
    counting_group_id = fields.Many2one(
        'dsd.counting.group', string='Counting Group', index='btree_not_null',
        help='Materials counted together during loading confirmation and checks.')
    tolerance_type_id = fields.Many2one(
        'dsd.tolerance.type', string='Tolerance Type', index='btree_not_null',
        help='Drives tolerance-group determination during difference determination.')
    dsd_aggregation_line_ids = fields.One2many(
        'dsd.product.aggregation', 'product_tmpl_id', string='Aggregation Totals')
    is_returnable = fields.Boolean(
        string='Returnable (Empties)',
        help='Empty containers managed as stock (untied empties in SAP terms).')
    # Empties BOM (tied empties explosion) lands in Phase 6; re-evaluate the
    # mrp dependency or a dedicated dsd.bom model then.

    @api.constrains('counting_group_id')
    def _check_counting_group_storable(self):
        for template in self:
            if template.counting_group_id and not template.is_storable:
                raise ValidationError(self.env._(
                    'Counting group on %s requires a storable product.',
                    template.name))
