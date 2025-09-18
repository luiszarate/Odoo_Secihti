# -*- coding: utf-8 -*-
import base64
import io
from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:  # pragma: no cover
    xlsxwriter = None


class SecExportReportWizard(models.TransientModel):
    _name = "sec.export.report.wizard"
    _description = "Exportar presupuesto SECIHTI"

    project_id = fields.Many2one("sec.project", string="Proyecto", required=True)
    date_from = fields.Date(string="Fecha desde")
    date_to = fields.Date(string="Fecha hasta")
    state_filter = fields.Selection(
        [
            ("purchase,done", "Confirmado y recibido"),
            ("purchase", "Solo confirmados"),
            ("done", "Solo recibidos"),
            ("all", "Todos los estados"),
        ],
        default="purchase,done",
        string="Estados",
    )
    include_pending = fields.Boolean(string="Incluir MXN pendiente", default=False)
    file_data = fields.Binary(string="Archivo", readonly=True)
    filename = fields.Char(string="Nombre de archivo", readonly=True)

    def action_export(self):
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_("No está disponible la librería xlsxwriter."))
        orders, pending_orders = self._get_orders()
        workbook_data = self._build_workbook(orders, pending_orders)
        filename = "Reporte_SECIHTI_%s.xlsx" % (self.project_id.code or self.project_id.name)
        self.write({
            "file_data": base64.b64encode(workbook_data.getvalue()),
            "filename": filename,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def _get_orders(self):
        self.ensure_one()
        project = self.project_id
        states = self._get_state_list()
        domain = [
            ("sec_project_id", "=", project.id),
        ]
        if states:
            domain.append(("state", "in", states))
        if self.date_from:
            domain.append(("date_order", ">=", self.date_from))
        if self.date_to:
            domain.append(("date_order", "<=", self.date_to))
        orders = self.env["purchase.order"].search(domain, order="date_order asc")
        pending_orders = orders.filtered(lambda o: o.sec_mxn_pending)
        if not self.include_pending:
            orders = orders - pending_orders
        return orders, pending_orders

    def _get_state_list(self):
        if self.state_filter == "all":
            return False
        if self.state_filter == "purchase,done":
            return ["purchase", "done"]
        return [self.state_filter]

    def _build_workbook(self, orders, pending_orders):
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        formats = self._get_formats(workbook)
        self._build_detail_sheet(workbook, orders, pending_orders, formats)
        self._build_summary_sheet(workbook, orders, pending_orders, formats)
        workbook.close()
        buffer.seek(0)
        return buffer

    def _get_formats(self, workbook):
        header = workbook.add_format({"bold": True, "bg_color": "#004080", "font_color": "#FFFFFF"})
        money = workbook.add_format({"num_format": "$#,##0.00"})
        bold = workbook.add_format({"bold": True})
        text = workbook.add_format({})
        return {
            "header": header,
            "money": money,
            "bold": bold,
            "text": text,
        }

    def _build_detail_sheet(self, workbook, orders, pending_orders, formats):
        sheet = workbook.add_worksheet("Detalle")
        headers = [
            "Fecha de compra",
            "Proveedor",
            "Nº OC",
            "Proyecto",
            "Etapa",
            "Actividad",
            "Rubro / Tipo de gasto",
            "Importe MXN",
            "Programa (MXN)",
            "Concurrente (MXN)",
            "Total MXN",
            "Moneda original",
            "Total original",
            "¿MXN pendiente?",
            "Notas",
        ]
        sheet.write_row(0, 0, headers, formats["header"])
        row = 1
        for order in orders:
            amount_mxn = order._sec_get_amount_mxn()
            programa = concurrente = total = 0.0
            if order.sec_project_id:
                programa = amount_mxn * (order.sec_project_id.pct_programa / 100.0)
                concurrente = amount_mxn * (order.sec_project_id.pct_concurrente / 100.0)
                total = programa + concurrente
            date_value = ""
            if order.date_order:
                date_value = fields.Date.to_string(order.date_order.date())
            sheet.write(row, 0, date_value, formats["text"])
            sheet.write(row, 1, order.partner_id.name or "", formats["text"])
            sheet.write(row, 2, order.name, formats["text"])
            sheet.write(row, 3, self._format_name(order.sec_project_id), formats["text"])
            sheet.write(row, 4, self._format_name(order.sec_stage_id), formats["text"])
            sheet.write(row, 5, self._format_name(order.sec_activity_id), formats["text"])
            rubro_label = order.sec_rubro_id.name or ""
            if order.sec_rubro_id:
                rubro_label = "%s / %s" % (order.sec_rubro_id.name, dict(order.sec_rubro_id._fields['tipo_gasto'].selection).get(order.sec_rubro_id.tipo_gasto, ""))
            sheet.write(row, 6, rubro_label, formats["text"])
            sheet.write_number(row, 7, amount_mxn, formats["money"])
            sheet.write_number(row, 8, programa, formats["money"])
            sheet.write_number(row, 9, concurrente, formats["money"])
            sheet.write_number(row, 10, total, formats["money"])
            sheet.write(row, 11, order.currency_id.name or "", formats["text"])
            sheet.write_number(row, 12, order.amount_total, formats["money"])
            sheet.write(row, 13, "Sí" if order.sec_mxn_pending else "No", formats["text"])
            sheet.write(row, 14, order.notes or "", formats["text"])
            row += 1
        sheet.autofilter(0, 0, row - 1, len(headers) - 1)
        sheet.freeze_panes(1, 0)

    def _build_summary_sheet(self, workbook, orders, pending_orders, formats):
        sheet = workbook.add_worksheet("Resumen")
        headers = [
            "Nivel",
            "Nombre",
            "Programa (MXN)",
            "Concurrente (MXN)",
            "Total (MXN)",
        ]
        sheet.write_row(0, 0, headers, formats["header"])
        summary = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"programa": 0.0, "concurrente": 0.0, "total": 0.0})))
        for order in orders:
            amount_mxn = order._sec_get_amount_mxn()
            if not amount_mxn or not order.sec_project_id:
                continue
            programa = amount_mxn * (order.sec_project_id.pct_programa / 100.0)
            concurrente = amount_mxn * (order.sec_project_id.pct_concurrente / 100.0)
            total = programa + concurrente
            project_key = order.sec_project_id.id
            stage_key = order.sec_stage_id.id if order.sec_stage_id else False
            activity_key = order.sec_activity_id.id if order.sec_activity_id else False
            summary[project_key][stage_key][activity_key]["programa"] += programa
            summary[project_key][stage_key][activity_key]["concurrente"] += concurrente
            summary[project_key][stage_key][activity_key]["total"] += total

        row = 1
        for project in self.project_id:
            project_totals = {"programa": 0.0, "concurrente": 0.0, "total": 0.0}
            project_summary = summary.get(project.id, {})
            for stage_id, activities in project_summary.items():
                for activity_id, values in activities.items():
                    for key in project_totals:
                        project_totals[key] += values[key]
            sheet.write(row, 0, "Proyecto", formats["bold"])
            sheet.write(row, 1, self._format_name(project), formats["bold"])
            sheet.write_number(row, 2, project_totals["programa"], formats["money"])
            sheet.write_number(row, 3, project_totals["concurrente"], formats["money"])
            sheet.write_number(row, 4, project_totals["total"], formats["money"])
            row += 1
            for stage in project.stage_ids:
                stage_values = project_summary.get(stage.id, {})
                stage_total = {"programa": 0.0, "concurrente": 0.0, "total": 0.0}
                for values in stage_values.values():
                    for key in stage_total:
                        stage_total[key] += values[key]
                sheet.write(row, 0, "Etapa", formats["text"])
                sheet.write(row, 1, self._format_name(stage), formats["text"])
                sheet.write_number(row, 2, stage_total["programa"], formats["money"])
                sheet.write_number(row, 3, stage_total["concurrente"], formats["money"])
                sheet.write_number(row, 4, stage_total["total"], formats["money"])
                row += 1
                for activity in stage.sec_activity_ids:
                    values = stage_values.get(activity.id, {"programa": 0.0, "concurrente": 0.0, "total": 0.0})
                    sheet.write(row, 0, "Actividad", formats["text"])
                    sheet.write(row, 1, self._format_name(activity), formats["text"])
                    sheet.write_number(row, 2, values["programa"], formats["money"])
                    sheet.write_number(row, 3, values["concurrente"], formats["money"])
                    sheet.write_number(row, 4, values["total"], formats["money"])
                    row += 1
            row += 1

        alerts_row = row
        sheet.write(alerts_row, 0, "Alertas", formats["header"])
        row = alerts_row + 1
        if pending_orders:
            sheet.write(row, 0, "Órdenes con MXN pendiente", formats["bold"])
            row += 1
            for order in pending_orders:
                date_value = ""
                if order.date_order:
                    date_value = fields.Date.to_string(order.date_order.date())
                sheet.write(row, 0, date_value, formats["text"])
                sheet.write(row, 1, order.partner_id.name or "", formats["text"])
                sheet.write(row, 2, order.name, formats["text"])
                row += 1
        inconsistencies = []
        if self.project_id.inconsistency_message:
            inconsistencies.append(self.project_id.inconsistency_message)
        for stage in self.project_id.stage_ids:
            if stage.inconsistency_message:
                inconsistencies.append("%s: %s" % (self._format_name(stage), stage.inconsistency_message))
        if inconsistencies:
            sheet.write(row, 0, "Inconsistencias", formats["bold"])
            row += 1
            for message in inconsistencies:
                sheet.write(row, 0, message, formats["text"])
                row += 1
        sheet.autofilter(0, 0, alerts_row - 1, len(headers) - 1)
        sheet.freeze_panes(1, 0)

    @staticmethod
    def _format_name(record):
        if not record:
            return ""
        name = record.name or ""
        code = getattr(record, "code", False)
        if code:
            return "%s – %s" % (code, name)
        return name
