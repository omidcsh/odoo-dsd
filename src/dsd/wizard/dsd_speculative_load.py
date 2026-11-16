from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DsdSpeculativeLoad(models.TransientModel):
    """Speculative load (SAP van-seller header reference): goods loaded onto
    the van without pre-sold orders, owned by the driver until settlement."""
    _name = 'dsd.speculative.load'
    _description = 'DSD Speculative Load'

    visit_list_id = fields.Many2one(
        'dsd.visit.list', required=True,
        domain=[('state', 'in', ('draft', 'confirmed'))])
    warehouse_id = fields.Many2one(
        'stock.warehouse', related='visit_list_id.route_id.warehouse_id')
    van_id = fields.Many2one(
        'fleet.vehicle', required=True, string='Van',
        domain=[('dsd_is_van', '=', True)])
    line_ids = fields.One2many(
        'dsd.speculative.load.line', 'wizard_id', string='Products')

    @api.constrains('line_ids')
    def _check_lines(self):
        for wizard in self:
            if not wizard.line_ids:
                raise UserError(_('Add at least one product to the speculative load.'))

    def action_create(self):
        self.ensure_one()
        visit_list = self.visit_list_id
        if visit_list.speculative_load_picking_id:
            raise UserError(_(
                'Visit list %s already has a speculative load (%s).',
                visit_list.name, visit_list.speculative_load_picking_id.name))
        if any(line.quantity <= 0 for line in self.line_ids):
            raise UserError(_('Speculative load quantities must be positive.'))
        van = self.van_id.dsd_van_location_id
        warehouse = self.warehouse_id
        picking_type = warehouse._dsd_get_load_picking_type()
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': van.id,
            'origin': f'{visit_list.name} speculative load',
            'move_ids': [
                (0, 0, {
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'uom_id': line.product_id.uom_id.id,
                    'location_id': warehouse.lot_stock_id.id,
                    'location_dest_id': van.id,
                })
                for line in self.line_ids
            ],
        })
        visit_list.speculative_load_picking_id = picking
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
        }


class DsdSpeculativeLoadLine(models.TransientModel):
    _name = 'dsd.speculative.load.line'
    _description = 'DSD Speculative Load Line'

    wizard_id = fields.Many2one('dsd.speculative.load', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True,
        domain="[('type', '=', 'consu'), ('is_storable', '=', True)]")
    quantity = fields.Float(default=1.0, required=True)
    uom_id = fields.Many2one(related='product_id.uom_id')
