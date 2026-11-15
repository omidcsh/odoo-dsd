from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MONDAY = date(2026, 11, 16)


@tagged('post_install', '-at_install')
class TestDsdVanSale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.RouteDay = cls.env['dsd.route.day']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.van_location = cls.env['stock.location'].search(
            [('is_dsd_van', '=', True)], limit=1)
        cls.journal = cls.env['account.journal'].create({
            'name': 'DSD Route Cash', 'type': 'cash', 'code': 'DSDC',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'DSD Van Sale Bottle',
            'type': 'consu',
            'list_price': 12.0,
        })
        cls.partner = cls.env['res.partner'].search([], limit=1)
        cls.route = cls.env['dsd.route'].create({
            'name': 'Van Sale Test Route',
            'mode': 'van_sales',
            'warehouse_id': cls.warehouse.id,
            'van_location_id': cls.van_location.id,
            'cash_journal_id': cls.journal.id,
            'stop_ids': [(0, 0, {
                'partner_id': cls.partner.id,
                'sequence': 1,
                'monday': True,
            })],
        })
        wizard = cls.env['dsd.route.day.generate.wizard'].create({
            'route_id': cls.route.id, 'date': MONDAY,
        })
        cls.day = cls.RouteDay.browse(wizard.action_generate()['res_id'])
        cls.day.action_load_van()  # stock not needed for consu products, but the load must be a real transfer
        load = cls.day.load_picking_id
        cls.env['stock.move'].create({
            'product_id': cls.product.id,
            'product_uom_qty': 4,
            'picking_id': load.id,
            'location_id': load.location_id.id,
            'location_dest_id': load.location_dest_id.id,
        })
        load.action_confirm()
        load.move_ids.quantity = 4
        load.button_validate()
        cls.day.action_start_route()
        cls.visit = cls.day.visit_ids

    def test_full_van_sale(self):
        # Take the order
        result = self.visit.action_start_van_sale()
        order = self.env['sale.order'].browse(result['res_id'])
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(self.visit.sale_kind, 'van_sale')
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 2,
            'price_unit': 12.0,
        })

        # Confirming retargets the delivery to the van location
        order.action_confirm()
        self.assertEqual(self.visit.delivery_id.location_id, self.van_location)
        self.assertEqual(self.visit.delivery_id.partner_id, self.partner)

        # One click: ship, invoice, cash
        self.visit.action_complete_van_sale()
        self.assertEqual(self.visit.state, 'done')
        invoice = self.visit.invoice_id
        self.assertEqual(invoice.move_type, 'out_invoice')
        self.assertEqual(invoice.state, 'posted')
        self.assertAlmostEqual(invoice.amount_total, order.amount_total)
        self.assertAlmostEqual(invoice.amount_untaxed, 24.0)
        payment = self.visit.payment_ids
        self.assertEqual(len(payment), 1)
        self.assertIn(payment.state, ('posted', 'reconciled'))
        self.assertEqual(payment.journal_id, self.journal)
        self.assertAlmostEqual(invoice.amount_residual, 0.0)

    def test_presale_ships_from_warehouse(self):
        presale_route = self.env['dsd.route'].create({
            'name': 'Presale Test Route',
            'mode': 'presale',
            'warehouse_id': self.warehouse.id,
            'stop_ids': [(0, 0, {
                'partner_id': self.partner.id,
                'sequence': 1,
                'monday': True,
            })],
        })
        wizard = self.env['dsd.route.day.generate.wizard'].create({
            'route_id': presale_route.id, 'date': MONDAY,
        })
        presale_day = self.RouteDay.browse(wizard.action_generate()['res_id'])
        visit = presale_day.visit_ids
        result = visit.action_create_presale()
        order = self.env['sale.order'].browse(result['res_id'])
        self.assertEqual(visit.sale_kind, 'presale')
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 5,
        })
        order.action_confirm()
        delivery = visit.delivery_id
        self.assertEqual(delivery.location_id, self.warehouse.lot_stock_id,
                         'Presale orders must be fulfilled from the warehouse')
        self.assertEqual(visit.state, 'done',
                         'Presale visit completes on order capture')

    def test_complete_requires_confirmed_order(self):
        self.visit.action_start_van_sale()
        with self.assertRaises(UserError):
            self.visit.action_complete_van_sale()

    def test_van_sale_refused_on_presale_route(self):
        self.route.mode = 'presale'
        with self.assertRaises(UserError):
            self.visit.action_start_van_sale()
