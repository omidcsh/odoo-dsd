from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdAggregation(models.Model):
    """Aggregation category (SAP: totals in crates/barrels regardless of content;
    limited to four, configured per company).
    """
    _name = 'dsd.aggregation'
    _description = 'DSD Aggregation Category'
    _order = 'sequence, name'
    _rec_names_search = ['name', 'code']

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict')
    product_line_ids = fields.One2many('dsd.product.aggregation', 'aggregation_id')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company')

    _code_unique = models.Constraint(
        'unique(code)',
        'The aggregation code must be unique.',
    )


class DsdProductAggregation(models.Model):
    """Per-product conversion into an aggregation category
    (SAP material master "DSD Totals" view: category + UoM + conversion factor).
    """
    _name = 'dsd.product.aggregation'
    _description = 'DSD Product Aggregation Conversion'
    _order = 'product_tmpl_id, sequence'

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='cascade')
    aggregation_id = fields.Many2one(
        'dsd.aggregation', required=True, ondelete='restrict')
    uom_id = fields.Many2one(related='aggregation_id.uom_id', readonly=True)
    factor = fields.Float(
        required=True, digits=(16, 6), default=1.0,
        help='How many aggregation units one unit of the product represents '
             '(e.g. 0.5 crate per 6-pack).')
    sequence = fields.Integer(default=10)

    _product_aggregation_unique = models.Constraint(
        'unique(product_tmpl_id, aggregation_id)',
        'The product already has this aggregation category.',
    )

    @api.constrains('factor')
    def _check_factor(self):
        for line in self:
            if line.factor <= 0:
                raise ValidationError(self.env._(
                    'The aggregation factor must be positive (product %s).',
                    line.product_tmpl_id.name))
