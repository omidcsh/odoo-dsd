from datetime import date

from odoo.tests import TransactionCase, tagged

MONDAY = date(2026, 11, 16)


@tagged('post_install', '-at_install')
class TestDsdFullLoop(TransactionCase):
    """One storable product through the entire loop: generate → load →
    van sale → end → return → settle, reconciling stock and cash."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.RouteDay = cls.env['dsd.route.day']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.van_location = cls.env['stock.location'].search(
            [('is_dsd_van', '=', True)], limit=1)
        cls.company = cls.warehouse.company_id
        cls.journal = cls.env['account.journal'].create({
            'name': 'Loop Cash', 'type': 'cash', 'code': 'LOOPC',
            'company_id': cls.company.id,
        })
        cls.variance_account = cls.env['account.account'].create({
            'name': 'Loop Variance', 'code': 'LOOPVAR',
            'account_type': 'expense',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Integration Soda Crate',
            'type': 'consu', 'is_storable': True, 'list_price': 5.0,
        })
        cls.partner = cls.env['res.partner'].search([], limit=1)
        cls.route = cls.env['dsd.route'].create({
            'name': 'Integration Route',
            'mode': 'mixed',
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
        # Warehouse starts with stock for the day's load
        cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.warehouse.lot_stock_id.id,
            'quantity': 5,
        })

    def _validate(self, picking, qty):
        move = self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom_qty': qty,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })
        picking.action_confirm()
        # Reservation may not create a line (no stock to reserve): put the
        # done quantity directly on a move line, as a driver would on the
        # operations tab.
        line = move.move_line_ids[:1]
        if line:
            line.write({'quantity': qty, 'picked': True})
        else:
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'product_id': self.product.id,
                'uom_id': move.uom_id.id,
                'quantity': qty,
                'picked': True,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
        picking.button_validate()

    def _van_quantity(self):
        quant = self.env['stock.quant'].search([
            ('location_id', '=', self.van_location.id),
            ('product_id', '=', self.product.id),
        ])
        return quant.quantity

    def test_full_loop_generation_to_settlement(self):
        # 1. Load 5 crates onto the van
        self.day.action_load_van()
        self._validate(self.day.load_picking_id, 5)
        self.assertAlmostEqual(self._van_quantity(), 5.0)

        # 2. Run the route and sell 3 crates for cash at the stop
        self.day.action_start_route()
        visit = self.day.visit_ids
        result = visit.action_start_van_sale()
        order = self.env['sale.order'].browse(result['res_id'])
        self.env['sale.order.line'].create({
            'order_id': order.id, 'product_id': self.product.id,
            'product_uom_qty': 3, 'price_unit': 5.0,
        })
        order.action_confirm()
        visit.action_complete_van_sale()
        self.assertEqual(visit.state, 'done')
        self.assertAlmostEqual(self._van_quantity(), 2.0)

        # 3. Close the day and return the remaining 2 crates
        self.day.action_end_route()
        self.day.action_create_stock_return()
        self._validate(self.day.return_picking_id, 2)
        self.assertAlmostEqual(self._van_quantity(), 0.0)

        # 4. Settle with an exact cash count
        settle_result = self.day.action_settle()
        settlement = self.env['dsd.settlement'].browse(settle_result['res_id'])
        settlement.counted_cash = settlement.expected_cash
        settlement.action_post_settlement()

        # 5. Assertions across the whole chain
        self.assertEqual(self.day.state, 'settled')
        invoice_total = order.invoice_ids.amount_total
        self.assertAlmostEqual(settlement.expected_cash, invoice_total)
        self.assertAlmostEqual(self.day.cash_collected, invoice_total)
        self.assertAlmostEqual(self.day.total_sales, invoice_total)
        self.assertAlmostEqual(invoice_total, 15.0 * (1 + 0.15),
                               msg='demo 15% sales tax applies')
        warehouse_quant = self.env['stock.quant'].search([
            ('location_id', '=', self.warehouse.lot_stock_id.id),
            ('product_id', '=', self.product.id),
        ])
        self.assertAlmostEqual(warehouse_quant.quantity, 2.0,
                               msg='Returned crates must land in warehouse stock')
        self.assertFalse(settlement.variance_move_id,
                         msg='Exact cash count posts no variance entry')
