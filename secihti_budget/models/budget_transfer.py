# -*- coding: utf-8 -*-
import csv
import base64
from io import StringIO, BytesIO
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_is_zero
from odoo.tools.misc import formatLang

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class SecBudgetTransfer(models.Model):
    _name = "sec.budget.transfer"
    _description = "Transferencia presupuestal"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia", default=lambda self: _("Nuevo"), copy=False, tracking=True
    )
    stage_id = fields.Many2one(
        "sec.stage", required=True, tracking=True, ondelete="cascade"
    )
    project_id = fields.Many2one(
        related="stage_id.project_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(
        related="project_id.currency_id", store=True, readonly=True
    )
    activity_from_id = fields.Many2one(
        "sec.activity",
        string="Actividad origen",
        required=True,
        tracking=True,
        ondelete="cascade",
        domain="[('stage_id', '=', stage_id)]",
        oldname="activity_id",
    )
    activity_to_id = fields.Many2one(
        "sec.activity",
        string="Actividad destino",
        required=True,
        tracking=True,
        domain="[('stage_id', '=', stage_id)]",
        ondelete="cascade",
    )
    line_from_id = fields.Many2one(
        "sec.activity.budget.line",
        string="Línea origen",
        required=True,
        tracking=True,
        domain="[('activity_id', '=', activity_from_id)]",
    )
    line_to_id = fields.Many2one(
        "sec.activity.budget.line",
        string="Línea destino",
        required=True,
        tracking=True,
        domain="[('activity_id', '=', activity_to_id)]",
    )
    amount_programa = fields.Monetary(
        string="Monto programa",
        currency_field="currency_id",
        tracking=True,
    )
    amount_concurrente = fields.Monetary(
        string="Monto concurrente",
        currency_field="currency_id",
        tracking=True,
    )
    amount = fields.Monetary(
        string="Total",
        compute="_compute_amount",
        inverse="_inverse_amount",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    date = fields.Date(default=fields.Date.context_today, tracking=True)
    justification = fields.Text(tracking=True)
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("confirmed", "Confirmado"),
        ],
        default="draft",
        tracking=True,
    )

    @api.onchange("stage_id")
    def _onchange_stage(self):
        for transfer in self:
            if transfer.activity_from_id and transfer.activity_from_id.stage_id != transfer.stage_id:
                transfer.activity_from_id = False
                transfer.line_from_id = False
            if transfer.activity_to_id and transfer.activity_to_id.stage_id != transfer.stage_id:
                transfer.activity_to_id = False
                transfer.line_to_id = False

    @api.onchange("line_from_id")
    def _onchange_line_from(self):
        for transfer in self:
            if transfer.line_from_id:
                transfer.activity_from_id = transfer.line_from_id.activity_id
                transfer.stage_id = transfer.line_from_id.stage_id
                transfer._onchange_amount()

    @api.onchange("line_to_id")
    def _onchange_line_to(self):
        for transfer in self:
            if transfer.line_to_id:
                transfer.activity_to_id = transfer.line_to_id.activity_id
                transfer.stage_id = transfer.line_to_id.stage_id
                transfer._onchange_amount()

    @api.onchange("activity_from_id")
    def _onchange_activity_from(self):
        for transfer in self:
            if transfer.activity_from_id:
                transfer.stage_id = transfer.activity_from_id.stage_id

    @api.onchange("activity_to_id")
    def _onchange_activity_to(self):
        for transfer in self:
            if transfer.activity_to_id:
                transfer.stage_id = transfer.activity_to_id.stage_id

    @api.constrains(
        "stage_id",
        "activity_from_id",
        "activity_to_id",
        "line_from_id",
        "line_to_id",
    )
    def _check_activity_consistency(self):
        for transfer in self:
            if (
                not transfer.stage_id
                or not transfer.activity_from_id
                or not transfer.activity_to_id
                or not transfer.line_from_id
                or not transfer.line_to_id
            ):
                continue
            if transfer.activity_from_id.stage_id != transfer.stage_id:
                raise ValidationError(
                    _("La actividad de origen debe pertenecer a la etapa indicada."),
                )
            if transfer.activity_to_id.stage_id != transfer.stage_id:
                raise ValidationError(
                    _("La actividad de destino debe pertenecer a la etapa indicada."),
                )
            if transfer.activity_from_id.stage_id != transfer.activity_to_id.stage_id:
                raise ValidationError(
                    _("Las actividades de la transferencia deben pertenecer a la misma etapa."),
                )
            if transfer.line_from_id.activity_id != transfer.activity_from_id:
                raise ValidationError(
                    _("La línea de origen debe pertenecer a la actividad de origen."),
                )
            if transfer.line_to_id.activity_id != transfer.activity_to_id:
                raise ValidationError(
                    _("La línea de destino debe pertenecer a la actividad de destino."),
                )

    @api.depends("amount_programa", "amount_concurrente")
    def _compute_amount(self):
        for transfer in self:
            transfer.amount = (transfer.amount_programa or 0.0) + (
                transfer.amount_concurrente or 0.0
            )

    def _inverse_amount(self):
        for transfer in self:
            project = transfer._get_project()
            if not project:
                continue

            total = transfer.amount or 0.0
            transfer.amount_programa = total * (project.pct_programa / 100.0)
            transfer.amount_concurrente = total * (project.pct_concurrente / 100.0)

    @api.onchange("amount")
    def _onchange_amount(self):
        for transfer in self:
            project = transfer._get_project()
            if not project:
                continue

            total = transfer.amount or 0.0
            transfer.amount_programa = total * (project.pct_programa / 100.0)
            transfer.amount_concurrente = total * (project.pct_concurrente / 100.0)

    def _get_precision(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return currency.rounding or self.env.company.currency_id.rounding

    def _get_project(self):
        self.ensure_one()
        if self.project_id:
            return self.project_id
        if self.stage_id:
            return self.stage_id.project_id
        activities = self.activity_from_id | self.activity_to_id
        if activities:
            return activities[0].project_id
        lines = self.line_from_id | self.line_to_id
        if lines:
            return lines[0].project_id
        return False

    def _validate_lines(self):
        for transfer in self:
            if not transfer.line_from_id or not transfer.line_to_id:
                raise ValidationError(
                    _("Debe seleccionar las líneas de origen y destino para la transferencia.")
                )
            if transfer.line_from_id == transfer.line_to_id:
                raise ValidationError(
                    _("La línea de origen y destino no pueden ser la misma.")
                )
            if (
                transfer.line_from_id.activity_id != transfer.activity_from_id
                or transfer.line_to_id.activity_id != transfer.activity_to_id
            ):
                raise ValidationError(
                    _("Las líneas seleccionadas deben pertenecer a las actividades indicadas."),
                )
            if transfer.activity_from_id.stage_id != transfer.activity_to_id.stage_id:
                raise ValidationError(
                    _("No es posible transferir entre actividades de diferentes etapas."),
                )
            if transfer.activity_from_id.stage_id != transfer.stage_id:
                raise ValidationError(
                    _("La etapa seleccionada debe coincidir con la etapa de la actividad de origen."),
                )
            if transfer.activity_to_id.stage_id != transfer.stage_id:
                raise ValidationError(
                    _("La etapa seleccionada debe coincidir con la etapa de la actividad de destino."),
                )

    def _validate_amounts(self):
        for transfer in self:
            precision = transfer._get_precision()
            prog = transfer.amount_programa or 0.0
            conc = transfer.amount_concurrente or 0.0
            if prog < 0.0 or conc < 0.0:
                raise ValidationError(
                    _("Los montos de la transferencia no pueden ser negativos.")
                )
            if float_is_zero(prog, precision_rounding=precision) and float_is_zero(
                conc, precision_rounding=precision
            ):
                raise ValidationError(
                    _("Debe especificar un monto en Programa y/o Concurrente para transferir.")
                )

    @api.model
    def create(self, vals):
        default_name = _("Nuevo")
        if not vals.get("name") or vals.get("name") == default_name:
            vals["name"] = (
                self.env["ir.sequence"].next_by_code("sec.budget.transfer")
                or default_name
            )

        if vals.get("amount") and not vals.get("amount_programa") and not vals.get(
            "amount_concurrente"
        ):
            project = False
            stage = False
            activity = False
            if vals.get("stage_id"):
                stage = self.env["sec.stage"].browse(vals["stage_id"])
            elif vals.get("activity_from_id"):
                activity = self.env["sec.activity"].browse(vals["activity_from_id"])
                stage = activity.stage_id
            elif vals.get("line_from_id"):
                line = self.env["sec.activity.budget.line"].browse(vals["line_from_id"])
                activity = line.activity_id
                stage = line.stage_id
                vals.setdefault("activity_from_id", activity.id)
            elif vals.get("line_to_id"):
                line = self.env["sec.activity.budget.line"].browse(vals["line_to_id"])
                activity = line.activity_id
                stage = line.stage_id
                vals.setdefault("activity_to_id", activity.id)
            if vals.get("activity_to_id") and not stage:
                activity = self.env["sec.activity"].browse(vals["activity_to_id"])
                stage = activity.stage_id
            if stage and not vals.get("stage_id"):
                vals["stage_id"] = stage.id
            if stage:
                project = stage.project_id
            elif activity:
                project = activity.project_id
            if project:
                total = vals.get("amount") or 0.0
                vals["amount_programa"] = total * (project.pct_programa / 100.0)
                vals["amount_concurrente"] = total * (project.pct_concurrente / 100.0)
        record = super().create(vals)
        if record.state == "confirmed":
            record.action_confirm()
        return record

    def write(self, vals):
        tracked_fields = {
            "amount_programa",
            "amount_concurrente",
            "amount",
            "line_from_id",
            "line_to_id",
        }

        confirmed_to_update = self.filtered(lambda t: t.state == "confirmed")
        should_update_budget = bool(tracked_fields & set(vals.keys()))

        if confirmed_to_update and should_update_budget:
            blocked_amount_fields = {"amount", "amount_programa", "amount_concurrente"}
            if blocked_amount_fields & set(vals.keys()):
                raise ValidationError(
                    _(
                        "No es posible modificar los montos de una transferencia confirmada."
                        " Solo puede actualizar la justificación."
                    )
                )
            updated_transfers = set()
            for transfer in confirmed_to_update:
                updated_transfers.add(transfer.id)
                transfer.line_from_id._apply_transfer_delta(
                    transfer.amount_programa or 0.0,
                    transfer.amount_concurrente or 0.0,
                    transfer,
                    direction="in",
                )
                transfer.line_to_id._apply_transfer_delta(
                    -1 * (transfer.amount_programa or 0.0),
                    -1 * (transfer.amount_concurrente or 0.0),
                    transfer,
                    direction="out",
                )
        else:
            updated_transfers = set()

        res = super().write(vals)

        if updated_transfers:
            for transfer in self.filtered(lambda t: t.id in updated_transfers):
                if transfer.state != "confirmed":
                    continue

                transfer._validate_lines()
                transfer._validate_amounts()

                transfer.line_from_id.apply_transfer_out(
                    transfer.amount_programa or 0.0,
                    transfer.amount_concurrente or 0.0,
                    transfer,
                )
                transfer.line_to_id.apply_transfer_in(
                    transfer.amount_programa or 0.0,
                    transfer.amount_concurrente or 0.0,
                    transfer,
                )

        return res

    def action_confirm(self):
        for transfer in self:
            if transfer.state == "confirmed":
                continue
            transfer._validate_lines()
            transfer._validate_amounts()

            transfer.line_from_id.apply_transfer_out(
                transfer.amount_programa, transfer.amount_concurrente, transfer
            )
            transfer.line_to_id.apply_transfer_in(
                transfer.amount_programa, transfer.amount_concurrente, transfer
            )

            transfer.write({"state": "confirmed"})

            currency = transfer.currency_id or self.env.company.currency_id
            body = _(
                "Transferencia aplicada: %(monto)s (Programa: %(prog)s, Concurrente: %(conc)s).",
                monto=formatLang(self.env, transfer.amount or 0.0, currency_obj=currency),
                prog=formatLang(
                    self.env, transfer.amount_programa or 0.0, currency_obj=currency
                ),
                conc=formatLang(
                    self.env, transfer.amount_concurrente or 0.0, currency_obj=currency
                ),
            )
            transfer.message_post(body="<p>%s</p>" % body, subtype_xmlid="mail.mt_note")
        return True

    def unlink(self):
        for transfer in self:
            if transfer.state != "confirmed":
                continue

            amount_programa = transfer.amount_programa or 0.0
            amount_concurrente = transfer.amount_concurrente or 0.0

            transfer.line_from_id._apply_transfer_delta(
                amount_programa,
                amount_concurrente,
                transfer,
                direction="in",
            )

            transfer.line_to_id._apply_transfer_delta(
                -amount_programa,
                -amount_concurrente,
                transfer,
                direction="out",
            )

            transfer.message_post(
                body="<p>%s</p>" %
                _(
                    "Se revirtieron los montos de la transferencia al eliminar el registro."
                ),
                subtype_xmlid="mail.mt_note",
            )

        return super().unlink()

    def action_export_transfer_csv(self):
        """
        Export selected transfers to CSV file grouped by rubro.
        Groups all transfers by rubro regardless of activity and calculates:
        - Authorized amounts (70% PP F003, 30% Concurrent)
        - Requested modifications (70% PP F003, 30% Concurrent)
        - Updated amounts (70% PP F003, 30% Concurrent)
        """
        if not self:
            raise UserError(_("Debe seleccionar al menos una transferencia para exportar."))

        # Get all stages involved in the selected transfers
        stages = self.mapped('stage_id')
        if len(stages) > 1:
            raise UserError(
                _("Solo puede exportar transferencias de una misma etapa. "
                  "Las transferencias seleccionadas pertenecen a múltiples etapas.")
            )

        stage = stages[0]

        # Collect all rubros involved (both from source and destination lines)
        rubros_data = {}

        # Get all budget lines in this stage to calculate authorized amounts
        all_stage_lines = self.env['sec.activity.budget.line'].search([
            ('stage_id', '=', stage.id)
        ])

        # Group stage lines by rubro to get authorized amounts
        for line in all_stage_lines:
            rubro_id = line.rubro_id.id
            if rubro_id not in rubros_data:
                rubros_data[rubro_id] = {
                    'rubro_name': line.rubro_id.name,
                    'etapa': stage.name,
                    'authorized_programa': 0.0,
                    'authorized_concurrente': 0.0,
                    'modification_programa': 0.0,
                    'modification_concurrente': 0.0,
                }

            # Sum authorized amounts (current budget)
            rubros_data[rubro_id]['authorized_programa'] += line.amount_programa or 0.0
            rubros_data[rubro_id]['authorized_concurrente'] += line.amount_concurrente or 0.0

        # Process selected transfers to calculate modifications per rubro
        for transfer in self:
            # Source rubro (losing budget)
            rubro_from_id = transfer.line_from_id.rubro_id.id
            if rubro_from_id in rubros_data:
                rubros_data[rubro_from_id]['modification_programa'] -= transfer.amount_programa or 0.0
                rubros_data[rubro_from_id]['modification_concurrente'] -= transfer.amount_concurrente or 0.0

            # Destination rubro (receiving budget)
            rubro_to_id = transfer.line_to_id.rubro_id.id
            if rubro_to_id not in rubros_data:
                rubros_data[rubro_to_id] = {
                    'rubro_name': transfer.line_to_id.rubro_id.name,
                    'etapa': stage.name,
                    'authorized_programa': 0.0,
                    'authorized_concurrente': 0.0,
                    'modification_programa': 0.0,
                    'modification_concurrente': 0.0,
                }

            rubros_data[rubro_to_id]['modification_programa'] += transfer.amount_programa or 0.0
            rubros_data[rubro_to_id]['modification_concurrente'] += transfer.amount_concurrente or 0.0

        # Create CSV file
        output = StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)

        # Write header (using 70% for PP F003 and 30% for Concurrent as requested)
        headers = [
            'Rubro',
            'Movimiento',
            'Etapa',
            'Monto autorizado PP F003',
            'Monto Autorizado Concurrente',
            'Modificacion Solicitada PP F003',
            'Modificacion Solicitada Concurrente',
            'Monto Actualizado PP F003',
            'Monto Actualizado Concurrente',
        ]
        writer.writerow(headers)

        # Write data rows - only include rubros with modifications
        for rubro_id, data in sorted(rubros_data.items(), key=lambda x: x[1]['rubro_name']):
            # Only include rubros that have modifications
            if float_is_zero(data['modification_programa'], precision_digits=2) and \
               float_is_zero(data['modification_concurrente'], precision_digits=2):
                continue

            # Calculate 70/30 split for authorized amounts
            authorized_total = data['authorized_programa'] + data['authorized_concurrente']
            authorized_ppf003 = authorized_total * 0.70
            authorized_concurrent = authorized_total * 0.30

            # Calculate 70/30 split for modifications
            modification_total = data['modification_programa'] + data['modification_concurrente']
            modification_ppf003 = modification_total * 0.70
            modification_concurrent = modification_total * 0.30

            # Calculate 70/30 split for updated amounts
            updated_total = authorized_total + modification_total
            updated_ppf003 = updated_total * 0.70
            updated_concurrent = updated_total * 0.30

            row = [
                data['rubro_name'],
                'Modificacion',
                data['etapa'],
                f"{authorized_ppf003:.2f}",
                f"{authorized_concurrent:.2f}",
                f"{modification_ppf003:.2f}",
                f"{modification_concurrent:.2f}",
                f"{updated_ppf003:.2f}",
                f"{updated_concurrent:.2f}",
            ]
            writer.writerow(row)

        # Get CSV content
        csv_content = output.getvalue()
        output.close()

        # Create attachment
        filename = f"transferencias_{stage.name}_{fields.Date.today()}.csv"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(csv_content.encode('utf-8-sig')),
            'mimetype': 'text/csv',
        })

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_export_transfers_history(self):
        """
        Export detailed history of selected transfers showing budget state before and after.
        Shows:
        - Budget by activity and rubro
        - Total amounts per rubro (sum across all activities)
        - State before and after each transfer

        The state is calculated by starting from the current state and reversing transfers
        from most recent to oldest, then displaying them in chronological order.
        """
        if not self:
            raise UserError(_("Debe seleccionar al menos una transferencia para exportar."))

        if not xlsxwriter:
            raise UserError(_("La biblioteca xlsxwriter no está instalada. Por favor instálela para usar esta funcionalidad."))

        # Get all stages involved in the selected transfers
        stages = self.mapped('stage_id')
        if len(stages) > 1:
            raise UserError(
                _("Solo puede exportar transferencias de una misma etapa. "
                  "Las transferencias seleccionadas pertenecen a múltiples etapas.")
            )

        stage = stages[0]
        currency = self[0].currency_id or self.env.company.currency_id

        # Get all budget lines in this stage to track state
        all_stage_lines = self.env['sec.activity.budget.line'].search([
            ('stage_id', '=', stage.id)
        ])

        # Build current state (after all transfers have been applied)
        # Key: (activity_id, rubro_id), Value: {programa, concurrente, total}
        current_state = {}
        for line in all_stage_lines:
            key = (line.activity_id.id, line.rubro_id.id)
            current_state[key] = {
                'line_id': line.id,
                'activity_name': line.activity_id.name,
                'rubro_id': line.rubro_id.id,
                'rubro_name': line.rubro_id.name,
                'programa': line.amount_programa or 0.0,
                'concurrente': line.amount_concurrente or 0.0,
                'total': line.amount_total or 0.0,
            }

        # Sort transfers from most recent to oldest for state reconstruction
        transfers_desc = self.sorted(key=lambda t: (t.date, t.id), reverse=True)

        # Dictionary to store the before/after state for each transfer
        # {transfer_id: {'before': state_dict, 'after': state_dict}}
        transfer_history = {}

        # Process transfers from most recent to oldest, reversing each one
        working_state = {}
        for key, data in current_state.items():
            working_state[key] = data.copy()

        for transfer in transfers_desc:
            # The "after" state for this transfer is the current working_state
            after_state = {}
            for key, data in working_state.items():
                after_state[key] = data.copy()

            # Now reverse this transfer in the working_state
            line_from = transfer.line_from_id
            line_to = transfer.line_to_id

            key_from = (line_from.activity_id.id, line_from.rubro_id.id)
            key_to = (line_to.activity_id.id, line_to.rubro_id.id)

            # Reverse the transfer: add back to origin, subtract from destination
            if key_from in working_state:
                working_state[key_from]['programa'] += transfer.amount_programa or 0.0
                working_state[key_from]['concurrente'] += transfer.amount_concurrente or 0.0
                working_state[key_from]['total'] = working_state[key_from]['programa'] + working_state[key_from]['concurrente']

            if key_to in working_state:
                working_state[key_to]['programa'] -= transfer.amount_programa or 0.0
                working_state[key_to]['concurrente'] -= transfer.amount_concurrente or 0.0
                working_state[key_to]['total'] = working_state[key_to]['programa'] + working_state[key_to]['concurrente']

            # The "before" state for this transfer is the new working_state
            before_state = {}
            for key, data in working_state.items():
                before_state[key] = data.copy()

            transfer_history[transfer.id] = {
                'before': before_state,
                'after': after_state,
            }

        # Create Excel file
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Historial de Transferencias')

        # Define formats
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1
        })

        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#D9E1F2',
            'border': 1,
            'text_wrap': True
        })

        subheader_format = workbook.add_format({
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'bg_color': '#E7E6E6',
            'border': 1
        })

        cell_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })

        number_format = workbook.add_format({
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '#,##0.00'
        })

        total_format = workbook.add_format({
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'bg_color': '#FFF2CC',
            'border': 1,
            'num_format': '#,##0.00'
        })

        # Set column widths
        worksheet.set_column('A:A', 30)  # Rubro/Actividad
        worksheet.set_column('B:B', 25)  # Info adicional
        worksheet.set_column('C:H', 18)  # Numeric columns

        # Write title
        row = 0
        worksheet.merge_range(row, 0, row, 7,
            f'Historial de Transferencias - Etapa: {stage.name}', title_format)
        row += 2

        # Now display transfers in chronological order (oldest to newest)
        for transfer in self.sorted(key=lambda t: (t.date, t.id)):
            history = transfer_history[transfer.id]
            before_state = history['before']
            after_state = history['after']

            # Transfer header
            worksheet.merge_range(row, 0, row, 7,
                f'Transferencia: {transfer.name} - Fecha: {transfer.date} - '
                f'Monto: {formatLang(self.env, transfer.amount or 0.0, currency_obj=currency)}',
                subheader_format)
            row += 1

            if transfer.justification:
                worksheet.merge_range(row, 0, row, 7,
                    f'Justificación: {transfer.justification}',
                    cell_format)
                row += 1

            # Column headers
            headers = [
                'Rubro / Actividad',
                'Tipo',
                'Programa (Antes)',
                'Concurrente (Antes)',
                'Total (Antes)',
                'Programa (Después)',
                'Concurrente (Después)',
                'Total (Después)'
            ]
            for col, header in enumerate(headers):
                worksheet.write(row, col, header, header_format)
            row += 1

            line_from = transfer.line_from_id
            line_to = transfer.line_to_id
            rubro_from = line_from.rubro_id
            rubro_to = line_to.rubro_id

            key_from = (line_from.activity_id.id, rubro_from.id)
            key_to = (line_to.activity_id.id, rubro_to.id)

            # RUBRO ORIGEN
            worksheet.write(row, 0, rubro_from.name, subheader_format)
            worksheet.write(row, 1, 'ORIGEN', subheader_format)
            row += 1

            # Origin activity line
            before_from = before_state.get(key_from, {'programa': 0.0, 'concurrente': 0.0, 'total': 0.0})
            after_from = after_state.get(key_from, {'programa': 0.0, 'concurrente': 0.0, 'total': 0.0})

            worksheet.write(row, 0, f'  {line_from.activity_id.name}', cell_format)
            worksheet.write(row, 1, 'Actividad', cell_format)
            worksheet.write(row, 2, before_from['programa'], number_format)
            worksheet.write(row, 3, before_from['concurrente'], number_format)
            worksheet.write(row, 4, before_from['total'], number_format)
            worksheet.write(row, 5, after_from['programa'], number_format)
            worksheet.write(row, 6, after_from['concurrente'], number_format)
            worksheet.write(row, 7, after_from['total'], number_format)
            row += 1

            # Calculate rubro origin totals (all activities in this rubro)
            before_rubro_from_programa = sum(
                data['programa'] for key, data in before_state.items()
                if data['rubro_id'] == rubro_from.id
            )
            before_rubro_from_concurrente = sum(
                data['concurrente'] for key, data in before_state.items()
                if data['rubro_id'] == rubro_from.id
            )
            before_rubro_from_total = before_rubro_from_programa + before_rubro_from_concurrente

            after_rubro_from_programa = sum(
                data['programa'] for key, data in after_state.items()
                if data['rubro_id'] == rubro_from.id
            )
            after_rubro_from_concurrente = sum(
                data['concurrente'] for key, data in after_state.items()
                if data['rubro_id'] == rubro_from.id
            )
            after_rubro_from_total = after_rubro_from_programa + after_rubro_from_concurrente

            # Rubro origin total
            worksheet.write(row, 0, f'  Total {rubro_from.name}', subheader_format)
            worksheet.write(row, 1, 'Total Rubro', subheader_format)
            worksheet.write(row, 2, before_rubro_from_programa, total_format)
            worksheet.write(row, 3, before_rubro_from_concurrente, total_format)
            worksheet.write(row, 4, before_rubro_from_total, total_format)
            worksheet.write(row, 5, after_rubro_from_programa, total_format)
            worksheet.write(row, 6, after_rubro_from_concurrente, total_format)
            worksheet.write(row, 7, after_rubro_from_total, total_format)
            row += 1

            # RUBRO DESTINO
            worksheet.write(row, 0, rubro_to.name, subheader_format)
            worksheet.write(row, 1, 'DESTINO', subheader_format)
            row += 1

            # Destination activity line
            before_to = before_state.get(key_to, {'programa': 0.0, 'concurrente': 0.0, 'total': 0.0})
            after_to = after_state.get(key_to, {'programa': 0.0, 'concurrente': 0.0, 'total': 0.0})

            worksheet.write(row, 0, f'  {line_to.activity_id.name}', cell_format)
            worksheet.write(row, 1, 'Actividad', cell_format)
            worksheet.write(row, 2, before_to['programa'], number_format)
            worksheet.write(row, 3, before_to['concurrente'], number_format)
            worksheet.write(row, 4, before_to['total'], number_format)
            worksheet.write(row, 5, after_to['programa'], number_format)
            worksheet.write(row, 6, after_to['concurrente'], number_format)
            worksheet.write(row, 7, after_to['total'], number_format)
            row += 1

            # Calculate rubro destination totals (all activities in this rubro)
            before_rubro_to_programa = sum(
                data['programa'] for key, data in before_state.items()
                if data['rubro_id'] == rubro_to.id
            )
            before_rubro_to_concurrente = sum(
                data['concurrente'] for key, data in before_state.items()
                if data['rubro_id'] == rubro_to.id
            )
            before_rubro_to_total = before_rubro_to_programa + before_rubro_to_concurrente

            after_rubro_to_programa = sum(
                data['programa'] for key, data in after_state.items()
                if data['rubro_id'] == rubro_to.id
            )
            after_rubro_to_concurrente = sum(
                data['concurrente'] for key, data in after_state.items()
                if data['rubro_id'] == rubro_to.id
            )
            after_rubro_to_total = after_rubro_to_programa + after_rubro_to_concurrente

            # Rubro destination total
            worksheet.write(row, 0, f'  Total {rubro_to.name}', subheader_format)
            worksheet.write(row, 1, 'Total Rubro', subheader_format)
            worksheet.write(row, 2, before_rubro_to_programa, total_format)
            worksheet.write(row, 3, before_rubro_to_concurrente, total_format)
            worksheet.write(row, 4, before_rubro_to_total, total_format)
            worksheet.write(row, 5, after_rubro_to_programa, total_format)
            worksheet.write(row, 6, after_rubro_to_concurrente, total_format)
            worksheet.write(row, 7, after_rubro_to_total, total_format)
            row += 2  # Extra space between transfers

        workbook.close()

        # Create attachment
        filename = f"historial_transferencias_{stage.name}_{fields.Date.today()}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        output.close()

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
