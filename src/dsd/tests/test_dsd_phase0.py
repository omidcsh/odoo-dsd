from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDsdMasterData(TransactionCase):

    def test_driver_code_sequence(self):
        driver1 = self.env['hr.employee'].create({
            'name': 'Driver One',
            'dsd_active_driver': True,
        })
        driver2 = self.env['hr.employee'].create({
            'name': 'Driver Two',
            'dsd_active_driver': True,
        })
        self.assertTrue(driver1.dsd_code, 'driver code assigned on create')
        self.assertTrue(driver2.dsd_code)
        self.assertNotEqual(driver1.dsd_code, driver2.dsd_code)

    def test_driver_code_on_activate(self):
        employee = self.env['hr.employee'].create({'name': 'Later Driver'})
        self.assertFalse(employee.dsd_code)
        employee.dsd_active_driver = True
        self.assertTrue(employee.dsd_code, 'driver code assigned when activated')

    def test_driver_discount_bounds(self):
        driver = self.env['hr.employee'].create({
            'name': 'Discount Driver',
            'dsd_active_driver': True,
            'dsd_max_discount_pct': 5,
        })
        with self.assertRaises(ValidationError):
            driver.dsd_max_discount_pct = 150

    def test_settlement_partner_lazy_create(self):
        driver = self.env['hr.employee'].create({
            'name': 'Custody Driver',
            'dsd_active_driver': True,
        })
        partner = driver._get_or_create_settlement_partner()
        self.assertEqual(driver.dsd_settlement_partner_id, partner)
        again = driver._get_or_create_settlement_partner()
        self.assertEqual(again, partner, 'settlement partner created once')


@tagged('post_install', '-at_install')
class TestDsdVanLocation(TransactionCase):

    def setUp(self):
        super().setUp()
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'DSD Test Brand'})
        self.model = self.env['fleet.vehicle.model'].create({
            'name': 'DSD Test Van', 'brand_id': brand.id})

    def _create_van(self, plate):
        return self.env['fleet.vehicle'].create({
            'model_id': self.model.id,
            'license_plate': plate,
            'dsd_vehicle_type': 'van',
        })

    def test_van_location_auto_created(self):
        van = self._create_van('T-DSD-001')
        self.assertTrue(van.dsd_van_location_id, 'van location created')
        self.assertEqual(van.dsd_van_location_id.usage, 'internal')
        self.assertIn('T-DSD-001', van.dsd_van_location_id.name)
        self.assertTrue(van.dsd_van_damaged_location_id, 'damaged sub-location created')
        self.assertEqual(
            van.dsd_van_damaged_location_id.location_id,
            van.dsd_van_location_id)

    def test_van_location_archived_when_not_van(self):
        van = self._create_van('T-DSD-002')
        location = van.dsd_van_location_id
        damaged = van.dsd_van_damaged_location_id
        van.dsd_is_van = False
        self.assertFalse(location.active, 'van location archived')
        self.assertFalse(damaged.active, 'damaged location archived')
        van.dsd_is_van = True
        self.assertTrue(location.active, 'van location reactivated')
        self.assertTrue(damaged.active)

    def test_van_location_idempotent(self):
        van = self._create_van('T-DSD-003')
        location = van.dsd_van_location_id
        van.license_plate = 'T-DSD-003B'
        van._sync_van_location()
        self.assertEqual(van.dsd_van_location_id, location, 'no duplicate location')


@tagged('post_install', '-at_install')
class TestDsdRoute(TransactionCase):

    def _route_vals(self, **kwargs):
        vals = {
            'name': 'Test Route',
            'code': 'TROUTE',
            'warehouse_id': self.env['stock.warehouse'].search([], limit=1).id,
        }
        vals.update(kwargs)
        return vals

    def test_no_serving_day(self):
        vals = self._route_vals(mon=False, tue=False, wed=False, thu=False,
                                fri=False, sat=False, sun=False)
        with self.assertRaises(ValidationError):
            self.env['dsd.route'].create(vals)

    def test_stop_limit_requires_value(self):
        with self.assertRaises(ValidationError):
            self.env['dsd.route'].create(self._route_vals(
                cap_stops=True, max_stops=0))

    def test_duration_limit_requires_value(self):
        with self.assertRaises(ValidationError):
            self.env['dsd.route'].create(self._route_vals(
                cap_duration=True, max_duration_hours=0))

    def test_attempts_at_least_one(self):
        with self.assertRaises(ValidationError):
            self.env['dsd.route'].create(self._route_vals(max_load_attempts=0))

    def test_unique_code_per_company(self):
        self.env['dsd.route'].create(self._route_vals())
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['dsd.route'].create(self._route_vals(name='Other Route'))

    def test_partner_count_computes(self):
        """Regression: this computed field used the pre-17 read_group
        signature and crashed the route form on read."""
        route = self.env['dsd.route'].create(self._route_vals())
        self.assertEqual(route.partner_count, 0)
        self.env['res.partner'].create(
            {'name': 'RC One', 'dsd_route_id': route.id})
        self.env['res.partner'].create(
            {'name': 'RC Two', 'dsd_route_id': route.id})
        self.assertEqual(route.partner_count, 2)


@tagged('post_install', '-at_install')
class TestDsdConfigModels(TransactionCase):

    def test_license_category_code_unique(self):
        self.env['dsd.license.category'].create({'name': 'B', 'code': 'X1'})
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['dsd.license.category'].create({'name': 'B2', 'code': 'X1'})

    def test_lock_period_needs_target_and_order(self):
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['dsd.lock.period'].create({
                'date_from': '2026-11-01', 'date_to': '2026-11-05'})
        employee = self.env['hr.employee'].create({
            'name': 'Locked Driver', 'dsd_active_driver': True})
        with self.assertRaises(ValidationError):
            self.env['dsd.lock.period'].create({
                'employee_id': employee.id,
                'date_from': '2026-11-05', 'date_to': '2026-11-01'})
        lock = self.env['dsd.lock.period'].create({
            'employee_id': employee.id,
            'date_from': '2026-11-01', 'date_to': '2026-11-05'})
        self.assertTrue(lock.name)

    def test_tolerance_group_line_rules(self):
        group = self.env['dsd.tolerance.group'].create({'name': 'G'})
        group.line_ids = [Command.create({
            'check_kind': 'qty_abs', 'threshold': 2, 'severity': 'warn'})]
        with self.assertRaises(ValidationError):
            group.line_ids = [Command.create({
                'check_kind': 'qty_abs', 'threshold': 3, 'severity': 'warn'})]

    def test_counting_group_rules(self):
        group = self.env['dsd.counting.group'].create({'name': 'CG', 'code': 'CG1'})
        uom = self.ref('uom.product_uom_unit')
        group.uom_line_ids = [Command.create({'uom_id': uom, 'sequence': 10})]
        with self.assertRaises(ValidationError):
            group.uom_line_ids = [Command.create({'uom_id': uom, 'sequence': 20})]

    def test_partner_collection_profile_requires_journal(self):
        with self.assertRaises(ValidationError):
            self.env['res.partner'].create({
                'name': 'Bad Collector',
                'dsd_collection_type': 'on_delivery'})

    def test_product_counting_group_requires_storable(self):
        group = self.env['dsd.counting.group'].create({'name': 'CG', 'code': 'CG-T'})
        service = self.env['product.template'].create({
            'name': 'Delivery Service', 'type': 'service'})
        with self.assertRaises(ValidationError):
            service.counting_group_id = group

    def test_product_aggregation_factor_positive(self):
        aggregation = self.env['dsd.aggregation'].create({
            'name': 'Units', 'code': 'UNIT-T',
            'uom_id': self.ref('uom.product_uom_unit')})
        product = self.env['product.template'].create({
            'name': 'Agg Product', 'type': 'consu', 'is_storable': True})
        line = self.env['dsd.product.aggregation'].create({
            'product_tmpl_id': product.id,
            'aggregation_id': aggregation.id,
            'factor': 1})
        with self.assertRaises(ValidationError):
            line.factor = 0
        with self.assertRaises(ValidationError):
            line.factor = -1

    def test_company_defaults(self):
        company = self.env.company
        self.assertEqual(company.dsd_planning_horizon_days, 21)
        self.assertTrue(company.dsd_stock_visibility)
        self.assertTrue(company.dsd_checkin_required)
        self.assertEqual(company.dsd_settlement_trigger, 'manual')
