from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DsdAssortment(models.Model):
    """Listing & exclusion (SAP group-based listing/exclusion, restricted to
    customer-group × product-category): which product categories a customer
    group may buy. Deny rules win over allow rules; no matching rule =
    allowed."""
    _name = 'dsd.assortment'
    _description = 'DSD Assortment Rule'
    _order = 'rule_type, id'

    name = fields.Char(compute='_compute_name')
    rule_type = fields.Selection([
        ('allow', 'Listing (allowed)'),
        ('deny', 'Exclusion (forbidden)'),
    ], required=True, default='deny')
    partner_group_id = fields.Many2one(
        'res.partner.category', required=True, string='Customer Group')
    product_category_id = fields.Many2one(
        'product.category', required=True, string='Product Category')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company')

    _rule_unique = models.Constraint(
        'unique(rule_type, partner_group_id, product_category_id)',
        'An assortment rule already exists for this combination.',
    )

    @api.depends('rule_type', 'partner_group_id', 'product_category_id')
    def _compute_name(self):
        for rule in self:
            rule.name = self.env._(
                '%(group)s × %(category)s (%(type)s)',
                group=rule.partner_group_id.name,
                category=rule.product_category_id.name,
                type=rule.rule_type)

    @api.model
    def is_allowed(self, partner, product):
        """Deny wins over allow; no rule at all = allowed."""
        partner_groups = partner.category_id
        product_category = product.categ_id
        rules = self.search([
            ('active', '=', True),
            ('partner_group_id', 'in', partner_groups.ids),
            ('product_category_id', 'parent_of', product_category.ids),
        ])
        if rules.filtered(lambda r: r.rule_type == 'deny'):
            return False
        return True

    @api.model
    def check_line(self, partner, product):
        if partner.dsd_route_id and not self.is_allowed(partner, product):
            raise UserError(self.env._(
                'Assortment: %s is not allowed to buy %s.',
                partner.display_name, product.display_name))
        return True
