from datetime import date

from odoo.tests import TransactionCase, tagged

MONDAY = date(2026, 11, 16)


@tagged('post_install', '-at_install')
class TestDsdSettlement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.RouteDay = cls.env['dsd.route.day']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.van_location = cls.env['stock.location'].search(
            [('is_dsd_van', '=', True)], limit=1)
        cls.company = cls.warehouse.company_id
        cls.journal = cls.env['account.journal'].create({
            'name': 'Settle Cash', 'type': 'cash', 'code': 'STLC',
            'company_id': cls.company.id,
        })
        cls.variance_account = cls.env['account.account'].create({
            'name': 'DSD Cash Variance', 'code': 'DSDVAR',
            'account_type': 'expense',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Settlement Case', 'type': 'consu', 'list_price': 10.0,
        })
        cls.partner = cls.env['res.partner'].search([], limit=1)
        cls.route = cls.env['dsd.route'].create({
            'name': 'Settlement Route',
            'mode': 'van_sales',
            'warehouse_id': cls.warehouse.id,
            'van_location_id': cls.van_location.id,
            'cash_journal_id': cls.journal.id,
            'variance_account_id': cls.variance_account.id,
            'stop_ids': [(0, 0, {
                'partner_id': cls.partner.id,
                'sequence': 1, 'monday': True,
            })],
        })
        wizard = cls.env['dsd.route.day.generate.wizard'].create({
            'route_id': cls.route.id, 'date': MONDAY,
        })
        cls.day = cls.RouteDay.browse(wizard.action_generate()['res_id'])
        cls.visit = cls.day.visit_ids

        # Complete day setup: load van and run a van sale of 2 × 10
        cls.day.action_load_van()
        load = cls.day.load_picking_id
        cls.env['stock.move'].create({
            'product_id': cls.product.id, 'product_uom_qty': 4,
            'picking_id': load.id,
            'location_id': load.location_id.id,
            'location_dest_id': load.location_dest_id.id,
        })
        load.action_confirm()
        load.move_ids.quantity = 4
        load.button_validate()
        cls.day.action_start_route()
        result = cls.visit.action_start_van_sale()
        order = cls.env['sale.order'].browse(result['res_id'])
        cls.env['sale.order.line'].create({
            'order_id': order.id, 'product_id': cls.product.id,
            'product_uom_qty': 2, 'price_unit': 10.0,
        })
        order.action_confirm()
        cls.visit.action_complete_van_sale()
        cls.day.action_end_route()
        cls.day.action_create_stock_return()
        stock_return = cls.day.return_picking_id
        cls.env['stock.move'].create({
            'product_id': cls.product.id, 'product_uom_qty': 2,
            'picking_id': stock_return.id,
            'location_id': stock_return.location_id.id,
            'location_dest_id': stock_return.location_dest_id.id,
        })
        stock_return.action_confirm()
        stock_return.move_ids.quantity = 2
        stock_return.button_validate()

    def _expected_cash(self):
        return sum(self.day.visit_ids.payment_ids.mapped('amount'))

    def test_settlement_with_shortage_posts_variance(self):
        result = self.day.action_settle()
        settlement = self.env['dsd.settlement'].browse(result['res_id'])
        self.assertAlmostEqual(settlement.expected_cash, self._expected_cash())
        settlement.counted_cash = settlement.expected_cash - 5.0
        settlement.action_post_settlement()
        self.assertEqual(settlement.state, 'posted')
        self.assertEqual(self.day.state, 'settled')
        move = settlement.variance_move_id
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        variance_line = move.line_ids.filtered(
            lambda l: l.account_id == self.variance_account)
        self.assertAlmostEqual(variance_line.debit, 5.0)

    def test_settlement_without_difference_posts_nothing(self):
        result = self.day.action_settle()
        settlement = self.env['dsd.settlement'].browse(result['res_id'])
        settlement.counted_cash = settlement.expected_cash
        settlement.action_post_settlement()
        self.assertEqual(self.day.state, 'settled')
        self.assertFalse(settlement.variance_move_id)

    def test_settlement_snapshots_van_leftover(self):
        forgotten = self.env['product.product'].create({
            'name': 'Forgotten Crate', 'type': 'consu', 'is_storable': True,
        })
        self.env['stock.quant'].create({
            'product_id': forgotten.id,
            'location_id': self.van_location.id,
            'quantity': 3,
        })
        result = self.day.action_settle()
        settlement = self.env['dsd.settlement'].browse(result['res_id'])
        leftover = settlement.leftover_line_ids.filtered(
            lambda l: l.product_id == forgotten)
        self.assertEqual(len(leftover), 1)
        self.assertAlmostEqual(leftover.quantity, 3.0)
