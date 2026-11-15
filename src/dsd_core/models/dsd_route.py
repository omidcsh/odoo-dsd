from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DsdRoute(models.Model):
    _name = 'dsd.route'
    _description = 'DSD Route'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    mode = fields.Selection(
        selection=[
            ('presale', 'Presale'),
            ('van_sales', 'Van Sales'),
            ('mixed', 'Mixed'),
        ],
        required=True,
        default='mixed',
        help='Presale: orders are taken at the stop and fulfilled from the '
             'warehouse. Van Sales: goods are sold directly from the van. '
             'Mixed allows both.',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        required=True,
        default=lambda self: self.env['stock.warehouse'].search([], limit=1),
    )
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle')
    van_location_id = fields.Many2one(
        'stock.location',
        string='Van Location',
        domain=[('usage', '=', 'internal'), ('is_dsd_van', '=', True)],
    )
    driver_id = fields.Many2one(
        'res.users', string='Default Driver',
        domain=[('share', '=', False)],
    )
    stop_ids = fields.One2many('dsd.route.stop', 'route_id', string='Stops')
    stop_count = fields.Integer(compute='_compute_stop_count')
    route_day_ids = fields.One2many('dsd.route.day', 'route_id', string='Route Days')
    route_day_count = fields.Integer(compute='_compute_route_day_count')

    @api.depends('stop_ids')
    def _compute_stop_count(self):
        for route in self:
            route.stop_count = len(route.stop_ids)

    @api.depends('route_day_ids')
    def _compute_route_day_count(self):
        for route in self:
            route.route_day_count = len(route.route_day_ids)

    def action_open_route_days(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Route Days'),
            'res_model': 'dsd.route.day',
            'view_mode': 'list,form',
            'domain': [('route_id', '=', self.id)],
            'context': {'default_route_id': self.id},
        }

    @api.constrains('mode', 'van_location_id')
    def _check_van_location(self):
        for route in self:
            if route.mode != 'presale' and not route.van_location_id:
                raise ValidationError(self.env._(
                    "Route %(route)s runs van sales, so it needs a van "
                    "location. Presale-only routes are delivered from the "
                    "warehouse instead.",
                    route=route.name,
                ))


class DsdRouteStop(models.Model):
    _name = 'dsd.route.stop'
    _description = 'DSD Route Stop'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    route_id = fields.Many2one(
        'dsd.route', required=True, ondelete='cascade', index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Store', required=True, index=True,
    )
    monday = fields.Boolean()
    tuesday = fields.Boolean()
    wednesday = fields.Boolean()
    thursday = fields.Boolean()
    friday = fields.Boolean()
    saturday = fields.Boolean()
    sunday = fields.Boolean()
