from odoo import _, fields, models


class FleetVehicleModelCategory(models.Model):
    _inherit = 'fleet.vehicle.model.category'

    dsd_loading_units = fields.Float(
        string='Loading Unit Capacity',
        help='Rigid-body capacity expressed in the route loading unit '
             '(e.g. pallets or crates); used by the tour loading-unit check.')
