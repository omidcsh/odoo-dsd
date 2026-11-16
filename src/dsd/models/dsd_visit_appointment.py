import datetime as dt_mod

from odoo import _, api, fields, models


class DsdVisitAppointment(models.Model):
    """Materialized customer time stream (SAP time stream / /DSD/VC_CAL_FILL):
    the concrete planned visit and delivery dates per customer, maintained by
    the fill cron from active visit plans and by visit-list synchronization.
    Consumed by order entry (requested delivery date + route proposal) and by
    the customer's upcoming-visits display.
    """
    _name = 'dsd.visit.appointment'
    _description = 'DSD Visit Appointment'
    _order = 'partner_id, date'
    _rec_name = 'display_label'

    partner_id = fields.Many2one('res.partner', required=True, index='btree')
    date = fields.Date(required=True, index='btree')
    kind = fields.Selection([
        ('visit', 'Visit'),
        ('delivery', 'Delivery'),
    ], required=True, default='visit')
    plan_id = fields.Many2one('dsd.visit.plan', index='btree_not_null')
    visit_list_id = fields.Many2one('dsd.visit.list', index='btree_not_null')
    route_id = fields.Many2one('dsd.route', index='btree_not_null')
    company_id = fields.Many2one('res.company', required=True)
    display_label = fields.Char(compute='_compute_display_label')

    _partner_date_kind_unique = models.Constraint(
        'unique(partner_id, date, kind)',
        'Only one visit and one delivery appointment per customer and date.',
    )

    @api.depends('partner_id', 'date', 'kind')
    def _compute_display_label(self):
        for appointment in self:
            kind_label = dict(self._fields['kind']._description_selection(self.env))
            appointment.display_label = self.env._(
                '%(kind)s on %(date)s — %(customer)s',
                kind=kind_label.get(appointment.kind, ''),
                date=appointment.date,
                customer=appointment.partner_id.display_name,
            )

    @api.model
    def cron_fill_appointments(self):
        """Nightly: materialize plan occurrences ahead of the planning horizon."""
        for company in self.env['res.company'].search([]):
            company = company.with_company(company)
            horizon = max(company.dsd_planning_horizon_days, 1)
            today = fields.Date.context_today(company)
            range_end = today + dt_mod.timedelta(days=horizon)
            plans = company.env['dsd.visit.plan'].search([
                ('state', '=', 'active'),
                ('company_id', '=', company.id),
            ])
            self._fill_from_plans(plans, today, range_end)
        return True

    @api.model
    def _fill_from_plans(self, plans, date_from, date_to):
        """Create plan-based appointments (visit_list_id empty) for the range."""
        Appointment = self.env['dsd.visit.appointment']
        created = Appointment.browse()
        for plan in plans:
            kind = 'delivery' if plan.plan_type_id.make_delivery else 'visit'
            dates = plan._occurrence_dates(date_from, date_to)
            for line in plan.line_ids.filtered(
                    lambda ln: not ln.inactive and ln.partner_id.dsd_route_id):
                for day in dates:
                    if any(exc.date == day for exc in line.exception_ids):
                        continue
                    existing = Appointment.search_count([
                        ('partner_id', '=', line.partner_id.id),
                        ('date', '=', day),
                        ('kind', '=', kind),
                    ])
                    if not existing:
                        created |= Appointment.create({
                            'partner_id': line.partner_id.id,
                            'date': day,
                            'kind': kind,
                            'plan_id': plan.id,
                            'route_id': plan.route_id.id,
                            'company_id': plan.company_id.id,
                        })
        return created
