from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DsdVisitListGenerate(models.TransientModel):
    """Generate operational visit lists from strategic visit plans
    (SAP "Create Lists"), with simulation, a generation log and the
    last-execution-date watermark guard.
    """
    _name = 'dsd.visit.list.generate'
    _description = 'Generate Visit Lists'

    plan_ids = fields.Many2many(
        'dsd.visit.plan', string='Visit Plans',
        domain=[('state', '=', 'active')])
    date_from = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self))
    date_to = fields.Date(
        required=True, default=lambda self: fields.Date.context_today(self))
    dry_run = fields.Boolean(
        string='Simulate Only',
        help='Run generation without writing visit lists; the result screen shows '
             'what would be created.')
    state = fields.Selection([
        ('form', 'Form'),
        ('done', 'Done'),
    ], default='form')
    result_html = fields.Html(string='Result', sanitize=False)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(self.env._(
                    'The generation start date must be before its end date.'))

    def action_generate(self):
        self.ensure_one()
        log_rows = []
        for plan in self.plan_ids:
            for day in plan._occurrence_dates(self.date_from, self.date_to):
                status, detail = plan._generate_list_for_date(day, self.dry_run)
                log_rows.append((plan, day, status, detail))
        generated_by_plan = {}
        for plan, day, status, visit_list in log_rows:
            if status == 'created':
                generated_by_plan.setdefault(plan, []).append(day)
        if not self.dry_run:
            for plan, days in generated_by_plan.items():
                plan.last_execution_date = max(days)
            self.env['dsd.visit.appointment']._fill_from_plans(
                self.plan_ids, self.date_from, self.date_to)
        self._log_summary(log_rows, generated_by_plan)
        self.write({
            'state': 'done',
            'result_html': self._render_result(log_rows, generated_by_plan),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_created(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Visit Lists'),
            'res_model': 'dsd.visit.list',
            'view_mode': 'list,form,calendar',
            'domain': [
                ('plan_id', 'in', self.plan_ids.ids),
                ('execution_date', '>=', self.date_from),
                ('execution_date', '<=', self.date_to),
            ],
        }

    def _log_summary(self, log_rows, generated_by_plan):
        for plan in self.plan_ids:
            plan_rows = [row for row in log_rows if row[0] == plan]
            if not plan_rows:
                continue
            created = len(generated_by_plan.get(plan, []))
            skipped = len(plan_rows) - created
            body = self.env._(
                'Visit-list generation %(range)s: %(created)s created, %(skipped)s skipped.',
                range=f'{self.date_from} → {self.date_to}',
                created=created, skipped=skipped)
            details = '<br/>'.join(
                f'{day}: {status}{" — " + detail if isinstance(detail, str) else ""}'
                for _plan, day, status, detail in plan_rows
                if status != 'created')
            if details:
                body += f'<br/>{details}'
            plan.message_post(body=body, body_is_html=True)

    def _render_result(self, log_rows, generated_by_plan):
        total_created = sum(len(days) for days in generated_by_plan.values())
        prefix = 'Simulated (no data written):' if self.dry_run else 'Created:'
        rows = []
        for plan, day, status, detail in log_rows:
            label = {
                'created': '✔ created' if not self.dry_run else '✔ would create',
                'exists': '— list already exists',
                'watermark': '— before last generated date',
                'no_customers': '— no active customers',
            }.get(status, status)
            suffix = ''
            if status == 'created' and hasattr(detail, 'display_name'):
                suffix = f' ({detail.display_name})'
            elif isinstance(detail, str):
                suffix = f' ({detail})'
            rows.append(f'<li>{plan.display_name} — {day}: {label}{suffix}</li>')
        if not rows:
            return f'<p>{prefix} nothing to do in the selected range.</p>'
        return f'<p><b>{prefix} {total_created} visit list(s).</b></p><ul>{"".join(rows)}</ul>'
