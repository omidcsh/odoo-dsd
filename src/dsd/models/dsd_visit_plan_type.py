from odoo import _, api, fields, models


class DsdVisitPlanType(models.Model):
    """Visit plan type: encodes the driver role and the SAP "Relevant Documents"
    matrix that decides whether the visit list, the tour, or both drive the
    business process for plans of this type.
    """
    _name = 'dsd.visit.plan.type'
    _description = 'DSD Visit Plan Type'
    _order = 'sequence, name'
    _rec_names_search = ['name', 'code']

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    role = fields.Selection([
        ('preseller', 'Preseller'),
        ('delivery', 'Delivery Driver'),
        ('van_sales', 'Van Seller'),
        ('mixed', 'Mixed Driver'),
    ], required=True, default='delivery')
    relevant_doc = fields.Selection([
        ('visit_list', 'Visit List'),
        ('tour', 'Tour'),
        ('both', 'Visit List and Tour'),
    ], required=True, default='both',
        help='SAP "Relevant Documents": delivery driver = tour; van seller = both; '
             'mixed = both; preseller = visit list only.')
    make_delivery = fields.Boolean(
        help='Drivers of this role deliver goods on their tours (SAP "Make Delivery").')
    visit_times_source = fields.Selection([
        ('receiving_hours', 'Customer Receiving Hours'),
        ('contact_times', 'Contact Person Times'),
    ], required=True, default='receiving_hours',
        help='Which master-data source plan items display as visit times.')
    default_waiting_minutes = fields.Integer(default=15)
    default_travel_minutes = fields.Integer(default=20)
    max_load_attempts = fields.Integer(
        help='Overrides the route value for tours planned from lists of this type.')
    driver_lockable = fields.Boolean(
        default=True, string='Driver Swappable on Lists',
        help='Lists of this type may swap driver/vehicle ad hoc (e.g. replacement driver).')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'unique(code)',
        'The visit plan type code must be unique.',
    )

    @api.depends('role')
    def _compute_display_name(self):
        role_labels = dict(self._fields['role']._description_selection(self.env))
        for plan_type in self:
            plan_type.display_name = f"{plan_type.name} ({role_labels.get(plan_type.role, '')})"
