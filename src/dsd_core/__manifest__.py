{
    'name': 'DSD Core',
    'version': '20.0.1.2.0',
    'category': 'Services/Direct Store Delivery',
    'summary': 'DSD base: sales-area master data (org/channel/division, valid combinations, customer sales areas)',
    'description': """
Direct Store Delivery — core master data (step 1).

SAP SD sales-area structure on Odoo:

- three master catalogs: sales organization (VKORG), distribution
  channel (VTWEG), division (SPART)
- dsd.sales.area: the valid-combination entity (SAP TVTA equivalent) —
  unique(sales org, distribution channel, division); future home of the
  per-area customizing flags (MSE_CUST_SALES_AREA)
- dsd.partner.sales.area: the customer x sales-area relationship with
  document blocks (sale/delivery/billing — distinct from active),
  partner functions (payer/sold-to/ship-to/bill-to), plant (stock.warehouse)
  and pricelist (product.pricelist — Odoo-native pricing decision)

Spec: docs/plans/2026-11-18-sales-area.md (v2.1).
    """,
    'author': 'Omid Shokri',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'stock',
    ],
    'data': [
        'security/dsd_security.xml',
        'security/ir.access.csv',
        'views/dsd_sales_area_views.xml',
        'views/dsd_partner_sales_area_views.xml',
        'views/dsd_route_views.xml',
        'views/res_partner_views.xml',
        'views/dsd_menus.xml',
    ],
    'installable': True,
    'application': False,
}
