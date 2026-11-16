from odoo import _, api, fields, models, Command
from odoo.exceptions import ValidationError


class DsdDealCondition(models.Model):
    """Deal condition (SAP DSD deal condition): a limited sales action —
    free goods or a discount — granted on the van when the cart meets the
    conditions. Obligatory conditions apply automatically; optional ones are
    offered to the driver."""
    _name = 'dsd.deal.condition'
    _description = 'DSD Deal Condition'
    _order = 'sequence, name'
    _rec_names_search = ['name', 'code']

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    code = fields.Char(copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
    ], default='draft', required=True, tracking=True)
    obligatory = fields.Boolean(
        help='Applied automatically when the cart matches; otherwise offered '
             'to the driver.')
    date_start = fields.Date(required=True, default=lambda self: fields.Date.context_today(self))
    date_end = fields.Date()
    result_type = fields.Selection([
        ('free_goods', 'Free Goods'),
        ('discount_percent', 'Discount %'),
    ], required=True, default='free_goods')
    free_product_id = fields.Many2one(
        'product.product', string='Free Product',
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]")
    free_qty = fields.Float(default=1.0)
    discount_percent = fields.Float(digits=(16, 2))
    partner_ids = fields.Many2many(
        'res.partner', string='Customers',
        help='Empty = all customers of the routes.')
    partner_group_ids = fields.Many2many(
        'res.partner.category', string='Customer Groups')
    line_ids = fields.One2many(
        'dsd.deal.condition.line', 'condition_id', string='Conditions')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company')

    _result_positive = models.Constraint(
        'CHECK (free_qty >= 0 AND discount_percent >= 0 AND discount_percent <= 100)',
        'The deal result must be a positive quantity or a 0-100 discount.',
    )

    @api.constrains('line_ids')
    def _check_lines(self):
        for condition in self:
            if condition.state == 'active' and not condition.line_ids:
                raise ValidationError(self.env._(
                    'Active deal condition %s needs at least one condition line.',
                    condition.name))
            if condition.result_type == 'free_goods' and not condition.free_product_id:
                raise ValidationError(self.env._(
                    'Deal condition %s grants free goods but no product is set.',
                    condition.name))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for condition in self:
            if condition.date_end and condition.date_start > condition.date_end:
                raise ValidationError(self.env._(
                    'Deal condition %s: the start date must precede the end.',
                    condition.name))

    def action_set_active(self):
        self.state = 'active'

    def action_expire(self):
        self.state = 'expired'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self.env['ir.sequence'].next_by_code('dsd.deal.condition')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Matching / application (used by the console van-sale flow)
    # ------------------------------------------------------------------

    def _applies_to(self, partner, order_date):
        self.ensure_one()
        if self.state != 'active' or not self.active:
            return False
        if order_date < self.date_start:
            return False
        if self.date_end and order_date > self.date_end:
            return False
        if self.partner_ids and partner not in self.partner_ids:
            return False
        if self.partner_group_ids and not (partner.category_id & self.partner_group_ids):
            return False
        return True

    def _cart_matches(self, order):
        """All condition lines met: the cart holds min_qty of each product."""
        self.ensure_one()
        quantities = {}
        for line in order.order_line.filtered(lambda l: not l.is_dsd_free_goods):
            quantities[line.product_id] = quantities.get(line.product_id, 0.0) + \
                line.product_uom_qty
        for cond in self.line_ids:
            if quantities.get(cond.product_id, 0.0) < cond.min_qty:
                return False
        return True

    @api.model
    def evaluate_for_order(self, order):
        """Returns {'obligatory': recordset, 'optional': recordset} of matching
        conditions not yet applied to the order."""
        order_date = order.date_order.date() if order.date_order \
            else fields.Date.context_today(order)
        active = self.search([('state', '=', 'active'), ('active', '=', True)])
        matching = active.filtered(
            lambda c: c._applies_to(order.partner_id, order_date)
            and c._cart_matches(order))
        applied = order.dsd_applied_deal_ids
        return {
            'obligatory': matching.filtered('obligatory') - applied,
            'optional': matching.filtered(lambda c: not c.obligatory) - applied,
        }

    def apply_to_order(self, order):
        self.ensure_one()
        Applied = order.dsd_applied_deal_ids
        if self in Applied:
            return
        if self.result_type == 'free_goods':
            existing = order.order_line.filtered(
                lambda l: l.product_id == self.free_product_id
                and l.is_dsd_free_goods)
            if existing:
                existing.product_uom_qty += self.free_qty
            else:
                order.write({'order_line': [Command.create({
                    'product_id': self.free_product_id.id,
                    'product_uom_qty': self.free_qty,
                    'price_unit': 0.0,
                    'is_dsd_free_goods': True,
                })]})
        else:
            for line in order.order_line.filtered(
                    lambda l: not l.is_dsd_free_goods and l.product_id):
                line.discount = max(line.discount, self.discount_percent)
        order.dsd_applied_deal_ids = [(4, self.id)]


class DsdDealConditionLine(models.Model):
    _name = 'dsd.deal.condition.line'
    _description = 'DSD Deal Condition Line'
    _order = 'condition_id, sequence'

    sequence = fields.Integer(default=10)
    condition_id = fields.Many2one(
        'dsd.deal.condition', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    min_qty = fields.Float(required=True, default=1.0)
