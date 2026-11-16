"""Phase 4 tests: driver console service methods (the same code path the
OWL console calls), assortment, deal conditions, and credit gating."""
import datetime as dt_mod
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


class DsdConsoleFixture(TransactionCase):

    def setUp(self):
        super().setUp()
        self.warehouse = self.env['stock.warehouse'].search([], limit=1)
        self.plan_type = self.env['dsd.visit.plan.type'].create({
            'name': 'FT Van', 'code': 'FT-VAN4',
            'role': 'van_sales', 'relevant_doc': 'both'})
        self.route = self.env['dsd.route'].create({
            'name': 'Console Route', 'code': 'FT-CN',
            'warehouse_id': self.warehouse.id})
        self.driver_user = self.env['res.users'].create({
            'name': 'Console Driver',
            'login': 'cn_drv_%d' % int(dt_mod.datetime.now().timestamp()),
            'group_ids': [(6, 0, [self.env.ref('dsd.group_dsd_driver').id])]})
        self.driver = self.env['hr.employee'].create({
            'name': 'Console Driver Emp', 'dsd_active_driver': True,
            'user_id': self.driver_user.id,
            'dsd_max_discount_pct': 5})
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'CNB'})
        self.van = self.env['fleet.vehicle'].create({
            'model_id': self.env['fleet.vehicle.model'].create({
                'name': 'Console Van', 'brand_id': brand.id}).id,
            'license_plate': 'CN-VAN',
            'dsd_vehicle_type': 'van'})
        self.cash_journal = self.env['account.journal'].create({
            'name': 'Console Cash', 'code': 'CNC', 'type': 'cash'})
        self.customer = self.env['res.partner'].create({
            'name': 'Console Customer', 'dsd_route_id': self.route.id,
            'dsd_collection_type': 'on_delivery',
            'dsd_accepted_journal_ids': [(6, 0, [self.cash_journal.id])],
            'dsd_pod_or_invoice': 'invoice',
            'dsd_invoice_generation': 'auto'})
        self.other = self.env['res.partner'].create({
            'name': 'Console Customer 2', 'dsd_route_id': self.route.id})
        self.product_category = self.env['product.category'].create({
            'name': 'Console Category'})
        self.product = self.env['product.product'].create({
            'name': 'Console Product', 'type': 'consu', 'is_storable': True,
            'weight': 2.0, 'list_price': 10.0,
            'categ_id': self.product_category.id})
        self.day = date.today()

    def _as_driver(self):
        return self.env(user=self.driver_user)

    def _tour_with_stop(self, env_override=None):
        """Confirmed tour + in-progress visit list with one stop, loaded."""
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'commitment_date': dt_mod.datetime.combine(
                self.day + timedelta(days=2), dt_mod.time(8, 0)),
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': 6})],
        })
        order.action_confirm()
        picking = order.picking_ids
        visit_list = self.env['dsd.visit.list'].create({
            'execution_date': self.day,
            'route_id': self.route.id,
            'plan_type_id': self.plan_type.id,
            'driver_id': self.driver.id,
            'vehicle_id': self.van.id,
            'line_ids': [(0, 0, {'partner_id': self.customer.id})],
        })
        tour = self.env['stock.picking.batch'].create({
            'name': 'CN TOUR',
            'dsd_route_id': self.route.id,
            'dsd_driver_id': self.driver.id,
            'vehicle_id': self.van.id,
            'scheduled_date': dt_mod.datetime.combine(self.day, dt_mod.time(8, 0)),
            'picking_ids': [(6, 0, picking.ids)],
            'dsd_visit_list_id': visit_list.id,
        })
        visit_list.tour_id = tour
        visit_list.state = 'confirmed'
        tour.action_dsd_confirm()
        tour.action_dsd_load()
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'quantity': 100})
        lc = self.env['dsd.loading.confirmation'].create({'tour_id': tour.id})
        lc.line_ids.counted_qty = 6
        lc.action_complete()
        check = self.env['dsd.check.record'].create({
            'tour_id': tour.id, 'check_type': 'out'})
        check.material_line_ids.counted_qty = 6
        check.action_confirm()
        tour.action_dsd_start()
        stop = visit_list.line_ids[0]
        return tour, visit_list, stop


@tagged('post_install', '-at_install')
class TestConsoleToday(DsdConsoleFixture):

    def test_today_shows_own_tour_and_list(self):
        tour, visit_list, stop = self._tour_with_stop()
        data = self._as_driver()['dsd.console'].get_console_data()
        self.assertEqual(data['driver']['id'], self.driver.id)
        tour_ids = [t['id'] for t in data['tours']]
        self.assertIn(tour.id, tour_ids)
        list_ids = [l['id'] for l in data['visit_lists']]
        self.assertIn(visit_list.id, list_ids)
        stops = data['visit_lists'][0]['stops']
        self.assertEqual(stops[0]['partner'], self.customer.display_name)

    def test_console_denied_for_non_drivers(self):
        admin_only_env = self.env(user=self.env.user)  # admin is not the driver
        with self.assertRaises(AccessError):
            admin_only_env['dsd.console'].get_console_data()

    def test_foreign_tour_denied(self):
        other_driver = self.env['hr.employee'].create({
            'name': 'Other Driver', 'dsd_active_driver': True})
        other_user = self.env['res.users'].create({
            'name': 'Other Driver U',
            'login': 'cn_other_%d' % int(dt_mod.datetime.now().timestamp()),
            'group_ids': [(6, 0, [self.env.ref('dsd.group_dsd_driver').id])]})
        other_driver.user_id = other_user
        tour, _vlist, _stop = self._tour_with_stop()
        data = self.env(user=other_user)['dsd.console'].get_console_data()
        self.assertEqual(data['tours'], [],
                         'foreign driver must not see this tour')
        self.assertEqual(data['visit_lists'], [])

    def test_duplicate_appointment_slot_is_clean_error(self):
        """Two lists covering the same customer/date/kind must raise the
        actionable UserError, not a raw psycopg2 IntegrityError (regression:
        a pre-existing list or the fill cron can already claim the slot)."""
        VisitList = self.env['dsd.visit.list']
        vals = {
            'execution_date': self.day, 'route_id': self.route.id,
            'plan_type_id': self.plan_type.id, 'driver_id': self.driver.id,
            'vehicle_id': self.van.id,
            'line_ids': [(0, 0, {'partner_id': self.customer.id})]}
        first = VisitList.create(vals)
        self.assertEqual(
            self.env['dsd.visit.appointment'].search_count(
                [('visit_list_id', '=', first.id)]), 1)
        with self.assertRaises(UserError):
            VisitList.create(vals)


@tagged('post_install', '-at_install')
class TestConsoleStopLifecycle(DsdConsoleFixture):

    def test_arrive_depart_status_note(self):
        tour, _list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        stop_data = service.get_stop(stop.id)
        self.assertEqual(stop_data['delivery']['lines'][0]['planned'], 6)
        service.set_arrival(stop.id)
        self.assertTrue(stop.arrival)
        service.set_departure(stop.id)
        self.assertTrue(stop.departure)
        service.set_visit_note(stop.id, 'Left samples')
        self.assertEqual(stop.visit_note, 'Left samples')
        reason = self.env.ref('dsd.reason_visit_closed')
        service.set_visit_status(stop.id, 'up', reason.id)
        self.assertEqual(stop.status, 'up')

    def test_add_unplanned_and_resequence(self):
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        result = service.add_unplanned_stop(
            visit_list.id, name='One Time Shop', street='Main St')
        new_stop = self.env['dsd.visit.list.line'].browse(result['stop_id'])
        self.assertTrue(new_stop.is_unplanned)
        self.assertTrue(new_stop.partner_id.dsd_is_one_time)
        service.resequence_stops(visit_list.id, [new_stop.id, stop.id])
        self.assertEqual(new_stop.sequence, 10)
        self.assertEqual(stop.sequence, 20)


@tagged('post_install', '-at_install')
class TestConsoleVanSale(DsdConsoleFixture):

    def test_van_sale_full_flow(self):
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        result = service.create_van_sale(stop.id, [
            {'product_id': self.product.id, 'qty': 2, 'discount': 5}])
        order = self.env['sale.order'].search(
            [('dsd_visit_list_line_id', '=', stop.id)])
        self.assertEqual(len(order), 1)
        self.assertEqual(order.order_line[0].discount, 5)
        self.assertEqual(stop.status, 'np')  # status managed at delivery
        self.assertIn(stop.id, order.dsd_visit_list_line_id.id and
                      [stop.id])
        # invoice posted automatically (auto profile), delivery from the van
        invoices = order.invoice_ids.filtered(lambda m: m.state == 'posted')
        self.assertEqual(len(invoices), 1)
        delivery = order.picking_ids[:1]
        self.assertEqual(delivery.location_id, self.van.dsd_van_location_id)

    def test_discount_authority_enforced(self):
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        with self.assertRaises(UserError):
            service.create_van_sale(stop.id, [
                {'product_id': self.product.id, 'qty': 1, 'discount': 50}])

    def test_assortment_deny_blocks(self):
        group = self.env['res.partner.category'].create({'name': 'CN Group'})
        self.customer.category_id = [(6, 0, [group.id])]
        self.env['dsd.assortment'].create({
            'rule_type': 'deny', 'partner_group_id': group.id,
            'product_category_id': self.product.categ_id.id})
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        with self.assertRaises(UserError):
            service.create_van_sale(stop.id, [
                {'product_id': self.product.id, 'qty': 1}])

    def test_credit_limit_blocks_invoice(self):
        self.customer.dsd_credit_limit = 5
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        # manual try/except: odoo's assertRaises rolls back a savepoint, which
        # would also undo the draft invoice we want to verify
        raised = False
        try:
            service.create_van_sale(stop.id, [
                {'product_id': self.product.id, 'qty': 2}])  # 2x10 = 20 > 5
        except UserError:
            raised = True
        self.assertTrue(raised, 'credit limit must block the invoice')
        # draft invoice left for the back office
        invoice = self.env['account.move'].search([
            ('partner_id', '=', self.customer.id), ('state', '=', 'draft')])
        self.assertTrue(invoice)

    def test_deal_condition_free_goods_obligatory(self):
        condition = self.env['dsd.deal.condition'].create({
            'name': 'Buy 2 get 1 free', 'result_type': 'free_goods',
            'obligatory': True,
            'free_product_id': self.product.id, 'free_qty': 1,
            'partner_ids': [(6, 0, [self.customer.id])],
            'state': 'active',
            'line_ids': [Command.create({
                'product_id': self.product.id, 'min_qty': 2})],
        })
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        service.create_van_sale(stop.id, [
            {'product_id': self.product.id, 'qty': 2}])
        order = self.env['sale.order'].search(
            [('dsd_visit_list_line_id', '=', stop.id)])
        free_lines = order.order_line.filtered(lambda l: l.is_dsd_free_goods)
        self.assertEqual(len(free_lines), 1)
        self.assertEqual(free_lines.product_uom_qty, 1)
        self.assertEqual(free_lines.price_unit, 0.0)
        self.assertIn(condition.id, order.dsd_applied_deal_ids.ids)


@tagged('post_install', '-at_install')
class TestConsoleCollection(DsdConsoleFixture):

    def test_collection_with_invoice_reconciliation(self):
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id, 'quantity': 1,
                'price_unit': 15.0})],
        })
        invoice.action_post()
        result = service.create_collection(
            stop.id, invoice.amount_total, self.cash_journal.id, [invoice.id])
        self.assertTrue(result['payment'])
        self.assertEqual(invoice.payment_state, 'paid')
        payment = self.env['account.payment'].search([
            ('memo', '=', f'{visit_list.name} collection')])
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.state, 'reconciled',
                         'fully reconciled payment is marked reconciled')

    def test_cash_only_customer_rejects_bank(self):
        self.customer.dsd_cash_only = True
        bank = self.env['account.journal'].search(
            [('type', '=', 'bank')], limit=1)
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        with self.assertRaises(UserError):
            service.create_collection(stop.id, 10, bank.id)

    def test_unaccepted_journal_rejected(self):
        bank = self.env['account.journal'].search(
            [('type', '=', 'bank')], limit=1)
        tour, visit_list, stop = self._tour_with_stop()
        service = self._as_driver()['dsd.console']
        with self.assertRaises(UserError):
            service.create_collection(stop.id, 10, bank.id)

    def test_non_collecting_customer_rejected(self):
        self.other.dsd_collection_type = 'none'
        list2 = self.env['dsd.visit.list'].create({
            'execution_date': self.day, 'route_id': self.route.id,
            'plan_type_id': self.plan_type.id, 'driver_id': self.driver.id,
            'line_ids': [(0, 0, {'partner_id': self.other.id})]})
        service = self._as_driver()['dsd.console']
        with self.assertRaises(UserError):
            service.create_collection(
                list2.line_ids[0].id, 10, self.cash_journal.id)


@tagged('post_install', '-at_install')
class TestConsoleCheckAndReload(DsdConsoleFixture):

    def test_submit_check_in_through_console(self):
        tour, _list, _stop = self._tour_with_stop()  # departed, in_progress
        service = self._as_driver()['dsd.console']
        result = service.submit_check(tour.id, 'in', material_counts={
            self.product.id: 6})
        self.assertEqual(result['state'], 'confirmed')
        self.assertEqual(tour.dsd_state, 'checked_in')

    def test_reload_through_console(self):
        tour, _list, _stop = self._tour_with_stop()  # already in_progress
        self.assertEqual(tour.dsd_state, 'in_progress')
        service = self._as_driver()['dsd.console']
        result = service.request_reload(tour.id, [
            {'product_id': self.product.id, 'qty': 4}])
        self.assertTrue(result['pickings'])
        reload_picking = tour.dsd_reload_picking_ids[:1]
        self.assertTrue(reload_picking)
        self.assertIn(reload_picking.id, tour.dsd_reload_picking_ids.ids)

    def test_adjust_van_stock_with_reason(self):
        tour, _list, _stop = self._tour_with_stop()  # loaded: van holds 6
        service = self._as_driver()['dsd.console']
        service.adjust_van_stock(
            tour.id, self.product.id, 4, self.env.ref('dsd.reason_adj_breakage').id)
        quant = self.env['stock.quant'].search([
            ('location_id', '=', self.van.dsd_van_location_id.id),
            ('product_id', '=', self.product.id)])
        self.assertEqual(quant.quantity, 4)

    def _count_and_seal(self, tour):
        lc = self.env['dsd.loading.confirmation'].create({'tour_id': tour.id})
        lc.line_ids.counted_qty = 6
        lc.action_complete()
