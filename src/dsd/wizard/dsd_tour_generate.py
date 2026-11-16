import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DsdTourGenerate(models.TransientModel):
    """Dynamic transportation planning (SAP /DSD/RP_DYNDISP): group due
    deliveries into tours per route and date, following the visit-list stop
    order and the activated capacity limits in SAP's checking order
    (weight → volume → stops → variable capacity → duration → loading units),
    with skip-ahead load attempts and remainder handling."""
    _name = 'dsd.tour.generate'
    _description = 'Generate Tours'

    date_from = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self))
    date_to = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self))
    route_ids = fields.Many2many(
        'dsd.route', string='Routes',
        help='Empty = every route with due deliveries.')
    include_new_customers = fields.Boolean(
        string='Include Customers Without Visit List',
        help='Also group deliveries of route customers that no visit list covers.')
    state = fields.Selection([('form', 'Form'), ('done', 'Done')], default='form')
    result_html = fields.Html(sanitize=False)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(self.env._(
                    'The generation start date must be before its end date.'))

    # ------------------------------------------------------------------
    # Candidate selection
    # ------------------------------------------------------------------

    def _candidate_pickings(self, routes):
        domain = [
            ('picking_type_code', '=', 'outgoing'),
            ('state', 'in', ('confirmed', 'waiting', 'assigned')),
            ('batch_id', '=', False),
            ('dsd_route_id', '!=', False),
            ('scheduled_date', '>=', f'{self.date_from} 00:00:00'),
            ('scheduled_date', '<=', f'{self.date_to} 23:59:59'),
        ]
        if routes:
            domain.append(('dsd_route_id', 'in', routes.ids))
        return self.env['stock.picking'].search(domain)

    def _candidate_lists(self, route, day):
        return self.env['dsd.visit.list'].search([
            ('route_id', '=', route.id),
            ('execution_date', '=', day),
            ('state', 'in', ('draft', 'confirmed')),
            ('inactive', '=', False),
            ('tour_id', '=', False),
            ('plan_type_id.relevant_doc', 'in', ('tour', 'both')),
        ], order='plan_type_id, id')

    # ------------------------------------------------------------------
    # Capacity evaluation (SAP fixed order)
    # ------------------------------------------------------------------

    def _move_load(self, picking):
        """(weight, volume, loading units) contributed by one picking; units
        count only products convertible into the route loading unit."""
        route = picking.dsd_route_id
        lu_uom = route.lu_uom_id if route.cap_loading_units else False
        weight = volume = lu = 0.0
        for move in picking.move_ids.filtered(lambda m: m.state != 'cancel'):
            qty = move.uom_id._compute_quantity(
                move.product_uom_qty, move.product_id.uom_id)
            weight += move.product_id.weight * qty
            volume += move.product_id.volume * qty
            if lu_uom and move.product_id.uom_id._has_common_reference(lu_uom):
                lu += move.product_id.uom_id._compute_quantity(qty, lu_uom)
        return weight, volume, lu

    def _stop_minutes(self, visit_list, partner_id):
        if not visit_list:
            return 0.0
        line = visit_list.line_ids.filtered(
            lambda ln: ln.partner_id.id == partner_id)
        return (line.waiting_minutes + line.travel_minutes) if line else 0.0

    def _capacity_ok(self, tour_vals, picking, route, vehicle, visit_list):
        """Would adding `picking` exceed any activated capacity limit?
        Returns (ok, reason). Checks in SAP's fixed order:
        weight → volume → stops → variable capacity (via loading units) →
        duration → loading units."""
        weight, volume, lu = self._move_load(picking)
        category = vehicle.category_id
        new_stops = len(tour_vals['partners'] | {picking.partner_id.id})
        duration = tour_vals['duration'] + self._stop_minutes(
            visit_list, picking.partner_id.id)
        lu_capacity = (category.dsd_loading_units or 0.0) + \
            (vehicle.variable_capacity or 0.0)
        if route.cap_weight and category.weight_capacity \
                and tour_vals['weight'] + weight > category.weight_capacity:
            return False, self.env._('weight limit (%s)', category.weight_capacity)
        if route.cap_volume and category.volume_capacity \
                and tour_vals['volume'] + volume > category.volume_capacity:
            return False, self.env._('volume limit (%s)', category.volume_capacity)
        if route.cap_stops and route.max_stops and new_stops > route.max_stops:
            return False, self.env._('stop limit (%s stops)', route.max_stops)
        if route.cap_duration and route.max_duration_hours \
                and duration > route.max_duration_hours * 60:
            return False, self.env._('duration limit (%s h)', route.max_duration_hours)
        if route.cap_loading_units and lu_capacity \
                and tour_vals['lu'] + lu > lu_capacity:
            return False, self.env._('loading-unit limit (%s)', lu_capacity)
        return True, ''

    # ------------------------------------------------------------------
    # Tour assembly
    # ------------------------------------------------------------------

    def _new_tour_vals(self, visit_list, route, driver, vehicle, trailer, day):
        return {
            'visit_list_id': visit_list.id if visit_list else False,
            'route_id': route.id,
            'driver_id': driver.id if driver else False,
            'vehicle_id': vehicle.id if vehicle else False,
            'trailer_id': trailer.id if trailer else False,
            'scheduled_date': fields.Datetime.to_datetime(day),
            'pickings': self.env['stock.picking'].browse(),
            'partners': set(),
            'weight': 0.0,
            'volume': 0.0,
            'lu': 0.0,
            'duration': 0.0,
        }

    def _add_to_tour(self, tour_vals, picking, visit_list):
        weight, volume, lu = self._move_load(picking)
        tour_vals['pickings'] |= picking
        tour_vals['partners'].add(picking.partner_id.id)
        tour_vals['weight'] += weight
        tour_vals['volume'] += volume
        tour_vals['lu'] += lu
        tour_vals['duration'] += self._stop_minutes(
            visit_list, picking.partner_id.id)

    def _create_tour(self, tour_vals):
        tour = self.env['stock.picking.batch'].sudo().create({
            'name': self.env._('TOUR %(route)s %(day)s',
                               route=self.env['dsd.route']
                               .browse(tour_vals['route_id']).code,
                               day=tour_vals['scheduled_date'].date()),
            'dsd_route_id': tour_vals['route_id'],
            'dsd_visit_list_id': tour_vals['visit_list_id'],
            'dsd_driver_id': tour_vals['driver_id'],
            'vehicle_id': tour_vals['vehicle_id'],
            'dsd_trailer_id': tour_vals['trailer_id'],
            'scheduled_date': tour_vals['scheduled_date'],
        })
        tour_vals['pickings'].write({'batch_id': tour.id})
        tour.message_post(body=self.env._(
            'Tour generated: %s delivery(ies), %s stop(s).',
            len(tour_vals['pickings']), len(tour_vals['partners'])))
        return tour

    # ------------------------------------------------------------------
    # Main generation
    # ------------------------------------------------------------------

    def action_generate(self):
        self.ensure_one()
        routes = self.route_ids or self.env['dsd.route'].search([('active', '=', True)])
        candidates = self._candidate_pickings(routes)
        by_route_day = {}
        for picking in candidates:
            day = picking.scheduled_date.date() if picking.scheduled_date else \
                fields.Date.context_today(self)
            key = (picking.dsd_route_id.id, day)
            by_route_day.setdefault(key, self.env['stock.picking'].browse())
            by_route_day[key] |= picking
        log_rows = []
        created_tours = self.env['stock.picking.batch'].browse()
        for (route_id, day), pickings in sorted(
                by_route_day.items(), key=lambda item: (item[0][0], item[0][1])):
            route = self.env['dsd.route'].browse(route_id)
            tours, rows = self._generate_route_day(route, day, pickings)
            created_tours |= tours
            log_rows.extend(rows)
        self.write({
            'state': 'done',
            'result_html': self._render_result(log_rows, created_tours),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_created(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Generated Tours'),
            'res_model': 'stock.picking.batch',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'in', self.env['stock.picking.batch']
                        .search([('dsd_state', '!=', 'settled')]).ids)],
        }

    def _generate_route_day(self, route, day, pickings):
        """One route+date. Each candidate visit list yields its own tour built
        from its covered partners in stop order; deliveries for partners
        without visit-list coverage follow the include-new-customers option;
        the rest is logged as unplanned (SAP remainder distribution to a
        further shipment is a later refinement)."""
        rows = []
        tours_created = []
        assigned = set()
        by_partner = {}
        for picking in pickings:
            by_partner.setdefault(picking.partner_id.id,
                                  self.env['stock.picking'].browse())
            by_partner[picking.partner_id.id] |= picking

        for visit_list in self._candidate_lists(route, day):
            driver = visit_list.driver_id or route.default_driver_id
            vehicle = visit_list.vehicle_id or route.default_vehicle_id
            trailer = visit_list.trailer_id or route.default_trailer_id
            if not vehicle:
                rows.append((route, day, visit_list, 'skipped',
                             self.env._('no vehicle available')))
                continue
            tour_vals = self._new_tour_vals(
                visit_list, route, driver, vehicle, trailer, day)
            attempt = 0
            for line in visit_list.line_ids.sorted('sequence'):
                partner_pickings = by_partner.get(line.partner_id.id)
                if not partner_pickings:
                    continue
                for picking in partner_pickings:
                    if picking.id in assigned:
                        continue
                    ok, reason = self._capacity_ok(
                        tour_vals, picking, route, vehicle, visit_list)
                    if ok:
                        self._add_to_tour(tour_vals, picking, visit_list)
                        assigned.add(picking.id)
                    else:
                        attempt += 1
                        rows.append((route, day, visit_list, 'capacity_skip',
                                     self.env._('%s: %s', picking.name, reason)))
                        if attempt >= route.max_load_attempts:
                            break
            if tour_vals['pickings']:
                tour = self._create_tour(tour_vals)
                tours_created.append(tour)
                visit_list.with_context(
                    dsd_allow_locked_list_edit=True).tour_id = tour
                rows.append((route, day, visit_list, 'created', tour.name))
            else:
                rows.append((route, day, visit_list, 'skipped',
                             self.env._('no deliverable stops')))

        # deliveries for partners without visit-list coverage
        uncovered = pickings.filtered(lambda p: p.id not in assigned)
        if uncovered and self.include_new_customers:
            if route.single_daily_tour and tours_created:
                main = tours_created[0]
                uncovered.write({'batch_id': main})
                assigned.update(uncovered.ids)
                main.message_post(body=self.env._(
                    '%s picking(s) appended (no visit-list coverage).',
                    len(uncovered)))
                rows.append((route, day, False, 'appended',
                             self.env._('%s pickings appended to %s',
                                        len(uncovered), main.name)))
            else:
                tour_vals = self._new_tour_vals(
                    False, route, route.default_driver_id,
                    route.default_vehicle_id, route.default_trailer_id, day)
                for picking in uncovered:
                    self._add_to_tour(tour_vals, picking, False)
                assigned.update(uncovered.ids)
                tour = self._create_tour(tour_vals)
                tours_created.append(tour)
                rows.append((route, day, False, 'created_new_customers', tour.name))
        for picking in pickings.filtered(lambda p: p.id not in assigned):
            rows.append((route, day, False, 'unplanned',
                         self.env._('%s (%s): no capacity or no visit list',
                                    picking.name, picking.partner_id.display_name)))
        return self.env['stock.picking.batch'].browse(
            [t.id for t in tours_created]), rows

    def _render_result(self, log_rows, created_tours):
        prefix = f'Created {len(created_tours)} tour(s).'
        if not log_rows:
            return f'<p>{prefix} No due deliveries in the selected range.</p>'
        label = {
            'created': '✔',
            'created_new_customers': '✔ (new customers)',
            'appended': '↳ appended',
            'capacity_skip': '⚠ capacity',
            'skipped': '✗ skipped',
            'unplanned': '✗ unplanned',
        }
        rows = []
        for route, day, visit_list, status, detail in log_rows:
            rows.append(
                f'<li>{route.code} {day} '
                f'{visit_list.name + ":" if visit_list else ":"} '
                f'{label.get(status, status)} {detail}</li>')
        return f'<p><b>{prefix}</b></p><ul>{"".join(rows)}</ul>'
