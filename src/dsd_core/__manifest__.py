{
    'name': 'DSD Core',
    'version': '20.0.1.0.0',
    'category': 'Services/Direct Store Delivery',
    'summary': 'Direct Store Delivery: routes, route days and store visits',
    'description': """
Foundations for Direct Store Delivery on Odoo:
- Route templates with ordered store stops and weekday frequency
- Route modes: presale, van sales, or mixed
- Vans modeled as internal stock locations paired with fleet vehicles
""",
    'author': 'Omid Shokri',
    'license': 'LGPL-3',
    'depends': ['stock', 'stock_fleet', 'sale_management', 'account'],
    'data': [
        'security/dsd_security.xml',
        'security/ir.access.csv',
        'views/dsd_route_views.xml',
    ],
    'demo': [
        'demo/dsd_demo.xml',
    ],
    'installable': True,
    'application': True,
}
