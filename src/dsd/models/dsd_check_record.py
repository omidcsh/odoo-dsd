from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DsdCheckRecord(models.Model):
    """Check-out / check-in (SAP /DSD/SV): custody counts of goods and cash
    at the tour boundaries, confirmed by a checker. Check-out closes the
    tour departure; check-in closes the return and creates the unload
    picking that returns remaining van stock to the warehouse."""
    _name = 'dsd.check.record'
    _description = 'DSD Check-Out / Check-In'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, copy=False, default=lambda self: _('New'))
    tour_id = fields.Many2one(
        'stock.picking.batch', required=True, ondelete='cascade',
        check_company=True, index='btree')
    company_id = fields.Many2one(related='tour_id.company_id')
    check_type = fields.Selection([
        ('out', 'Check-Out'),
        ('in', 'Check-In'),
    ], required=True)
    is_reload_check = fields.Boolean(
        string='Reload Check', default=False,
        help='Mid-tour stop-off check; counts only the delta.')
    state = fields.Selection([
        ('open', 'Open'),
        ('confirmed', 'Confirmed'),
    ], default='open', required=True, copy=False)
    checked_by_id = fields.Many2one(
        'res.users', string='Checker', default=lambda self: self.env.user)
    countersigned_by_id = fields.Many2one(
        'res.users', string='Countersigned By', readonly=True, copy=False,
        help='Supervisor approval — required when differences were confirmed.')
    signature_attachment_id = fields.Many2one('ir.attachment', copy=False)
    material_line_ids = fields.One2many(
        'dsd.check.record.material', 'check_id', string='Material Count')
    payment_line_ids = fields.One2many(
        'dsd.check.record.payment', 'check_id', string='Cash & Payment Count')
    has_difference = fields.Boolean(compute='_compute_has_difference')

    @api.depends('material_line_ids.counted_qty', 'material_line_ids.planned_qty',
                 'payment_line_ids.counted_amount', 'payment_line_ids.expected_amount')
    def _compute_has_difference(self):
        for record in self:
            record.has_difference = bool(
                record.material_line_ids.filtered(
                    lambda ln: ln.counted_qty != ln.planned_qty)
                or record.payment_line_ids.filtered(
                    lambda ln: ln.counted_amount != ln.expected_amount))

    @api.constrains('tour_id', 'check_type')
    def _check_type_unique_per_tour(self):
        for record in self:
            duplicate = self.search([
                ('tour_id', '=', record.tour_id.id),
                ('check_type', '=', record.check_type),
                ('is_reload_check', '=', False),
                ('id', '!=', record.id),
            ], limit=1)
            if duplicate and not record.is_reload_check:
                raise ValidationError(self.env._(
                    'Tour %s already has a %s record (%s).',
                    record.tour_id.name, record.check_type, duplicate.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dsd.check.record')
        records = super().create(vals_list)
        records.filtered(lambda r: not r.material_line_ids)._prepare_material_lines()
        return records

    def _prepare_material_lines(self):
        """Planned material quantities = current van stock (products in the
        stock and damaged sub-locations)."""
        self.ensure_one()
        self.material_line_ids.unlink()
        van = self.tour_id.vehicle_id.dsd_van_location_id
        if not van:
            return True
        locations = van + van.child_internal_location_ids
        quants = self.env['stock.quant'].search([
            ('location_id', 'in', locations.ids),
            ('quantity', '>', 0),
        ])
        per_product = {}
        for quant in quants:
            # physical count: `quantity` includes units reserved for the tour's
            # own deliveries — `available_quantity` would wrongly report 0
            per_product[quant.product_id] = per_product.get(
                quant.product_id, 0.0) + quant.quantity
        self.material_line_ids = [
            (0, 0, {
                'product_id': product.id,
                'uom_id': product.uom_id.id,
                'planned_qty': qty,
            })
            for product, qty in sorted(per_product.items(),
                                       key=lambda item: item[0].display_name)
        ]
        return True

    def action_reprepare(self):
        for record in self:
            if record.state != 'open':
                raise UserError(_('Confirmed checks cannot be re-prepared.'))
            record._prepare_material_lines()

    def _expected_payment_lines(self):
        """Opening cash at check-out: entered manually. At check-in: expected
        = opening cash + tour collections − driver expenses (wired in P5)."""
        return []

    def action_confirm(self):
        """Confirm the count, apply the tour transition, and side effects."""
        self.ensure_one()
        tour = self.tour_id
        missing_material = self.material_line_ids.filtered(
            lambda ln: ln.counted_qty != ln.planned_qty and not ln.reason_id)
        missing_payment = self.payment_line_ids.filtered(
            lambda ln: ln.counted_amount != ln.expected_amount
            and not ln.reason_id)
        missing_count = len(missing_material) + len(missing_payment)
        if missing_count:
            raise UserError(_(
                '%s difference line(s) need a reason code.', missing_count))
        if self.has_difference:
            supervisor_group = self.env.ref('dsd.group_dsd_supervisor')
            if not self.env.user.has_group('dsd.group_dsd_supervisor'):
                raise UserError(_(
                    'Differences require supervisor countersigning: a member '
                    'of %s must confirm this check.', supervisor_group.name))
            self.countersigned_by_id = self.env.user
        self.state = 'confirmed'
        if self.check_type == 'out':
            if tour.dsd_state != 'loaded':
                raise UserError(_(
                    'Check-out requires the tour to be loaded (state: %s).',
                    tour.dsd_state))
            tour.dsd_state = 'checked_out'
            if tour.dsd_odometer_start:
                self.env['fleet.vehicle.odometer'].create({
                    'vehicle_id': tour.vehicle_id.id,
                    'value': tour.dsd_odometer_start,
                    'date': fields.Date.context_today(self),
                })
            tour._log_dsd_status(_('Checked out: goods and cash custody confirmed.'))
        else:
            if tour.dsd_state not in ('checked_out', 'in_progress'):
                raise UserError(_(
                    'Check-in requires a departed tour (state: %s).',
                    tour.dsd_state))
            tour.dsd_state = 'checked_in'
            if tour.dsd_odometer_end:
                self.env['fleet.vehicle.odometer'].create({
                    'vehicle_id': tour.vehicle_id.id,
                    'value': tour.dsd_odometer_end,
                    'date': fields.Date.context_today(self),
                })
            unload = tour._create_unload_picking()
            if unload:
                unload.action_confirm()
                unload.move_ids.write({'quantity': unload.move_ids.product_uom_qty})
                unload.with_context(skip_cancel_backorder=True).button_validate()
                tour._log_dsd_status(self.env._(
                    'Checked in; van returned to warehouse (%s).', unload.name))
            else:
                tour._log_dsd_status(_('Checked in; van was empty.'))
        return True


class DsdCheckRecordMaterial(models.Model):
    _name = 'dsd.check.record.material'
    _description = 'DSD Check Record Material Line'
    _order = 'check_id, product_id'

    check_id = fields.Many2one('dsd.check.record', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    uom_id = fields.Many2one(related='product_id.uom_id')
    planned_qty = fields.Float(required=True)
    counted_qty = fields.Float()
    reason_id = fields.Many2one(
        'dsd.reason', domain=[('scope', 'in', ('checkout_diff', 'checkin_diff'))])


class DsdCheckRecordPayment(models.Model):
    _name = 'dsd.check.record.payment'
    _description = 'DSD Check Record Payment Line'
    _order = 'check_id, journal_id'

    check_id = fields.Many2one('dsd.check.record', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='check_id.company_id.currency_id')
    journal_id = fields.Many2one(
        'account.journal', required=True, string='Payment Method',
        domain=[('type', 'in', ('cash', 'bank', 'check'))])
    expected_amount = fields.Float(
        string='Expected', currency_field='currency_id')
    counted_amount = fields.Float(
        string='Counted', currency_field='currency_id')
    reason_id = fields.Many2one(
        'dsd.reason', domain=[('scope', '=', 'checkin_diff')])
