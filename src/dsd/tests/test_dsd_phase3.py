import datetime as dt_mod
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


class DsdExecutionFixture(TransactionCase):

    def setUp(self):
        super().setUp()
        self.warehouse = self.env['stock.warehouse'].search([], limit=1)
        self.route = self.env['dsd.route'].create({
            'name': 'Exec Route', 'code': 'FT-EX',
            'warehouse_id': self.warehouse.id})
        self.driver = self.env['hr.employee'].create({
            'name': 'Exec Driver', 'dsd_active_driver': True})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'EXB'})
        self.van = self.env['fleet.vehicle'].create({
            'model_id': self.env['fleet.vehicle.model'].create({
                'name': 'Exec Van', 'brand_id': brand.id}).id,
            'license_plate': 'EXEC-VAN',
            'dsd_vehicle_type': 'van'})
        self.route.default_driver_id = self.driver
        self.route.default_vehicle_id = self.van
        self.customer = self.env['res.partner'].create({
            'name': 'Exec Customer', 'dsd_route_id': self.route.id})
        self.product = self.env['product.product'].create({
            'name': 'Exec Product', 'type': 'consu', 'is_storable': True,
            'weight': 5.0, 'list_price': 3.0})
        self.day = date.today() + timedelta(days=5)

    def _loaded_tour(self, qty=10):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'commitment_date': dt_mod.datetime.combine(self.day, dt_mod.time(8, 0)),
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': qty})],
        })
        order.action_confirm()
        picking = order.picking_ids
        picking.action_confirm()
        tour = self.env['stock.picking.batch'].create({
            'name': 'EX TOUR',
            'dsd_route_id': self.route.id,
            'dsd_driver_id': self.driver.id,
            'vehicle_id': self.van.id,
            'scheduled_date': dt_mod.datetime.combine(self.day, dt_mod.time(8, 0)),
            'picking_ids': [(6, 0, picking.ids)],
        })
        tour.action_dsd_confirm()
        tour.action_dsd_load()
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'quantity': 100})
        return tour, picking

    def _van_quantity(self):
        quants = self.env['stock.quant'].search([
            ('location_id', 'child_of', self.van.dsd_van_location_id.id),
            ('product_id', '=', self.product.id)])
        return sum(quants.mapped('quantity'))

    def _make_lc(self, tour, counted=10):
        lc = self.env['dsd.loading.confirmation'].create({
            'tour_id': tour.id, 'counting_scope': 'product'})
        lc.line_ids.counted_qty = counted
        return lc

    def _count_and_seal(self, tour, counted=10):
        lc = self._make_lc(tour, counted)
        if counted != 10:
            lc.line_ids.reason_id = self.env.ref('dsd.reason_co_load_short')
        lc.action_complete()
        return lc


@tagged('post_install', '-at_install')
class TestDsdLoadingConfirmation(DsdExecutionFixture):

    def test_targets_from_load_out(self):
        tour, _picking = self._loaded_tour(qty=10)
        lc = self._make_lc(tour)
        self.assertEqual(lc.line_ids.product_id, self.product)
        self.assertEqual(lc.line_ids.target_qty, 10)

    def test_complete_adjusts_and_seals_tour(self):
        tour, _picking = self._loaded_tour(qty=10)
        lc = self._count_and_seal(tour, counted=8)
        self.assertEqual(lc.state, 'done')
        self.assertEqual(tour.dsd_state, 'loaded')
        self.assertEqual(tour.dsd_load_picking_id.state, 'done')
        self.assertEqual(self._van_quantity(), 8,
                         'van holds the counted quantity (8 loaded, '
                         '8 reserved for the delivery)')

    def test_difference_requires_reason(self):
        tour, _picking = self._loaded_tour(qty=10)
        lc = self._make_lc(tour, counted=7)
        with self.assertRaises(UserError):
            lc.action_complete()

    def test_counting_group_scope_and_itemize(self):
        group = self.env['dsd.counting.group'].create({
            'name': 'Exec Group', 'code': 'EX-G'})
        self.env['dsd.counting.group.uom'].create({
            'counting_group_id': group.id, 'sequence': 10,
            'uom_id': self.env.ref('uom.product_uom_unit').id})
        self.product.counting_group_id = group.id
        tour, _picking = self._loaded_tour(qty=10)
        lc = self.env['dsd.loading.confirmation'].create({
            'tour_id': tour.id, 'counting_scope': 'counting_group'})
        self.assertEqual(len(lc.line_ids), 1)
        self.assertEqual(lc.line_ids.counting_group_id, group)
        self.assertEqual(lc.line_ids.target_qty, 10)
        lc.line_ids.counted_qty = 9  # group-level difference
        with self.assertRaises(UserError):
            lc.action_complete()
        lc.action_itemize()
        self.assertFalse(lc.line_ids.mapped('counting_group_id'))
        self.assertEqual(sum(lc.line_ids.mapped('target_qty')), 10)
        lc.line_ids.counted_qty = 9
        lc.line_ids.reason_id = self.env.ref('dsd.reason_co_load_short')
        lc.action_complete()
        self.assertEqual(tour.dsd_state, 'loaded')
        self.assertEqual(self._van_quantity(), 9)


@tagged('post_install', '-at_install')
class TestDsdCheckOutIn(DsdExecutionFixture):

    def _checked_out_tour(self):
        tour, _picking = self._loaded_tour(qty=10)
        self._count_and_seal(tour, counted=10)
        check = self.env['dsd.check.record'].create({
            'tour_id': tour.id, 'check_type': 'out'})
        self.assertEqual(len(check.material_line_ids), 1)
        self.assertEqual(check.material_line_ids.planned_qty, 10)
        return tour, check

    def test_full_loop(self):
        tour, check = self._checked_out_tour()
        tour.dsd_odometer_start = 12000.0
        tour.dsd_odometer_end = 12150.0
        check.material_line_ids.counted_qty = 10
        check.action_confirm()
        self.assertEqual(tour.dsd_state, 'checked_out')
        self.assertEqual(check.state, 'confirmed')
        odometers = self.env['fleet.vehicle.odometer'].search(
            [('vehicle_id', '=', tour.vehicle_id.id)])
        self.assertEqual(len(odometers), 1, 'start-of-day odometer recorded')
        tour.action_dsd_start()
        self.assertEqual(tour.dsd_state, 'in_progress')
        # check-in
        check_in = self.env['dsd.check.record'].create({
            'tour_id': tour.id, 'check_type': 'in'})
        self.assertEqual(check_in.material_line_ids.planned_qty, 10)
        check_in.material_line_ids.counted_qty = 10
        check_in.action_confirm()
        self.assertEqual(tour.dsd_state, 'checked_in')
        self.assertTrue(tour.dsd_unload_picking_id)
        self.assertEqual(tour.dsd_unload_picking_id.state, 'done')
        self.assertEqual(self._van_quantity(), 0, 'van emptied at check-in')
        wh_quant = self.env['stock.quant'].search([
            ('location_id', '=', self.warehouse.lot_stock_id.id),
            ('product_id', '=', self.product.id)])
        self.assertEqual(sum(wh_quant.mapped('quantity')), 100,
                         'remaining stock returned to warehouse')
        statuses = tour.message_ids.mapped('body')
        self.assertTrue(any('Tour status:' in body for body in statuses),
                        'status timeline logged on chatter')

    def test_difference_requires_supervisor(self):
        tour, check = self._checked_out_tour()
        check.material_line_ids.counted_qty = 9
        check.material_line_ids.reason_id = self.env.ref('dsd.reason_co_load_short')
        with self.assertRaises(UserError):
            check.action_confirm()

    def test_checkout_out_of_order_blocked(self):
        tour, _picking = self._loaded_tour(qty=10)
        # tour is still 'loading'; LC not completed
        check = self.env['dsd.check.record'].create({
            'tour_id': tour.id, 'check_type': 'out'})
        check.material_line_ids.counted_qty = 0
        with self.assertRaises(UserError):
            check.action_confirm()

    def test_duplicate_check_type_blocked(self):
        tour, check = self._checked_out_tour()
        with self.assertRaises(Exception):
            self.env['dsd.check.record'].create({
                'tour_id': tour.id, 'check_type': 'out'})


@tagged('post_install', '-at_install')
class TestDsdReload(DsdExecutionFixture):

    def test_reload_and_unload_lines(self):
        tour, _picking = self._loaded_tour(qty=10)
        self._count_and_seal(tour, counted=10)
        check = self.env['dsd.check.record'].create({
            'tour_id': tour.id, 'check_type': 'out'})
        check.material_line_ids.counted_qty = 10
        check.action_confirm()
        tour.action_dsd_start()
        wizard = self.env['dsd.reload'].create({
            'tour_id': tour.id,
            'line_ids': [
                Command.create({'product_id': self.product.id, 'quantity': 5}),
                Command.create({'product_id': self.product.id, 'quantity': -3}),
            ]})
        result = wizard.action_apply()
        pickings = self.env['stock.picking'].browse(result['domain'][0][2])
        self.assertEqual(len(pickings), 2)
        wh_to_van = pickings.filtered(
            lambda p: p.location_dest_id == self.van.dsd_van_location_id)
        van_to_wh = pickings.filtered(
            lambda p: p.location_id == self.van.dsd_van_location_id)
        self.assertEqual(len(wh_to_van), 1)
        self.assertEqual(len(van_to_wh), 1)
        self.assertIn(wh_to_van.id, tour.dsd_reload_picking_ids.ids)
        # validate both and verify van stock: 10 + 5 - 3 = 12
        for picking in pickings:
            picking.action_confirm()
            picking.move_ids.write({'quantity': picking.move_ids.product_uom_qty})
            picking.with_context(skip_cancel_backorder=True).button_validate()
        self.assertEqual(self._van_quantity(), 12)
