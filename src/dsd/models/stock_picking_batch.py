from odoo import _, api, fields, models
from odoo.exceptions import UserError

DSD_TOUR_STATES = [
    ('draft', 'Draft'),
    ('confirmed', 'Confirmed'),
    ('loading', 'Loading'),
    ('loaded', 'Loaded'),
    ('checked_out', 'Checked Out'),
    ('in_progress', 'On Tour'),
    ('checked_in', 'Checked In'),
    ('to_settle', 'To Settle'),
    ('settled', 'Settled'),
    ('cancelled', 'Cancelled'),
]


class StockPickingBatch(models.Model):
    """DSD tour: one driver/vehicle day-run built on the stock batch transfer
    (SAP shipment). `stock_fleet` provides vehicle, driver and capacity usage;
    this extension adds the tour lifecycle, visit-list link, co-driver,
    trailer, seals and the van load-out."""
    _inherit = 'stock.picking.batch'

    dsd_state = fields.Selection(
        DSD_TOUR_STATES, string='Tour Status', default='draft',
        tracking=True, copy=False, index='btree')
    # Operational DSD driver (hr.employee with licenses/locks). The stock_fleet
    # `driver_id` on this model is a res.partner contact kept for consignment
    # documents; the tour runs on the employee.
    dsd_driver_id = fields.Many2one(
        'hr.employee', string='Tour Driver',
        domain=[('dsd_active_driver', '=', True)], check_company=True, tracking=True)
    dsd_route_id = fields.Many2one(
        'dsd.route', string='DSD Route', check_company=True,
        help='Route this tour runs; defaults from the visit list.')
    dsd_visit_list_id = fields.Many2one(
        'dsd.visit.list', string='Visit List', check_company=True,
        copy=False, index='btree_not_null',
        help='Defining visit list for sales-oriented roles; locks the list once set.')
    dsd_driver2_id = fields.Many2one(
        'hr.employee', string='Co-Driver',
        domain=[('dsd_active_driver', '=', True)], check_company=True)
    dsd_trailer_id = fields.Many2one(
        'fleet.vehicle', string='Trailer',
        domain=[('dsd_vehicle_type', '=', 'trailer')])
    dsd_execution_date = fields.Date(
        compute='_compute_dsd_execution_date', store=True, string='Tour Date')
    dsd_load_picking_id = fields.Many2one(
        'stock.picking', string='Van Load-Out', copy=False,
        help='Internal picking moving the loaded goods warehouse → van.')
    dsd_unload_picking_id = fields.Many2one(
        'stock.picking', string='Van Unload', copy=False,
        help='Internal picking returning remaining van stock at check-in.')
    dsd_reload_picking_ids = fields.Many2many(
        'stock.picking', 'dsd_tour_reload_rel', 'batch_id', 'picking_id',
        string='Reload Pickings', copy=False,
        help='Mid-tour WH→Van / Van→WH stop-off pickings.')
    dsd_check_ids = fields.One2many(
        'dsd.check.record', 'tour_id', string='Check-Out / Check-In')
    dsd_loading_confirmation_ids = fields.One2many(
        'dsd.loading.confirmation', 'tour_id', string='Loading Confirmations')
    dsd_seal_numbers = fields.Char(
        string='Seal Numbers', copy=False,
        help='Recorded with the loading confirmation before departure.')
    dsd_odometer_start = fields.Float(string='Odometer Start', copy=False)
    dsd_odometer_end = fields.Float(string='Odometer End', copy=False)
    dsd_planned_weight = fields.Float(
        compute='_compute_dsd_planned_load', string='Planned Weight', digits='Product Unit')
    dsd_planned_volume = fields.Float(
        compute='_compute_dsd_planned_load', string='Planned Volume', digits='Product Unit')
    dsd_stop_count = fields.Integer(
        compute='_compute_dsd_stop_count', string='Stops')
    dsd_lu_total = fields.Float(
        compute='_compute_dsd_planned_load', string='Loading Units',
        help='Planned loading units against the vehicle capacity '
             '(route loading-unit UoM).')
    dsd_lu_capacity = fields.Float(compute='_compute_dsd_lu_capacity')
    dsd_weight_usage = fields.Float(
        compute='_compute_dsd_planned_load', string='Weight Usage %')
    dsd_volume_usage = fields.Float(
        compute='_compute_dsd_planned_load', string='Volume Usage %')
    dsd_lu_usage = fields.Float(
        compute='_compute_dsd_planned_load', string='Loading Units Usage %')
    dsd_attention = fields.Boolean(
        compute='_compute_dsd_attention', string='Needs Attention',
        search='_search_dsd_attention')

    _planned_load_sql = models.Constraint(
        'CHECK (dsd_odometer_end >= 0 AND dsd_odometer_start >= 0)',
        'Odometer readings cannot be negative.',
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('dsd_visit_list_id.execution_date', 'scheduled_date')
    def _compute_dsd_execution_date(self):
        for tour in self:
            if tour.dsd_visit_list_id:
                tour.dsd_execution_date = tour.dsd_visit_list_id.execution_date
            elif tour.scheduled_date:
                tour.dsd_execution_date = tour.scheduled_date.date()
            else:
                tour.dsd_execution_date = False

    def _compute_dsd_stop_count(self):
        for tour in self:
            tour.dsd_stop_count = len(tour.picking_ids.mapped('partner_id'))

    def _compute_dsd_lu_capacity(self):
        for tour in self:
            capacity = tour.vehicle_id.category_id.dsd_loading_units or 0.0
            tour.dsd_lu_capacity = capacity + (tour.vehicle_id.variable_capacity or 0.0)

    def _compute_dsd_planned_load(self):
        for tour in self:
            weight = volume = 0.0
            lu = 0.0
            lu_uom = tour.dsd_route_id.lu_uom_id \
                if tour.dsd_route_id and tour.dsd_route_id.cap_loading_units else False
            for move in tour.picking_ids.move_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')):
                qty = move.uom_id._compute_quantity(
                    move.product_uom_qty, move.product_id.uom_id)
                weight += move.product_id.weight * qty
                volume += move.product_id.volume * qty
                if lu_uom and move.product_id.uom_id._has_common_reference(lu_uom):
                    lu += move.product_id.uom_id._compute_quantity(qty, lu_uom)
            tour.dsd_planned_weight = weight
            tour.dsd_planned_volume = volume
            tour.dsd_lu_total = lu
            category = tour.vehicle_id.category_id
            tour.dsd_weight_usage = (100 * weight / category.weight_capacity
                                     if category.weight_capacity else 0.0)
            tour.dsd_volume_usage = (100 * volume / category.volume_capacity
                                     if category.volume_capacity else 0.0)
            tour.dsd_lu_usage = (100 * lu / tour.dsd_lu_capacity
                                 if tour.dsd_lu_capacity else 0.0)

    def _compute_dsd_attention(self):
        for tour in self:
            tour.dsd_attention = (
                tour.dsd_state in ('draft', 'confirmed')
                and bool(tour._validate_tour(raise_error=False)))

    def _search_dsd_attention(self, operator, value):
        failing = [tour.id for tour in self.search([
            ('dsd_state', 'in', ('draft', 'confirmed'))])
            if tour._validate_tour(raise_error=False)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            return [('id', 'not in', failing)]
        return [('id', 'in', failing)]

    # ------------------------------------------------------------------
    # Validation (SAP shipment checks)
    # ------------------------------------------------------------------

    def _validate_tour(self, raise_error=True):
        """SAP shipment checks: drivers, vehicle, trailer, licenses, locks,
        warehouse consistency. Returns an empty list when valid (or raises)."""
        self.ensure_one()
        errors = []
        vehicle = self.vehicle_id
        driver = self.dsd_driver_id
        if self.dsd_driver2_id and not driver:
            errors.append(_('A co-driver requires a main driver.'))
        if self.dsd_trailer_id:
            if self.dsd_trailer_id.dsd_vehicle_type != 'trailer':
                errors.append(_('The trailer %s is not of trailer type.',
                                self.dsd_trailer_id.display_name))
            if vehicle and self.dsd_trailer_id.dsd_trailer_of_id \
                    and self.dsd_trailer_id.dsd_trailer_of_id != vehicle:
                errors.append(_('Trailer %s is attached to %s, not to %s.',
                                self.dsd_trailer_id.display_name,
                                self.dsd_trailer_id.dsd_trailer_of_id.display_name,
                                vehicle.display_name))
        if vehicle and driver:
            missing = vehicle.dsd_license_category_ids - driver.license_category_ids
            if missing:
                errors.append(_('Driver %s lacks license category %s required by %s.',
                                driver.name,
                                ', '.join(missing.mapped('code')),
                                vehicle.display_name))
            day = self.dsd_execution_date
            if day:
                locks = self.env['dsd.lock.period'].search([
                    '|', ('employee_id', '=', driver.id),
                    ('vehicle_id', '=', vehicle.id),
                    ('date_from', '<=', day), ('date_to', '>=', day)])
                for lock in locks:
                    who = lock.employee_id.name or lock.vehicle_id.name
                    errors.append(_('%s is locked from %s to %s (%s).',
                                    who, lock.date_from, lock.date_to, lock.reason or '-'))
        warehouses = self.picking_ids.picking_type_id.warehouse_id
        if len(warehouses) > 1:
            errors.append(_('Tour pickings span multiple warehouses (%s).',
                            ', '.join(warehouses.mapped('display_name'))))
        if raise_error and errors:
            raise UserError('\n'.join(errors))
        return errors

    def _log_dsd_status(self, message):
        self.ensure_one()
        self.message_post(body=message, body_is_html=False)

    def write(self, vals):
        for tour in self:
            if 'dsd_state' in vals and vals['dsd_state'] != tour.dsd_state:
                label = dict(self._fields['dsd_state']._description_selection(self.env))
                tour.message_post(body=self.env._(
                    'Tour status: %s → %s.',
                    label.get(tour.dsd_state, tour.dsd_state or '-'),
                    label.get(vals['dsd_state'], vals['dsd_state'])))
        return super().write(vals)

    def action_dsd_start(self):
        for tour in self:
            if tour.dsd_state != 'checked_out':
                raise UserError(_('Only checked-out tours can depart.'))
        self.write({'dsd_state': 'in_progress'})
        for tour in self:
            tour._log_dsd_status(_('Tour departed.'))
        return True

    def action_dsd_open_reload(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reload Van'),
            'res_model': 'dsd.reload',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tour_id': self.id},
        }

    def _create_unload_picking(self):
        """Return remaining van stock to the warehouse (SAP final unloading
        document): one internal picking covering the van sub-locations."""
        self.ensure_one()
        van = self.vehicle_id.dsd_van_location_id
        if not van:
            return False
        warehouse = self.dsd_route_id.warehouse_id \
            or self.picking_ids.picking_type_id.warehouse_id[:1]
        if not warehouse:
            return False
        picking_type = warehouse._dsd_get_load_picking_type()
        quants = self.env['stock.quant'].search([
            ('location_id', 'child_of', van.id),
            ('quantity', '>', 0),
        ])
        if not quants:
            return False
        unload = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': van.id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'origin': f'{self.name} check-in unload',
            'move_ids': [
                (0, 0, {
                    'product_id': quant.product_id.id,
                    'product_uom_qty': quant.quantity,
                    'uom_id': quant.product_id.uom_id.id,
                    'location_id': quant.location_id.id,
                    'location_dest_id': warehouse.lot_stock_id.id,
                })
                for quant in quants
            ],
        })
        self.dsd_unload_picking_id = unload
        return unload

    def action_dsd_confirm(self):
        for tour in self:
            tour._validate_tour()
            if not tour.vehicle_id:
                raise UserError(_('Tour %s needs a vehicle before confirming.',
                                  tour.display_name))
            if not tour.dsd_driver_id:
                raise UserError(_('Tour %s needs a driver before confirming.',
                                  tour.display_name))
        self.write({'dsd_state': 'confirmed'})
        for tour in self:
            tour._log_dsd_status(_('Tour confirmed.'))

    # ------------------------------------------------------------------
    # Van load-out (aggregation picking WH → Van)
    # ------------------------------------------------------------------

    def _dsd_van_location(self):
        self.ensure_one()
        van = self.vehicle_id.dsd_van_location_id
        if not van:
            raise UserError(_('Vehicle %s has no van stock location.',
                              self.vehicle_id.display_name))
        return van

    def _get_or_create_load_picking_type(self, warehouse):
        return warehouse._dsd_get_load_picking_type()

    def action_dsd_load(self):
        """Prepare the van load-out: unreserve the customer deliveries,
        re-route them to the van stock location, and create ONE internal
        picking warehouse → van aggregating the planned quantities."""
        for tour in self:
            if tour.dsd_state not in ('draft', 'confirmed'):
                raise UserError(_('Tour %s is not in a loadable state.', tour.name))
            if not tour.picking_ids:
                raise UserError(_('Tour %s has no deliveries to load.', tour.name))
            van = tour._dsd_van_location()
            warehouse = tour.picking_ids.picking_type_id.warehouse_id[:1]
            if not warehouse:
                warehouse = tour.dsd_route_id.warehouse_id
            tour._validate_tour()
            # unreserve then re-route: goods will be reserved from the van once
            # the load-out picking is validated
            tour.picking_ids.mapped('move_ids')._do_unreserve()
            tour.picking_ids.write({'location_id': van.id})
            tour.picking_ids.mapped('move_ids').write({'location_id': van.id})
            load = tour._create_load_picking(van, warehouse)
            tour.dsd_load_picking_id = load
            tour.dsd_state = 'loading'
            tour._log_dsd_status(self.env._(
                'Load-out %s prepared (%s): %s.',
                load.name, van.display_name,
                ', '.join(f'{move.product_uom_qty} {move.uom_id.name}'
                          for move in load.move_ids) or _('nothing')))
        return True

    def _create_load_picking(self, van, warehouse):
        self.ensure_one()
        Picking = self.env['stock.picking']
        aggregated = {}
        for move in self.picking_ids.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')):
            key = (move.product_id, move.uom_id)
            aggregated[key] = aggregated.get(key, 0.0) + move.product_uom_qty
        picking_type = self._get_or_create_load_picking_type(warehouse)
        load = Picking.create({
            'picking_type_id': picking_type.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': van.id,
            'origin': self.name,
            'move_ids': [
                (0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'uom_id': uom.id,
                    'location_id': warehouse.lot_stock_id.id,
                    'location_dest_id': van.id,
                })
                for (product, uom), qty in aggregated.items()
            ],
        })
        return load

    # ------------------------------------------------------------------
    # Materials overview (SAP shipment materials overview)
    # ------------------------------------------------------------------

    def action_view_materials(self):
        """Aggregate the planned products across the tour deliveries."""
        self.ensure_one()
        lines = {}
        for move in self.picking_ids.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')):
            key = move.product_id
            entry = lines.setdefault(key, {'qty': 0.0, 'uom': move.uom_id})
            qty = move.uom_id._compute_quantity(
                move.product_uom_qty, move.product_id.uom_id)
            entry['qty'] += move.product_id.uom_id._compute_quantity(
                qty, entry['uom'])
        body = ''.join(
            f'<tr><td>{product.display_name}</td>'
            f'<td class="text-end">{entry["qty"]:.2f} {entry["uom"].name}</td></tr>'
            for product, entry in sorted(lines.items(),
                                         key=lambda item: item[0].display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tour Materials — %s', self.name),
            'res_model': 'dsd.tour.materials',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_tour_id': self.id,
                'default_materials_html': f'<table class="table">{body}</table>',
            },
        }

    # ------------------------------------------------------------------
    # Goods-issue hook: load-out validation fills the van
    # ------------------------------------------------------------------

    def _dsd_on_load_validated(self):
        """Called from stock.picking.button_validate when the tour load-out
        picking is validated: mark the tour loaded and reserve the deliveries
        from the van."""
        for tour in self:
            tour.dsd_state = 'loaded'
            tour.picking_ids.mapped('move_ids')._action_assign()
            tour._log_dsd_status(_('Van loaded; deliveries reserved from van stock.'))
