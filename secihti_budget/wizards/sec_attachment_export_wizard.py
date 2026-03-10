# -*- coding: utf-8 -*-
import base64
import io
import logging
import threading
import zipfile

import odoo
from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("processing", "Procesando..."),
            ("done", "Listo"),
            ("error", "Error"),
        ],
        default="draft",
        string="Estado",
        readonly=True,
    )
    progress_message = fields.Char(string="Progreso", readonly=True)
    error_message = fields.Text(string="Mensaje de error", readonly=True)
    file_data = fields.Binary(string="Archivo", readonly=True)
    filename = fields.Char(string="Nombre de archivo", readonly=True)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_export(self):
        self.ensure_one()
        if not self.export_attachments and not self.export_purchase_orders:
            raise UserError(
                _("Debe seleccionar al menos una opción de exportación.")
            )

        # Fast path: attachments only (no PDF rendering) – synchronous
        if not self.export_purchase_orders:
            orders = self._get_orders()
            zip_buffer = self._build_zip_buffer(orders)
            filename = self._build_filename()
            self.write(
                {
                    "file_data": base64.b64encode(zip_buffer.getvalue()),
                    "filename": filename,
                    "state": "done",
                    "progress_message": _(
                        "Exportación completada: %d órdenes."
                    ) % len(orders),
                }
            )
            return self._reopen_wizard()

        # Slow path: PDF generation required – background thread
        self.write(
            {
                "state": "processing",
                "progress_message": _("Iniciando exportación..."),
                "file_data": False,
                "filename": False,
                "error_message": False,
            }
        )
        self._launch_background_export()
        return self._reopen_wizard()

    def action_refresh(self):
        self.ensure_one()
        return self._reopen_wizard()

    def action_reset(self):
        self.ensure_one()
        self.write(
            {
                "state": "draft",
                "file_data": False,
                "filename": False,
                "error_message": False,
                "progress_message": False,
            }
        )
        return self._reopen_wizard()

    def _reopen_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Background export
    # ------------------------------------------------------------------

    def _launch_background_export(self):
        db_name = self.env.cr.dbname
        uid = self.env.uid
        wizard_id = self.id

        def _generate():
            with odoo.api.Environment.manage():
                try:
                    with odoo.registry(db_name).cursor() as new_cr:
                        env = odoo.api.Environment(new_cr, uid, {})
                        wizard = env["sec.attachment.export.wizard"].browse(
                            wizard_id
                        )
                        if not wizard.exists():
                            _logger.warning(
                                "Export wizard %s no longer exists, aborting.",
                                wizard_id,
                            )
                            return

                        orders = wizard._get_orders()
                        total = len(orders)
                        wizard.write(
                            {
                                "progress_message": _(
                                    "Procesando %d órdenes..."
                                ) % total,
                            }
                        )
                        new_cr.commit()

                        zip_buffer = wizard._build_zip_buffer_with_progress(
                            orders, new_cr
                        )
                        filename = wizard._build_filename()

                        wizard.write(
                            {
                                "file_data": base64.b64encode(
                                    zip_buffer.getvalue()
                                ),
                                "filename": filename,
                                "state": "done",
                                "progress_message": _(
                                    "Exportación completada: %d órdenes."
                                ) % total,
                            }
                        )
                        new_cr.commit()
                except Exception as e:
                    _logger.exception(
                        "Background export failed for wizard %s", wizard_id
                    )
                    try:
                        with odoo.registry(db_name).cursor() as err_cr:
                            env = odoo.api.Environment(err_cr, uid, {})
                            wizard = env[
                                "sec.attachment.export.wizard"
                            ].browse(wizard_id)
                            if wizard.exists():
                                wizard.write(
                                    {
                                        "state": "error",
                                        "error_message": str(e),
                                        "progress_message": False,
                                    }
                                )
                            err_cr.commit()
                    except Exception:
                        _logger.exception(
                            "Failed to write error state for wizard %s",
                            wizard_id,
                        )

        thread = threading.Thread(
            target=_generate,
            name="export-wizard-%d" % wizard_id,
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Order query helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # ZIP builders
    # ------------------------------------------------------------------

    def _build_zip_buffer(self, orders):
        """Synchronous ZIP builder (used for attachments-only export)."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zip_file:
            for order in orders:
                if self.export_attachments:
                    self._add_attachments_to_zip(zip_file, order)
                if self.export_purchase_orders:
                    self._add_order_pdf_to_zip(zip_file, order)
        buffer.seek(0)
        return buffer

    def _build_zip_buffer_with_progress(self, orders, cr):
        """ZIP builder with periodic progress commits (background thread)."""
        buffer = io.BytesIO()
        total = len(orders)
        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zip_file:
            for idx, order in enumerate(orders, 1):
                if self.export_attachments:
                    self._add_attachments_to_zip(zip_file, order)
                if self.export_purchase_orders:
                    self._add_order_pdf_to_zip(zip_file, order)

                if idx % 10 == 0 or idx == total:
                    self.write(
                        {
                            "progress_message": _(
                                "Procesando orden %d de %d..."
                            ) % (idx, total),
                        }
                    )
                    cr.commit()
        buffer.seek(0)
        return buffer

    def _add_attachments_to_zip(self, zip_file, order):
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
            zip_file.writestr(arcname, base64.b64decode(attachment.datas))

    def _add_order_pdf_to_zip(self, zip_file, order):
        pdf_content = self._render_order_pdf(order)
        if pdf_content:
            pdf_filename = "%s.pdf" % order.name.replace("/", "-")
            arcname = self._get_attachment_path(order, pdf_filename)
            zip_file.writestr(arcname, pdf_content)

    def _render_order_pdf(self, order):
        report = self.env.ref("purchase.action_report_purchase_order")
        pdf_content, _content_type = report._render_qweb_pdf([order.id])
        return pdf_content

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

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
