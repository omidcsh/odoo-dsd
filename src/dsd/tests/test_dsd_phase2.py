import datetime as dt_mod
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


class DsdTourFixture(TransactionCase):
    """Self-sufficient fixtures for tour preparation tests."""

    def setUp(self):
        super().setUp()
        self.warehouse = self.env['stock.warehouse'].search([], limit=1)
        self.plan_type = self.env['dsd.visit.plan.type'].create({
            'name': 'FT Delivery', 'code': 'FT-DEL2',
            'role': 'delivery', 'relevant_doc': 'tour', 'make_delivery': True})
        self.route = self.env['dsd.route'].create({
            'name': 'Tour Route', 'code': 'FT-TR',
            'warehouse_id': self.warehouse.id})
        self.driver = self.env['hr.employee'].create({
            'name': 'Tour Driver', 'dsd_active_driver': True})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'TB'})
        self.category = self.env['fleet.vehicle.model.category'].create({
            'name': 'Tour Cat'})
        self.van = self.env['fleet.vehicle'].create({
            'model_id': self.env['fleet.vehicle.model'].create({
                'name': 'Tour Van', 'brand_id': brand.id}).id,
            'category_id': self.category.id,
            'license_plate': 'TOUR-VAN',
            'dsd_vehicle_type': 'van'})
        self.customer = self.env['res.partner'].create({
            'name': 'Tour Customer', 'dsd_route_id': self.route.id})
        self.customer2 = self.env['res.partner'].create({
            'name': 'Tour Customer 2', 'dsd_route_id': self.route.id})
        self.product = self.env['product.product'].create({
            'name': 'Tour Product', 'type': 'consu', 'is_storable': True,
            'weight': 10.0, 'volume': 0.5, 'list_price': 5.0})
        self.day = date.today() + timedelta(days=7)
        # generation falls back to route defaults when the visit list has none
        self.route.default_driver_id = self.driver
        self.route.default_vehicle_id = self.van

    def _make_sale_and_picking(self, partner, qty=10, day=None):
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'commitment_date': dt_mod.datetime.combine(
                day or self.day, dt_mod.time(8, 0)),
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': qty})],
        })
        order.action_confirm()
        return order.picking_ids

    def _make_visit_list(self, partners, **vals):
        driver = vals.pop('driver', self.driver)
        return self.env['dsd.visit.list'].create({
            'execution_date': self.day,
            'route_id': self.route.id,
            'plan_type_id': self.plan_type.id,
            'driver_id': driver.id if driver else False,
            'line_ids': [
                (0, 0, {'sequence': 10 * (i + 1), 'partner_id': partner.id})
                for i, partner in enumerate(partners)
            ],
            **vals,
        })


@tagged('post_install', '-at_install')
class TestDsdTourValidation(DsdTourFixture):

    def _tour(self, **vals):
        picking = self._make_sale_and_picking(self.customer)
        driver = vals.pop('driver', self.driver)
        vehicle = vals.pop('vehicle', self.van)
        return self.env['stock.picking.batch'].create({
            'name': 'FT TOUR',
            'dsd_route_id': self.route.id,
            'dsd_driver_id': driver.id if driver else False,
            'vehicle_id': vehicle.id if vehicle else False,
            'scheduled_date': dt_mod.datetime.combine(self.day, dt_mod.time(8, 0)),
            'picking_ids': [(6, 0, picking.ids)],
            **vals,
        })

    def test_confirm_requires_driver_vehicle(self):
        tour = self.env['stock.picking.batch'].create({'name': 'FT EMPTY'})
        with self.assertRaises(UserError):
            tour.action_dsd_confirm()

    def test_codriver_requires_driver(self):
        tour = self._tour(driver=False)
        tour.dsd_driver2_id = self.driver
        with self.assertRaises(UserError):
            tour._validate_tour()

    def test_license_mismatch_blocks(self):
        lic = self.env['dsd.license.category'].create({'name': 'Heavy', 'code': 'FT-H'})
        self.van.dsd_license_category_ids = [(6, 0, [lic.id])]
        tour = self._tour()
        with self.assertRaises(UserError):
            tour.action_dsd_confirm()

    def test_locked_driver_blocks(self):
        self.env['dsd.lock.period'].create({
            'employee_id': self.driver.id,
            'date_from': self.day, 'date_to': self.day, 'reason': 'off'})
        tour = self._tour()
        with self.assertRaises(UserError):
            tour.action_dsd_confirm()

    def test_trailer_checks(self):
        trailer = self.env['fleet.vehicle'].create({
            'model_id': self.env['fleet.vehicle.model'].create({
                'name': 'Tour Trailer', 'brand_id': self.env.ref(
                    'fleet.brand_alfa').id if False else self.env[
                    'fleet.vehicle.model.brand'].create({'name': 'TB2'}).id}).id,
            'license_plate': 'TOUR-TRL',
            'dsd_vehicle_type': 'trailer'})
        trailer.dsd_trailer_of_id = False
        tour = self._tour()
        tour.dsd_trailer_id = trailer
        tour._validate_tour()  # unattached trailer is fine
        other_van = self.van.copy({'license_plate': 'TOUR-VAN2'})
        trailer.dsd_trailer_of_id = other_van
        with self.assertRaises(UserError):
            tour._validate_tour()

    def test_confirm_ok_and_status(self):
        tour = self._tour()
        tour.action_dsd_confirm()
        self.assertEqual(tour.dsd_state, 'confirmed')
        self.assertFalse(tour._validate_tour(raise_error=False))


@tagged('post_install', '-at_install')
class TestDsdLoadOut(DsdTourFixture):

    def _loaded_tour(self):
        picking = self._make_sale_and_picking(self.customer, qty=10)
        tour = self.env['stock.picking.batch'].create({
            'name': 'FT LOAD',
            'dsd_route_id': self.route.id,
            'dsd_driver_id': self.driver.id,
            'vehicle_id': self.van.id,
            'scheduled_date': dt_mod.datetime.combine(self.day, dt_mod.time(8, 0)),
            'picking_ids': [(6, 0, picking.ids)],
        })
        tour.action_dsd_confirm()
        tour.action_dsd_load()
        return tour, picking

    def test_load_out_creates_aggregation(self):
        tour, customer_picking = self._loaded_tour()
        self.assertEqual(tour.dsd_state, 'loading')
        load = tour.dsd_load_picking_id
        self.assertTrue(load)
        self.assertEqual(load.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(load.location_dest_id, self.van.dsd_van_location_id)
        self.assertEqual(load.move_ids.product_id, self.product)
        self.assertEqual(sum(load.move_ids.mapped('product_uom_qty')), 10)
        self.assertEqual(customer_picking.location_id, self.van.dsd_van_location_id,
                         'delivery re-routed to van source')

    def test_load_picking_validation_marks_loaded(self):
        tour, customer_picking = self._loaded_tour()
        load = tour.dsd_load_picking_id
        # put stock in the warehouse so the load-out can be validated
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'quantity': 50})
        load.action_confirm()
        load.move_ids.write({'quantity': 50})
        load.button_validate()
        self.assertEqual(tour.dsd_state, 'loaded')
        self.assertEqual(customer_picking.state, 'assigned',
                         'delivery reserved from van after load validated')
        quant = self.env['stock.quant']._get_available_quantity(
            self.product, self.van.dsd_van_location_id)
        self.assertEqual(quant, 40,
                         '50 loaded minus 10 reserved for the delivery')

    def test_van_stock_isolated_from_warehouse_atp(self):
        # stock only on the van: warehouse deliveries must not reserve it
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.van.dsd_van_location_id.id,
            'quantity': 100})
        picking = self._make_sale_and_picking(self.customer2, qty=5)
        picking.action_confirm()
        self.assertEqual(picking.state, 'confirmed',
                         'van stock must not satisfy warehouse delivery')
        self.assertFalse(picking.move_ids.mapped('move_line_ids'))


@tagged('post_install', '-at_install')
class TestDsdSpeculativeLoad(DsdTourFixture):

    def test_speculative_load_creates_picking(self):
        visit_list = self._make_visit_list([self.customer])
        wizard = self.env['dsd.speculative.load'].create({
            'visit_list_id': visit_list.id,
            'van_id': self.van.id,
            'line_ids': [Command.create({
                'product_id': self.product.id, 'quantity': 20})],
        })
        result = wizard.action_create()
        picking = self.env['stock.picking'].browse(result['res_id'])
        self.assertEqual(picking.location_dest_id, self.van.dsd_van_location_id)
        self.assertEqual(visit_list.speculative_load_picking_id, picking)
        with self.assertRaises(UserError):
            wizard.action_create()  # second speculative load refused


@tagged('post_install', '-at_install')
class TestDsdTourGeneration(DsdTourFixture):

    def _delivery_and_list(self, partner=None, qty=10):
        partner = partner or self.customer
        picking = self._make_sale_and_picking(partner, qty=qty)
        visit_list = self._make_visit_list([partner])
        return picking, visit_list

    def test_generation_builds_tour_in_stop_order(self):
        picking1, visit_list = self._delivery_and_list(self.customer)
        picking2 = self._make_sale_and_picking(self.customer2, qty=5)
        visit_list.line_ids = [Command.create({
            'sequence': 20, 'partner_id': self.customer2.id})]
        wizard = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day})
        wizard.action_generate()
        tours = self.env['stock.picking.batch'].search(
            [('dsd_route_id', '=', self.route.id)])
        self.assertEqual(len(tours), 1)
        tour = tours
        self.assertEqual(tour.dsd_state, 'draft')
        self.assertEqual(tour.dsd_visit_list_id, visit_list)
        self.assertEqual(set(tour.picking_ids.ids), {picking1.id, picking2.id})
        self.assertEqual(visit_list.tour_id, tour)
        self.assertGreaterEqual(len(tour.message_ids), 1, 'generation log on chatter')

    def test_generation_respects_stop_limit(self):
        self.route.write({'cap_stops': True, 'max_stops': 1})
        picking1, visit_list = self._delivery_and_list(self.customer)
        picking2 = self._make_sale_and_picking(self.customer2, qty=5)
        visit_list.line_ids = [Command.create({
            'sequence': 20, 'partner_id': self.customer2.id})]
        wizard = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day})
        wizard.action_generate()
        tours = self.env['stock.picking.batch'].search(
            [('dsd_route_id', '=', self.route.id)])
        self.assertEqual(len(tours), 1)
        self.assertEqual(len(tours.picking_ids), 1)
        self.assertIn('stop limit', wizard.result_html)

    def test_generation_weight_limit_with_attempts(self):
        self.route.write({'cap_weight': True, 'max_load_attempts': 1})
        self.category.weight_capacity = 150  # product 10kg → 15 cases max
        heavy = self._make_sale_and_picking(self.customer, qty=20)  # 200 kg
        light_partner = self.customer2
        visit_list = self._make_visit_list([self.customer, light_partner])
        light = self._make_sale_and_picking(light_partner, qty=2)  # 20 kg
        wizard = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day})
        wizard.action_generate()
        tours = self.env['stock.picking.batch'].search(
            [('dsd_route_id', '=', self.route.id)])
        self.assertEqual(len(tours), 1)
        self.assertEqual(tours.picking_ids, light,
                         'heavy delivery skipped, light next stop loaded')
        self.assertIn('weight limit', wizard.result_html)
        self.assertIn('unplanned', wizard.result_html)

    def test_generation_include_new_customers(self):
        picking = self._make_sale_and_picking(self.customer, qty=10)
        wizard = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day,
            'include_new_customers': True})
        wizard.action_generate()
        tours = self.env['stock.picking.batch'].search(
            [('dsd_route_id', '=', self.route.id)])
        self.assertEqual(len(tours), 1)
        self.assertEqual(tours.picking_ids, picking)
        self.assertFalse(tours.dsd_visit_list_id)
        self.assertEqual(tours.dsd_driver_id, self.driver or self.route.default_driver_id)

    def test_no_double_generation(self):
        picking, visit_list = self._delivery_and_list(self.customer)
        wizard = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day})
        wizard.action_generate()
        wizard2 = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day})
        wizard2.action_generate()
        self.assertEqual(self.env['stock.picking.batch'].search_count(
            [('dsd_route_id', '=', self.route.id)]), 1)

    def test_list_lock_on_tour(self):
        picking, visit_list = self._delivery_and_list(self.customer)
        wizard = self.env['dsd.tour.generate'].create({
            'date_from': self.day, 'date_to': self.day})
        wizard.action_generate()
        with self.assertRaises(Exception):
            visit_list.execution_date = self.day + timedelta(days=3)
