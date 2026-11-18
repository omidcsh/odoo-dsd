import psycopg2

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('standard')
class TestDsdRoute(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.org = cls.env['dsd.sales.org'].create({'code': '1000', 'name': 'Head Office'})
        cls.channel = cls.env['dsd.distribution.channel'].create({'code': '10', 'name': 'Retail'})
        cls.division = cls.env['dsd.division'].create({'code': '01', 'name': 'Dairy'})
        cls.division2 = cls.env['dsd.division'].create({'code': '02', 'name': 'Beverages'})
        cls.combo = cls.env['dsd.sales.area'].create({
            'sales_org_id': cls.org.id,
            'dist_channel_id': cls.channel.id,
            'division_id': cls.division.id,
        })
        cls.combo2 = cls.env['dsd.sales.area'].create({
            'sales_org_id': cls.org.id,
            'dist_channel_id': cls.channel.id,
            'division_id': cls.division2.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Route Customer'})

    def _membership(self, route, sa=None, **kw):
        vals = {
            'route_id': route.id,
            'partner_id': self.partner.id,
            'sales_area_id': (sa or self.combo).id,
        }
        vals.update(kw)
        return self.env['dsd.route.customer'].create(vals)

    def test_01_route_code_unique(self):
        self.env['dsd.route'].create({'code': 'R001', 'name': 'North'})
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['dsd.route'].create({'code': 'R001', 'name': 'North Again'})

    def test_02_membership_windows_no_overlap(self):
        route = self.env['dsd.route'].create({'code': 'R002', 'name': 'Central'})
        self._membership(route, valid_from='2026-01-01', valid_to='2026-06-30')
        # overlapping window for the same triple raises
        with self.assertRaises(ValidationError):
            self._membership(route, valid_from='2026-06-01', valid_to='2026-09-30')
        # sequential re-join (history) is allowed
        self._membership(route, valid_from='2026-07-01', valid_to='2026-12-31')

    def test_03_same_partner_multiple_routes(self):
        r1 = self.env['dsd.route'].create({'code': 'R003', 'name': 'East'})
        r2 = self.env['dsd.route'].create({'code': 'R004', 'name': 'West'})
        self._membership(r1)
        self._membership(r2)
        memberships = self.env['dsd.route.customer'].search(
            [('partner_id', '=', self.partner.id)])
        self.assertEqual(len(memberships), 2)

    def test_04_same_route_different_sales_areas(self):
        route = self.env['dsd.route'].create({'code': 'R005', 'name': 'Multi-SA'})
        self._membership(route, sa=self.combo)
        self._membership(route, sa=self.combo2)
        self.assertEqual(len(route.customer_sequence_ids), 2)

    def test_05_membership_ordering(self):
        """Visit order follows `sequence` — needs DISTINCT customers: three
        open-ended windows of the same (route, partner, SA) would rightly
        trigger the overlap rule."""
        route = self.env['dsd.route'].create({'code': 'R006', 'name': 'Ordered'})
        p3 = self.env['res.partner'].create({'name': 'Customer C'})
        p1 = self.env['res.partner'].create({'name': 'Customer A'})
        p2 = self.env['res.partner'].create({'name': 'Customer B'})
        m3 = self.env['dsd.route.customer'].create(
            {'route_id': route.id, 'partner_id': p3.id,
             'sales_area_id': self.combo.id, 'sequence': 30})
        m1 = self.env['dsd.route.customer'].create(
            {'route_id': route.id, 'partner_id': p1.id,
             'sales_area_id': self.combo.id, 'sequence': 10})
        m2 = self.env['dsd.route.customer'].create(
            {'route_id': route.id, 'partner_id': p2.id,
             'sales_area_id': self.combo.id, 'sequence': 20})
        ordered = self.env['dsd.route.customer'].search(
            [('route_id', '=', route.id)])
        self.assertEqual(ordered.mapped('id'), [m1.id, m2.id, m3.id],
                         'search() must return memberships in sequence order')

    def test_06_sa_compatibility_with_scoped_route(self):
        scoped = self.env['dsd.route'].create({
            'code': 'R007', 'name': 'Scoped', 'sales_area_id': self.combo.id})
        self._membership(scoped, sa=self.combo)  # matching SA is fine
        with self.assertRaises(ValidationError):
            self._membership(scoped, sa=self.combo2)  # different SA raises
        unscoped = self.env['dsd.route'].create({'code': 'R008', 'name': 'Open'})
        self._membership(unscoped, sa=self.combo2)  # unscoped accepts any
