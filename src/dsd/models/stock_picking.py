from odoo import _, api, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    dsd_route_id = fields.Many2one(
        'dsd.route', string='DSD Route', compute='_compute_dsd_route_id',
        store=True, readonly=False, index='btree_not_null',
        help='Route serving this delivery; defaults from the customer.')
    dsd_is_dsd_delivery = fields.Boolean(
        compute='_compute_dsd_is_dsd_delivery',
        help='Delivery to a customer assigned to a DSD route.')

    @api.depends('partner_id')
    def _compute_dsd_route_id(self):
        for picking in self:
            picking.dsd_route_id = picking.dsd_route_id or (
                picking.partner_id.dsd_route_id if picking.partner_id else False)

    @api.depends('dsd_route_id', 'picking_type_code')
    def _compute_dsd_is_dsd_delivery(self):
        for picking in self:
            picking.dsd_is_dsd_delivery = bool(
                picking.dsd_route_id and picking.picking_type_code == 'outgoing')

    def button_validate(self):
        result = super().button_validate()
        tours = self.env['stock.picking.batch'].search([
            ('dsd_load_picking_id', 'in', self.ids)])
        if tours:
            done_tours = tours.filtered(
                lambda t: t.dsd_load_picking_id.state == 'done')
            done_tours._dsd_on_load_validated()
        return result
