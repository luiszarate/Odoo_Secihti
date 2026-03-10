# -*- coding: utf-8 -*-
import base64
import io
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError


class SecAttachmentExportWizard(models.TransientModel):
    _name = "sec.attachment.export.wizard"
    _description = "Exportar adjuntos de ordenes SECIHTI"

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
    rubro_id = fields.Many2one("sec.rubro", string="Rubro / Tipo de gasto")
    include_pending = fields.Boolean(string="Incluir MXN pendiente", default=False)
    export_attachments = fields.Boolean(string="Adjuntos", default=True)
    export_purchase_orders = fields.Boolean(
        string="Órdenes de compra (PDF)", default=False
    )
    file_data = fields.Binary(string="Archivo", readonly=True)
    filename = fields.Char(string="Nombre de archivo", readonly=True)

    def action_export(self):
        self.ensure_one()
        if not self.export_attachments and not self.export_purchase_orders:
            raise UserError(
                _("Debe seleccionar al menos una opción de exportación.")
            )
        orders = self._get_orders()
        zip_buffer = self._build_zip_buffer(orders)
        filename = self._build_filename()
        self.write(
            {
                "file_data": base64.b64encode(zip_buffer.getvalue()),
                "filename": filename,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def _get_orders(self):
        project = self.project_id
        states = self._get_state_list()
        domain = [("sec_project_id", "=", project.id)]
        if states:
            domain.append(("state", "in", states))
        if self.date_from:
            domain.append(("date_order", ">=", self.date_from))
        if self.date_to:
            domain.append(("date_order", "<=", self.date_to))
        if self.rubro_id:
            domain.append(("sec_rubro_id", "=", self.rubro_id.id))
        orders = self.env["purchase.order"].search(domain, order="date_order asc")
        pending_orders = orders.filtered(lambda o: o.sec_mxn_pending)
        if not self.include_pending:
            orders = orders - pending_orders
        return orders

    def _get_state_list(self):
        if self.state_filter == "all":
            return False
        if self.state_filter == "purchase,done":
            return ["purchase", "done"]
        return [self.state_filter]

    def _build_zip_buffer(self, orders):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for order in orders:
                if self.export_attachments:
                    attachments = self.env["ir.attachment"].search(
                        [
                            ("res_model", "=", "purchase.order"),
                            ("res_id", "=", order.id),
                            ("type", "=", "binary"),
                        ]
                    )
                    for attachment in attachments:
                        if not attachment.datas:
                            continue
                        filename = (
                            getattr(attachment, "datas_fname", False)
                            or attachment.name
                            or "adjunto"
                        )
                        arcname = self._get_attachment_path(order, filename)
                        zip_file.writestr(
                            arcname, base64.b64decode(attachment.datas)
                        )

                if self.export_purchase_orders:
                    pdf_content = self._render_order_pdf(order)
                    if pdf_content:
                        pdf_filename = "%s.pdf" % order.name.replace("/", "-")
                        arcname = self._get_attachment_path(order, pdf_filename)
                        zip_file.writestr(arcname, pdf_content)
        buffer.seek(0)
        return buffer

    def _render_order_pdf(self, order):
        report = self.env.ref("purchase.action_report_purchase_order")
        pdf_content, _content_type = report._render_qweb_pdf([order.id])
        return pdf_content

    def _get_attachment_path(self, order, filename):
        if self.rubro_id:
            return "%s/%s" % (order.name, filename)
        rubro_folder = self._get_rubro_folder(order)
        return "%s/%s/%s" % (rubro_folder, order.name, filename)

    def _get_rubro_folder(self, order):
        rubro = order.sec_rubro_id
        label = rubro.name if rubro else "Sin_rubro"
        return label.replace("/", "-") if label else "Sin_rubro"

    def _build_filename(self):
        project_label = self.project_id.code or self.project_id.name or "Proyecto"
        if self.date_from or self.date_to:
            date_from_label = (
                fields.Date.to_string(self.date_from) if self.date_from else "inicio"
            )
            date_to_label = (
                fields.Date.to_string(self.date_to) if self.date_to else "hoy"
            )
            range_label = "%s_a_%s" % (date_from_label, date_to_label)
        else:
            range_label = "todas_las_fechas"
        if self.export_attachments and self.export_purchase_orders:
            prefix = "Adjuntos_y_OC"
        elif self.export_purchase_orders:
            prefix = "Ordenes_Compra"
        else:
            prefix = "Adjuntos"
        return "%s_%s_%s.zip" % (prefix, project_label, range_label)
