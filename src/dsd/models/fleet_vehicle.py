from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    dsd_vehicle_type = fields.Selection([
        ('truck', 'Truck'),
        ('van', 'Van'),
        ('trailer', 'Trailer'),
    ], string='DSD Vehicle Type', default='van')
    dsd_is_van = fields.Boolean(
        string='DSD Van (managed stock)',
        help='Manages a van stock location for this vehicle. Auto-enabled for newly '
             'created van/truck-type vehicles; legacy fleet vehicles must opt in.')
    dsd_trailer_of_id = fields.Many2one(
        'fleet.vehicle', string='Attached To',
        domain=[('dsd_vehicle_type', '!=', 'trailer')],
        help='For trailers: the tractor this trailer is coupled to.')
    dsd_license_category_ids = fields.Many2many(
        'dsd.license.category', string='Required License Categories',
        help='A driver must hold all of these categories to run a tour with this vehicle.')
    dsd_is_own_vehicle = fields.Boolean(string='Own Vehicle', default=True)
    variable_capacity = fields.Float(
        string='Variable Capacity',
        help='Extra flexible capacity (in loading units) beyond the rigid body, '
             'e.g. roof rack crates. Counted by the loading-unit capacity check.')
    dsd_max_stops_override = fields.Integer(string='Max Stops Override')
    dsd_max_duration_override = fields.Float(
        string='Max Duration Override (hours)', digits=(16, 2))
    dsd_van_location_id = fields.Many2one(
        'stock.location', string='Van Stock Location', copy=False,
        domain=[('usage', '=', 'internal')], check_company=True)
    dsd_van_damaged_location_id = fields.Many2one(
        'stock.location', string='Van Damaged Location', copy=False,
        domain=[('usage', '=', 'internal')], check_company=True)
    dsd_lock_ids = fields.One2many('dsd.lock.period', 'vehicle_id', string='Lock Periods')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('dsd_is_van') and vals.get('dsd_vehicle_type') in ('van', 'truck'):
                vals['dsd_is_van'] = True
        vehicles = super().create(vals_list)
        vehicles._sync_van_location()
        return vehicles

    def write(self, vals):
        result = super().write(vals)
        if {'dsd_is_van', 'dsd_vehicle_type', 'license_plate', 'company_id'} & vals.keys():
            # dsd_is_van is stored-computed from dsd_vehicle_type; read the
            # recomputed value from cache when syncing
            self._sync_van_location()
        return result

    def unlink(self):
        self.mapped('dsd_van_location_id').write({'active': False})
        self.mapped('dsd_van_damaged_location_id').write({'active': False})
        return super().unlink()

    def _get_van_parent_location(self):
        """Parent stock location: the vehicle company's main warehouse stock."""
        self.ensure_one()
        company = self.company_id or self.env.company
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=1, order='sequence')
        if not warehouse:
            raise ValidationError(self.env._(
                'Company %s has no warehouse to place the van stock location of %s.',
                company.name, self.name))
        return warehouse.lot_stock_id

    def _sync_van_location(self):
        for vehicle in self:
            if vehicle.dsd_is_van:
                vehicle._ensure_van_location()
            elif vehicle.dsd_van_location_id:
                vehicle.dsd_van_location_id.active = False
                if vehicle.dsd_van_damaged_location_id:
                    vehicle.dsd_van_damaged_location_id.active = False

    def _ensure_van_location(self):
        """Create (or reactivate) the van location and its damaged sub-location."""
        self.ensure_one()
        location = self.dsd_van_location_id
        if not location:
            parent = self._get_van_parent_location()
            name = self.env._('VAN/%s', self.license_plate or self.name)
            location = self.env['stock.location'].with_context(
                active_test=False).search(
                [('location_id', '=', parent.id), ('name', '=', name)], limit=1)
            if not location:
                location = self.env['stock.location'].create({
                    'name': name,
                    'usage': 'internal',
                    'location_id': parent.id,
                    'company_id': parent.company_id.id,
                })
            self.dsd_van_location_id = location
        if not location.active:
            location.active = True

        damaged = self.dsd_van_damaged_location_id
        if not damaged:
            damaged = self.env['stock.location'].with_context(
                active_test=False).search(
                [('location_id', '=', location.id), ('name', '=', _('Damaged'))], limit=1)
            if not damaged:
                damaged = self.env['stock.location'].create({
                    'name': _('Damaged'),
                    'usage': 'internal',
                    'location_id': location.id,
                    'company_id': location.company_id.id,
                })
            self.dsd_van_damaged_location_id = damaged
        if not damaged.active:
            damaged.active = True
