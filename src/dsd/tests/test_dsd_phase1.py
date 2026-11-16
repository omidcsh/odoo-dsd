import datetime as dt_mod
from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged


class DsdVisitFixture(TransactionCase):
    """Self-sufficient fixtures: no dependency on demo data (fresh test
    databases skip demo by default in this environment)."""

    def setUp(self):
        super().setUp()
        self.plan_type_visit = self.env['dsd.visit.plan.type'].create({
            'name': 'FT Presale', 'code': 'FT-PRE',
            'role': 'preseller', 'relevant_doc': 'visit_list'})
        self.plan_type_delivery = self.env['dsd.visit.plan.type'].create({
            'name': 'FT Delivery', 'code': 'FT-DEL',
            'role': 'delivery', 'relevant_doc': 'tour',
            'make_delivery': True})
        self.warehouse = self.env['stock.warehouse'].search([], limit=1)
        self.route = self.env['dsd.route'].create({
            'name': 'Fixture Route', 'code': 'FT-R',
            'warehouse_id': self.warehouse.id,
            'mon': True, 'thu': True})
        self.driver = self.env['hr.employee'].create({
            'name': 'Fixture Driver', 'dsd_active_driver': True})
        self.customer = self.env['res.partner'].create({
            'name': 'Fixture Customer',
            'dsd_route_id': self.route.id,
            'dsd_receiving_hours': 'Mon-Fri 08:00-16:00'})
        self.customer2 = self.env['res.partner'].create({
            'name': 'Fixture Customer 2',
            'dsd_route_id': self.route.id})


@tagged('post_install', '-at_install')
class TestDsdPlanType(DsdVisitFixture):

    def test_appointment_kind_follows_make_delivery(self):
        ListModel = self.env['dsd.visit.list']
        day = date.today() + timedelta(days=10)
        presale_list = ListModel.create({
            'execution_date': day, 'route_id': self.route.id,
            'plan_type_id': self.plan_type_visit.id,
            'driver_id': self.driver.id,
            'line_ids': [(0, 0, {'partner_id': self.customer.id})],
        })
        self.assertEqual(presale_list._appointment_kind(), 'visit')
        delivery_list = ListModel.create({
            'execution_date': day + timedelta(days=1),
            'route_id': self.route.id,
            'plan_type_id': self.plan_type_delivery.id,
            'driver_id': self.driver.id,
            'line_ids': [(0, 0, {'partner_id': self.customer.id})],
        })
        self.assertEqual(delivery_list._appointment_kind(), 'delivery')

    def test_appointment_unique_per_partner_date_kind(self):
        from psycopg2 import IntegrityError
        day = date.today() + timedelta(days=10)
        Appointment = self.env['dsd.visit.appointment']
        Appointment.create({
            'partner_id': self.customer.id, 'date': day,
            'kind': 'visit', 'route_id': self.route.id,
            'company_id': self.env.company.id})
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            Appointment.create({
                'partner_id': self.customer.id, 'date': day,
                'kind': 'visit', 'route_id': self.route.id,
                'company_id': self.env.company.id})
        # same date, other kind: allowed
        Appointment.create({
            'partner_id': self.customer.id, 'date': day,
            'kind': 'delivery', 'route_id': self.route.id,
            'company_id': self.env.company.id})


@tagged('post_install', '-at_install')
class TestDsdRecurrence(DsdVisitFixture):

    def setUp(self):
        super().setUp()
        self.plan = self.env['dsd.visit.plan'].create({
            'name': 'Recurrence Test',
            'plan_type_id': self.plan_type_visit.id,
            'route_id': self.route.id,
            'frequency': 'weekly',
            'mon': True,
            'thu': True,
            'interval_weeks': 1,
            'anchor_date': date(2026, 11, 2),  # a Monday
            'valid_from': date(2026, 1, 1),
        })

    def test_weekly_two_weekdays(self):
        # Mon 2026-11-16 .. Sun 2026-11-22 -> Mon 16 and Thu 19
        dates = self.plan._occurrence_dates(date(2026, 11, 16), date(2026, 11, 22))
        self.assertEqual(dates, [date(2026, 11, 16), date(2026, 11, 19)])

    def test_biweekly_interval(self):
        self.plan.interval_weeks = 2
        dates = self.plan._occurrence_dates(date(2026, 11, 2), date(2026, 11, 22))
        # anchored on Mon 11-02: weeks of 11-02 and 11-16 hit, 11-09 skipped
        self.assertEqual(dates, [date(2026, 11, 2), date(2026, 11, 5),
                                 date(2026, 11, 16), date(2026, 11, 19)])

    def test_rrule_mode(self):
        self.plan.write({
            'frequency': 'rrule',
            'recurrence_rrule': 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU',
            'anchor_date': date(2026, 11, 3),  # Tuesday
        })
        dates = self.plan._occurrence_dates(date(2026, 11, 3), date(2026, 11, 21))
        self.assertEqual(dates, [date(2026, 11, 3), date(2026, 11, 17)])

    def test_invalid_rrule_rejected(self):
        with self.assertRaises(Exception):
            self.plan.write({
                'frequency': 'rrule',
                'recurrence_rrule': 'NOT=A;RULE',
            })

    def test_validity_bounds(self):
        self.plan.valid_from = date(2026, 11, 18)
        dates = self.plan._occurrence_dates(date(2026, 11, 16), date(2026, 11, 22))
        self.assertEqual(dates, [date(2026, 11, 19)])

    def test_nonworking_skip_policy(self):
        calendar = self.env['resource.calendar'].create({
            'name': 'Mon-Thu Only',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 17}),
                (0, 0, {'dayofweek': '3', 'hour_from': 8, 'hour_to': 17}),
            ],
        })
        # without a calendar, no day is non-working
        self.assertFalse(self.plan._is_nonworking(date(2026, 11, 21)))
        self.plan.calendar_id = calendar
        # Saturday non-working, Monday/Thursday working
        self.assertTrue(self.plan._is_nonworking(date(2026, 11, 21)))
        self.assertFalse(self.plan._is_nonworking(date(2026, 11, 16)))
        dates = self.plan._occurrence_dates(date(2026, 11, 16), date(2026, 11, 22))
        self.assertEqual(dates, [date(2026, 11, 16), date(2026, 11, 19)])

    def test_nonworking_move_next_policy(self):
        # Plan visits only on Saturday; calendar works Mon-Fri; policy next -> Monday
        self.plan.write({'mon': False, 'thu': False, 'sat': True})
        calendar = self.env['resource.calendar'].create({
            'name': 'Mon-Fri Half Days',
            'attendance_ids': [
                (0, 0, {'dayofweek': '0', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '1', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '2', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '3', 'hour_from': 8, 'hour_to': 12}),
                (0, 0, {'dayofweek': '4', 'hour_from': 8, 'hour_to': 12}),
            ],
        })
        self.plan.calendar_id = calendar
        self.plan.nonworking_policy = 'next'
        dates = self.plan._occurrence_dates(date(2026, 11, 16), date(2026, 11, 22))
        self.assertEqual(dates, [date(2026, 11, 23)])  # Sat 21 -> Mon 23

    def test_next_occurrence_respects_exception(self):
        line = self.env['dsd.visit.plan.line'].create({
            'plan_id': self.plan.id, 'partner_id': self.customer.id})
        self.plan.state = 'active'
        today = date.today()
        first = line._get_next_occurrence(today)
        self.assertTrue(first)
        upcoming = self.plan._occurrence_dates(
            today, today + timedelta(days=self.env.company.dsd_planning_horizon_days))
        self.env['dsd.visit.plan.line.exception'].create({
            'line_id': line.id, 'date': upcoming[0]})
        second = line._get_next_occurrence(today)
        self.assertEqual(second, upcoming[1] if len(upcoming) > 1 else False)
        self.assertNotEqual(first, second)


@tagged('post_install', '-at_install')
class TestDsdListGeneration(DsdVisitFixture):

    def setUp(self):
        super().setUp()
        self.plan = self.env['dsd.visit.plan'].create({
            'name': 'Generation Test',
            'plan_type_id': self.plan_type_visit.id,
            'route_id': self.route.id,
            'driver_id': self.driver.id,
            'frequency': 'weekly',
            'mon': True,
            'interval_weeks': 1,
            'anchor_date': date(2026, 11, 2),
            'valid_from': date(2026, 1, 1),
        })
        self.line1 = self.env['dsd.visit.plan.line'].create({
            'plan_id': self.plan.id, 'sequence': 10, 'partner_id': self.customer.id})
        self.line2 = self.env['dsd.visit.plan.line'].create({
            'plan_id': self.plan.id, 'sequence': 20, 'partner_id': self.customer2.id})
        self.plan.state = 'active'  # wizard selection requires active plans
        self.day = date(2026, 11, 16)  # a Monday

    def test_generate_creates_list_with_lines_in_order(self):
        status, visit_list = self.plan._generate_list_for_date(self.day)
        self.assertEqual(status, 'created')
        self.assertEqual(visit_list.plan_id, self.plan)
        self.assertEqual(visit_list.route_id, self.route)
        self.assertEqual(visit_list.driver_id, self.driver)
        self.assertEqual(
            visit_list.line_ids.mapped('partner_id'), self.customer + self.customer2)
        self.assertEqual(visit_list.state, 'draft')

    def test_planned_list_count_reads(self):
        """Regression: this computed field used the pre-17 read_group
        signature and crashed the Visit Plans screen on read."""
        self.plan._generate_list_for_date(self.day)
        self.assertEqual(self.plan.planned_list_count, 1)

    def test_duplicate_generation_blocked(self):
        _status, first = self.plan._generate_list_for_date(self.day)
        status, detail = self.plan._generate_list_for_date(self.day)
        self.assertEqual(status, 'exists')
        self.assertEqual(detail, first)

    def test_watermark_blocks_regeneration(self):
        self.plan.last_execution_date = self.day
        status, _detail = self.plan._generate_list_for_date(self.day)
        self.assertEqual(status, 'watermark')
        status, _detail = self.plan._generate_list_for_date(self.day, dry_run=True)
        self.assertEqual(status, 'created')

    def test_inactive_and_exception_lines_skipped(self):
        self.line1.inactive = True
        self.env['dsd.visit.plan.line.exception'].create({
            'line_id': self.line2.id, 'date': self.day})
        status, _detail = self.plan._generate_list_for_date(self.day)
        self.assertEqual(status, 'no_customers')

    def test_generation_syncs_appointments(self):
        _status, visit_list = self.plan._generate_list_for_date(self.day)
        appointments = self.env['dsd.visit.appointment'].search([
            ('visit_list_id', '=', visit_list.id)])
        self.assertEqual(len(appointments), 2)
        self.assertTrue(all(appt.kind == 'visit' for appt in appointments))
        self.assertTrue(all(appt.route_id == self.route for appt in appointments))

    def test_wizard_dry_run_writes_nothing(self):
        wizard = self.env['dsd.visit.list.generate'].create({
            'plan_ids': [(6, 0, [self.plan.id])],
            'date_from': self.day,
            'date_to': self.day + timedelta(days=6),
            'dry_run': True,
        })
        wizard.action_generate()
        self.assertFalse(self.env['dsd.visit.list'].search([
            ('plan_id', '=', self.plan.id)]))
        self.assertFalse(self.plan.last_execution_date)

    def test_wizard_generates_and_sets_watermark(self):
        wizard = self.env['dsd.visit.list.generate'].create({
            'plan_ids': [(6, 0, [self.plan.id])],
            'date_from': self.day,
            'date_to': self.day + timedelta(days=6),
        })
        wizard.action_generate()
        lists = self.env['dsd.visit.list'].search([('plan_id', '=', self.plan.id)])
        self.assertEqual(len(lists), 1)  # Monday only in this fixture plan
        self.assertEqual(self.plan.last_execution_date, date(2026, 11, 16))
        wizard2 = self.env['dsd.visit.list.generate'].create({
            'plan_ids': [(6, 0, [self.plan.id])],
            'date_from': self.day,
            'date_to': self.day + timedelta(days=6),
        })
        wizard2.action_generate()
        self.assertEqual(len(self.env['dsd.visit.list'].search([
            ('plan_id', '=', self.plan.id)])), 1)

    def test_cron_fills_appointments_for_active_plans(self):
        self.plan.state = 'active'
        Appointment = self.env['dsd.visit.appointment']
        Appointment.cron_fill_appointments()
        today = date.today()
        horizon = today + timedelta(days=self.env.company.dsd_planning_horizon_days)
        dates = self.plan._occurrence_dates(today, horizon)
        expected = len(dates) * 2  # two customers
        self.assertGreater(expected, 0)
        self.assertEqual(Appointment.search_count([
            ('plan_id', '=', self.plan.id)]), expected)
        Appointment.cron_fill_appointments()
        self.assertEqual(Appointment.search_count([
            ('plan_id', '=', self.plan.id)]), expected)

    def test_postpone_moves_appointments(self):
        _status, visit_list = self.plan._generate_list_for_date(self.day)
        Appointment = self.env['dsd.visit.appointment']
        self.assertEqual(
            Appointment.search([('visit_list_id', '=', visit_list.id)]).mapped('date'),
            [self.day] * 2)
        visit_list.action_postpone(new_date=self.day + timedelta(days=1))
        self.assertFalse(Appointment.search([
            ('date', '=', self.day), ('visit_list_id', '=', visit_list.id)]))
        self.assertEqual(len(Appointment.search([
            ('visit_list_id', '=', visit_list.id)])), 2)

    def test_cancel_releases_appointments(self):
        _status, visit_list = self.plan._generate_list_for_date(self.day)
        Appointment = self.env['dsd.visit.appointment']
        self.assertEqual(len(Appointment.search([
            ('visit_list_id', '=', visit_list.id)])), 2)
        visit_list.action_cancel()
        self.assertFalse(Appointment.search([
            ('visit_list_id', '=', visit_list.id)]),
            'cancelled list must release its time-stream slots')

    def test_confirm_requires_driver_and_stops(self):
        from odoo.exceptions import UserError
        status, visit_list = self.plan._generate_list_for_date(self.day)
        visit_list.driver_id = False
        with self.assertRaises(UserError):
            visit_list.action_confirm()
        visit_list.driver_id = self.driver.id
        visit_list.action_confirm()
        self.assertEqual(visit_list.state, 'confirmed')


@tagged('post_install', '-at_install')
class TestDsdSaleOrderProposal(DsdVisitFixture):

    def test_apply_dsd_defaults(self):
        plan = self.env['dsd.visit.plan'].create({
            'name': 'Proposal Plan',
            'plan_type_id': self.plan_type_delivery.id,
            'route_id': self.route.id,
            'frequency': 'weekly',
            'mon': True,
            'anchor_date': date(2026, 11, 2),
            'valid_from': date(2026, 1, 1),
            'state': 'active',
        })
        self.env['dsd.visit.plan.line'].create({
            'plan_id': plan.id, 'partner_id': self.customer.id})
        self.env['dsd.visit.appointment'].cron_fill_appointments()
        order = self.env['sale.order'].create({'partner_id': self.customer.id})
        order.action_apply_dsd_defaults()
        self.assertEqual(order.dsd_route_id, self.route)
        self.assertTrue(order.commitment_date, 'delivery date proposed from appointment')
        Appointment = self.env['dsd.visit.appointment']
        today = date.today()
        lead = self.env.company.dsd_min_lead_days
        expected = Appointment.search([
            ('partner_id', '=', self.customer.id),
            ('date', '>=', today + dt_mod.timedelta(days=lead)),
        ], order='date', limit=1)
        self.assertEqual(order.commitment_date.date(), expected.date)

    def test_apply_defaults_without_appointments(self):
        order = self.env['sale.order'].create({'partner_id': self.customer2.id})
        order.action_apply_dsd_defaults()
        self.assertEqual(order.dsd_route_id, self.route)
        self.assertFalse(order.commitment_date)

    def test_existing_commitment_date_not_clobbered(self):
        plan = self.env['dsd.visit.plan'].create({
            'name': 'Clobber Plan',
            'plan_type_id': self.plan_type_delivery.id,
            'route_id': self.route.id,
            'frequency': 'weekly',
            'mon': True,
            'anchor_date': date(2026, 11, 2),
            'valid_from': date(2026, 1, 1),
            'state': 'active',
        })
        self.env['dsd.visit.plan.line'].create({
            'plan_id': plan.id, 'partner_id': self.customer.id})
        self.env['dsd.visit.appointment'].cron_fill_appointments()
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'commitment_date': dt_mod.datetime.combine(
                date.today() + timedelta(days=30), dt_mod.time(9, 0)),
        })
        order.action_apply_dsd_defaults()
        self.assertEqual(order.commitment_date.date(), date.today() + timedelta(days=30))
