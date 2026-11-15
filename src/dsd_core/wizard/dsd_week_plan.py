from datetime import timedelta

from odoo import api, fields, models
from odoo.tools.translate import _

from ..models.dsd_route import WEEKDAY_FIELDS


class DsdWeekPlan(models.TransientModel):
    _name = 'dsd.week.plan.wizard'
    _description = 'Plan Visits for a Week'

    week_start = fields.Date(
        required=True,
        default=lambda self: self._default_week_start(),
        help='First day of the week to plan; the following 7 days are '
             'planned from here.',
    )
    route_ids = fields.Many2many(
        'dsd.route', string='Routes',
        domain=[('active', '=', True)],
        default=lambda self: self.env['dsd.route'].search([]),
    )

    @api.model
    def _default_week_start(self):
        today = fields.Date.context_today(self)
        return today - timedelta(days=today.weekday())

    def action_plan_week(self):
        """Generate a route day for every route/day with scheduled stops,
        skipping days that already exist."""
        self.ensure_one()
        RouteDay = self.env['dsd.route.day']
        created = RouteDay
        for route in self.route_ids:
            for offset in range(7):
                date = self.week_start + timedelta(days=offset)
                weekday_field = WEEKDAY_FIELDS[date.weekday()]
                if not route.stop_ids.filtered(weekday_field):
                    continue
                if RouteDay.search([
                    ('route_id', '=', route.id), ('date', '=', date),
                ], limit=1):
                    continue
                created += route._create_route_day(date)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._(
                '%(count)s route day(s) planned', count=len(created)),
            'res_model': 'dsd.route.day',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
            'target': 'current',
        }
