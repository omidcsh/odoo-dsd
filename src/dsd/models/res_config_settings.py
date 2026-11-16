from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dsd_default_warehouse_id = fields.Many2one(
        related='company_id.dsd_default_warehouse_id', readonly=False)
    dsd_planning_horizon_days = fields.Integer(
        related='company_id.dsd_planning_horizon_days', readonly=False)
    dsd_stock_visibility = fields.Boolean(
        related='company_id.dsd_stock_visibility', readonly=False)
    dsd_loading_confirmation_required = fields.Boolean(
        related='company_id.dsd_loading_confirmation_required', readonly=False)
    dsd_checkout_required = fields.Boolean(
        related='company_id.dsd_checkout_required', readonly=False)
    dsd_checkin_required = fields.Boolean(
        related='company_id.dsd_checkin_required', readonly=False)
    dsd_auto_release_when_clean = fields.Boolean(
        related='company_id.dsd_auto_release_when_clean', readonly=False)
    dsd_settlement_trigger = fields.Selection(
        related='company_id.dsd_settlement_trigger', readonly=False)
    dsd_cash_journal_id = fields.Many2one(
        related='company_id.dsd_cash_journal_id', readonly=False)
    dsd_inv_diff_gain_account_id = fields.Many2one(
        related='company_id.dsd_inv_diff_gain_account_id', readonly=False)
    dsd_inv_diff_loss_account_id = fields.Many2one(
        related='company_id.dsd_inv_diff_loss_account_id', readonly=False)
    dsd_cash_diff_account_id = fields.Many2one(
        related='company_id.dsd_cash_diff_account_id', readonly=False)
    dsd_driver_clearing_account_id = fields.Many2one(
        related='company_id.dsd_driver_clearing_account_id', readonly=False)
