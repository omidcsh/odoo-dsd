from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDsdRoute(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Route = cls.env['dsd.route']
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)

    def test_route_requires_van_location_for_van_sales(self):
        with self.assertRaises(ValidationError):
            self.Route.create({
                'name': 'Broken Van Route',
                'mode': 'van_sales',
                'warehouse_id': self.warehouse.id,
            })

    def test_presale_route_needs_no_van_location(self):
        route = self.Route.create({
            'name': 'Presale Route',
            'mode': 'presale',
            'warehouse_id': self.warehouse.id,
        })
        self.assertEqual(route.stop_count, 0)

    def test_route_with_stops_counts_them(self):
        route = self.Route.create({
            'name': 'Mixed Route',
            'mode': 'mixed',
            'warehouse_id': self.warehouse.id,
            'van_location_id': self.env['stock.location'].search(
                [('is_dsd_van', '=', True)], limit=1,
            ).id,
            'stop_ids': [(0, 0, {
                'partner_id': self.env['res.partner'].search([], limit=1).id,
                'sequence': 1,
                'monday': True,
            })],
        })
        self.assertEqual(route.stop_count, 1)
        self.assertTrue(route.stop_ids.monday)
        self.assertFalse(route.stop_ids.sunday)
