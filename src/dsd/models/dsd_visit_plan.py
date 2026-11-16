import logging
from datetime import datetime, timedelta, date, timezone

import dateutil.rrule
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .dsd_route import WEEKDAY_FIELDS

_logger = logging.getLogger(__name__)

WEEKDAY_NUMBERS = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}


class DsdVisitPlan(models.Model):
    """Strategic visit plan (SAP Visit Control): which customers a driver
    contacts on which days, recurring. Operational visit lists are generated
    from plans per execution date.
    """
    _name = 'dsd.visit.plan'
    _description = 'DSD Visit Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(copy=False, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], default='draft', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    plan_type_id = fields.Many2one(
        'dsd.visit.plan.type', required=True, string='Plan Type')
    route_id = fields.Many2one('dsd.route', required=True, check_company=True)
    sales_team_id = fields.Many2one('crm.team', string='Sales Team')

    valid_from = fields.Date(required=True, default=lambda self: date.today())
    valid_to = fields.Date()

    # Shipment defaults copied to generated lists (SAP visit plan shipment data)
    driver_id = fields.Many2one(
        'hr.employee', string='Driver',
        domain=[('dsd_active_driver', '=', True)], check_company=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle',
        domain=[('dsd_is_van', '=', True)], check_company=True)
    trailer_id = fields.Many2one(
        'fleet.vehicle', string='Trailer',
        domain=[('dsd_vehicle_type', '=', 'trailer')])
    driver_notes = fields.Text(
        string='Driver Notes', translate=True,
        help='Printed on visit lists and tour manifests for this plan.')

    # Header appointment rule (SAP: e.g. "every two weeks on Tuesdays")
    frequency = fields.Selection([
        ('weekly', 'Weekly Pattern'),
        ('rrule', 'Custom Rule (RRULE)'),
    ], required=True, default='weekly')
    mon = fields.Boolean(string='Monday', default=False)
    tue = fields.Boolean(string='Tuesday', default=False)
    wed = fields.Boolean(string='Wednesday', default=False)
    thu = fields.Boolean(string='Thursday', default=False)
    fri = fields.Boolean(string='Friday', default=False)
    sat = fields.Boolean(string='Saturday', default=False)
    sun = fields.Boolean(string='Sunday', default=False)
    interval_weeks = fields.Integer(
        default=1, required=True,
        help='Visit every N weeks (1 = every week on the selected days).')
    anchor_date = fields.Date(
        default=lambda self: date.today().replace(day=1),
        help='Week pattern is aligned to this date; e.g. a two-week interval '
             'visits on weeks whose Monday is 0, 2, 4... weeks after it.')
    recurrence_rrule = fields.Text(
        string='RRULE',
        placeholder='FREQ=WEEKLY;INTERVAL=2;BYDAY=TU',
        help='RFC 5545 recurrence evaluated from the anchor date. Used when the '
             'frequency is "Custom Rule (RRULE)".')

    # Non-working-day handling (SAP calendar handling)
    calendar_id = fields.Many2one(
        'resource.calendar', string='Working Calendar',
        help='Working days and global leaves of this calendar decide which dates '
             'are non-working.')
    nonworking_policy = fields.Selection([
        ('skip', 'Skip the visit'),
        ('previous', 'Move to previous working day'),
        ('next', 'Move to next working day'),
    ], required=True, default='skip')

    line_ids = fields.One2many('dsd.visit.plan.line', 'plan_id', string='Customers')
    line_count = fields.Integer(compute='_compute_line_count')
    last_execution_date = fields.Date(
        string='Last Generated Date', copy=False, readonly=True,
        help='Generation watermark: lists are only generated for dates after this one.')
    planned_list_ids = fields.One2many('dsd.visit.list', 'plan_id', string='Visit Lists')
    planned_list_count = fields.Integer(compute='_compute_planned_list_count')

    _interval_positive = models.Constraint(
        'CHECK (interval_weeks >= 1)',
        'The visit interval must be at least one week.',
    )

    def _compute_line_count(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)

    def _compute_planned_list_count(self):
        counts = self.env['dsd.visit.list'].read_group(
            [('plan_id', 'in', self.ids)], ['plan_id'], ['plan_id'])
        by_plan = {row['plan_id'][0]: row['plan_id_count'] for row in counts}
        for plan in self:
            plan.planned_list_count = by_plan.get(plan.id, 0)

    @api.constrains('valid_from', 'valid_to')
    def _check_validity(self):
        for plan in self:
            if plan.valid_to and plan.valid_from and plan.valid_from > plan.valid_to:
                raise ValidationError(self.env._(
                    'The validity end must be after its start on plan %s.', plan.name))

    @api.constrains('line_ids')
    def _check_lines(self):
        for plan in self:
            partners = plan.line_ids.mapped('partner_id')
            if len(partners) != len(plan.line_ids):
                raise ValidationError(self.env._(
                    'Customer %s appears more than once on plan %s.',
                    partners.mapped('display_name'), plan.name))

    @api.constrains('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'frequency',
                    'recurrence_rrule')
    def _check_recurrence(self):
        for plan in self:
            if plan.frequency == 'weekly':
                if not any(plan[f] for f in WEEKDAY_FIELDS):
                    raise ValidationError(self.env._(
                        'Plan %s must visit on at least one weekday.', plan.name))
            else:
                try:
                    plan._rrule(date.today(), date.today() + timedelta(days=1))
                except (ValueError, TypeError):
                    raise ValidationError(self.env._(
                        'The recurrence rule of plan %s cannot be parsed. '
                        'Example: FREQ=WEEKLY;INTERVAL=2;BYDAY=TU', plan.name)) from None

    # ------------------------------------------------------------------
    # Recurrence engine
    # ------------------------------------------------------------------

    def _rrule(self, range_start, range_end):
        """Materialize the header appointment rule into concrete dates."""
        self.ensure_one()
        if self.frequency == 'weekly':
            weekdays = sorted(WEEKDAY_NUMBERS[f] for f in WEEKDAY_FIELDS if self[f])
            rule = dateutil.rrule.rrule(
                dateutil.rrule.WEEKLY,
                interval=self.interval_weeks,
                byweekday=weekdays,
                dtstart=datetime.combine(self.anchor_date or range_start, datetime.min.time()),
            )
            return [dt.date() for dt in rule.between(
                datetime.combine(range_start, datetime.min.time()),
                datetime.combine(range_end, datetime.min.time()),
                inc=True)]
        rule = dateutil.rrule.rrulestr(
            self.recurrence_rrule,
            dtstart=datetime.combine(self.anchor_date or range_start, datetime.min.time()))
        return [dt.date() if isinstance(dt, datetime) else dt for dt in rule.between(
            datetime.combine(range_start, datetime.min.time()),
            datetime.combine(range_end, datetime.min.time()),
            inc=True)]

    def _is_nonworking(self, day):
        """A date is non-working when the plan calendar has no work intervals
        on it (attendance hours or global leaves). Intervals are evaluated in
        UTC day boundaries (calendars no longer carry their own timezone)."""
        self.ensure_one()
        if not self.calendar_id:
            return False
        day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        intervals = self.calendar_id._work_intervals_batch(day_start, day_end)
        for calendar_intervals in intervals.values():
            if any(interval[0].date() == day for interval in calendar_intervals):
                return False
        return True

    def _resolve_execution_date(self, occurrence):
        """Apply the non-working-day policy to a planned occurrence date."""
        self.ensure_one()
        if not self._is_nonworking(occurrence):
            return occurrence
        if self.nonworking_policy == 'skip':
            return None
        step = -1 if self.nonworking_policy == 'previous' else 1
        candidate = occurrence
        for _days in range(31):
            candidate += timedelta(days=step)
            if not self._is_nonworking(candidate):
                return candidate
        return None

    def _occurrence_dates(self, range_start, range_end):
        """Candidate execution dates between the bounds, validity and
        non-working policy applied, deduplicated and sorted."""
        self.ensure_one()
        result = []
        for occurrence in self._rrule(range_start, range_end):
            if self.valid_from and occurrence < self.valid_from:
                continue
            if self.valid_to and occurrence > self.valid_to:
                continue
            resolved = self._resolve_execution_date(occurrence)
            if resolved and resolved not in result:
                result.append(resolved)
        return sorted(result)

    def action_view_lists(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Visit Lists'),
            'res_model': 'dsd.visit.list',
            'view_mode': 'list,form,calendar',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    def action_set_active(self):
        for plan in self:
            if not plan.line_ids:
                raise ValidationError(self.env._(
                    'Plan %s needs at least one customer before it can be activated.',
                    plan.name))
            plan.state = 'active'

    def action_set_draft(self):
        self.state = 'draft'

    def action_set_closed(self):
        self.state = 'closed'

    # ------------------------------------------------------------------
    # List generation (SAP "Create Lists")
    # ------------------------------------------------------------------

    def _generate_list_for_date(self, day, dry_run=False):
        """Generate the visit list for one execution date.

        Returns (status, detail): status is 'created' (detail = the new list),
        'exists', 'watermark' or 'no_customers' (detail = explanation string).
        """
        self.ensure_one()
        VisitList = self.env['dsd.visit.list']
        existing = VisitList.search([
            ('plan_id', '=', self.id),
            ('execution_date', '=', day),
            ('state', '!=', 'cancelled'),
        ])
        if existing:
            return 'exists', existing
        if self.last_execution_date and day <= self.last_execution_date and not dry_run:
            return 'watermark', self.env._(
                'on or before the last generated date (%s)', self.last_execution_date)
        active_lines = self.line_ids.filtered(
            lambda ln: not ln.inactive
            and not any(exc.date == day for exc in ln.exception_ids))
        if not active_lines:
            return 'no_customers', self.env._('all customers inactive or non-appointments')
        if dry_run:
            return 'created', VisitList.browse()
        visit_list = VisitList.create({
            'plan_id': self.id,
            'plan_type_id': self.plan_type_id.id,
            'route_id': self.route_id.id,
            'execution_date': day,
            'driver_id': self.driver_id.id,
            'vehicle_id': self.vehicle_id.id,
            'trailer_id': self.trailer_id.id,
            'driver_notes': self.driver_notes,
            'line_ids': [
                (0, 0, {
                    'sequence': line.sequence,
                    'partner_id': line.partner_id.id,
                    'waiting_minutes': line.waiting_minutes,
                    'travel_minutes': line.travel_minutes,
                    'unloading_point_id': line.unloading_point_id.id,
                    'contact_id': line.contact_id.id,
                    'customer_notes': line.customer_notes,
                })
                for line in active_lines
            ],
        })
        return 'created', visit_list
