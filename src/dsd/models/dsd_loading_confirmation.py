from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DsdLoadingConfirmation(models.Model):
    """Loading confirmation (SAP /DSD/SV_LC): count the physical van load
    against the load-out picking. Counted quantities are the truth — on
    completion the load picking is adjusted to the counted quantities and
    validated, so the van stock matches the physical load. Differences must
    be reason-coded (value posting happens in settlement)."""
    _name = 'dsd.loading.confirmation'
    _description = 'DSD Loading Confirmation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, copy=False, default=lambda self: _('New'))
    tour_id = fields.Many2one(
        'stock.picking.batch', required=True, ondelete='cascade',
        check_company=True, index='btree')
    company_id = fields.Many2one(related='tour_id.company_id')
    state = fields.Selection([
        ('open', 'Open'),
        ('done', 'Completed'),
    ], default='open', required=True, copy=False)
    counting_scope = fields.Selection([
        ('product', 'By Product'),
        ('counting_group', 'By Counting Group'),
    ], required=True, default='product')
    line_ids = fields.One2many(
        'dsd.loading.confirmation.line', 'confirmation_id', string='Counted Lines')
    difference_count = fields.Integer(compute='_compute_difference_count')
    has_difference = fields.Boolean(compute='_compute_difference_count')
    completed_by_id = fields.Many2one('res.users', readonly=True, copy=False)

    @api.depends('line_ids.counted_qty', 'line_ids.target_qty')
    def _compute_difference_count(self):
        for confirmation in self:
            diffs = confirmation.line_ids.filtered(
                lambda ln: ln.counted_qty != ln.target_qty)
            confirmation.difference_count = len(diffs)
            confirmation.has_difference = bool(diffs)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'dsd.loading.confirmation')
        confirmations = super().create(vals_list)
        confirmations.filtered(lambda c: not c.line_ids)._prepare_lines()
        return confirmations

    def _load_quantities(self):
        """{product: base qty} planned on the tour's load-out picking."""
        self.ensure_one()
        load = self.tour_id.dsd_load_picking_id
        if not load:
            raise UserError(_(
                'Tour %s has no load-out picking to count against.',
                self.tour_id.name))
        quantities = {}
        for move in load.move_ids.filtered(lambda m: m.state != 'cancel'):
            qty = move.uom_id._compute_quantity(
                move.product_uom_qty, move.product_id.uom_id)
            quantities[move.product_id] = quantities.get(move.product_id, 0.0) + qty
        return quantities

    def _prepare_lines(self):
        """Build target lines from the load-out picking for the chosen scope."""
        self.ensure_one()
        self.line_ids.unlink()
        quantities = self._load_quantities()
        if self.counting_scope == 'product':
            self.line_ids = [
                (0, 0, {
                    'product_id': product.id,
                    'uom_id': product.uom_id.id,
                    'target_qty': qty,
                })
                for product, qty in sorted(
                    quantities.items(), key=lambda item: item[0].display_name)
            ]
        else:
            lines = []
            groups = quantities and self.env['dsd.counting.group'].search([
                ('id', 'in', [p.counting_group_id.id for p in quantities
                              if p.counting_group_id])])
            for group in groups:
                products = [p for p in quantities if p.counting_group_id == group]
                base_total = sum(quantities[p] for p in products)
                for group_uom in group.uom_line_ids.sorted('sequence').mapped('uom_id'):
                    if not group_uom._has_common_reference(products[0].uom_id):
                        continue
                    lines.append((0, 0, {
                        'counting_group_id': group.id,
                        'uom_id': group_uom.id,
                        'target_qty': products[0].uom_id._compute_quantity(
                            base_total, group_uom),
                    }))
            leftover = {p: q for p, q in quantities.items() if not p.counting_group_id}
            for product, qty in sorted(leftover.items(),
                                       key=lambda item: item[0].display_name):
                lines.append((0, 0, {
                    'product_id': product.id,
                    'uom_id': product.uom_id.id,
                    'target_qty': qty,
                }))
            self.line_ids = lines
        return True

    def action_reprepare(self):
        self.ensure_one()
        if self.state != 'open':
            raise UserError(_('Completed confirmations cannot be re-prepared.'))
        self._prepare_lines()

    def action_itemize(self):
        """Split a counting-group line with a difference into product lines
        (targets from the load, counted 0 to force an entry)."""
        self.ensure_one()
        for line in self.line_ids.filtered(
                lambda ln: ln.counting_group_id and ln.counted_qty):
            group = line.counting_group_id
            quantities = self._load_quantities()
            products = {p: q for p, q in quantities.items()
                        if p.counting_group_id == group}
            if not products:
                continue
            commands = [(2, line.id, False)]
            for product, qty in sorted(products.items(),
                                       key=lambda item: item[0].display_name):
                commands.append((0, 0, {
                    'product_id': product.id,
                    'uom_id': product.uom_id.id,
                    'target_qty': qty,
                    'counted_qty': 0.0,
                }))
            self.line_ids = commands
        return True

    def action_complete(self):
        """Apply counted quantities to the load-out picking and validate it."""
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('Loading confirmation already completed.'))
        load = self.tour_id.dsd_load_picking_id
        if load.state == 'done':
            raise UserError(_('The load-out picking is already validated.'))
        pending = self.line_ids.filtered(
            lambda ln: not ln.counted_qty and ln.target_qty)
        if pending:
            raise UserError(_('%s line(s) not counted yet.', len(pending)))
        no_reason = self.line_ids.filtered(
            lambda ln: ln.counted_qty != ln.target_qty and not ln.reason_id)
        if no_reason:
            raise UserError(_(
                '%s difference line(s) need a reason code.', len(no_reason)))
        grouped = self.line_ids.filtered(lambda ln: ln.counting_group_id
                                         and ln.counted_qty != ln.target_qty)
        if grouped:
            raise UserError(_(
                'Group-level differences must be itemized to products first '
                '(use Itemize).'))
        quantities = self._load_quantities()
        for line in self.line_ids.filtered(lambda ln: ln.product_id):
            diff_base = line.uom_id._compute_quantity(
                line.counted_qty, line.product_id.uom_id)
            old_base = quantities.get(line.product_id, 0.0)
            if line.product_id not in quantities:
                raise UserError(_(
                    'Product %s is not on the load-out picking.',
                    line.product_id.display_name))
            new_move_qty = line.product_id.uom_id._compute_quantity(
                diff_base, line.uom_id)
            move = load.move_ids.filtered(
                lambda m: m.product_id == line.product_id
                and m.state not in ('done', 'cancel'))
            move.write({'product_uom_qty': new_move_qty})
        load.action_confirm()
        load.move_ids.write({'quantity': load.move_ids.product_uom_qty})
        load.with_context(skip_cancel_backorder=True).button_validate()
        if self.tour_id.dsd_seal_numbers:
            self.tour_id._log_dsd_status(self.env._(
                'Van sealed (%s).', self.tour_id.dsd_seal_numbers))
        self.write({'state': 'done',
                    'completed_by_id': self.env.user.id})
        return True


class DsdLoadingConfirmationLine(models.Model):
    _name = 'dsd.loading.confirmation.line'
    _description = 'DSD Loading Confirmation Line'
    _order = 'confirmation_id, counting_group_id, product_id'

    confirmation_id = fields.Many2one(
        'dsd.loading.confirmation', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    counting_group_id = fields.Many2one('dsd.counting.group', string='Counting Group')
    uom_id = fields.Many2one('uom.uom', required=True)
    target_qty = fields.Float(required=True)
    counted_qty = fields.Float()
    difference_qty = fields.Float(compute='_compute_difference_qty')
    reason_id = fields.Many2one(
        'dsd.reason', domain=[('scope', '=', 'checkout_diff')])

    @api.depends('target_qty', 'counted_qty')
    def _compute_difference_qty(self):
        for line in self:
            line.difference_qty = line.counted_qty - line.target_qty

    @api.constrains('product_id', 'counting_group_id')
    def _check_subject(self):
        for line in self:
            if bool(line.product_id) == bool(line.counting_group_id):
                raise ValidationError(self.env._(
                    'A loading-confirmation line counts either a product or a '
                    'counting group.'))
