from odoo import _, api, fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    dsd_load_picking_type_id = fields.Many2one(
        'stock.picking.type', string='DSD Van Load Type', copy=False,
        help='Internal operation type used for van load-outs and speculative '
             'loads; created on first use.')

    def _dsd_get_load_picking_type(self):
        self.ensure_one()
        if self.dsd_load_picking_type_id:
            return self.dsd_load_picking_type_id
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', self.id),
            ('sequence_code', '=', 'VLOAD'),
        ], limit=1)
        if not picking_type:
            sequence = self.env['ir.sequence'].create({
                'name': _('DSD Van Load Sequence'),
                'prefix': 'VLOAD/',
                'padding': 5,
                'company_id': self.company_id.id,
            })
            picking_type = self.env['stock.picking.type'].create({
                'name': _('DSD Van Load'),
                'code': 'internal',
                'sequence_code': 'VLOAD',
                'sequence_id': sequence.id,
                'warehouse_id': self.id,
                'company_id': self.company_id.id,
                'use_create_lots': False,
                'use_existing_lots': True,
            })
        self.dsd_load_picking_type_id = picking_type
        return picking_type
