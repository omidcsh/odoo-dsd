from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

# 2026-11-16 is a Monday, 2026-11-19 a Thursday — fixed dates keep tests deterministic.
MONDAY = date(2026, 11, 16)
THURSDAY = date(2026, 11, 19)


@tagged('post_install', '-at_install')
class TestDsdRouteDay(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Route = cls.env['dsd.route']
        cls.RouteDay = cls.env['dsd.route.day']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.van_location = cls.env['stock.location'].search(
            [('is_dsd_van', '=', True)], limit=1)
        cls.partners = cls.env['res.partner'].search([], limit=2)
        cls.route = cls.Route.create({
            'name': 'Test Route',
            'mode': 'mixed',
            'warehouse_id': cls.warehouse.id,
            'van_location_id': cls.van_location.id,
            'stop_ids': [
                (0, 0, {
                    'partner_id': cls.partners[0].id, 'sequence': 1,
                    'monday': True,
                }),
                (0, 0, {
                    'partner_id': cls.partners[1].id, 'sequence': 2,
                    'thursday': True,
                }),
            ],
        })

    def test_generation_snapshots_weekday_stops(self):
        wizard = self.env['dsd.route.day.generate.wizard'].create({
            'route_id': self.route.id, 'date': MONDAY,
        })
        result = wizard.action_generate()
        day = self.RouteDay.browse(result['res_id'])
        self.assertEqual(day.state, 'draft')
        self.assertTrue(day.name.startswith('RD/2026/'))
        self.assertEqual(len(day.visit_ids), 1)
        self.assertEqual(day.visit_ids.partner_id, self.partners[0])
        self.assertEqual(day.visit_ids.state, 'pending')

    def test_generation_skips_non_scheduled_stops(self):
        wizard = self.env['dsd.route.day.generate.wizard'].create({
            'route_id': self.route.id, 'date': THURSDAY,
        })
        result = wizard.action_generate()
        day = self.RouteDay.browse(result['res_id'])
        self.assertEqual(day.visit_ids.partner_id, self.partners[1])

    def test_duplicate_route_day_raises(self):
        self.RouteDay.create({'route_id': self.route.id, 'date': MONDAY})
        wizard = self.env['dsd.route.day.generate.wizard'].create({
            'route_id': self.route.id, 'date': MONDAY,
        })
        with self.assertRaises(UserError):
            wizard.action_generate()

    def test_generation_without_scheduled_stops_raises(self):
        wizard = self.env['dsd.route.day.generate.wizard'].create({
            'route_id': self.route.id,
            'date': date(2026, 11, 17),  # Tuesday: no stops scheduled
        })
        with self.assertRaises(UserError):
            wizard.action_generate()
