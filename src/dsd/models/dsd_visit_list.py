from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DsdVisitList(models.Model):
    """Operational visit list (SAP): the ordered customer stops for one
    execution date. Generated from visit plans or maintained manually;
    for preseller/van-seller/mixed roles it is a defining document of the
    tour process, for delivery drivers the tour is.
    """
    _name = 'dsd.visit.list'
    _description = 'DSD Visit List'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'execution_date desc, id desc'
    _rec_names_search = ['name', 'route_id']

    name = fields.Char(required=True, copy=False, default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    inactive = fields.Boolean(
        help='Inactive lists are not executed; generation and settlement skip them.')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    execution_date = fields.Date(required=True, tracking=True)
    plan_id = fields.Many2one('dsd.visit.plan', string='Visit Plan', index='btree_not_null')
    plan_type_id = fields.Many2one('dsd.visit.plan.type', string='Plan Type')
    route_id = fields.Many2one('dsd.route', required=True, check_company=True)
    driver_id = fields.Many2one(
        'hr.employee', string='Driver',
        domain=[('dsd_active_driver', '=', True)], check_company=True, tracking=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle',
        domain=[('dsd_is_van', '=', True)], check_company=True, tracking=True)
    trailer_id = fields.Many2one(
        'fleet.vehicle', string='Trailer',
        domain=[('dsd_vehicle_type', '=', 'trailer')])

    line_ids = fields.One2many('dsd.visit.list.line', 'list_id', string='Stops')
    stop_count = fields.Integer(compute='_compute_stop_count')
    driver_notes = fields.Text(string='Driver Notes')
    plan_type_driver_lockable = fields.Boolean(
        related='plan_type_id.driver_lockable',
        help='If set, driver/vehicle may be swapped on this list (replacement driver).')

    # Reference documents (SAP header references). The tour link locks the list
    # (Phase 2); the speculative load is an internal WH→Van picking for
    # van-seller/mixed roles.
    tour_id = fields.Many2one('stock.picking.batch', string='Tour', copy=False,
                              index='btree_not_null')
    speculative_load_picking_id = fields.Many2one(
        'stock.picking', string='Speculative Load', copy=False)

    _list_date_plan_unique = models.Constraint(
        'unique(plan_id, execution_date)',
        'A visit list already exists for this plan and date.',
    )

    def _compute_stop_count(self):
        for visit_list in self:
            visit_list.stop_count = len(visit_list.line_ids)

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        for visit_list in self:
            plan = visit_list.plan_id
            if plan:
                visit_list.plan_type_id = plan.plan_type_id
                visit_list.route_id = plan.route_id
                visit_list.driver_id = plan.driver_id
                visit_list.vehicle_id = plan.vehicle_id
                visit_list.trailer_id = plan.trailer_id
                visit_list.driver_notes = plan.driver_notes

    # ------------------------------------------------------------------
    # Appointment (time-stream) sync
    # ------------------------------------------------------------------

    def _sync_appointments(self):
        """Keep the customer time stream in line with this list: one
        appointment per planned stop (partner, execution date, plan-type kind).
        Runs as sudo: the time stream is a system-maintained projection that
        restricted users (drivers) may not write directly, and it reads
        configuration (plan types) drivers cannot see."""
        Appointment = self.env['dsd.visit.appointment'].sudo()
        for visit_list in self.sudo().filtered(lambda lst: lst.state != 'cancelled'):
            kind = visit_list._appointment_kind()
            Appointment.search([('visit_list_id', '=', visit_list.id)]).unlink()
            if visit_list.inactive:
                continue
            for line in visit_list.line_ids.filtered(lambda ln: not ln.is_unplanned):
                Appointment.search([
                    ('partner_id', '=', line.partner_id.id),
                    ('date', '=', visit_list.execution_date),
                    ('kind', '=', kind),
                    ('visit_list_id', '=', False),
                ]).unlink()
                taken = Appointment.search([
                    ('partner_id', '=', line.partner_id.id),
                    ('date', '=', visit_list.execution_date),
                    ('kind', '=', kind),
                ], limit=1)
                if taken and taken.visit_list_id != visit_list:
                    raise UserError(_(
                        '%(partner)s already has a %(kind)s appointment on '
                        '%(date)s through visit list %(list)s. Remove the '
                        'duplicate stop or cancel that list first.',
                        partner=line.partner_id.display_name,
                        kind=kind,
                        date=visit_list.execution_date,
                        list=taken.visit_list_id.display_name,
                    ))
                Appointment.create({
                    'partner_id': line.partner_id.id,
                    'date': visit_list.execution_date,
                    'kind': kind,
                    'plan_id': visit_list.plan_id.id,
                    'visit_list_id': visit_list.id,
                    'route_id': visit_list.route_id.id,
                    'company_id': visit_list.company_id.id,
                })

    def _appointment_kind(self):
        self.ensure_one()
        if self.plan_type_id and self.plan_type_id.make_delivery:
            return 'delivery'
        return 'visit'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dsd.visit.list')
        lists = super().create(vals_list)
        lists._sync_appointments()
        return lists

    def write(self, vals):
        # SAP parity: once a shipment/tour references the list, header data and
        # stops are locked; only the driver/vehicle swap remains open.
        locked_keys = {'execution_date', 'plan_id', 'plan_type_id', 'route_id',
                       'inactive', 'line_ids'}
        for visit_list in self:
            if visit_list.tour_id and locked_keys & vals.keys() \
                    and not self.env.context.get('dsd_allow_locked_list_edit'):
                raise ValidationError(self.env._(
                    'Visit list %s is locked: tour %s references it. Only the '
                    'driver/vehicle can be swapped.',
                    visit_list.name, visit_list.tour_id.display_name))
        result = super().write(vals)
        if vals.get('state') == 'cancelled':
            # cancelling releases the list's time-stream slots
            self.env['dsd.visit.appointment'].sudo().search([
                ('visit_list_id', 'in', self.ids)]).unlink()
        elif {'line_ids', 'execution_date', 'inactive', 'plan_type_id', 'route_id',
                'state', 'plan_id'} & vals.keys():
            self._sync_appointments()
        return result

    def unlink(self):
        self.env['dsd.visit.appointment'].sudo().search([
            ('visit_list_id', 'in', self.ids)]).unlink()
        return super().unlink()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_confirm(self):
        for visit_list in self:
            if not visit_list.line_ids:
                raise UserError(self.env._(
                    'Visit list %s has no stops; add customers before confirming.',
                    visit_list.name))
            if not visit_list.driver_id:
                raise UserError(self.env._(
                    'Visit list %s needs a driver before confirming.', visit_list.name))
        self.write({'state': 'confirmed'})

    def action_start(self):
        if any(visit_list.state != 'confirmed' for visit_list in self):
            raise UserError(_('Only confirmed visit lists can be started.'))
        self.write({'state': 'in_progress'})

    def action_done(self):
        if any(visit_list.state != 'in_progress' for visit_list in self):
            raise UserError(_('Only in-progress visit lists can be completed.'))
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reopen(self):
        self.write({'state': 'draft'})

    def action_postpone(self, new_date=None):
        """Move this list to another execution date; appointments follow."""
        self.ensure_one()
        if not new_date:
            raise UserError(_('Provide the new execution date.'))
        self.execution_date = new_date

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('dsd_visit_list_line_id', 'in', self.line_ids.ids)],
        }

    def action_view_appointments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Appointments'),
            'res_model': 'dsd.visit.appointment',
            'view_mode': 'list,calendar',
            'domain': [('visit_list_id', '=', self.id)],
        }


class DsdVisitListLine(models.Model):
    """One stop on a visit list: the customer, its position in the itinerary,
    and the execution data captured before, during and after the visit
    (SAP visit list item + execution statuses NP/SP/PP/UP/RS).
    """
    _name = 'dsd.visit.list.line'
    _description = 'DSD Visit List Line'
    _order = 'list_id, sequence, id'
    _rec_name = 'partner_id'

    list_id = fields.Many2one('dsd.visit.list', required=True, ondelete='cascade',
                              index='btree')
    company_id = fields.Many2one(related='list_id.company_id')
    currency_id = fields.Many2one(related='list_id.company_id.currency_id')
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', required=True, string='Customer')
    is_unplanned = fields.Boolean(
        string='Unplanned Stop',
        help='Added by the driver or the back office on the day, not present in the plan.')
    waiting_minutes = fields.Integer(default=15)
    travel_minutes = fields.Integer(default=20)
    unloading_point_id = fields.Many2one('res.partner', string='Unloading Point')
    contact_id = fields.Many2one('res.partner', string='Contact Person')

    # Execution (SAP visit statuses: Not processed / Successful / Partial /
    # Unsuccessful / Rescheduled)
    status = fields.Selection([
        ('np', 'Not Processed'),
        ('sp', 'Successfully Processed'),
        ('pp', 'Partially Processed'),
        ('up', 'Unsuccessfully Processed'),
        ('rs', 'Rescheduled'),
    ], default='np', required=True, tracking=True)
    parent_state = fields.Selection(related='list_id.state')
    editable_in_list = fields.Boolean(compute='_compute_editable_in_list')
    reason_id = fields.Many2one(
        'dsd.reason', string='Visit Reason',
        domain=[('scope', '=', 'visit_outcome')])
    arrival = fields.Datetime()
    departure = fields.Datetime()
    odometer_value = fields.Float(string='Odometer')
    signature_attachment_id = fields.Many2one('ir.attachment', string='Signature')
    customer_notes = fields.Text(
        string='Customer Notes',
        help='Notes about this stop, printed on the tour manifest.')
    visit_note = fields.Text(string='Visit Note')

    # Result documents (SAP reference documents at item level)
    order_ids = fields.Many2many('sale.order', string='Orders')
    picking_ids = fields.Many2many('stock.picking', string='Deliveries')
    invoice_ids = fields.Many2many('account.move', string='Invoices')
    payment_ids = fields.Many2many('account.payment', string='Collections')

    @api.depends('parent_state')
    def _compute_editable_in_list(self):
        for line in self:
            line.editable_in_list = line.parent_state in ('in_progress', 'done')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for line in self:
            partner = line.partner_id
            if partner:
                line.unloading_point_id = partner.dsd_unloading_point_id or False

    @api.constrains('status', 'reason_id')
    def _check_outcome_reason(self):
        for line in self:
            if line.status in ('up', 'rs') and not line.reason_id:
                raise ValidationError(self.env._(
                    'Stop %s needs a reason code for an unsuccessful or '
                    'rescheduled visit.', line.partner_id.display_name))
            if line.reason_id and not line.reason_id.needs_reschedule \
                    and line.status == 'rs':
                raise ValidationError(self.env._(
                    'Reason %s does not allow rescheduling.',
                    line.reason_id.name))
