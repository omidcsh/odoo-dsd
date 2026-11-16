from odoo import _, fields, models


class DsdTourMaterials(models.TransientModel):
    """Read-only materials overview dialog (SAP shipment materials overview):
    planned quantities aggregated across the tour deliveries."""
    _name = 'dsd.tour.materials'
    _description = 'DSD Tour Materials Overview'

    tour_id = fields.Many2one('stock.picking.batch')
    materials_html = fields.Html(sanitize=False)
    tour_state = fields.Selection(related='tour_id.dsd_state')
    tour_stop_count = fields.Integer(related='tour_id.dsd_stop_count')
