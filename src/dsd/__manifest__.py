{
    'name': 'Direct Store Delivery',
    'version': '20.0.0.1.0',
    'category': 'Services/Direct Store Delivery',
    'summary': 'SAP-style DSD on Odoo: visit planning, tours, van stock, route settlement',
    'description': """
Direct Store Delivery for consumer-goods distribution.

Implements the four SAP DSD pillars natively on Odoo 20:

- DSD master data: routes, drivers, vans, counting groups, tolerances, assortments
- Visit control: strategic visit plans and operational visit lists
- Tour preparation and execution: tours on stock.picking.batch, van stock,
  loading confirmation, check-out/check-in, driver console
- Route accounting: difference determination, final settlement run,
  collection clearing

See docs/dsd-implementation-plan.md (v2) for the full specification.
    """,
    'author': 'Omid Shokri',
    'license': 'LGPL-3',
    'depends': [
        'sale_stock',
        'stock_fleet',
        'hr_expense',
        'account_payment',
        'base_geolocalize',
    ],
    'data': [
        'security/dsd_security.xml',
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'data/dsd_master_data.xml',
        'views/res_config_settings_views.xml',
        'views/dsd_route_views.xml',
        'views/dsd_driver_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/product_template_views.xml',
        'views/dsd_config_views.xml',
        'views/dsd_visit_views.xml',
        'views/dsd_visit_list_generate_views.xml',
        'views/stock_picking_batch_views.xml',
        'views/dsd_execution_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/dsd_menus.xml',
    ],
    'demo': [
        'demo/dsd_demo.xml',
    ],
    'installable': True,
    'application': True,
}
