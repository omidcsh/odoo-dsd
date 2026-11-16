from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdDriver(models.Model):
    """Driver master (SAP models drivers in the customer master; we extend
    hr.employee instead, keeping HR availability/expenses and an optional
    auto-created settlement partner for cash custody postings).
    """
    _inherit = 'hr.employee'

    dsd_active_driver = fields.Boolean(
        string='Active DSD Driver', index='btree_not_null',
        help='Include this employee in DSD driver selection.')
    dsd_code = fields.Char(
        string='DSD Code', copy=False, index='btree_not_null', tracking=True)
    license_category_ids = fields.Many2many(
        'dsd.license.category', string='License Categories')
    default_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Default Vehicle',
        domain=[('dsd_is_van', '=', True), ('dsd_vehicle_type', '!=', 'trailer')])
    default_route_ids = fields.Many2many('dsd.route', string='Default Routes')
    dsd_sales_team_id = fields.Many2one(
        'crm.team', string='Sales Team',
        help='Orders and tours of this driver are expected to stay within this team '
             '(single sales-area parity check).')
    dsd_max_discount_pct = fields.Float(
        string='Max Manual Discount %', digits=(16, 2),
        help='Highest discount the driver may grant on the road without back-office '
             'approval. 0 = no manual discounts.')
    dsd_cash_journal_id = fields.Many2one(
        'account.journal', string='Cash Custody Journal',
        domain=[('type', '=', 'cash')], check_company=True,
        help='Per-driver cash journal; defaults to the company DSD cash journal.')
    dsd_settlement_partner_id = fields.Many2one(
        'res.partner', string='Cash Custody Partner', copy=False,
        help='Auto-created on first settlement; carries the driver cash custody balance.')
    dsd_lock_ids = fields.One2many(
        'dsd.lock.period', 'employee_id', string='Lock Periods')

    @api.constrains('dsd_max_discount_pct')
    def _check_discount(self):
        for driver in self:
            if driver.dsd_max_discount_pct < 0 or driver.dsd_max_discount_pct > 100:
                raise ValidationError(self.env._(
                    'The manual discount authority of %s must be between 0 and 100.',
                    driver.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('dsd_active_driver') and not vals.get('dsd_code'):
                vals['dsd_code'] = self.env['ir.sequence'].next_by_code('dsd.driver')
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('dsd_active_driver'):
            for driver in self:
                if not driver.dsd_code and not vals.get('dsd_code'):
                    driver.dsd_code = self.env['ir.sequence'].next_by_code('dsd.driver')
        return super().write(vals)

    def action_view_locks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lock Periods'),
            'res_model': 'dsd.lock.period',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def _get_or_create_settlement_partner(self):
        """Lazy-create the cash-custody partner used by settlement postings."""
        self.ensure_one()
        if self.dsd_settlement_partner_id:
            return self.dsd_settlement_partner_id
        partner = self.env['res.partner'].create({
            'name': self.env._('Cash custody — %s', self.name),
            'supplier_rank': 1,
            'customer_rank': 1,
            'comment': _('Auto-created DSD driver cash custody account.'),
        })
        self.dsd_settlement_partner_id = partner
        return partner
