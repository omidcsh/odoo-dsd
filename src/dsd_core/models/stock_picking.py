from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _open_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def button_validate(self):
        res = super().button_validate()
        # Keep DSD documents in sync when their pickings complete: the van
        # load marks the route day loaded and a validated delivery closes
        # its visit. Settling is an explicit act on the settlement record.
        done = self.filtered(lambda p: p.state == 'done')
        if done:
            env = self.env
            load_days = env['dsd.route.day'].search(
                [('load_picking_id', 'in', done.ids)])
            load_days.filtered(
                lambda d: d.state == 'draft').write({'state': 'loaded'})
            visits = env['dsd.visit'].search(
                [('delivery_id', 'in', done.ids)])
            visits.filtered(
                lambda v: v.state == 'pending').write({'state': 'done'})
        return res
