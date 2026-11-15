from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _


class DsdSettlement(models.Model):
    _name = 'dsd.settlement'
    _description = 'DSD Route Settlement'
    _order = 'id desc'

    name = fields.Char(required=True, copy=False, default='New')
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
        ],
        default='draft', required=True,
    )
    route_day_id = fields.Many2one(
        'dsd.route.day', required=True, index=True, ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='route_day_id.warehouse_id.company_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    expected_cash = fields.Monetary(compute='_compute_expected_cash', store=True)
    counted_cash = fields.Monetary(
        help='Cash actually handed in by the driver at the end of the day.')
    cash_diff = fields.Monetary(compute='_compute_cash_diff', store=True)
    leftover_line_ids = fields.One2many(
        'dsd.settlement.line', 'settlement_id', string='Van Leftover Stock',
        help='Products still sitting in the van when the day was settled — '
             'everything not delivered, sold or returned.',
    )
    variance_move_id = fields.Many2one(
        'account.move', string='Variance Entry', readonly=True, copy=False)
    notes = fields.Text()

    _day_uniq = models.Constraint(
        'unique(route_day_id)',
        'This route day is already settled.',
    )

    @api.depends('route_day_id.visit_ids.payment_ids')
    def _compute_expected_cash(self):
        for settlement in self:
            payments = settlement.route_day_id.visit_ids.payment_ids
            settlement.expected_cash = sum(payments.mapped('amount'))

    @api.depends('expected_cash', 'counted_cash')
    def _compute_cash_diff(self):
        for settlement in self:
            settlement.cash_diff = (
                settlement.counted_cash - settlement.expected_cash)

    @api.model_create_multi
    def create(self, vals_list):
        RouteDay = self.env['dsd.route.day']
        for vals in vals_list:
            day = RouteDay.browse(vals['route_day_id'])
            quants = self.env['stock.quant'].search([
                ('location_id', '=', day.van_location_id.id),
                ('quantity', '!=', 0),
            ]) if day.van_location_id else self.env['stock.quant']
            vals.setdefault('leftover_line_ids', [
                (0, 0, {'product_id': q.product_id.id, 'quantity': q.quantity})
                for q in quants
            ])
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env._('%(day)s — settlement', day=day.name)
        return super().create(vals_list)

    def _open_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_post_settlement(self):
        for settlement in self:
            if settlement.state == 'posted':
                continue
            day = settlement.route_day_id
            route = day.route_id
            if day.state != 'done':
                raise UserError(self.env._(
                    'End the route day before settling it.'))
            if day.return_picking_id and day.return_picking_id.state != 'done':
                raise UserError(self.env._(
                    'Validate the stock return %(picking)s before settling.',
                    picking=day.return_picking_id.name,
                ))
            company = day.warehouse_id.company_id
            journal = route.cash_journal_id or self.env['account.journal'].search(
                [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
            if not journal:
                raise UserError(self.env._(
                    'No cash journal found for company %(company)s — set one '
                    'on the route.', company=company.name,
                ))
            variance_account = route.variance_account_id
            if settlement.cash_diff and not variance_account:
                raise UserError(self.env._(
                    'Cash differs by %(diff)s but the route has no '
                    'settlement variance account.',
                    diff=settlement.cash_diff,
                ))
            if settlement.cash_diff:
                liquidity_account = journal.default_account_id
                if not liquidity_account:
                    raise UserError(self.env._(
                        'The cash journal has no default liquidity account.'))
                diff = settlement.cash_diff
                move = self.env['account.move'].create({
                    'journal_id': journal.id,
                    'date': day.date,
                    'ref': self.env._('Cash variance — %(day)s', day=day.name),
                    'line_ids': [
                        (0, 0, {
                            'name': self.env._(
                                'Cash shortage on %(day)s', day=day.name)
                            if diff < 0 else self.env._(
                                'Cash surplus on %(day)s', day=day.name),
                            'account_id': variance_account.id,
                            'debit': max(0.0, -diff),
                            'credit': max(0.0, diff),
                        }),
                        (0, 0, {
                            'name': self.env._(
                                'Cash count — %(day)s', day=day.name),
                            'account_id': liquidity_account.id,
                            'debit': max(0.0, diff),
                            'credit': max(0.0, -diff),
                        }),
                    ],
                })
                move.action_post()
                settlement.variance_move_id = move
            settlement.state = 'posted'
            day.state = 'settled'
        return True


class DsdSettlementLine(models.Model):
    _name = 'dsd.settlement.line'
    _description = 'DSD Settlement Van Leftover Line'

    settlement_id = fields.Many2one(
        'dsd.settlement', required=True, index=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    quantity = fields.Float('Leftover Quantity', digits='Product Unit')
