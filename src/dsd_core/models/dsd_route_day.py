from odoo import api, fields, models
from odoo.tools.translate import _


class DsdRouteDay(models.Model):
    _name = 'dsd.route.day'
    _description = 'DSD Route Day'
    _order = 'date desc, id desc'

    name = fields.Char(required=True, copy=False, default='New')
    active = fields.Boolean(default=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    route_id = fields.Many2one('dsd.route', required=True, index=True, ondelete='cascade')
    mode = fields.Selection(related='route_id.mode', store=True)
    warehouse_id = fields.Many2one(related='route_id.warehouse_id', store=True)
    driver_id = fields.Many2one(
        'res.users', string='Driver',
        related='route_id.driver_id', store=True, readonly=False,
        domain=[('share', '=', False)],
        help='Defaults to the route driver; can be overridden per day.',
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle',
        related='route_id.vehicle_id', store=True, readonly=False,
    )
    van_location_id = fields.Many2one(
        'stock.location', string='Van Location',
        related='route_id.van_location_id', store=True, readonly=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('loaded', 'Loaded'),
            ('in_progress', 'In Progress'),
            ('done', 'Completed'),
            ('settled', 'Settled'),
        ],
        default='draft', required=True, index=True,
    )
    visit_ids = fields.One2many('dsd.visit', 'route_day_id', string='Visits')
    visit_count = fields.Integer(compute='_compute_visit_count')
    pending_visit_count = fields.Integer(compute='_compute_visit_count')

    _route_date_uniq = models.Constraint(
        'unique(route_id, date)',
        'A route day already exists for this route and date.',
    )

    @api.depends('visit_ids', 'visit_ids.state')
    def _compute_visit_count(self):
        for day in self:
            day.visit_count = len(day.visit_ids)
            day.pending_visit_count = len(day.visit_ids.filtered(
                lambda v: v.state == 'pending'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                seq = self.env['ir.sequence'].next_by_code('dsd.route.day')
                vals['name'] = seq or _('New')
        return super().create(vals_list)

    def action_open_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Visits'),
            'res_model': 'dsd.visit',
            'view_mode': 'list,form',
            'domain': [('route_day_id', '=', self.id)],
            'context': {'default_route_day_id': self.id},
        }


class DsdVisit(models.Model):
    _name = 'dsd.visit'
    _description = 'DSD Route Visit'
    _order = 'sequence, id'
    _rec_name = 'partner_id'

    sequence = fields.Integer(default=10)
    route_day_id = fields.Many2one(
        'dsd.route.day', required=True, index=True, ondelete='cascade',
    )
    partner_id = fields.Many2one('res.partner', string='Store', required=True)
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('done', 'Done'),
            ('skipped', 'Skipped'),
        ],
        default='pending', required=True, index=True,
    )
    skip_reason = fields.Char(
        invisible="state != 'skipped'",
        placeholder="e.g. store closed",
    )
    # Document links filled by later phases (delivery, van sale, settlement).
    sale_order_id = fields.Many2one('sale.order', string='Presale Order')
    delivery_id = fields.Many2one(
        'stock.picking', string='Delivery',
        domain="[('partner_id', '=', partner_id)]",
    )
    return_id = fields.Many2one(
        'stock.picking', string='Return',
        domain="[('partner_id', '=', partner_id)]",
    )
    invoice_id = fields.Many2one(
        'account.move', string='Invoice',
        domain=[('move_type', '=', 'out_invoice')],
    )
    payment_ids = fields.Many2many('account.payment', string='Payments')
    signature = fields.Binary('Proof of Delivery', attachment=True)
