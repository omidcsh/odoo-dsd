from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged

MONDAY = date(2026, 11, 16)  # Mon 16th … Sun 22nd, deterministic week


@tagged('post_install', '-at_install')
class TestDsdWeekPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Route = cls.env['dsd.route']
        cls.RouteDay = cls.env['dsd.route.day']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.van_location = cls.env['stock.location'].search(
            [('is_dsd_van', '=', True)], limit=1)
        cls.partners = cls.env['res.partner'].search([], limit=2)
        cls.monday_route = cls.Route.create({
            'name': 'Plan Monday Route', 'mode': 'mixed',
            'warehouse_id': cls.warehouse.id,
            'van_location_id': cls.van_location.id,
            'stop_ids': [(0, 0, {
                'partner_id': cls.partners[0].id,
                'sequence': 1, 'monday': True,
            })],
        })
        cls.tuesday_route = cls.Route.create({
            'name': 'Plan Tuesday Route', 'mode': 'presale',
            'warehouse_id': cls.warehouse.id,
            'stop_ids': [(0, 0, {
                'partner_id': cls.partners[1].id,
                'sequence': 1, 'tuesday': True,
            })],
        })

    def test_week_plan_creates_scheduled_days_only(self):
        wizard = self.env['dsd.week.plan.wizard'].create({
            'week_start': MONDAY,
            'route_ids': [(6, 0, [self.monday_route.id, self.tuesday_route.id])],
        })
        result = wizard.action_plan_week()
        created = self.RouteDay.browse(result['domain'][0][2])
        self.assertEqual(len(created), 2)
        days_by_route = {d.route_id.id: d for d in created}
        self.assertEqual(
            days_by_route[self.monday_route.id].date, MONDAY)
        self.assertEqual(
            days_by_route[self.tuesday_route.id].date, MONDAY + timedelta(days=1))
        self.assertEqual(
            len(days_by_route[self.monday_route.id].visit_ids), 1)

    def test_week_plan_is_idempotent(self):
        wizard = self.env['dsd.week.plan.wizard'].create({
            'week_start': MONDAY,
            'route_ids': [(6, 0, [self.monday_route.id])],
        })
        wizard.action_plan_week()
        wizard.action_plan_week()
        days = self.RouteDay.search([('route_id', '=', self.monday_route.id)])
        self.assertEqual(len(days), 1, 'Re-planning must not duplicate days')

    def test_week_plan_covers_full_week_range(self):
        # Saturday stop: planned on MONDAY + 5 days
        saturday_route = self.Route.create({
            'name': 'Plan Saturday Route', 'mode': 'presale',
            'warehouse_id': self.warehouse.id,
            'stop_ids': [(0, 0, {
                'partner_id': self.partners[0].id,
                'sequence': 1, 'saturday': True,
            })],
        })
        wizard = self.env['dsd.week.plan.wizard'].create({
            'week_start': MONDAY,
            'route_ids': [(6, 0, [saturday_route.id])],
        })
        wizard.action_plan_week()
        day = self.RouteDay.search([('route_id', '=', saturday_route.id)])
        self.assertEqual(len(day), 1)
        self.assertEqual(day.date, MONDAY + timedelta(days=5))
