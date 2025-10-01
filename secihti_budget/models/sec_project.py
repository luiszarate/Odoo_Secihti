# -*- coding: utf-8 -*-
import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class SecRubro(models.Model):
    _name = "sec.rubro"
    _description = "SECIHTI Rubro"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    tipo_gasto = fields.Selection([
        ("inversion", "Inversión"),
        ("corriente", "Corriente"),
    ], required=True, tracking=True, default="inversion")
    active = fields.Boolean(default=True)
    activity_line_ids = fields.One2many("sec.activity.budget.line", "rubro_id")
    

    def unlink(self):
        for rubro in self:
            if rubro.activity_line_ids:
                raise ValidationError(
                    _("No se puede eliminar un rubro que está en uso. Puede archivarlo en su lugar."))
        return super(SecRubro, self).unlink()

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        args = list(args or [])
        activity_id = (
            self.env.context.get("sec_activity_id")
            or self.env.context.get("default_sec_activity_id")
        )

        if not activity_id:
            return super().name_search(name, args, operator=operator, limit=limit)

        # Rubros vinculados a la actividad a través de líneas presupuestales.
        BudgetLine = self.env["sec.activity.budget.line"]
        rubro_ids = BudgetLine.search(
            [("activity_id", "=", activity_id)]
        ).mapped("rubro_id").ids

        if not rubro_ids:
            return super().name_search(name, args, operator=operator, limit=limit)

        # 1) Prioriza los rubros relacionados a la actividad.
        prioritized = super().name_search(
            name,
            args + [("id", "in", rubro_ids)],
            operator=operator,
            limit=limit or False,
        )

        # Si el límite es estricto y ya está cubierto con los rubros priorizados, retorna.
        if limit and len(prioritized) >= limit:
            return prioritized[:limit]

        taken_ids = {rubro_id for rubro_id, _dummy in prioritized}

        # 2) Agrega el resto de rubros disponibles respetando el límite.
        remaining_limit = False
        if limit:
            remaining_limit = max(limit - len(prioritized), 0)
            if remaining_limit == 0:
                return prioritized

        other_args = list(args)
        if taken_ids:
            other_args.append(("id", "not in", list(taken_ids)))

        others = super().name_search(
            name,
            other_args,
            operator=operator,
            limit=remaining_limit,
        )

        # Evita duplicados y conserva el orden: primero asociados, luego el resto.
        other_filtered = [res for res in others if res[0] not in taken_ids]
        return prioritized + other_filtered


class SecProject(models.Model):
    _name = "sec.project"
    _description = "Proyecto SECIHTI"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    description = fields.Text()

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.ref("base.MXN", raise_if_not_found=False),
        required=True,
        readonly=True,
    )

    amount_total = fields.Monetary(tracking=True, currency_field="currency_id")
    pct_programa = fields.Float(string="% Programa", tracking=True, default=50.0)
    pct_concurrente = fields.Float(string="% Concurrente", tracking=True, default=50.0)

    stage_ids = fields.One2many("sec.stage", "project_id", string="Etapas")
    sec_activity_ids = fields.One2many(
        "sec.activity", "project_id", string="Actividades"
    )

    amount_stages_total = fields.Monetary(
        compute="_compute_stage_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_executed_total = fields.Monetary(
        compute="_compute_execution_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_remaining_total = fields.Monetary(
        compute="_compute_execution_amounts",
        store=True,
        currency_field="currency_id",
    )
    stage_count = fields.Integer(compute="_compute_stage_count")

    inconsistency_message = fields.Char(compute="_compute_inconsistency_message")

    has_inconsistency = fields.Boolean(
        string="¿Con inconsistencia?",
        compute="_compute_has_inconsistency",
        store=True,
    )

    purchase_order_ids = fields.One2many(
        "purchase.order", "sec_project_id", string="Órdenes de compra"
    )
    purchase_order_count = fields.Integer(compute="_compute_purchase_orders")
    purchase_pending_count = fields.Integer(compute="_compute_purchase_orders")

    @api.constrains("pct_programa", "pct_concurrente")
    def _check_percentages(self):
        for record in self:
            total = (record.pct_programa or 0.0) + (record.pct_concurrente or 0.0)
            if not float_is_zero(total - 100.0, precision_digits=2):
                raise ValidationError(_("La suma de % Programa y % Concurrente debe ser 100."))

    def _compute_stage_count(self):
        for project in self:
            project.stage_count = len(project.stage_ids)

    @api.depends("stage_ids.amount_total")
    def _compute_stage_amounts(self):
        for project in self:
            project.amount_stages_total = sum(project.stage_ids.mapped("amount_total"))

    @api.depends(
        "stage_ids.exec_total",
        "purchase_order_ids.state",
        "purchase_order_ids.amount_total",
        "purchase_order_ids.currency_id",
        "purchase_order_ids.sec_total_mxn_manual",
        "purchase_order_ids.sec_activity_id",
        "purchase_order_ids.sec_stage_id",
        "purchase_order_ids.sec_rubro_id",
    )
    def _compute_execution_amounts(self):
        execution = self._collect_execution_data()
        for project in self:
            values = execution.get("project", {}).get(project.id, {})
            project.amount_executed_total = values.get("total", 0.0)
            project.amount_remaining_total = project.amount_total - project.amount_executed_total

    @api.depends(
        "purchase_order_ids.state",
        "purchase_order_ids.sec_project_id",
        "purchase_order_ids.sec_mxn_pending",  # importante para refrescar al vuelo
    )
    def _compute_purchase_orders(self):
        PurchaseOrder = self.env["purchase.order"]
        grouped_total = PurchaseOrder.read_group(
            [
                ("sec_project_id", "in", self.ids),
                ("state", "in", ["purchase", "done"]),
            ],
            ["sec_project_id"],
            ["sec_project_id"],
        )
        total_counts = {row["sec_project_id"][0]: row["sec_project_id_count"]
                        for row in grouped_total if row.get("sec_project_id")}

        # 2) Solo pendientes MXN
        grouped_pending = PurchaseOrder.read_group(
            [
                ("sec_project_id", "in", self.ids),
                ("state", "in", ["purchase", "done"]),
                ("sec_mxn_pending", "=", True),
            ],
            ["sec_project_id"],
            ["sec_project_id"],
        )
        pending_counts = {row["sec_project_id"][0]: row["sec_project_id_count"]
                          for row in grouped_pending if row.get("sec_project_id")}

        for project in self:
            project.purchase_order_count = int(total_counts.get(project.id, 0))
            project.purchase_pending_count = int(pending_counts.get(project.id, 0))

    def _compute_inconsistency_message(self):
        for project in self:
            if project.amount_stages_total > project.amount_total and project.amount_total:
                project.inconsistency_message = _(
                    "La suma del presupuesto de las etapas excede el presupuesto del proyecto."
                )
            else:
                project.inconsistency_message = False
    
    def _compute_has_inconsistency(self):
        for project in self:
            project.has_inconsistency = bool(project.inconsistency_message)

    def _compute_has_inconsistency(self):
        for project in self:
            project.has_inconsistency = bool(project.inconsistency_message)

    def action_view_purchase_orders(self):
        self.ensure_one()
        action_ref = self.env.ref("purchase.purchase_rfq", raise_if_not_found=False)
        if not action_ref:
            action_ref = self.env.ref("purchase.purchase_form_action")
        action = action_ref.read()[0]
        action["domain"] = [("sec_project_id", "=", self.id), ("state", "in", ["purchase", "done"])]
        action["context"] = {"default_sec_project_id": self.id}
        return action

    def action_view_pending_purchase_orders(self):
        self.ensure_one()
        action = self.action_view_purchase_orders()
        domain = action.get("domain", [])
        domain.append(("sec_mxn_pending", "=", True))
        action["domain"] = domain
        return action

    @api.model
    def _collect_execution_data(self, stage_ids=None, activity_ids=None, line_ids=None):
        project_ids = self.ids
        domain = [
            ("state", "in", ["purchase", "done"]),  # amplía si quieres contar draft/sent
            ("sec_project_id", "in", project_ids),
        ]
        PurchaseOrder = self.env["purchase.order"]
        orders = PurchaseOrder.search(domain)
        
        project_data = defaultdict(lambda: {"programa": 0.0, "concurrente": 0.0, "total": 0.0})
        stage_data = defaultdict(lambda: {"programa": 0.0, "concurrente": 0.0, "total": 0.0})
        activity_data = defaultdict(lambda: {"programa": 0.0, "concurrente": 0.0, "total": 0.0})
        line_data = defaultdict(lambda: {"programa": 0.0, "concurrente": 0.0, "total": 0.0})

        for order in orders:
            #amount_mxn = order.sec_effective_mxn or 0.0
            amount_mxn = order.sec_total_mxn_manual or 0.0
            if amount_mxn <= 0.0:
                continue

            project = order.sec_project_id
            if not project:
                continue

            programa = amount_mxn * (project.pct_programa / 100.0)
            concurrente = amount_mxn * (project.pct_concurrente / 100.0)
            total = programa + concurrente

            project_data[project.id]["programa"] += programa
            project_data[project.id]["concurrente"] += concurrente
            project_data[project.id]["total"] += total

            activity = order.sec_activity_id
            if activity:
                activity_data[activity.id]["programa"] += programa
                activity_data[activity.id]["concurrente"] += concurrente
                activity_data[activity.id]["total"] += total

            stage = order.sec_stage_id or (activity.stage_id if activity else False)
            if stage:
                stage_data[stage.id]["programa"] += programa
                stage_data[stage.id]["concurrente"] += concurrente
                stage_data[stage.id]["total"] += total

            rubro = order.sec_rubro_id
            if rubro and activity:
                key = (activity.id, rubro.id)
                line_data[key]["programa"] += programa
                line_data[key]["concurrente"] += concurrente
                line_data[key]["total"] += total

        return {"project": project_data, "stage": stage_data, "activity": activity_data, "line": line_data}


class SecStage(models.Model):
    _name = "sec.stage"
    _description = "Etapa SECIHTI"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    project_id = fields.Many2one("sec.project", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="project_id.currency_id", store=True, readonly=True)

    amount_programa = fields.Monetary(required=True, currency_field="currency_id")
    amount_concurrente = fields.Monetary(required=True, currency_field="currency_id")
    amount_total = fields.Monetary(
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )

    exec_programa = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    exec_concurrente = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    exec_total = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    rem_programa = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    rem_concurrente = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    rem_total = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )

    sec_activity_ids = fields.One2many("sec.activity", "stage_id")
    activity_count = fields.Integer(compute="_compute_activity_count")
    inconsistency_message = fields.Char(compute="_compute_inconsistency_message")
    has_inconsistency = fields.Boolean(
        string="¿Con inconsistencia?",
        compute="_compute_has_inconsistency",
        store=True,
    )

    @api.depends("amount_programa", "amount_concurrente")
    def _compute_totals(self):
        for stage in self:
            stage.amount_total = (stage.amount_programa or 0.0) + (stage.amount_concurrente or 0.0)

    @api.depends(
        "sec_activity_ids.exec_total",
        "project_id.pct_programa",
        "project_id.pct_concurrente",
        "project_id.stage_ids",
        "project_id.purchase_order_ids.state",
        "project_id.purchase_order_ids.currency_id",
        "project_id.purchase_order_ids.amount_total",
        "project_id.purchase_order_ids.sec_total_mxn_manual",
        "project_id.purchase_order_ids.sec_activity_id",
        "project_id.purchase_order_ids.sec_stage_id",
        "project_id.purchase_order_ids.sec_rubro_id",
    )
    def _compute_execution(self):
        projects = self.mapped("project_id")
        execution = projects._collect_execution_data()
        stage_data = execution.get("stage", {})
        for stage in self:
            values = stage_data.get(stage.id, {})
            stage.exec_programa = values.get("programa", 0.0)
            stage.exec_concurrente = values.get("concurrente", 0.0)
            stage.exec_total = values.get("total", 0.0)
            stage.rem_programa = stage.amount_programa - stage.exec_programa
            stage.rem_concurrente = stage.amount_concurrente - stage.exec_concurrente
            stage.rem_total = stage.amount_total - stage.exec_total

    def _compute_activity_count(self):
        for stage in self:
            stage.activity_count = len(stage.sec_activity_ids)

    def _compute_inconsistency_message(self):
        for stage in self:
            activities_budget = sum(stage.sec_activity_ids.mapped("amount_total"))
            if stage.amount_total and activities_budget > stage.amount_total:
                stage.inconsistency_message = _(
                    "La suma del presupuesto de actividades excede el presupuesto de la etapa."
                )
            else:
                stage.inconsistency_message = False

    @api.constrains("project_id", "amount_programa", "amount_concurrente")
    def _check_project_split(self):
        for stage in self:
            project = stage.project_id
            if not project:
                continue
            total = stage.amount_total or 0.0
            if not total:
                continue
            prog_pct = (stage.amount_programa / total) * 100 if total else 0.0
            conc_pct = (stage.amount_concurrente / total) * 100 if total else 0.0
            if not float_is_zero(prog_pct - project.pct_programa, precision_digits=2):
                raise ValidationError(
                    _("El presupuesto de la etapa debe respetar el % Programa del proyecto (%s%%).",
                      project.pct_programa)
                )
            if not float_is_zero(conc_pct - project.pct_concurrente, precision_digits=2):
                raise ValidationError(
                    _("El presupuesto de la etapa debe respetar el % Concurrente del proyecto (%s%%).",
                      project.pct_concurrente)
                )
            if total <= 0:
                raise ValidationError(_("La etapa debe tener un presupuesto mayor que cero."))
    
    def _compute_has_inconsistency(self):
        for stage in self:
            stage.has_inconsistency = bool(stage.inconsistency_message)


class SecActivity(models.Model):
    _name = "sec.activity"
    _description = "Actividad SECIHTI"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    stage_id = fields.Many2one("sec.stage", required=True, ondelete="cascade")
    project_id = fields.Many2one(related="stage_id.project_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="project_id.currency_id", store=True, readonly=True)
    justif_general = fields.Text(string="Justificación general")

    budget_line_ids = fields.One2many("sec.activity.budget.line", "activity_id")

    amount_programa = fields.Monetary(
        compute="_compute_budget_totals",
        store=True,
        currency_field="currency_id",
    )
    amount_concurrente = fields.Monetary(
        compute="_compute_budget_totals",
        store=True,
        currency_field="currency_id",
    )
    amount_total = fields.Monetary(
        compute="_compute_budget_totals",
        store=True,
        currency_field="currency_id",
    )

    exec_programa = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    exec_concurrente = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    exec_total = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )

    traffic_light = fields.Selection(
        [
            ("green", "Dentro del presupuesto"),
            ("orange", "Sobreejercido"),
        ],
        compute="_compute_traffic_light",
        store=True,
    )

    purchase_order_ids = fields.One2many("purchase.order", "sec_activity_id")

    @api.depends("budget_line_ids.amount_programa", "budget_line_ids.amount_concurrente", "budget_line_ids.amount_total")
    def _compute_budget_totals(self):
        for activity in self:
            programa = sum(activity.budget_line_ids.mapped("amount_programa"))
            concurrente = sum(activity.budget_line_ids.mapped("amount_concurrente"))
            activity.amount_programa = programa
            activity.amount_concurrente = concurrente
            activity.amount_total = programa + concurrente

    @api.depends(
        "project_id.purchase_order_ids.state",
        "project_id.purchase_order_ids.currency_id",
        "project_id.purchase_order_ids.amount_total",
        "project_id.purchase_order_ids.sec_total_mxn_manual",
        "project_id.purchase_order_ids.sec_activity_id",
        "project_id.purchase_order_ids.sec_stage_id",
        "project_id.purchase_order_ids.sec_rubro_id",
        "budget_line_ids.exec_total",
    )
    def _compute_execution(self):
        projects = self.mapped("project_id")
        execution = projects._collect_execution_data()
        activity_data = execution.get("activity", {})
        for activity in self:
            values = activity_data.get(activity.id, {})
            activity.exec_programa = values.get("programa", 0.0)
            activity.exec_concurrente = values.get("concurrente", 0.0)
            activity.exec_total = values.get("total", 0.0)

    @api.depends("exec_total", "amount_total")
    def _compute_traffic_light(self):
        for activity in self:
            if activity.exec_total > activity.amount_total:
                activity.traffic_light = "orange"
            else:
                activity.traffic_light = "green"


class SecActivityBudgetLine(models.Model):
    _name = "sec.activity.budget.line"
    _description = "Línea de presupuesto de actividad"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Descripción")
    activity_id = fields.Many2one("sec.activity", required=True, ondelete="cascade")
    project_id = fields.Many2one(related="activity_id.project_id", store=True, readonly=True)
    stage_id = fields.Many2one(related="activity_id.stage_id", store=True, readonly=True)
    rubro_id = fields.Many2one("sec.rubro", required=True)
    tipo_gasto = fields.Selection(related="rubro_id.tipo_gasto", store=True)
    currency_id = fields.Many2one(related="project_id.currency_id", store=True, readonly=True)

    amount_programa = fields.Monetary(currency_field="currency_id")
    amount_concurrente = fields.Monetary(currency_field="currency_id")
    amount_total = fields.Monetary(
        compute="_compute_total",
        inverse="_inverse_total",
        store=True,
        currency_field="currency_id",
    )

    exec_programa = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    exec_concurrente = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )
    exec_total = fields.Monetary(
        compute="_compute_execution",
        store=True,
        currency_field="currency_id",
    )

    traffic_light = fields.Selection(
        [
            ("green", "Dentro del presupuesto"),
            ("orange", "Sobreejercido"),
        ],
        compute="_compute_traffic_light",
        store=True,
    )
    justification = fields.Text(string="Justificación específica")

    @api.depends("amount_programa", "amount_concurrente")
    def _compute_total(self):
        for line in self:
            line.amount_total = (line.amount_programa or 0.0) + (line.amount_concurrente or 0.0)

    def _inverse_total(self):
        for line in self:
            project = line.project_id
            if not project:
                continue
            total = line.amount_total or 0.0
            if total and (
                float_is_zero(line.amount_programa or 0.0, precision_digits=2)
                and float_is_zero(line.amount_concurrente or 0.0, precision_digits=2)
            ):
                line.amount_programa = total * (project.pct_programa / 100.0)
                line.amount_concurrente = total * (project.pct_concurrente / 100.0)

    @api.depends(
        "project_id.purchase_order_ids.state",
        "project_id.purchase_order_ids.currency_id",
        "project_id.purchase_order_ids.amount_total",
        "project_id.purchase_order_ids.sec_total_mxn_manual",
        "project_id.purchase_order_ids.sec_activity_id",
        "project_id.purchase_order_ids.sec_rubro_id",
    )
    def _compute_execution(self):
        projects = self.mapped("project_id")
        execution = projects._collect_execution_data()
        line_data = execution.get("line", {})
        for line in self:
            key = (line.activity_id.id, line.rubro_id.id)
            values = line_data.get(key, {})
            line.exec_programa = values.get("programa", 0.0)
            line.exec_concurrente = values.get("concurrente", 0.0)
            line.exec_total = values.get("total", 0.0)

    @api.depends("exec_total", "amount_total")
    def _compute_traffic_light(self):
        for line in self:
            if line.exec_total > line.amount_total:
                line.traffic_light = "orange"
            else:
                line.traffic_light = "green"

    @api.onchange("amount_total")
    def _onchange_amount_total(self):
        for line in self:
            if not line.project_id:
                continue
            project = line.project_id
            total = line.amount_total or 0.0
            if not total:
                continue
            if not line.amount_programa and not line.amount_concurrente:
                line.amount_programa = total * (project.pct_programa / 100.0)
                line.amount_concurrente = total * (project.pct_concurrente / 100.0)

