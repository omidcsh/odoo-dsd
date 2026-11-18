from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DsdRouteCustomer(models.Model):
    """Ordered customer membership in a route, with history.

    A customer may leave and re-join a route: rows are per validity window
    and windows for the same (route, partner, sales area) must not overlap
    (review round-2 rule — replaces a plain unique triple).
    """
    _name = 'dsd.route.customer'
    _description = 'DSD Route Customer Membership'
    _order = 'sequence, id'
    _rec_names_search = ['partner_id', 'route_id']

    route_id = fields.Many2one(
        'dsd.route', required=True, index=True, ondelete='cascade')
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, index=True,
        ondelete='cascade')
    sales_area_id = fields.Many2one(
        'dsd.sales.area', string='Sales Area', required=True, index=True,
        ondelete='restrict',
        help="The visit identity sales area — disambiguates customers "
             "active in several sales areas")
    sequence = fields.Integer(default=10, help="Visit order within the route")
    valid_from = fields.Date()
    valid_to = fields.Date(help="Empty = open-ended")

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s — %s' % (
                rec.route_id.display_name or '?',
                rec.partner_id.display_name or '?')

    @api.constrains('route_id', 'partner_id', 'sales_area_id',
                    'valid_from', 'valid_to')
    def _check_membership_rules(self):
        for rec in self:
            # SA compatibility: a scoped route only accepts its own SA (D9-2)
            route_sa = rec.route_id.sales_area_id
            if route_sa and route_sa != rec.sales_area_id:
                raise ValidationError(_(
                    'Route %(route)s is scoped to sales area %(route_sa)s; '
                    'customer %(partner)s cannot join it via %(membership_sa)s.',
                    route=rec.route_id.display_name,
                    route_sa=route_sa.display_name,
                    partner=rec.partner_id.display_name,
                    membership_sa=rec.sales_area_id.display_name,
                ))
            # window sanity
            if rec.valid_from and rec.valid_to and rec.valid_from > rec.valid_to:
                raise ValidationError(_(
                    'Membership validity: "valid from" must not be after '
                    '"valid to" (customer %s).', rec.partner_id.display_name))
            # no overlapping windows for the same triple (history allowed)
            others = self.search([
                ('route_id', '=', rec.route_id.id),
                ('partner_id', '=', rec.partner_id.id),
                ('sales_area_id', '=', rec.sales_area_id.id),
                ('id', '!=', rec.id),
            ])
            for other in others:
                if rec._overlaps(other):
                    raise ValidationError(_(
                        'Customer %(partner)s already has an overlapping '
                        'membership window on route %(route)s (sales area '
                        '%(sa)s). Sequential re-joins are fine; overlaps are not.',
                        partner=rec.partner_id.display_name,
                        route=rec.route_id.display_name,
                        sa=rec.sales_area_id.display_name))

    def _overlaps(self, other):
        """Two date windows overlap (open end = +infinity; open start rare)."""
        s1, e1 = self.valid_from, self.valid_to or fields.Date.today().replace(year=9999)
        s2, e2 = other.valid_from, other.valid_to or fields.Date.today().replace(year=9999)
        if not s1:
            s1 = fields.Date.to_date('1900-01-01')
        if not s2:
            s2 = fields.Date.to_date('1900-01-01')
        return s1 <= e2 and s2 <= e1
