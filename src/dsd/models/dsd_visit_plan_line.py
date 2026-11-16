import datetime as dt_mod

from odoo import _, api, fields, models


class DsdVisitPlanLine(models.Model):
    """One customer on a strategic visit plan, with its stop position and
    per-customer visit data (SAP visit plan item).
    """
    _name = 'dsd.visit.plan.line'
    _description = 'DSD Visit Plan Line'
    _order = 'plan_id, sequence, id'
    _rec_name = 'partner_id'

    plan_id = fields.Many2one('dsd.visit.plan', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='plan_id.company_id')
    currency_id = fields.Many2one(related='plan_id.company_id.currency_id')
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one(
        'res.partner', required=True, string='Customer',
        domain=[('is_company', 'in', (True, False))])
    waiting_minutes = fields.Integer(default=15)
    travel_minutes = fields.Integer(default=20)
    unloading_point_id = fields.Many2one(
        'res.partner', string='Unloading Point',
        help='Defaults from the customer; per-type settings decide which source '
             'plan items display.')
    contact_id = fields.Many2one('res.partner', string='Contact Person')
    inactive = fields.Boolean(
        help='Inactive customers are skipped when visit lists are generated.')
    customer_notes = fields.Text(string='Customer Notes')
    exception_ids = fields.One2many(
        'dsd.visit.plan.line.exception', 'line_id', string='Non-Appointments')
    next_occurrence_date = fields.Date(compute='_compute_next_occurrence_date')

    @api.depends('plan_id', 'inactive', 'exception_ids.date')
    def _compute_next_occurrence_date(self):
        today = fields.Date.context_today(self)
        for line in self:
            line.next_occurrence_date = line._get_next_occurrence(today)

    def _get_next_occurrence(self, after):
        self.ensure_one()
        plan = self.plan_id
        if plan.state != 'active' or self.inactive:
            return False
        horizon = after + dt_mod.timedelta(days=plan.company_id.dsd_planning_horizon_days)
        for occurrence in plan._occurrence_dates(after, horizon):
            if any(exc.date == occurrence for exc in self.exception_ids):
                continue
            return occurrence
        return False

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for line in self:
            partner = line.partner_id
            if partner:
                line.unloading_point_id = partner.dsd_unloading_point_id or False
                line.contact_id = partner.user_id.partner_id if partner.user_id else False


class DsdVisitPlanLineException(models.Model):
    """Non-appointment: a date on which this customer is not visited
    (SAP item-level appointment rule / non-appointments)."""
    _name = 'dsd.visit.plan.line.exception'
    _description = 'DSD Visit Plan Non-Appointment'
    _order = 'line_id, date'
    _rec_name = 'date'

    line_id = fields.Many2one('dsd.visit.plan.line', required=True, ondelete='cascade')
    date = fields.Date(required=True)
    reason = fields.Char()

    _line_date_unique = models.Constraint(
        'unique(line_id, date)',
        'This customer already has a non-appointment on that date.',
    )
