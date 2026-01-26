# -*- coding: utf-8 -*-
import base64
import csv
import io

from odoo import _, fields, models
from odoo.exceptions import UserError


class SecPurchaseOrderExportWizard(models.TransientModel):
    _name = "sec.purchase.order.export.wizard"
    _description = "Exportar ordenes de compra a CSV"

    stage_id = fields.Many2one("sec.stage", string="Etapa", required=True)
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
    file_data = fields.Binary(string="Archivo", readonly=True)
    filename = fields.Char(string="Nombre de archivo", readonly=True)

    def _is_control_interno_installed(self):
        """Check if om_control_interno module is installed."""
        module = self.env["ir.module.module"].sudo().search(
            [("name", "=", "om_control_interno"), ("state", "=", "installed")],
            limit=1,
        )
        return bool(module)

    def _get_control_interno_lines(self, purchase_order):
        """Get control interno lines related to a purchase order."""
        if not self._is_control_interno_installed():
            return []
        try:
            CostosGastosLine = self.env["costos.gastos.line"]
            lines = CostosGastosLine.search([
                ("orden_compra_id", "=", purchase_order.id)
            ])
            return lines
        except Exception:
            return []

    def _get_state_list(self):
        if self.state_filter == "all":
            return False
        if self.state_filter == "purchase,done":
            return ["purchase", "done"]
        return [self.state_filter]

    def _get_orders(self):
        """Get purchase orders for the selected stage."""
        self.ensure_one()
        stage = self.stage_id
        states = self._get_state_list()
        domain = [
            ("sec_stage_id", "=", stage.id),
        ]
        if states:
            domain.append(("state", "in", states))
        orders = self.env["purchase.order"].search(domain, order="date_order asc")
        return orders

    def _get_tipo_gasto_label(self, rubro):
        """Get the tipo_gasto label from rubro."""
        if not rubro or not rubro.tipo_gasto:
            return ""
        selection_dict = dict(rubro._fields['tipo_gasto'].selection)
        return selection_dict.get(rubro.tipo_gasto, "")

    def _format_date(self, date_value):
        """Format date for CSV output."""
        if not date_value:
            return ""
        if hasattr(date_value, 'date'):
            date_value = date_value.date()
        return fields.Date.to_string(date_value)

    def _build_csv_rows(self, orders):
        """Build CSV rows from purchase orders."""
        rows = []
        row_number = 1
        control_interno_installed = self._is_control_interno_installed()

        for order in orders:
            tipo_aportacion = "PP F003 70% / Concurrente 30%"
            tipo_gasto = self._get_tipo_gasto_label(order.sec_rubro_id)
            no_rubro = ""
            nombre_rubro = order.sec_rubro_id.name if order.sec_rubro_id else ""
            monto_total = order.sec_effective_mxn or order.amount_total or 0.0
            beneficiario = order.partner_id.name if order.partner_id else ""
            no_poliza = ""
            observaciones = ""

            if control_interno_installed:
                control_lines = self._get_control_interno_lines(order)
                if control_lines:
                    for line in control_lines:
                        no_factura = line.folio_fiscal or line.no_comprobante or ""
                        fecha_factura = self._format_date(line.fecha_comprobante)
                        proveedor = line.proveedor_text or ""
                        concepto = line.concepto or ""
                        subtotal = line.importe or 0.0
                        iva = line.iva or 0.0
                        impuestos_retenidos = line.otras_retenciones or 0.0
                        fecha_pago = self._format_date(line.fecha_pago)

                        rows.append({
                            'no': row_number,
                            'tipo_aportacion': tipo_aportacion,
                            'tipo_gasto': tipo_gasto,
                            'no_rubro': no_rubro,
                            'nombre_rubro': nombre_rubro,
                            'no_factura': no_factura,
                            'fecha_factura': fecha_factura,
                            'proveedor': proveedor,
                            'concepto': concepto,
                            'subtotal': subtotal,
                            'iva': iva,
                            'impuestos_retenidos': impuestos_retenidos,
                            'monto_total': monto_total,
                            'fecha_pago': fecha_pago,
                            'no_poliza': no_poliza,
                            'beneficiario': beneficiario,
                            'monto_pagado': monto_total,
                            'observaciones': observaciones,
                        })
                        row_number += 1
                else:
                    rows.append(self._build_row_without_control_interno(
                        row_number, order, tipo_aportacion, tipo_gasto,
                        no_rubro, nombre_rubro, monto_total, beneficiario,
                        no_poliza, observaciones
                    ))
                    row_number += 1
            else:
                rows.append(self._build_row_without_control_interno(
                    row_number, order, tipo_aportacion, tipo_gasto,
                    no_rubro, nombre_rubro, monto_total, beneficiario,
                    no_poliza, observaciones
                ))
                row_number += 1

        return rows

    def _build_row_without_control_interno(self, row_number, order, tipo_aportacion,
                                            tipo_gasto, no_rubro, nombre_rubro,
                                            monto_total, beneficiario, no_poliza,
                                            observaciones):
        """Build a row when control interno is not available or no lines found."""
        return {
            'no': row_number,
            'tipo_aportacion': tipo_aportacion,
            'tipo_gasto': tipo_gasto,
            'no_rubro': no_rubro,
            'nombre_rubro': nombre_rubro,
            'no_factura': order.name or "",
            'fecha_factura': self._format_date(order.date_order),
            'proveedor': order.partner_id.name if order.partner_id else "",
            'concepto': "",
            'subtotal': order.amount_untaxed or 0.0,
            'iva': order.amount_tax or 0.0,
            'impuestos_retenidos': 0.0,
            'monto_total': monto_total,
            'fecha_pago': "",
            'no_poliza': no_poliza,
            'beneficiario': beneficiario,
            'monto_pagado': monto_total,
            'observaciones': observaciones,
        }

    def _build_csv(self, rows):
        """Build CSV file from rows."""
        buffer = io.StringIO()
        fieldnames = [
            'no',
            'tipo_aportacion',
            'tipo_gasto',
            'no_rubro',
            'nombre_rubro',
            'no_factura',
            'fecha_factura',
            'proveedor',
            'concepto',
            'subtotal',
            'iva',
            'impuestos_retenidos',
            'monto_total',
            'fecha_pago',
            'no_poliza',
            'beneficiario',
            'monto_pagado',
            'observaciones',
        ]
        headers = {
            'no': 'N°',
            'tipo_aportacion': 'Tipo de Aportación (Fondo/Concurrente)',
            'tipo_gasto': 'Tipo de Gasto (Corriente/Inversión)',
            'no_rubro': 'N° Rubro',
            'nombre_rubro': 'Nombre del Rubro',
            'no_factura': 'No. Factura/ Folio',
            'fecha_factura': 'Fecha de la Factura',
            'proveedor': 'Proveedor',
            'concepto': 'Concepto',
            'subtotal': 'Subtotal',
            'iva': 'I.V.A.',
            'impuestos_retenidos': 'Impuestos Retenidos',
            'monto_total': 'Monto Total',
            'fecha_pago': 'Fecha de Pago',
            'no_poliza': 'No. de Póliza',
            'beneficiario': 'Beneficiario',
            'monto_pagado': 'Monto Pagado',
            'observaciones': 'Observaciones',
        }

        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction='ignore')
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)

        buffer.seek(0)
        return buffer.getvalue()

    def action_export(self):
        self.ensure_one()
        orders = self._get_orders()
        if not orders:
            raise UserError(_("No se encontraron órdenes de compra para la etapa seleccionada."))

        rows = self._build_csv_rows(orders)
        csv_content = self._build_csv(rows)

        stage_name = self.stage_id.code or self.stage_id.name or "Etapa"
        stage_name = stage_name.replace(" ", "_").replace("/", "-")
        filename = "Ordenes_Compra_%s.csv" % stage_name

        self.write({
            "file_data": base64.b64encode(csv_content.encode('utf-8-sig')),
            "filename": filename,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
