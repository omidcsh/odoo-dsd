"""Driver console HTTP API (versioned). Thin wrappers over the dsd.console
service methods — the OWL console calls only these, and every endpoint
requires a logged-in driver (or dispatcher) session."""
from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request, route


class DsdConsoleController(http.Controller):

    def _service(self):
        return request.env['dsd.console']

    def _call(self, method, *args, **kwargs):
        try:
            return {'ok': True, 'data': getattr(self._service(), method)(*args, **kwargs)}
        except (AccessError, UserError) as error:
            return {'ok': False, 'error': str(error)}

    @route('/dsd/console', auth='user', website=False)
    def console_page(self, **kwargs):
        if not request.env.user.has_group('dsd.group_dsd_driver') \
                and not request.env.user.has_group('dsd.group_dsd_dispatcher'):
            return request.redirect('/web/login')
        return request.render('dsd.console_shell')

    @route('/dsd/api/v1/get_console_data', auth='user', type='json', csrf=True)
    def api_get_console_data(self, **kwargs):
        return self._call('get_console_data')

    @route('/dsd/api/v1/get_stop', auth='user', type='json', csrf=True)
    def api_get_stop(self, visit_line_id, **kwargs):
        return self._call('get_stop', visit_line_id)

    @route('/dsd/api/v1/set_arrival', auth='user', type='json', csrf=True)
    def api_set_arrival(self, visit_line_id, **kwargs):
        return self._call('set_arrival', visit_line_id)

    @route('/dsd/api/v1/set_departure', auth='user', type='json', csrf=True)
    def api_set_departure(self, visit_line_id, **kwargs):
        return self._call('set_departure', visit_line_id)

    @route('/dsd/api/v1/set_visit_status', auth='user', type='json', csrf=True)
    def api_set_visit_status(self, visit_line_id, status, reason_id=None, **kwargs):
        return self._call('set_visit_status', visit_line_id, status, reason_id)

    @route('/dsd/api/v1/set_visit_note', auth='user', type='json', csrf=True)
    def api_set_visit_note(self, visit_line_id, note, **kwargs):
        return self._call('set_visit_note', visit_line_id, note)

    @route('/dsd/api/v1/confirm_delivery', auth='user', type='json', csrf=True)
    def api_confirm_delivery(self, picking_id, quantities=None, **kwargs):
        return self._call('confirm_delivery', picking_id, quantities)

    @route('/dsd/api/v1/create_van_sale', auth='user', type='json', csrf=True)
    def api_create_van_sale(self, visit_line_id, lines, apply_deal_ids=None, **kwargs):
        return self._call('create_van_sale', visit_line_id, lines, apply_deal_ids)

    @route('/dsd/api/v1/create_collection', auth='user', type='json', csrf=True)
    def api_create_collection(self, visit_line_id, amount, journal_id,
                              invoice_ids=None, **kwargs):
        return self._call('create_collection', visit_line_id, amount, journal_id,
                          invoice_ids)

    @route('/dsd/api/v1/add_unplanned_stop', auth='user', type='json', csrf=True)
    def api_add_unplanned_stop(self, visit_list_id, partner_id=None, name=None,
                               street=False, city=False, phone=False, **kwargs):
        return self._call('add_unplanned_stop', visit_list_id, partner_id, name,
                          street, city, phone)

    @route('/dsd/api/v1/resequence_stops', auth='user', type='json', csrf=True)
    def api_resequence_stops(self, visit_list_id, ordered_line_ids, **kwargs):
        return self._call('resequence_stops', visit_list_id, ordered_line_ids)

    @route('/dsd/api/v1/add_expense', auth='user', type='json', csrf=True)
    def api_add_expense(self, tour_id, product_id, amount, description=None, **kwargs):
        return self._call('add_expense', tour_id, product_id, amount, description)

    @route('/dsd/api/v1/adjust_van_stock', auth='user', type='json', csrf=True)
    def api_adjust_van_stock(self, tour_id, product_id, new_qty, reason_id, **kwargs):
        return self._call('adjust_van_stock', tour_id, product_id, new_qty, reason_id)

    @route('/dsd/api/v1/submit_check', auth='user', type='json', csrf=True)
    def api_submit_check(self, tour_id, check_type, material_counts=None,
                         payment_counts=None, **kwargs):
        return self._call('submit_check', tour_id, check_type, material_counts,
                          payment_counts)

    @route('/dsd/api/v1/depart_tour', auth='user', type='json', csrf=True)
    def api_depart_tour(self, tour_id, **kwargs):
        return self._call('depart_tour', tour_id)

    @route('/dsd/api/v1/request_reload', auth='user', type='json', csrf=True)
    def api_request_reload(self, tour_id, lines, **kwargs):
        return self._call('request_reload', tour_id, lines)
