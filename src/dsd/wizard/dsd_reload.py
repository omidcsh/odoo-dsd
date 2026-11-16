from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DsdReload(models.TransientModel):
    """Mid-tour reload (SAP /DSD/SV_RELOAD): load additional goods onto the
    van (positive quantities, WH→Van) or unload unneeded goods (negative,
    Van→WH) while the tour is departed."""
    _name = 'dsd.reload'
    _description = 'DSD Reload'

    tour_id = fields.Many2one(
        'stock.picking.batch', required=True,
        domain=[('dsd_state', 'in', ('checked_out', 'in_progress'))])
    warehouse_id = fields.Many2one(related='tour_id.dsd_route_id.warehouse_id')
    line_ids = fields.One2many('dsd.reload.line', 'wizard_id', string='Reload Lines')

    @api.constrains('line_ids')
    def _check_lines(self):
        for wizard in self:
            if not wizard.line_ids:
                raise UserError(_('Enter at least one reload line.'))

    def action_apply(self):
        self.ensure_one()
        tour = self.tour_id
        warehouse = tour.dsd_route_id.warehouse_id
        if not warehouse:
            raise UserError(_('Tour %s has no departure warehouse.', tour.name))
        van = tour._dsd_van_location()
        picking_type = warehouse._dsd_get_load_picking_type()
        positive = self.line_ids.filtered(lambda ln: ln.quantity > 0)
        negative = self.line_ids.filtered(lambda ln: ln.quantity < 0)
        created = self.env['stock.picking'].browse()
        if positive:
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': van.id,
                'origin': f'{tour.name} reload',
                'move_ids': [
                    (0, 0, {
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.quantity,
                        'uom_id': line.product_id.uom_id.id,
                        'location_id': warehouse.lot_stock_id.id,
                        'location_dest_id': van.id,
                    })
                    for line in positive
                ],
            })
            created |= picking
        if negative:
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': van.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'origin': f'{tour.name} unload during reload',
                'move_ids': [
                    (0, 0, {
                        'product_id': line.product_id.id,
                        'product_uom_qty': -line.quantity,
                        'uom_id': line.product_id.uom_id.id,
                        'location_id': van.id,
                        'location_dest_id': warehouse.lot_stock_id.id,
                    })
                    for line in negative
                ],
            })
            created |= picking
        tour.dsd_reload_picking_ids = [(4, picking.id) for picking in created]
        tour._log_dsd_status(self.env._(
            'Reload: %s.',
            ', '.join(created.mapped('name')) or _('nothing')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reload Pickings'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }


class DsdReloadLine(models.TransientModel):
    _name = 'dsd.reload.line'
    _description = 'DSD Reload Line'

    wizard_id = fields.Many2one('dsd.reload', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True,
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]")
    quantity = fields.Float(
        required=True, default=1.0,
        help='Positive: load onto the van. Negative: return to the warehouse.')
    uom_id = fields.Many2one(related='product_id.uom_id')
