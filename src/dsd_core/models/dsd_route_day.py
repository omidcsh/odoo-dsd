from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _


class DsdRouteDay(models.Model):
    _name = 'dsd.route.day'
    _description = 'DSD Route Day'
    _order = 'date desc, id desc'

    name = fields.Char(required=True, copy=False, default='New')
    active = fields.Boolean(default=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    route_id = fields.Many2one('dsd.route', required=True, index=True, ondelete='cascade')
    mode = fields.Selection(related='route_id.mode', store=True)
    warehouse_id = fields.Many2one(related='route_id.warehouse_id', store=True)
    driver_id = fields.Many2one(
        'res.users', string='Driver',
        related='route_id.driver_id', store=True, readonly=False,
        domain=[('share', '=', False)],
        help='Defaults to the route driver; can be overridden per day.',
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehicle',
        related='route_id.vehicle_id', store=True, readonly=False,
    )
    van_location_id = fields.Many2one(
        'stock.location', string='Van Location',
        related='route_id.van_location_id', store=True, readonly=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('loaded', 'Loaded'),
            ('in_progress', 'In Progress'),
            ('done', 'Completed'),
            ('settled', 'Settled'),
        ],
        default='draft', required=True, index=True,
    )
    visit_ids = fields.One2many('dsd.visit', 'route_day_id', string='Visits')
    visit_count = fields.Integer(compute='_compute_visit_count')
    pending_visit_count = fields.Integer(compute='_compute_visit_count')
    load_picking_id = fields.Many2one(
        'stock.picking', string='Van Load',
        copy=False,
        help='Internal transfer loading the van from warehouse stock.',
    )
    return_picking_id = fields.Many2one(
        'stock.picking', string='Stock Return',
        copy=False,
        help='Internal transfer returning unsold goods from the van to the '
             'warehouse at the end of the day.',
    )
    settlement_ids = fields.One2many('dsd.settlement', 'route_day_id')
    company_id = fields.Many2one(related='warehouse_id.company_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    total_sales = fields.Monetary(
        compute='_compute_metrics', store=True,
        help='Posted invoice total of all van sales and presales of the day.')
    cash_collected = fields.Monetary(
        compute='_compute_metrics', store=True,
        help='Cash registered on the visits of this day.')
    done_visit_count = fields.Integer(compute='_compute_metrics', store=True)

    @api.depends('visit_ids.invoice_id.state', 'visit_ids.invoice_id.amount_total',
                 'visit_ids.payment_ids.amount', 'visit_ids.state')
    def _compute_metrics(self):
        for day in self:
            invoices = day.visit_ids.invoice_id.filtered(
                lambda m: m.state == 'posted')
            day.total_sales = sum(invoices.mapped('amount_total'))
            day.cash_collected = sum(
                day.visit_ids.payment_ids.mapped('amount'))
            day.done_visit_count = len(day.visit_ids.filtered(
                lambda v: v.state == 'done'))

    _route_date_uniq = models.Constraint(
        'unique(route_id, date)',
        'A route day already exists for this route and date.',
    )

    @api.depends('visit_ids', 'visit_ids.state')
    def _compute_visit_count(self):
        for day in self:
            day.visit_count = len(day.visit_ids)
            day.pending_visit_count = len(day.visit_ids.filtered(
                lambda v: v.state == 'pending'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                seq = self.env['ir.sequence'].next_by_code('dsd.route.day')
                vals['name'] = seq or _('New')
        return super().create(vals_list)

    def action_open_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Visits'),
            'res_model': 'dsd.visit',
            'view_mode': 'list,form',
            'domain': [('route_day_id', '=', self.id)],
            'context': {'default_route_day_id': self.id},
        }

    # ------------------------------------------------------------------
    # Day workflow: load → start → visits → end → return
    # ------------------------------------------------------------------

    def _require_single(self):
        if len(self) != 1:
            raise UserError(self.env._('Select exactly one route day.'))
        return self

    def action_load_van(self):
        """Create the internal transfer loading the van from warehouse stock."""
        day = self._require_single()
        if day.state != 'draft':
            raise UserError(self.env._(
                'The van can only be loaded while the route day is in draft.'))
        if not day.van_location_id:
            raise UserError(self.env._(
                'This route has no van location — van sales routes need one.'))
        if day.load_picking_id:
            return day.load_picking_id._open_form()
        warehouse = day.warehouse_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': day.van_location_id.id,
            'origin': day.name,
        })
        day.load_picking_id = picking
        return picking._open_form()

    def action_start_route(self):
        day = self._require_single()
        if day.state not in ('draft', 'loaded'):
            raise UserError(self.env._('The route has already started.'))
        if day.load_picking_id and day.load_picking_id.state != 'done':
            raise UserError(self.env._(
                'Validate the van load %(picking)s before starting the route.',
                picking=day.load_picking_id.name,
            ))
        day.state = 'in_progress'

    def action_end_route(self):
        day = self._require_single()
        if day.state != 'in_progress':
            raise UserError(self.env._('Only a route in progress can be ended.'))
        pending = day.visit_ids.filtered(lambda v: v.state == 'pending')
        if pending:
            raise UserError(self.env._(
                '%(count)s visit(s) are still pending — mark them done or '
                'skipped before ending the route.',
                count=len(pending),
            ))
        day.state = 'done'

    def action_settle(self):
        """Open (or create) the end-of-day settlement for this route day."""
        day = self._require_single()
        if day.state != 'done':
            raise UserError(self.env._(
                'Only a completed route day can be settled.'))
        settlement = day.settlement_ids[:1]
        if not settlement:
            settlement = self.env['dsd.settlement'].create({
                'route_day_id': day.id,
            })
        return settlement._open_form()

    def action_create_stock_return(self):
        """End-of-day internal transfer returning unsold stock to the warehouse."""
        day = self._require_single()
        if day.state not in ('in_progress', 'done'):
            raise UserError(self.env._(
                'The stock return can only be created during or after the '
                'route, and before settlement.'))
        if day.return_picking_id:
            return day.return_picking_id._open_form()
        warehouse = day.warehouse_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': day.van_location_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'origin': self.env._('%(day)s — stock return', day=day.name),
        })
        day.return_picking_id = picking
        return picking._open_form()


class DsdVisit(models.Model):
    _name = 'dsd.visit'
    _description = 'DSD Route Visit'
    _order = 'sequence, id'
    _rec_name = 'partner_id'

    sequence = fields.Integer(default=10)
    route_day_id = fields.Many2one(
        'dsd.route.day', required=True, index=True, ondelete='cascade',
    )
    partner_id = fields.Many2one('res.partner', string='Store', required=True)
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('done', 'Done'),
            ('skipped', 'Skipped'),
        ],
        default='pending', required=True, index=True,
    )
    skip_reason = fields.Char(
        invisible="state != 'skipped'",
        placeholder="e.g. store closed",
    )
    # Document links filled by later phases (delivery, van sale, settlement).
    sale_order_id = fields.Many2one('sale.order', string='Presale Order')
    delivery_id = fields.Many2one(
        'stock.picking', string='Delivery',
        domain="[('partner_id', '=', partner_id)]",
    )
    return_id = fields.Many2one(
        'stock.picking', string='Return',
        domain="[('partner_id', '=', partner_id)]",
    )
    invoice_id = fields.Many2one(
        'account.move', string='Invoice',
        domain=[('move_type', '=', 'out_invoice')],
    )
    payment_ids = fields.Many2many('account.payment', string='Payments')
    signature = fields.Binary('Proof of Delivery', attachment=True)
    sale_kind = fields.Selection(
        selection=[
            ('presale', 'Presale'),
            ('van_sale', 'Van Sale'),
        ],
        string='Sale Kind',
        help='Which action created the linked sale order: a van sale ships '
             'from the van, a presale order is fulfilled from the warehouse.',
    )
    # Server-side relateds so view modifiers never traverse m2o chains
    # (the web client only loads fields declared in the view).
    route_mode = fields.Selection(related='route_day_id.route_id.mode')
    sale_state = fields.Selection(related='sale_order_id.state')

    # ------------------------------------------------------------------
    # Visit workflow
    # ------------------------------------------------------------------

    def _delivery_location(self, visit):
        return visit.route_day_id.van_location_id

    def action_deliver(self):
        """Deliver from the van to this store: creates the outgoing picking."""
        for visit in self:
            if visit.state != 'pending':
                raise UserError(self.env._(
                    'Only a pending visit can be delivered.'))
            day = visit.route_day_id
            if day.state != 'in_progress':
                raise UserError(self.env._(
                    'Start the route day before delivering to stores.'))
            warehouse = day.warehouse_id
            picking = self.env['stock.picking'].create({
                'picking_type_id': warehouse.out_type_id.id,
                'location_id': self._delivery_location(visit).id,
                'location_dest_id': visit.partner_id.property_stock_customer.id,
                'partner_id': visit.partner_id.id,
                'origin': self.env._(
                    '%(day)s — %(store)s',
                    day=day.name,
                    store=visit.partner_id.display_name,
                ),
            })
            visit.delivery_id = picking
            return picking._open_form()
        return True

    def action_take_return(self):
        """Take goods/empties back from this store into the van."""
        for visit in self:
            if visit.state == 'skipped':
                raise UserError(self.env._(
                    'Returns cannot be taken on a skipped visit.'))
            day = visit.route_day_id
            warehouse = day.warehouse_id
            picking = self.env['stock.picking'].create({
                'picking_type_id': warehouse.in_type_id.id,
                'location_id': visit.partner_id.property_stock_supplier.id,
                'location_dest_id': self._delivery_location(visit).id,
                'partner_id': visit.partner_id.id,
                'origin': self.env._(
                    '%(day)s — return from %(store)s',
                    day=day.name,
                    store=visit.partner_id.display_name,
                ),
            })
            visit.return_id = picking
            return picking._open_form()
        return True

    # ------------------------------------------------------------------
    # Van sale & presale
    # ------------------------------------------------------------------

    def _create_visit_order(self, kind):
        """Shared order creation for van sales and presale orders."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(self.env._(
                'Sales can only be taken while the visit is pending.'))
        if self.sale_order_id or self.delivery_id:
            raise UserError(self.env._(
                'This visit already has a sale order or delivery.'))
        day = self.route_day_id
        route = day.route_id
        if kind == 'van_sale':
            if route.mode == 'presale':
                raise UserError(self.env._(
                    'This is a presale route — van sales are not allowed.'))
            if not day.van_location_id:
                raise UserError(self.env._(
                    'The route has no van location for a van sale.'))
        elif route.mode == 'van_sales':
            raise UserError(self.env._(
                'This is a van sales route — only van sales are allowed.'))
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'warehouse_id': day.warehouse_id.id,
            'origin': self.env._('%(day)s — %(store)s',
                                 day=day.name,
                                 store=self.partner_id.display_name),
        })
        self.write({
            'sale_order_id': order.id,
            'sale_kind': kind,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_start_van_sale(self):
        """Start a van sale: creates the draft sale order to fill in."""
        return self._create_visit_order('van_sale')

    def action_create_presale(self):
        """Take a presale order fulfilled later from the warehouse."""
        return self._create_visit_order('presale')

    def action_complete_van_sale(self):
        """One click: ship from the van, invoice, and register the cash."""
        self.ensure_one()
        order = self.sale_order_id
        if self.sale_kind != 'van_sale' or not order:
            raise UserError(self.env._(
                'Start a van sale on this visit first.'))
        if order.state != 'sale':
            raise UserError(self.env._(
                'Confirm the sale order %(order)s before completing the '
                'van sale.', order=order.name,
            ))
        env = self.env
        day = self.route_day_id

        # 1. Ship from the van: prefill any unpicked quantity with the full
        #    demand — storable van lines are never reserved (source location
        #    is retargeted after confirmation), so without this the
        #    validation would see zero quantities.
        delivery = self.delivery_id
        if delivery and delivery.state != 'done':
            for move in delivery.move_ids.filtered(lambda m: not m.quantity):
                move.quantity = move.product_uom_qty
            delivery.move_ids.picked = True
            res = delivery.button_validate()
            if isinstance(res, dict) and res.get('res_model') and res.get('res_id'):
                wizard = env[res['res_model']].browse(res['res_id'])
                if res['res_model'] == 'stock.backorder.confirmation':
                    wizard.process()
                elif res['res_model'] == 'stock.zero.demand.confirmation':
                    wizard.process()

        # 2. Invoice
        if not self.invoice_id:
            invoice = order._create_invoices(final=True)
            invoice.action_post()
            self.invoice_id = invoice

        # 3. Register the cash against the route's journal. The payment's
        #    counterpart is moved onto the invoice's receivable account
        #    (journals book on an outstanding account, which cannot
        #    reconcile with the invoice) and matched explicitly.
        invoice = self.invoice_id
        company = day.warehouse_id.company_id
        journal = day.route_id.cash_journal_id or env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise UserError(self.env._(
                'No cash journal found for company %(company)s — set one on '
                'the route.', company=company.name,
            ))
        if journal.company_id != company:
            raise UserError(self.env._(
                'The route cash journal belongs to %(journal_company)s but '
                'the route day runs in %(company)s.',
                journal_company=journal.company_id.name,
                company=company.name,
            ))
        payment = env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': order.partner_id.id,
            'journal_id': journal.id,
            'amount': invoice.amount_residual,
            'currency_id': invoice.currency_id.id,
            'date': day.date,
            'memo': invoice.name,
        })
        payment.action_post()
        _liquidity, counterpart, _writeoff = payment._seek_for_lines()
        invoice_receivable = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        counterpart.write({'account_id': invoice_receivable.account_id.id})
        (counterpart + invoice_receivable).reconcile()
        self.payment_ids = [(4, payment.id)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
