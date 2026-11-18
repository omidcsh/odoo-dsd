from odoo import api, fields, models


class DsdSalesArea(models.Model):
    """A valid sales-area combination (SAP TVTA equivalent).

    One row per (sales organization, distribution channel, division).
    The trio is the join key across the DSD wire protocol (registry
    MSE_CUSTOMER_SA/PF, MSE_CUST_SALES_AREA, MSE_DEALCOND_ASGN, …) and the
    device's visit identity — combinations must be defined here before a
    customer can be assigned to them. Future per-area customizing flags
    (the 68 fields of MSE_CUST_SALES_AREA) will live on this model.
    """
    _name = 'dsd.sales.area'
    _description = 'DSD Sales Area (valid combination)'
    _order = 'sales_org_id, dist_channel_id, division_id'
    _rec_names_search = ['display_name']

    sales_org_id = fields.Many2one(
        'dsd.sales.org', string='Sales Organization', required=True,
        index=True, ondelete='restrict')
    dist_channel_id = fields.Many2one(
        'dsd.distribution.channel', string='Distribution Channel', required=True,
        index=True, ondelete='restrict')
    division_id = fields.Many2one(
        'dsd.division', string='Division', required=True,
        index=True, ondelete='restrict')
    active = fields.Boolean(default=True)

    _combo_uniq = models.Constraint(
        'unique (sales_org_id, dist_channel_id, division_id)',
        'This sales-area combination (org/channel/division) already exists!',
    )

    @api.depends('sales_org_id.code', 'dist_channel_id.code', 'division_id.code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s/%s/%s' % (
                rec.sales_org_id.code or '?',
                rec.dist_channel_id.code or '?',
                rec.division_id.code or '?',
            )
