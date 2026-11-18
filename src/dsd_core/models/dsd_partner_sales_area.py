from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdPartnerSalesArea(models.Model):
    """Customer x sales-area relationship (SSD customer sales-area view KNVV).

    Wire counterpart: MSE_CUSTOMER_SA + MSE_CUSTOMER_PF. Blocks suppress
    document *creation* while the row stays downloadable; archiving
    (active=False) removes it from the download entirely — the two mechanisms
    must stay separate (M01 3.2).
    """
    _name = 'dsd.partner.sales.area'
    _description = 'DSD Customer Sales Area'
    _order = 'partner_id, sales_area_id'
    _rec_names_search = ['display_name']

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, index=True,
        ondelete='cascade', domain=[('is_company', 'in', (True, False))])
    sales_area_id = fields.Many2one(
        'dsd.sales.area', string='Sales Area', required=True, index=True,
        ondelete='restrict')
    # exactly one ACTIVE primary per partner (python constraint below) — the
    # deterministic "main" SA (review P0); replaces first-row-by-id
    is_primary = fields.Boolean(string='Primary')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    # -- document blocks (wire SALE_BLOCK2 / DELV_BLOCK2 / BILL_BLOCK2) ------
    sale_block = fields.Boolean(string='Block Sales')
    sale_block_reason = fields.Char()
    delivery_block = fields.Boolean(string='Block Delivery')
    delivery_block_reason = fields.Char()
    billing_block = fields.Boolean(string='Block Billing')
    billing_block_reason = fields.Char()

    # -- partner functions (wire MSE_CUSTOMER_PF) ----------------------------
    payer_id = fields.Many2one('res.partner', string='Payer')
    sold_to_id = fields.Many2one('res.partner', string='Sold To')
    ship_to_id = fields.Many2one('res.partner', string='Ship To')
    bill_to_id = fields.Many2one('res.partner', string='Bill To')

    # -- Odoo-native reuse (wire PLANT / PRC_LIST) ---------------------------
    # plant: DEPLOYMENT MAPPING ASSUMPTION (SAP plant ≈ Odoo warehouse for
    # this deployment) — documented, revisit at the van-stock step (D9).
    plant_id = fields.Many2one('stock.warehouse', string='Plant')
    # D5+D9: read at ORDER/PRICE time from the relevant SA row; never synced
    # onto res.partner.property_product_pricelist (multi-SA partners hold
    # several pricelists; the partner property carries only one).
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist')

    _partner_area_uniq = models.Constraint(
        'unique (partner_id, sales_area_id)',
        'This customer already has this sales area!',
    )

    @api.constrains('partner_id', 'is_primary', 'active')
    def _check_single_primary(self):
        for rec in self:
            if rec.is_primary and rec.active:
                others = self.search([
                    ('partner_id', '=', rec.partner_id.id),
                    ('is_primary', '=', True),
                    ('active', '=', True),
                    ('id', '!=', rec.id),
                ])
                if others:
                    raise ValidationError(_(
                        'Customer %s already has a primary sales area (%s).',
                        rec.partner_id.display_name,
                        others[:1].sales_area_id.display_name,
                    ))

    @api.depends('partner_id.display_name', 'sales_area_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s — %s' % (
                rec.partner_id.display_name or '?',
                rec.sales_area_id.display_name or '?',
            )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Partner functions default to the customer itself (SAP defaults)."""
        for fn in ('payer_id', 'sold_to_id', 'ship_to_id', 'bill_to_id'):
            if not self[fn]:
                self[fn] = self.partner_id

    # PF defaults must ALSO cover API/code paths, not only the UI onchange
    # (review 1.4)
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('partner_id'):
                for fn in ('payer_id', 'sold_to_id', 'ship_to_id', 'bill_to_id'):
                    if not vals.get(fn):
                        vals[fn] = vals['partner_id']
        return super().create(vals_list)
