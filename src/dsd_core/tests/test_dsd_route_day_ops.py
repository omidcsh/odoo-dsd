from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MONDAY = date(2026, 11, 16)


@tagged('post_install', '-at_install')
class TestDsdRouteDayOps(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.RouteDay = cls.env['dsd.route.day']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.van_location = cls.env['stock.location'].search(
            [('is_dsd_van', '=', True)], limit=1)
        cls.product = cls.env['product.product'].create({
            'name': 'DSD Test Case of Soda',
            'type': 'consu',
            'list_price': 10.0,
        })
        cls.partner = cls.env['res.partner'].search([], limit=1)
        cls.route = cls.env['dsd.route'].create({
            'name': 'Ops Test Route',
            'mode': 'mixed',
            'warehouse_id': cls.warehouse.id,
            'van_location_id': cls.van_location.id,
            'stop_ids': [(0, 0, {
                'partner_id': cls.partner.id,
                'sequence': 1,
                'monday': True,
            })],
        })
        wizard = cls.env['dsd.route.day.generate.wizard'].create({
            'route_id': cls.route.id, 'date': MONDAY,
        })
        result = wizard.action_generate()
        cls.day = cls.RouteDay.browse(result['res_id'])
        cls.visit = cls.day.visit_ids

    def _validate(self, picking, qty=2):
        self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom_qty': qty,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })
        picking.action_confirm()
        picking.move_ids.quantity = qty
        picking.button_validate()

    def test_full_day_lifecycle(self):
        self.assertEqual(self.day.state, 'draft')

        # Load van: internal transfer warehouse → van, validation syncs state
        self.day.action_load_van()
        load = self.day.load_picking_id
        self.assertEqual(load.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(load.location_dest_id, self.van_location)
        self._validate(load)
        self.assertEqual(self.day.state, 'loaded')

        # Start route
        self.day.action_start_route()
        self.assertEqual(self.day.state, 'in_progress')

        # Deliver to the store: outgoing picking van → customer
        self.visit.action_deliver()
        delivery = self.visit.delivery_id
        self.assertEqual(delivery.location_id, self.van_location)
        self.assertEqual(delivery.partner_id, self.partner)
        self._validate(delivery)
        self.assertEqual(self.visit.state, 'done')

        # End route: all visits closed
        self.day.action_end_route()
        self.assertEqual(self.day.state, 'done')

        # Return unsold stock to warehouse; settlement then closes the day
        self.day.action_create_stock_return()
        stock_return = self.day.return_picking_id
        self.assertEqual(stock_return.location_id, self.van_location)
        self.assertEqual(
            stock_return.location_dest_id, self.warehouse.lot_stock_id)
        self._validate(stock_return)
        self.assertEqual(self.day.state, 'done',
                         'Return alone must not settle the day')

        settle_result = self.day.action_settle()
        settlement = self.env['dsd.settlement'].browse(settle_result['res_id'])
        settlement.counted_cash = settlement.expected_cash
        settlement.action_post_settlement()
        self.assertEqual(self.day.state, 'settled')

    def test_start_route_requires_validated_load(self):
        self.day.action_load_van()
        with self.assertRaises(UserError):
            self.day.action_start_route()

    def test_end_route_requires_no_pending_visits(self):
        self.day.action_load_van()
        self._validate(self.day.load_picking_id)
        self.day.action_start_route()
        self.visit.action_deliver()
        with self.assertRaises(UserError):
            self.day.action_end_route()

    def test_load_only_once(self):
        self.day.action_load_van()
        first = self.day.load_picking_id
        self.day.action_load_van()  # reopening the same load picking
        self.assertEqual(self.day.load_picking_id, first)
