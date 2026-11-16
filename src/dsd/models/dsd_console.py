"""Driver console service layer.

All driver-facing business operations live here as public methods on the
`dsd.console` abstract model. The HTTP API controllers (/dsd/api/v1/...)
are thin wrappers and the OWL console calls only these — one business
path, two clients. Console access is restricted to the assigned driver
(dispatchers may inspect).
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class DsdConsole(models.AbstractModel):
    _name = 'dsd.console'
    _description = 'DSD Driver Console Service'
    _abstract = True

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------

    def _get_driver(self):
        # sudo: driver users cannot read private hr.employee fields (public
        # profile restriction) — the console only needs our DSD extension data
        driver = self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.env.user.id)], limit=1)
        if not driver or not driver.dsd_active_driver:
            raise AccessError(_('The console is only available to DSD drivers.'))
        return driver

    def _is_dispatcher(self):
        return self.env.user.has_group('dsd.group_dsd_dispatcher')

    def _ensure_stop_access(self, stop):
        driver = self._get_driver()
        if stop.list_id.driver_id.id != driver.id and not self._is_dispatcher():
            raise AccessError(_('This stop is not yours.'))
        return stop

    def _ensure_tour_access(self, tour):
        driver = self._get_driver()
        if tour.dsd_driver_id.id != driver.id and not self._is_dispatcher():
            raise AccessError(_('This tour is not yours.'))
        return tour

    def _ensure_list_access(self, visit_list):
        driver = self._get_driver()
        if visit_list.driver_id.id != driver.id and not self._is_dispatcher():
            raise AccessError(_('This list is not yours.'))
        return visit_list

    def _my_list_ids(self):
        driver = self._get_driver()
        return self.env['dsd.visit.list'].search(
            [('driver_id', '=', driver.id)]).ids

    # ------------------------------------------------------------------
    # Today view
    # ------------------------------------------------------------------

    @api.model
    def get_console_data(self):
        driver = self._get_driver()
        today = fields.Date.context_today(self)
        lists = self.env['dsd.visit.list'].search([
            ('driver_id', '=', driver.id),
            ('execution_date', '=', today),
            ('state', 'in', ('confirmed', 'in_progress')),
            ('inactive', '=', False),
        ], order='route_id, id')
        tours = self.env['stock.picking.batch'].search([
            ('dsd_driver_id', '=', driver.id),
            ('dsd_state', 'in',
             ('confirmed', 'loading', 'loaded', 'checked_out', 'in_progress')),
            ('dsd_execution_date', '<=', today + timedelta(days=1)),
        ], order='dsd_execution_date, id')
        return {
            'driver': {'id': driver.id, 'name': driver.name,
                       'code': driver.dsd_code},
            'date': str(today),
            'visit_lists': [self._list_values(lst) for lst in lists],
            'tours': [self._tour_values(t) for t in tours],
        }

    def _list_values(self, visit_list):
        # sudo: read-only projection after the caller verified ownership;
        # drivers may lack access to referenced master data (routes, fleet)
        visit_list = visit_list.sudo()
        return {
            'id': visit_list.id,
            'name': visit_list.name,
            'route': visit_list.route_id.display_name,
            'state': visit_list.state,
            'stop_count': visit_list.stop_count,
            'stops': [self._stop_values(line) for line in
                      visit_list.line_ids.sorted('sequence')],
        }

    def _tour_values(self, tour):
        tour = tour.sudo()
        van = tour.vehicle_id.dsd_van_location_id
        quants = tour.env['stock.quant'].search(
            [('location_id', 'child_of', van.ids), ('quantity', '>', 0)]) if van \
            else tour.env['stock.quant'].browse()
        return {
            'id': tour.id,
            'name': tour.name,
            'route': tour.dsd_route_id.display_name,
            'state': tour.dsd_state,
            'stop_count': tour.dsd_stop_count,
            'check_states': {c.check_type: c.state for c in tour.dsd_check_ids},
            'van_stock': [
                {'product': q.product_id.display_name,
                 'qty': q.quantity, 'uom': q.uom_id.name}
                for q in quants],
        }

    def _stop_values(self, line):
        partner = line.partner_id
        return {
            'id': line.id,
            'partner': partner.display_name,
            'address': (partner.contact_address or '').replace('\n', ', '),
            'status': line.status,
            'reason': line.reason_id.display_name or '',
            'notes': line.customer_notes or '',
            'maps_url': self._maps_url(partner),
            'orders': len(line.order_ids),
            'collections': len(line.payment_ids),
        }

    def _maps_url(self, partner):
        if partner.partner_latitude and partner.partner_longitude:
            return (f'https://maps.google.com/?q={partner.partner_latitude},'
                    f'{partner.partner_longitude}')
        address = (partner.contact_address or partner.display_name) \
            .replace('\n', ', ')
        return f'https://maps.google.com/?q={address}'

    # ------------------------------------------------------------------
    # Stop detail + visit lifecycle
    # ------------------------------------------------------------------

    @api.model
    def get_stop(self, visit_line_id):
        line = self._ensure_stop_access(
            self.env['dsd.visit.list.line'].browse(visit_line_id))
        # sudo: the stop detail is a read-only projection (stats, invoices,
        # journals, master data) the driver should see regardless of ACLs on
        # the referenced models; ownership was verified above and the
        # operations below still run with full authority checks
        line = line.sudo()
        partner = line.partner_id
        stats = partner.env['dsd.customer.product.stat'].search(
            [('partner_id', '=', partner.id)], limit=5, order='qty_90d desc')
        open_invoices = partner.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])
        picking = line.list_id.tour_id.picking_ids.filtered(
            lambda p: p.partner_id == partner
            and p.state not in ('done', 'cancel'))[:1]
        return {
            'id': line.id,
            'partner': partner.display_name,
            'address': (partner.contact_address or '').replace('\n', ', '),
            'phone': partner.phone or '',
            'status': line.status,
            'reason': line.reason_id.display_name or '',
            'maps_url': self._maps_url(partner),
            'receiving_hours': partner.dsd_receiving_hours or '',
            'driver_notes': line.customer_notes or '',
            'credit': {
                'limit': partner.dsd_credit_limit,
                'used': sum(open_invoices.mapped('amount_residual')),
                'over_limit': bool(partner.dsd_credit_limit
                                   and sum(open_invoices.mapped('amount_residual'))
                                   > partner.dsd_credit_limit),
            },
            'collection_type': partner.dsd_collection_type,
            'cash_only': partner.dsd_cash_only,
            'pod_or_invoice': partner.dsd_pod_or_invoice,
            'accepted_journals': [
                {'id': j.id, 'name': j.name}
                for j in partner.dsd_accepted_journal_ids],
            'open_invoices': [
                {'id': inv.id, 'name': inv.name,
                 'residual': inv.amount_residual}
                for inv in open_invoices],
            'statistics': [
                {'product': s.product_id.display_name, 'qty_90d': s.qty_90d,
                 'avg_week': s.avg_qty_per_week}
                for s in stats],
            'delivery': {
                'id': picking.id,
                'name': picking.name,
                'lines': [
                    {'move_id': move.id,
                     'product_id_int': move.product_id.id,
                     'product': move.product_id.display_name,
                     'planned': move.product_uom_qty,
                     'uom': move.uom_id.name}
                    for move in picking.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel'))],
            } if picking else None,
            'saleable_products': [
                {'id': p.id, 'name': p.display_name}
                for p in self.env['product.product'].sudo().search([
                    ('dsd_group_id', '!=', False), ('is_storable', '=', True),
                ], limit=100)],
        }

    def _get_own_stop(self, visit_line_id):
        return self._ensure_stop_access(
            self.env['dsd.visit.list.line'].browse(visit_line_id))

    @api.model
    def set_arrival(self, visit_line_id):
        stop = self._get_own_stop(visit_line_id)
        stop.arrival = fields.Datetime.now()
        return True

    @api.model
    def set_departure(self, visit_line_id):
        stop = self._get_own_stop(visit_line_id)
        stop.departure = fields.Datetime.now()
        return True

    @api.model
    def set_visit_status(self, visit_line_id, status, reason_id=None):
        stop = self._get_own_stop(visit_line_id)
        # single write: the outcome-reason constraint fires during the status
        # write and would see a stale (empty) reason otherwise
        stop.write({'status': status,
                    'reason_id': reason_id or stop.reason_id.id})
        return True

    @api.model
    def set_visit_note(self, visit_line_id, note):
        stop = self._get_own_stop(visit_line_id)
        stop.visit_note = note
        return True

    # ------------------------------------------------------------------
    # Delivery execution (actuals on the pre-sold picking)
    # ------------------------------------------------------------------

    @api.model
    def confirm_delivery(self, picking_id, quantities=None):
        """Apply driver actuals (product → counted qty) and validate the
        delivery from the van. Marks the stop SP/PP accordingly."""
        picking = self.env['stock.picking'].sudo().browse(picking_id)
        stop = self._get_own_stop(self.env['dsd.visit.list.line'].search(
            [('partner_id', '=', picking.partner_id.id),
             ('list_id', 'in', self._my_list_ids())], limit=1))
        quantities = quantities or {}
        for move in picking.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')):
            qty = quantities.get(move.product_id.id)
            if qty is not None:
                move.write({'quantity': qty})
        picking.with_context(skip_cancel_backorder=True).button_validate()
        if stop:
            stop.picking_ids = [(4, picking.id)]
            delivered = all(
                m.quantity >= m.product_uom_qty
                for m in picking.move_ids if m.state == 'done')
            stop.status = 'sp' if delivered else 'pp'
        return {'picking': picking.name, 'state': picking.state}

    # ------------------------------------------------------------------
    # Van sale (sell from the van)
    # ------------------------------------------------------------------

    @api.model
    def create_van_sale(self, visit_line_id, lines, apply_deal_ids=None):
        """Create + confirm a van sale for the stop: lines = [{product_id, qty,
        discount}] (discount within the driver's authority). Pricing from the
        partner pricelist; assortment enforced at line creation; deal
        conditions applied; the delivery is routed from the van; invoice
        created/posted automatically for auto-invoice customers, gated by the
        credit limit."""
        stop = self._get_own_stop(visit_line_id)
        partner = stop.partner_id
        driver = self._get_driver()
        if not lines:
            raise UserError(_('The van sale is empty.'))
        # sudo: sale/stock mechanics run elevated — the driver authority is
        # enforced above (_driver_discount) and by the assortment checks
        order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'dsd_route_id': partner.dsd_route_id.id,
            'dsd_visit_list_line_id': stop.id,
            'order_line': [
                (0, 0, {
                    'product_id': line['product_id'],
                    'product_uom_qty': line['qty'],
                    'dsd_visit_list_line_id': stop.id,
                    'discount': self._driver_discount(driver, line),
                })
                for line in lines
            ],
        })
        deals = self.env['dsd.deal.condition'].evaluate_for_order(order)
        for condition in deals['obligatory']:
            condition.apply_to_order(order)
        for condition in self.env['dsd.deal.condition'].browse(apply_deal_ids or []):
            condition.apply_to_order(order)
        order.sudo().action_confirm()
        delivery = order.picking_ids[:1]
        van = self._stop_van(stop)
        if van and delivery:
            delivery.sudo().move_ids._do_unreserve()
            delivery.sudo().write({'location_id': van.id})
            delivery.sudo().mapped('move_ids').write({'location_id': van.id})
            delivery.sudo().action_confirm()
            # the van sale is completed at the stop: post the goods issue
            # out of the van immediately, not when the tour checks in
            for move in delivery.sudo().move_ids:
                move.quantity = move.product_uom_qty
            delivery.sudo().with_context(
                skip_cancel_backorder=True).button_validate()
        stop.order_ids = [(4, order.id)]
        invoice = None
        if partner.dsd_pod_or_invoice == 'invoice' \
                and partner.dsd_invoice_generation == 'auto':
            invoice = self._invoice_order(order, partner)
            stop.invoice_ids = [(4, invoice.id)]
        return {
            'order': order.name,
            'total': order.amount_total,
            'invoice': invoice.display_name if invoice else None,
        }

    def _stop_van(self, stop):
        tour = stop.list_id.tour_id
        # sudo: van lookup only — drivers hold no fleet.vehicle grant
        return tour.sudo().vehicle_id.dsd_van_location_id if tour else False

    def _driver_discount(self, driver, line):
        discount = line.get('discount') or 0.0
        limit = driver.dsd_max_discount_pct
        if discount > 0 and not limit:
            raise UserError(self.env._(
                'Driver %s has no manual-discount authority.', driver.name))
        if discount > limit:
            raise UserError(self.env._(
                'Discount %s%% exceeds the driver authority of %s%%.',
                discount, limit))
        return discount

    def _invoice_order(self, order, partner):
        # sudo: the invoice is a back-office document; drivers must not need
        # direct account.move create rights
        invoice = order.sudo()._create_invoices()
        exposure = partner.credit + invoice.sudo().amount_total
        if partner.dsd_credit_limit and exposure > partner.dsd_credit_limit:
            # keep the draft for the back office; the driver cannot post it
            raise UserError(self.env._(
                'Credit limit exceeded for %s (exposure %s > limit %s): the '
                'invoice stays in draft for the back office.',
                partner.display_name, exposure, partner.dsd_credit_limit))
        invoice.sudo().action_post()
        order.invoice_ids = [(4, invoice.id)]
        return invoice

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    @api.model
    def create_collection(self, visit_line_id, amount, journal_id, invoice_ids=None):
        stop = self._get_own_stop(visit_line_id)
        # sudo: the collection profile is customer master data — m2m journal
        # reads come back empty through the driver's own access rights
        partner = stop.sudo().partner_id
        if partner.dsd_collection_type != 'on_delivery':
            raise UserError(self.env._(
                '%s is not a cash-collection customer.', partner.display_name))
        journal = self.env['account.journal'].sudo().browse(journal_id)
        if partner.dsd_cash_only and journal.type != 'cash':
            raise UserError(self.env._(
                '%s accepts cash only.', partner.display_name))
        if journal not in partner.dsd_accepted_journal_ids:
            raise UserError(self.env._(
                'Payment method %s is not accepted by %s.',
                journal.name, partner.display_name))
        payment = self.env['account.payment'].sudo().create({
            'journal_id': journal.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': amount,
            'memo': f'{stop.list_id.name} collection',
        })
        payment.sudo().action_post()
        for invoice in self.env['account.move'].sudo().browse(invoice_ids or []):
            self._reconcile_payment(invoice, payment)
        stop.payment_ids = [(4, payment.id)]
        return {
            'payment': payment.name,
            'amount': amount,
            'journal': journal.name,
        }

    def _reconcile_payment(self, invoice, payment):
        """Reconcile the payment with the invoice: try the standard
        outstanding-line path first; on charts where the invoice receivable
        account differs from the outstanding receipts account it silently
        no-ops, so fall back to a direct receivable-to-receivable
        reconciliation."""
        receivable = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
            and l.amount_residual)
        before = invoice.amount_residual
        outstanding = payment.move_id.line_ids.filtered(
            lambda l: l.account_id == payment.outstanding_account_id)
        for line in outstanding:
            invoice.js_assign_outstanding_line(line.id)
        if invoice.amount_residual != before:
            return
        payment_side = payment.move_id.line_ids.filtered(
            lambda l: l.account_id == receivable.account_id and l.credit > 0)
        if payment_side and receivable:
            (payment_side + receivable).reconcile()

    # ------------------------------------------------------------------
    # Stops: unplanned + resequencing
    # ------------------------------------------------------------------

    @api.model
    def add_unplanned_stop(self, visit_list_id, partner_id=None, name=None,
                           street=False, city=False, phone=False):
        visit_list = self._ensure_list_access(
            self.env['dsd.visit.list'].browse(visit_list_id))
        if partner_id:
            partner = self.env['res.partner'].sudo().browse(partner_id)
        else:
            if not name:
                raise UserError(_('Provide a name for the one-time customer.'))
            partner = self.env['res.partner'].sudo().create({
                'name': name,
                'street': street or False,
                'city': city or False,
                'phone': phone or False,
                'dsd_is_one_time': True,
                'dsd_route_id': visit_list.route_id.id,
            })
        stop = self.env['dsd.visit.list.line'].create({
            'list_id': visit_list.id,
            'partner_id': partner.id,
            'is_unplanned': True,
            'sequence': (max(visit_list.line_ids.mapped('sequence'), default=0)) + 10,
        })
        visit_list._sync_appointments()
        return {'stop_id': stop.id, 'partner_id': partner.id}

    @api.model
    def resequence_stops(self, visit_list_id, ordered_line_ids):
        visit_list = self._ensure_list_access(
            self.env['dsd.visit.list'].browse(visit_list_id))
        for index, line_id in enumerate(ordered_line_ids):
            line = self.env['dsd.visit.list.line'].browse(line_id)
            if line.list_id != visit_list:
                raise UserError(_('Stop %s is not on this list.', line_id))
            line.sequence = (index + 1) * 10
        return True

    # ------------------------------------------------------------------
    # Expenses, van adjustments, checks, reload
    # ------------------------------------------------------------------

    @api.model
    def add_expense(self, tour_id, product_id, amount, description=None):
        tour = self._ensure_tour_access(
            self.env['stock.picking.batch'].browse(tour_id))
        driver = self._get_driver()
        expense = self.env['hr.expense'].sudo().create({
            'employee_id': driver.id,
            'product_id': product_id,
            'total_amount': amount,
            'description': description or tour.name,
            'dsd_tour_id': tour.id,
            'date': fields.Date.context_today(self),
        })
        return {'expense': expense.name}

    @api.model
    def adjust_van_stock(self, tour_id, product_id, new_qty, reason_id):
        tour = self._ensure_tour_access(
            self.env['stock.picking.batch'].browse(tour_id))
        van = tour.sudo().vehicle_id.dsd_van_location_id
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product_id),
            ('location_id', '=', van.id)], limit=1)
        if quant:
            quant.write({'inventory_quantity': new_qty})
            quant.action_apply_inventory()
        else:
            self.env['stock.quant'].sudo().create({
                'product_id': product_id,
                'location_id': van.id,
                'inventory_quantity': new_qty,
            }).action_apply_inventory()
        return True

    @api.model
    def submit_check(self, tour_id, check_type, material_counts=None,
                     payment_counts=None):
        """material_counts: {product_id: qty}; payment_counts: [{journal_id,
        amount}]. Differences need a dispatcher/supervisor to confirm."""
        tour = self._ensure_tour_access(
            self.env['stock.picking.batch'].browse(tour_id))
        material_counts = material_counts or {}
        check = self.env['dsd.check.record'].create({
            'tour_id': tour.id, 'check_type': check_type})
        for line in check.material_line_ids:
            if line.product_id.id in material_counts:
                line.counted_qty = material_counts[line.product_id.id]
        for entry in payment_counts or []:
            check.payment_line_ids = [(0, 0, {
                'journal_id': entry['journal_id'],
                'counted_amount': entry['amount'],
            })]
        check.action_confirm()
        return {'check': check.name, 'state': check.state}

    @api.model
    def depart_tour(self, tour_id):
        tour = self._ensure_tour_access(
            self.env['stock.picking.batch'].browse(tour_id))
        tour.action_dsd_start()
        return {'state': tour.dsd_state}

    @api.model
    def request_reload(self, tour_id, lines):
        """lines: [{product_id, qty}] (qty negative = return to warehouse).
        Creates the pickings; the warehouse executes them."""
        tour = self._ensure_tour_access(
            self.env['stock.picking.batch'].browse(tour_id))
        # sudo: reload pickings are executed by the warehouse; the driver
        # only requests them (van/warehouse/picking-type lookups included)
        warehouse = tour.sudo().dsd_route_id.warehouse_id
        van = tour.sudo()._dsd_van_location()
        picking_type = warehouse.sudo()._dsd_get_load_picking_type()
        positive = [l for l in lines if l['qty'] > 0]
        negative = [l for l in lines if l['qty'] < 0]
        created = self.env['stock.picking'].sudo().browse()
        if positive:
            created |= self.env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': van.id,
                'origin': f'{tour.name} reload',
                'move_ids': [
                    (0, 0, {
                        'product_id': l['product_id'],
                        'product_uom_qty': l['qty'],
                        'uom_id': self.env['product.product'].sudo()
                        .browse(l['product_id']).uom_id.id,
                        'location_id': warehouse.lot_stock_id.id,
                        'location_dest_id': van.id,
                    }) for l in positive
                ],
            })
        if negative:
            created |= self.env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': van.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'origin': f'{tour.name} unload during reload',
                'move_ids': [
                    (0, 0, {
                        'product_id': l['product_id'],
                        'product_uom_qty': -l['qty'],
                        'uom_id': self.env['product.product'].sudo()
                        .browse(l['product_id']).uom_id.id,
                        'location_id': van.id,
                        'location_dest_id': warehouse.lot_stock_id.id,
                    }) for l in negative
                ],
            })
        tour.dsd_reload_picking_ids = [(4, p.id) for p in created]
        return {'pickings': created.mapped('name')}
