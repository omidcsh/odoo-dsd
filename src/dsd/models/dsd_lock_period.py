from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdLockPeriod(models.Model):
    """Availability lock for a driver or a vehicle (SAP: Lock Times / Lock Periods).

    Tours must not default-assign a locked driver/vehicle for the execution date.
    """
    _name = 'dsd.lock.period'
    _description = 'DSD Lock Period'
    _order = 'date_from'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Driver',
        domain=[('dsd_active_driver', '=', True)], index='btree_not_null')
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle',
        domain=[('dsd_is_van', '=', True)], index='btree_not_null')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    reason = fields.Char()
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', store=True, readonly=True)

    _driver_or_vehicle = models.Constraint(
        'CHECK (employee_id IS NOT NULL OR vehicle_id IS NOT NULL)',
        'A lock period must apply to a driver or a vehicle.',
    )

    @api.depends('employee_id', 'vehicle_id', 'date_from', 'date_to')
    def _compute_name(self):
        for lock in self:
            who = lock.employee_id.name or lock.vehicle_id.name or _('Unknown')
            lock.name = f"{who}: {lock.date_from} → {lock.date_to}"

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for lock in self:
            if lock.date_from and lock.date_to and lock.date_from > lock.date_to:
                raise ValidationError(_('The lock period start must be before its end.'))
