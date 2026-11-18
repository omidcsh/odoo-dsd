from odoo import api, fields, models


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
    plant_id = fields.Many2one('stock.warehouse', string='Plant')
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist')

    _partner_area_uniq = models.Constraint(
        'unique (partner_id, sales_area_id)',
        'This customer already has this sales area!',
    )

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

    # -- pricelist sync -------------------------------------------------------
    def _sync_partner_pricelist(self):
        """Keep the partner's Odoo pricelist aligned with the primary
        (first active) sales area — the "use Odoo pricing" decision (plan
        D5): Odoo-native orders must price from the customer's primary SA.
        Never clears the property, only sets it."""
        for rec in self:
            if not rec.pricelist_id or not rec.active:
                continue
            rows = rec.partner_id.sales_area_ids.filtered(lambda r: r.active)
            primary = rows.sorted(key=lambda r: r.id)[:1]
            if primary == rec and rec.pricelist_id != rec.partner_id.property_product_pricelist:
                rec.partner_id.property_product_pricelist = rec.pricelist_id

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_partner_pricelist()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'pricelist_id', 'active'} & set(vals):
            self._sync_partner_pricelist()
        return res
