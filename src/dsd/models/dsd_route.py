from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

WEEKDAY_FIELDS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


class DsdRoute(models.Model):
    """Strategic route template (SAP tour master header): departure warehouse,
    serving-day pattern, capacity limits and default resources for tours.
    The operational tour (SAP individual tour/shipment) is built on
    stock.picking.batch from Phase 2.
    """
    _name = 'dsd.route'
    _description = 'DSD Route'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    warehouse_id = fields.Many2one(
        'stock.warehouse', required=True, check_company=True, tracking=True,
        string='Departure Warehouse')
    color = fields.Integer()

    # Serving-day pattern (used by visit planning, Phase 1)
    mon = fields.Boolean(string='Monday', default=True)
    tue = fields.Boolean(string='Tuesday', default=True)
    wed = fields.Boolean(string='Wednesday', default=True)
    thu = fields.Boolean(string='Thursday', default=True)
    fri = fields.Boolean(string='Friday', default=True)
    sat = fields.Boolean(string='Saturday')
    sun = fields.Boolean(string='Sunday')

    # Capacity activation (checked by tour generation in SAP's fixed order:
    # weight -> volume -> stops -> variable capacity -> duration -> loading units)
    cap_weight = fields.Boolean(string='Check Weight', default=True)
    cap_volume = fields.Boolean(string='Check Volume', default=True)
    cap_stops = fields.Boolean(string='Check Number of Stops')
    max_stops = fields.Integer()
    cap_duration = fields.Boolean(string='Check Tour Duration')
    max_duration_hours = fields.Float(digits=(16, 2))
    cap_loading_units = fields.Boolean(string='Check Loading Units')
    lu_uom_id = fields.Many2one('uom.uom', string='Loading Unit')

    max_load_attempts = fields.Integer(
        default=2, required=True,
        help='When a stop would exceed a capacity limit, try this many following stops '
             'before closing the tour (SAP "Number of Attempts").')
    single_daily_tour = fields.Boolean(
        string='One Tour per Day',
        help='Tour generation creates at most one tour per day for this route.')

    # Default resources
    default_driver_id = fields.Many2one(
        'hr.employee', string='Default Driver',
        domain=[('dsd_active_driver', '=', True)], check_company=True)
    default_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Default Vehicle',
        domain=[('dsd_is_van', '=', True), ('dsd_vehicle_type', '!=', 'trailer')],
        check_company=True)
    default_trailer_id = fields.Many2one(
        'fleet.vehicle', string='Default Trailer',
        domain=[('dsd_vehicle_type', '=', 'trailer')])

    partner_ids = fields.One2many('res.partner', 'dsd_route_id', string='Customers')
    partner_count = fields.Integer(compute='_compute_partner_count')

    _code_company_unique = models.Constraint(
        'unique(code, company_id)',
        'The route code must be unique per company.',
    )

    def _compute_partner_count(self):
        partners = self.env['res.partner'].with_context(active_test=False).read_group(
            [('dsd_route_id', 'in', self.ids)], ['dsd_route_id'], ['dsd_route_id'])
        counts = {row['dsd_route_id'][0]: row['dsd_route_id_count'] for row in partners}
        for route in self:
            route.partner_count = counts.get(route.id, 0)

    @api.constrains('max_stops', 'cap_stops')
    def _check_stops(self):
        for route in self:
            if route.cap_stops and route.max_stops <= 0:
                raise ValidationError(self.env._(
                    'Route %s activates the stop limit but has no positive maximum stops.',
                    route.name))

    @api.constrains('max_duration_hours', 'cap_duration')
    def _check_duration(self):
        for route in self:
            if route.cap_duration and route.max_duration_hours <= 0:
                raise ValidationError(self.env._(
                    'Route %s activates the duration limit but has no positive maximum duration.',
                    route.name))

    @api.constrains('max_load_attempts')
    def _check_attempts(self):
        for route in self:
            if route.max_load_attempts < 1:
                raise ValidationError(self.env._(
                    'Route %s must allow at least one load attempt.', route.name))

    @api.constrains('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    def _check_serving_days(self):
        for route in self:
            if not any(route[f] for f in WEEKDAY_FIELDS):
                raise ValidationError(self.env._(
                    'Route %s must serve at least one weekday.', route.name))

    def action_view_customers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Customers'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('dsd_route_id', '=', self.id)],
            'context': {'default_dsd_route_id': self.id},
        }
