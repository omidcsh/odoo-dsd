import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('standard')
class TestDsdSalesArea(TransactionCase):

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
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer', 'is_company': True,
        })

    def test_01_combo_unique_trio(self):
        """Duplicate (org, channel, division) raises an integrity error."""
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['dsd.sales.area'].create({
                'sales_org_id': self.org.id,
                'dist_channel_id': self.channel.id,
                'division_id': self.division.id,
            })

    def test_02_partner_sales_area_unique(self):
        """A customer cannot have the same sales area twice."""
        self.env['dsd.partner.sales.area'].create({
            'partner_id': self.partner.id,
            'sales_area_id': self.combo.id,
        })
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['dsd.partner.sales.area'].create({
                'partner_id': self.partner.id,
                'sales_area_id': self.combo.id,
            })

    def test_03_block_is_not_inactive(self):
        """A blocked row stays visible/active; an archived row is hidden."""
        row = self.env['dsd.partner.sales.area'].create({
            'partner_id': self.partner.id,
            'sales_area_id': self.combo.id,
            'sale_block': True,
            'sale_block_reason': 'Credit hold',
        })
        rows = self.env['dsd.partner.sales.area'].search(
            [('partner_id', '=', self.partner.id)])
        self.assertIn(row, rows, 'blocked row must remain downloadable')
        row.active = False
        rows = self.env['dsd.partner.sales.area'].search(
            [('partner_id', '=', self.partner.id)])
        self.assertNotIn(row, rows, 'archived row must leave the download')

    def test_04_primary_sales_area_compute(self):
        """is_primary: one active primary per partner; read-through follows
        the flagged row; archiving it with no replacement clears fields."""
        first = self.env['dsd.partner.sales.area'].create({
            'partner_id': self.partner.id,
            'sales_area_id': self.combo.id,
            'is_primary': True,
            'delivery_block': True,
        })
        second = self.env['dsd.partner.sales.area'].create({
            'partner_id': self.partner.id,
            'sales_area_id': self.combo2.id,
        })
        self.assertEqual(self.partner.dsd_sales_org, '1000')
        self.assertEqual(self.partner.dsd_dist_channel, '10')
        self.assertEqual(self.partner.dsd_division, '01')
        self.assertTrue(self.partner.dsd_delivery_block)
        with self.assertRaises(ValidationError):
            second.write({'is_primary': True})
        # move the flag: unflag first, then flag second
        first.is_primary = False
        second.is_primary = True
        self.assertEqual(self.partner.dsd_division, '02')
        self.assertFalse(self.partner.dsd_delivery_block)
        second.active = False  # primary archived, no replacement
        self.assertFalse(self.partner.dsd_sales_org,
                         'archived primary without replacement clears fields')

    def test_05_partner_function_defaults(self):
        """PF defaults: UI onchange AND the create() code/API path (review
        1.4) both fill the four roles with the customer."""
        with Form(self.env['dsd.partner.sales.area']) as f:
            f.partner_id = self.partner
            f.sales_area_id = self.combo
            self.assertEqual(f.payer_id, self.partner)
            self.assertEqual(f.sold_to_id, self.partner)
            self.assertEqual(f.ship_to_id, self.partner)
            self.assertEqual(f.bill_to_id, self.partner)
            row = f.save()
        self.assertEqual(row.payer_id, self.partner)
        # direct create (no onchange) — server-side default must apply too
        row2 = self.env['dsd.partner.sales.area'].create({
            'partner_id': self.partner.id,
            'sales_area_id': self.combo.id if row.sales_area_id != self.combo else self.combo2.id,
        })
        self.assertEqual(row2.sold_to_id, self.partner)
        self.assertEqual(row2.bill_to_id, self.partner)

    def test_06_two_sales_areas_on_partner(self):
        """Customer 360: both SA rows are attached to the partner."""
        self.env['dsd.partner.sales.area'].create([{
            'partner_id': self.partner.id,
            'sales_area_id': self.combo.id,
        }, {
            'partner_id': self.partner.id,
            'sales_area_id': self.combo2.id,
        }])
        self.assertEqual(len(self.partner.sales_area_ids), 2)

    def test_07_no_pricelist_property_sync(self):
        """D9: SA rows NEVER write the partner-level pricelist property —
        pricing resolves from the SA at order time instead."""
        pricelist = self.env['product.pricelist'].create({'name': 'DSD Test PL'})
        partner = self.env['res.partner'].create({'name': 'PL Customer'})
        before = partner.property_product_pricelist
        row = self.env['dsd.partner.sales.area'].create({
            'partner_id': partner.id,
            'sales_area_id': self.combo.id,
            'is_primary': True,
            'pricelist_id': pricelist.id,
        })
        row.write({'pricelist_id': pricelist.id})
        self.assertEqual(partner.property_product_pricelist, before,
                         'partner property must stay untouched by SA rows')
