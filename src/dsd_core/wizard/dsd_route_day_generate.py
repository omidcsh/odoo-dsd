from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.dsd_route import WEEKDAY_FIELDS


class DsdRouteDayGenerate(models.TransientModel):
    _name = 'dsd.route.day.generate.wizard'
    _description = 'Generate Route Day'

    route_id = fields.Many2one(
        'dsd.route', required=True, domain=[('active', '=', True)],
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    weekday = fields.Char(compute='_compute_weekday')
    scheduled_stop_count = fields.Integer(compute='_compute_scheduled_stops')

    @api.depends('date')
    def _compute_weekday(self):
        for wizard in self:
            wizard.weekday = wizard.date.strftime('%A') if wizard.date else False

    @api.depends('route_id', 'date')
    def _compute_scheduled_stops(self):
        for wizard in self:
            wizard.scheduled_stop_count = len(
                wizard._scheduled_stops()) if wizard.route_id and wizard.date else 0

    def _scheduled_stops(self):
        self.ensure_one()
        weekday_field = WEEKDAY_FIELDS[self.date.weekday()]
        return self.route_id.stop_ids.filtered(weekday_field)

    def action_generate(self):
        self.ensure_one()
        RouteDay = self.env['dsd.route.day']
        existing = RouteDay.search([
            ('route_id', '=', self.route_id.id),
            ('date', '=', self.date),
        ], limit=1)
        if existing:
            raise UserError(self.env._(
                "Route day %(day)s already exists for %(route)s on %(date)s. "
                "Open it instead of generating a new one.",
                day=existing.name,
                route=self.route_id.name,
                date=self.date,
            ))
        stops = self._scheduled_stops()
        if not stops:
            raise UserError(self.env._(
                "%(route)s has no stops scheduled on a %(weekday)s.",
                route=self.route_id.name,
                weekday=self.weekday,
            ))
        day = self.route_id._create_route_day(self.date)
        return {
            'type': 'ir.actions.act_window',
            'name': day.name,
            'res_model': 'dsd.route.day',
            'res_id': day.id,
            'view_mode': 'form',
            'target': 'current',
        }
