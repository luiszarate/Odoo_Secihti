# -*- coding: utf-8 -*-
import base64
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:  # pragma: no cover
    xlsxwriter = None


class SecAssetsReportWizard(models.TransientModel):
    _name = "sec.assets.report.wizard"
    _description = "Reporte de Bienes"

    stage_id = fields.Many2one("sec.stage", string="Etapa", required=True)
    rubro_ids = fields.Many2many("sec.rubro", string="Rubros", required=True)
    min_amount = fields.Float(
        string="Monto mínimo",
        help="Solo incluir órdenes de compra cuyo Total MXN manual sea mayor a este valor. Dejar en 0 para incluir todas.",
        default=0.0,
    )
    file_data = fields.Binary(string="Archivo", readonly=True)
    filename = fields.Char(string="Nombre de archivo", readonly=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_control_interno_installed(self):
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search(
                [("name", "=", "om_control_interno"), ("state", "=", "installed")],
                limit=1,
            )
        )
        return bool(module)

    def _get_control_interno_lines(self, purchase_order):
        if not self._is_control_interno_installed():
            return []
        try:
            CostosGastosLine = self.env["costos.gastos.line"]
            return CostosGastosLine.search(
                [("orden_compra_id", "=", purchase_order.id)]
            )
        except Exception:
            return []

    def _format_date(self, date_value):
        if not date_value:
            return ""
        if hasattr(date_value, "date"):
            date_value = date_value.date()
        return date_value.strftime("%d/%m/%Y")

    def _format_date_for_sku(self, date_value):
        if not date_value:
            return "000000"
        if hasattr(date_value, "date"):
            date_value = date_value.date()
        return date_value.strftime("%y%m%d")

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _get_purchase_orders(self):
        """Get purchase orders for the selected stage and rubros."""
        self.ensure_one()
        domain = [
            ("sec_stage_id", "=", self.stage_id.id),
            ("sec_rubro_id", "in", self.rubro_ids.ids),
            ("state", "in", ["purchase", "done"]),
        ]
        if self.min_amount:
            domain.append(("sec_total_mxn_manual", ">=", self.min_amount))
        return self.env["purchase.order"].search(domain, order="date_order asc")

    def _build_rows(self, orders):
        """Build report rows: one row per PO line with amount > 0."""
        rows = []
        consecutivo = 1
        control_installed = self._is_control_interno_installed()

        for order in orders:
            rubro_name = order.sec_rubro_id.name if order.sec_rubro_id else ""
            purchase_date = order.date_order
            currency_name = order.currency_id.name if order.currency_id else ""

            # Get control interno data for this order (if available)
            ci_lines = []
            if control_installed:
                ci_lines = self._get_control_interno_lines(order)

            ci_line = ci_lines[0] if ci_lines else None

            proveedor = ""
            folio_fiscal = ""
            monto_factura = ""
            fecha_pago = ""

            if ci_line:
                proveedor = ci_line.proveedor_text or ""
                folio_fiscal = ci_line.folio_fiscal or ""
                monto_total_ci = (
                    (ci_line.importe or 0.0)
                    + (ci_line.iva or 0.0)
                    + (ci_line.otras_retenciones or 0.0)
                )
                monto_factura = monto_total_ci
                fecha_pago = self._format_date(ci_line.fecha_pago)

            if not proveedor:
                proveedor = order.partner_id.name if order.partner_id else ""

            # Iterate over PO lines (order_line) with price_subtotal > 0
            for po_line in order.order_line:
                if po_line.price_subtotal <= 0:
                    continue

                sku = "IMGO-%s-%04d" % (
                    self._format_date_for_sku(purchase_date),
                    consecutivo,
                )

                row = {
                    "consecutivo": consecutivo,
                    "rubro": rubro_name,
                    "articulo": po_line.name or (
                        po_line.product_id.display_name
                        if po_line.product_id
                        else ""
                    ),
                    "cantidad": po_line.product_qty or 0,
                    "proveedor": proveedor,
                    "fecha_contrato": "N/A",
                    "fecha_entrega_contrato": "N/A",
                    "folio_fiscal": folio_fiscal,
                    "precio_unitario": po_line.price_unit or 0.0,
                    "monto_factura": monto_factura,
                    "moneda": currency_name,
                    "fecha_pago": fecha_pago,
                    "poliza": "",
                    "fecha_recepcion": fecha_pago,
                    "modificatorios": "",
                    "no_serie": "",
                    "no_inventario": sku,
                    "marca": "",
                    "modelo": "",
                    "evidencia_fotografica": "",
                }
                rows.append(row)
                consecutivo += 1

        return rows

    # ------------------------------------------------------------------
    # Excel generation
    # ------------------------------------------------------------------

    def _get_headers(self):
        return [
            "Consecutivo",
            "Rubro",
            "Artículo",
            "Cantidad",
            "Proveedor",
            "Fecha de Contrato",
            "Fecha de entrega según contrato",
            "Folio Fiscal de la Factura",
            "Precio Unitario",
            "Monto total de la factura",
            "Moneda",
            "Fecha de Pago",
            "Póliza",
            "Fecha de Recepción",
            "Modificatorios o prórrogas para la entrega",
            "No. de Serie",
            "No. de Inventario",
            "Marca",
            "Modelo",
            "Evidencia Fotográfica",
        ]

    def _build_workbook(self, rows):
        buf = io.BytesIO()
        workbook = xlsxwriter.Workbook(buf, {"in_memory": True})
        sheet = workbook.add_worksheet("Reporte de Bienes")

        # Formats
        header_fmt = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#004080",
                "font_color": "#FFFFFF",
                "border": 1,
                "text_wrap": True,
                "valign": "vcenter",
                "align": "center",
            }
        )
        text_fmt = workbook.add_format({"border": 1, "text_wrap": True, "valign": "vcenter"})
        number_fmt = workbook.add_format(
            {"border": 1, "num_format": "#,##0", "valign": "vcenter"}
        )
        money_fmt = workbook.add_format(
            {"border": 1, "num_format": "$#,##0.00", "valign": "vcenter"}
        )

        headers = self._get_headers()

        # Column widths
        col_widths = [12, 20, 40, 12, 25, 18, 18, 22, 16, 22, 10, 16, 12, 18, 20, 14, 22, 14, 14, 22]
        for i, w in enumerate(col_widths):
            sheet.set_column(i, i, w)

        # Write headers
        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_fmt)

        # Write data rows
        for row_idx, row_data in enumerate(rows, start=1):
            col = 0
            sheet.write_number(row_idx, col, row_data["consecutivo"], number_fmt); col += 1
            sheet.write(row_idx, col, row_data["rubro"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["articulo"], text_fmt); col += 1
            sheet.write_number(row_idx, col, row_data["cantidad"], number_fmt); col += 1
            sheet.write(row_idx, col, row_data["proveedor"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["fecha_contrato"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["fecha_entrega_contrato"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["folio_fiscal"], text_fmt); col += 1
            sheet.write_number(row_idx, col, row_data["precio_unitario"], money_fmt); col += 1
            if row_data["monto_factura"] != "":
                sheet.write_number(row_idx, col, row_data["monto_factura"], money_fmt)
            else:
                sheet.write(row_idx, col, "", text_fmt)
            col += 1
            sheet.write(row_idx, col, row_data["moneda"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["fecha_pago"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["poliza"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["fecha_recepcion"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["modificatorios"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["no_serie"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["no_inventario"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["marca"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["modelo"], text_fmt); col += 1
            sheet.write(row_idx, col, row_data["evidencia_fotografica"], text_fmt)

        if rows:
            sheet.autofilter(0, 0, len(rows), len(headers) - 1)
        sheet.freeze_panes(1, 0)

        workbook.close()
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------
    # Main action
    # ------------------------------------------------------------------

    def action_export(self):
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_("No está disponible la librería xlsxwriter."))

        orders = self._get_purchase_orders()
        if not orders:
            raise UserError(
                _(
                    "No se encontraron órdenes de compra para la etapa y rubros seleccionados."
                )
            )

        rows = self._build_rows(orders)
        if not rows:
            raise UserError(
                _(
                    "No se encontraron líneas de orden de compra que cumplan con los filtros."
                )
            )

        workbook_data = self._build_workbook(rows)

        stage_name = (
            self.stage_id.code or self.stage_id.name or "Etapa"
        ).replace(" ", "_").replace("/", "-")
        filename = "Reporte_Bienes_%s.xlsx" % stage_name

        self.write(
            {
                "file_data": base64.b64encode(workbook_data.getvalue()),
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
