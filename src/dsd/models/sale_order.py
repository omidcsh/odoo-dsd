import datetime as dt_mod

from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dsd_route_id = fields.Many2one(
        'dsd.route', string='DSD Route', index='btree_not_null',
        help='Route carrying this order; defaults from the customer, aligned with '
             'the planned delivery appointment.')
    dsd_visit_list_line_id = fields.Many2one(
        'dsd.visit.list.line', string='Visit Stop', copy=False, index='btree_not_null',
        help='The stop this order was captured on (console or back office).')
    dsd_proposed_date = fields.Date(
        compute='_compute_dsd_proposal', string='Next Planned Visit',
        help='Earliest planned visit/delivery appointment for this customer within '
             'the lead-time window.')

    @api.depends('partner_id')
    def _compute_dsd_proposal(self):
        Appointment = self.env['dsd.visit.appointment']
        for order in self:
            order.dsd_proposed_date = False
            order.dsd_route_id = order.dsd_route_id or (
                order.partner_id.dsd_route_id if order.partner_id else False)

    def action_apply_dsd_defaults(self):
        """Apply DSD order-entry integration: route from the customer and the
        requested delivery date from the next planned appointment (SAP DSD
        order type + calendar type behavior)."""
        Appointment = self.env['dsd.visit.appointment']
        for order in self:
            if order.partner_id and not order.dsd_route_id:
                order.dsd_route_id = order.partner_id.dsd_route_id
            if order.partner_id and not order.commitment_date:
                today = fields.Date.context_today(order)
                lead = max(order.company_id.dsd_min_lead_days, 0)
                earliest = today + dt_mod.timedelta(days=lead)
                appointment = Appointment.search([
                    ('partner_id', '=', order.partner_id.id),
                    ('date', '>=', earliest),
                ], order='date', limit=1)
                if appointment:
                    order.commitment_date = dt_mod.datetime.combine(
                        appointment.date, dt_mod.time(8, 0))
                    order.message_post(body=_(
                        'Delivery date proposed from the planned %(kind)s on %(date)s '
                        '(route %(route)s).',
                        kind=dict(Appointment._fields['kind']._description_selection(
                            order.env)).get(appointment.kind, ''),
                        date=appointment.date,
                        route=appointment.route_id.display_name or '-',
                    ))
