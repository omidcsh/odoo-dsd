from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sales_area_ids = fields.One2many(
        'dsd.partner.sales.area', 'partner_id', string='Sales Areas')
    # IMPL doc names these x_sales_org/x_dist_channel/x_division — clean
    # names here per plan D3; compatibility filters will query these.
    dsd_sales_org = fields.Char(
        string='Sales Org (primary)', compute='_compute_dsd_primary_sales_area',
        store=True)
    dsd_dist_channel = fields.Char(
        string='Distribution Channel (primary)', compute='_compute_dsd_primary_sales_area',
        store=True)
    dsd_division = fields.Char(
        string='Division (primary)', compute='_compute_dsd_primary_sales_area',
        store=True)
    dsd_sale_block = fields.Boolean(
        string='Sales Blocked (primary)', compute='_compute_dsd_primary_sales_area',
        store=True)
    dsd_delivery_block = fields.Boolean(
        string='Delivery Blocked (primary)', compute='_compute_dsd_primary_sales_area',
        store=True)
    dsd_billing_block = fields.Boolean(
        string='Billing Blocked (primary)', compute='_compute_dsd_primary_sales_area',
        store=True)

    @api.depends(
        'sales_area_ids',
        'sales_area_ids.active',
        'sales_area_ids.sale_block', 'sales_area_ids.delivery_block',
        'sales_area_ids.billing_block',
        'sales_area_ids.sales_area_id.sales_org_id.code',
        'sales_area_ids.sales_area_id.dist_channel_id.code',
        'sales_area_ids.sales_area_id.division_id.code',
    )
    def _compute_dsd_primary_sales_area(self):
        """Primary = first active sales-area row (lowest id). Read-through of
        its trio codes and block flags for list filtering."""
        for partner in self:
            rows = partner.sales_area_ids.filtered(lambda r: r.active)
            primary = rows.sorted(key=lambda r: r.id)[:1]
            if primary:
                combo = primary.sales_area_id
                partner.dsd_sales_org = combo.sales_org_id.code or False
                partner.dsd_dist_channel = combo.dist_channel_id.code or False
                partner.dsd_division = combo.division_id.code or False
                partner.dsd_sale_block = primary.sale_block
                partner.dsd_delivery_block = primary.delivery_block
                partner.dsd_billing_block = primary.billing_block
            else:
                partner.update({
                    'dsd_sales_org': False,
                    'dsd_dist_channel': False,
                    'dsd_division': False,
                    'dsd_sale_block': False,
                    'dsd_delivery_block': False,
                    'dsd_billing_block': False,
                })
