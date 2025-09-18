# -*- coding: utf-8 -*-
import base64
import csv
import io
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SecImportActivityWizard(models.TransientModel):
    _name = "sec.import.activity.wizard"
    _description = "Importar actividades SECIHTI"

    project_id = fields.Many2one("sec.project", string="Proyecto", required=True)
    data_file = fields.Binary(string="Archivo CSV", required=True)
    filename = fields.Char(string="Nombre del archivo")

    def action_import(self):
        self.ensure_one()
        if not self.data_file:
            raise UserError(_("Debe seleccionar un archivo CSV."))
        try:
            decoded = base64.b64decode(self.data_file)
        except Exception as exc:  # pylint: disable=broad-except
            raise UserError(_("El archivo no pudo decodificarse: %s") % exc) from exc
        try:
            content = decoded.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = decoded.decode("latin-1")
        sniffer = csv.Sniffer()
        sample = content[:1024]
        try:
            dialect = sniffer.sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.get_dialect("excel")
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        required_headers = {
            "Etapa",
            "Actividad",
            "Concepto",
            "Tipo de Gasto",
            "Total",
            "Monto Programa",
            "Monto Concurrente",
            "Justificación Específica",
            "Justificacion General",
        }
        missing = required_headers.difference(reader.fieldnames or [])
        if missing:
            raise UserError(_("El archivo CSV no contiene las columnas requeridas: %s") % ", ".join(sorted(missing)))

        project = self.project_id
        pct_programa = project.pct_programa / 100.0
        pct_concurrente = project.pct_concurrente / 100.0

        stage_payload = {}
        for row in reader:
            stage_name = (row.get("Etapa") or "").strip()
            activity_name = (row.get("Actividad") or "").strip()
            rubro_name = (row.get("Concepto") or "").strip()
            tipo_gasto_label = (row.get("Tipo de Gasto") or "").strip().lower()
            total_str = (row.get("Total") or "0").strip()
            programa_str = (row.get("Monto Programa") or "0").strip()
            concurrente_str = (row.get("Monto Concurrente") or "0").strip()
            justific_especifica = (row.get("Justificación Específica") or "").strip()
            justific_general = (row.get("Justificacion General") or "").strip()

            if not stage_name or not activity_name or not rubro_name:
                _logger.warning("Fila omitida por falta de datos mínimos: %s", row)
                continue

            total = self._parse_float(total_str)
            programa = self._parse_float(programa_str)
            concurrente = self._parse_float(concurrente_str)

            if not total:
                continue

            if float_compare(total, programa + concurrente, precision_digits=2) != 0:
                programa = total * pct_programa
                concurrente = total * pct_concurrente

            rubro = self.env["sec.rubro"].search([("name", "=ilike", rubro_name)], limit=1)
            if not rubro:
                raise UserError(_("El rubro '%s' no existe en el catálogo." % rubro_name))

            desired_tipo = "inversion" if "invers" in tipo_gasto_label else "corriente"
            if desired_tipo and rubro.tipo_gasto != desired_tipo:
                _logger.warning(
                    "Ajustando tipo de gasto del rubro %s de %s a %s durante la importación", rubro.name, rubro.tipo_gasto, desired_tipo
                )
                rubro.tipo_gasto = desired_tipo

            payload_stage = stage_payload.setdefault(stage_name, {
                "total": 0.0,
                "activities": {},
            })
            payload_stage["total"] += total
            payload_activity = payload_stage["activities"].setdefault(activity_name, {
                "justificacion": justific_general,
                "lines": [],
            })
            if justific_general:
                payload_activity["justificacion"] = justific_general
            payload_activity["lines"].append({
                "rubro": rubro,
                "total": total,
                "programa": programa,
                "concurrente": concurrente,
                "justificacion": justific_especifica,
            })

        created_lines = self.env["sec.activity.budget.line"]
        for stage_name, data in stage_payload.items():
            stage = self.env["sec.stage"].search([
                ("project_id", "=", project.id),
                ("name", "=", stage_name),
            ], limit=1)
            if not stage:
                total = data["total"]
                stage_vals = {
                    "name": stage_name,
                    "code": stage_name,
                    "project_id": project.id,
                    "amount_programa": total * pct_programa,
                    "amount_concurrente": total * pct_concurrente,
                }
                stage = self.env["sec.stage"].create(stage_vals)
            else:
                total = data["total"]
                stage_vals = {
                    "amount_programa": stage.amount_programa + total * pct_programa,
                    "amount_concurrente": stage.amount_concurrente + total * pct_concurrente,
                }
                stage.write(stage_vals)

            for activity_name, activity_data in data["activities"].items():
                activity = self.env["sec.activity"].search([
                    ("stage_id", "=", stage.id),
                    ("name", "=", activity_name),
                ], limit=1)
                if not activity:
                    activity = self.env["sec.activity"].create({
                        "name": activity_name,
                        "code": activity_name,
                        "stage_id": stage.id,
                        "justif_general": activity_data.get("justificacion"),
                    })
                else:
                    if activity_data.get("justificacion"):
                        activity.write({"justif_general": activity_data["justificacion"]})

                for line_vals in activity_data["lines"]:
                    line = self.env["sec.activity.budget.line"].create({
                        "activity_id": activity.id,
                        "rubro_id": line_vals["rubro"].id,
                        "name": line_vals["rubro"].name,
                        "amount_programa": line_vals["programa"],
                        "amount_concurrente": line_vals["concurrente"],
                        "justification": line_vals["justificacion"],
                    })
                    created_lines |= line

        project.message_post(
            body=_("Importación completada. Se crearon %s líneas de presupuesto." % len(created_lines))
        )
        return {"type": "ir.actions.act_window_close"}

    @staticmethod
    def _parse_float(value):
        value = (value or "0").strip()
        if not value:
            return 0.0
        value = value.replace(",", "")
        try:
            return float(value)
        except ValueError:
            return 0.0


try:
    from odoo.tools.float_utils import float_compare
except ImportError:  # pragma: no cover
    from odoo.tools import float_compare
