from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # --- Visit information (SAP customer master "Visit Information" tab) ---
    dsd_route_id = fields.Many2one(
        'dsd.route', string='DSD Route', index='btree_not_null',
        help='Route serving this customer; also proposed on their sale orders.')
    dsd_visit_required = fields.Boolean(
        string='Requires Visits', default=True,
        help='Suggest this customer when composing visit plans.')
    dsd_receiving_hours = fields.Char(
        string='Receiving Hours',
        help='Free-form goods receiving hours, e.g. "Mon–Fri 08:00–12:00, 13:00–17:00".')
    dsd_unloading_point_id = fields.Many2one(
        'res.partner', string='Unloading Point',
        help='Specific delivery address or contact at the customer site '
             '(typically a child contact of this customer).')
    dsd_driver_notes = fields.Text(
        string='Driver Notes',
        help='Printed on the tour manifest for the driver.')

    # --- Payment & document profile (SAP Enhanced Terms of Payment) ---
    dsd_collection_type = fields.Selection([
        ('none', 'No collection on tour'),
        ('on_delivery', 'Collect on delivery'),
    ], string='Collection Type', default='none')
    dsd_accepted_journal_ids = fields.Many2many(
        'account.journal', string='Accepted Payment Methods',
        domain=[('type', 'in', ('cash', 'bank', 'check'))])
    dsd_pod_or_invoice = fields.Selection([
        ('pod', 'Proof of Delivery'),
        ('invoice', 'Invoice'),
    ], string='Print at Stop', default='pod',
        help='What the driver hands over when confirming a delivery.')
    dsd_invoice_generation = fields.Selection([
        ('auto', 'Per stop (automatic)'),
        ('manual', 'Per stop (driver decision)'),
        ('consolidated', 'Consolidated per tour'),
    ], string='Invoice Generation', default='auto')
    dsd_cash_only = fields.Boolean(
        string='Cash Only',
        help='Driver may only accept cash from this customer.')
    dsd_credit_limit = fields.Float(
        string='DSD Credit Limit',
        help='Console credit gate for on-the-road invoicing, on top of standard accounting.')
    dsd_customer_group_id = fields.Many2one(
        'res.partner.category', string='Customer Group',
        help='Used by assortment rules and deal-condition assignments.')

    # --- Identity ---
    dsd_barcode = fields.Char(
        string='DSD Barcode',
        help='GLN/EAN or customer number; printed as a barcode on the manifest '
             'so drivers scan to open the stop.')
    dsd_is_one_time = fields.Boolean(string='One-Time Customer')

    @api.constrains('dsd_collection_type', 'dsd_accepted_journal_ids', 'dsd_cash_only')
    def _check_collection_profile(self):
        for partner in self:
            if partner.dsd_collection_type == 'on_delivery' \
                    and not partner.dsd_accepted_journal_ids:
                raise ValidationError(self.env._(
                    'Customer %s collects on delivery but accepts no payment method.',
                    partner.name))
