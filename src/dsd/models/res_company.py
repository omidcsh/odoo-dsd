from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # --- DSD process settings (exposed on res.config.settings) ---
    dsd_default_warehouse_id = fields.Many2one(
        'stock.warehouse', string='DSD Default Warehouse')
    dsd_planning_horizon_days = fields.Integer(default=21)
    dsd_stock_visibility = fields.Boolean(
        string='DSD Stock Visibility', default=True,
        help='Van stock is isolated from warehouse availability: warehouse orders '
             'never reserve goods sitting on a van.')
    dsd_loading_confirmation_required = fields.Boolean(default=True)
    dsd_checkout_required = fields.Boolean(string='Check-Out Required', default=True)
    dsd_checkin_required = fields.Boolean(string='Check-In Required', default=True)
    dsd_auto_release_when_clean = fields.Boolean(
        string='Auto-release Clean Settlements', default=False)
    dsd_settlement_trigger = fields.Selection([
        ('manual', 'Manual'),
        ('auto_clean', 'Automatic when no blocking differences'),
    ], string='Settlement Trigger', default='manual')

    # --- Financial wiring for route settlement ---
    dsd_cash_journal_id = fields.Many2one(
        'account.journal', string='DSD Cash Journal',
        domain=[('type', '=', 'cash')])
    dsd_inv_diff_gain_account_id = fields.Many2one(
        'account.account', string='Inventory Difference Gain Account',
        domain=[('deprecated', '=', False)], check_company=False)
    dsd_inv_diff_loss_account_id = fields.Many2one(
        'account.account', string='Inventory Difference Loss Account',
        domain=[('deprecated', '=', False)], check_company=False)
    dsd_cash_diff_account_id = fields.Many2one(
        'account.account', string='Cash Difference Account',
        domain=[('deprecated', '=', False)], check_company=False)
    dsd_driver_clearing_account_id = fields.Many2one(
        'account.account', string='Driver Cash Custody Clearing Account',
        domain=[('deprecated', '=', False)], check_company=False)
