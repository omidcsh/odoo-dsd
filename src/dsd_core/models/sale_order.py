from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _action_confirm(self):
        res = super()._action_confirm()
        # Van sales must ship from the van location, not warehouse stock:
        # retarget the pickings this confirmation created, and link the
        # delivery to the visit for the completion flow. Runs after
        # _action_confirm because pickings only exist by then.
        visits = self.env['dsd.visit'].search([
            ('sale_order_id', 'in', self.ids)])
        for visit in visits:
            order = visit.sale_order_id
            pickings = order.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel'))
            if visit.sale_kind == 'van_sale' and pickings:
                van = visit.route_day_id.van_location_id
                pickings.write({'location_id': van.id})
                pickings.move_ids.write({'location_id': van.id})
            if pickings and not visit.delivery_id:
                visit.delivery_id = pickings[0]
        return res
