# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    sec_project_id = fields.Many2one("sec.project", string="Proyecto SECIHTI")
    sec_stage_id = fields.Many2one("sec.stage", string="Etapa SECIHTI")
    sec_activity_id = fields.Many2one("sec.activity", string="Actividad SECIHTI")
    sec_rubro_id = fields.Many2one("sec.rubro", string="Rubro SECIHTI")

    company_currency_id = fields.Many2one(
        "res.currency",
        string="Company Currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    sec_total_mxn_manual = fields.Monetary(string="Total MXN manual", currency_field="company_currency_id")
    sec_mxn_pending = fields.Boolean(compute="_compute_sec_mxn_pending", store=True)

    sec_attachment_state = fields.Selection(
        [
            ("red", "Sin adjuntos"),
            ("orange", "Un adjunto"),
            ("green", "Múltiples adjuntos"),
        ],
        compute="_compute_attachment_state",
        store=True,
    )

    def _ensure_budget_line_for_activity_rubro(self):
        """Si la actividad no tiene subpartida para el rubro, crearla con montos en 0."""
        for order in self:
            if not (order.sec_activity_id and order.sec_rubro_id):
                continue
            BudgetLine = self.env["sec.activity.budget.line"]
            exists = BudgetLine.search([
                ("activity_id", "=", order.sec_activity_id.id),
                ("rubro_id", "=", order.sec_rubro_id.id),
            ], limit=1)
            if not exists:
                BudgetLine.create({
                    "activity_id": order.sec_activity_id.id,
                    "rubro_id": order.sec_rubro_id.id,
                    "name": "",                # descripción en blanco
                    "amount_programa": 0.0,
                    "amount_concurrente": 0.0, # amount_total se computa (=0)
                })

    

    @api.depends("sec_project_id", "currency_id", "sec_total_mxn_manual", "amount_total", "state")
    def _compute_sec_mxn_pending(self):
        for order in self:
            if order.state not in ("purchase", "done"):
                order.sec_mxn_pending = False
                continue
            if not order.sec_project_id:
                order.sec_mxn_pending = False
                continue
            if order.currency_id == order.company_currency_id:
                order.sec_mxn_pending = False
            else:
                order.sec_mxn_pending = not bool(order.sec_total_mxn_manual)

    @api.depends("message_attachment_count")
    def _compute_attachment_state(self):
        for order in self:
            if order.message_attachment_count == 0:
                order.sec_attachment_state = "red"
            elif order.message_attachment_count == 1:
                order.sec_attachment_state = "orange"
            else:
                order.sec_attachment_state = "green"

    @api.onchange("sec_project_id")
    def _onchange_project(self):
        for order in self:
            if order.sec_stage_id and order.sec_stage_id.project_id != order.sec_project_id:
                order.sec_stage_id = False
            if order.sec_activity_id and order.sec_activity_id.project_id != order.sec_project_id:
                order.sec_activity_id = False

    @api.onchange("sec_stage_id")
    def _onchange_stage(self):
        for order in self:
            if order.sec_stage_id and order.sec_activity_id and order.sec_activity_id.stage_id != order.sec_stage_id:
                order.sec_activity_id = False

    def _sec_get_amount_mxn(self):
        self.ensure_one()
        if not self.sec_project_id:
            return 0.0
        if self.currency_id == self.company_currency_id:
            return self.amount_total
        return self.sec_total_mxn_manual

    def _sync_mxn_manual_for_company_currency(self):
        for order in self:
            if order.currency_id == order.company_currency_id:
                # Copia el total de la OC al campo manual (en MXN) automáticamente
                order.sec_total_mxn_manual = order.amount_total
            
    @api.onchange('currency_id', 'amount_total')
    def _onchange_sync_mxn_manual(self):
        # Al cambiar moneda o total, si es MXN, mantenemos sec_total_mxn_manual = amount_total
        self._sync_mxn_manual_for_company_currency()
    

    @api.model
    def create(self, vals):
        order = super().create(vals)
        # Si ya vienen actividad/rubro en create, crear subpartida
        order._ensure_budget_line_for_activity_rubro()
        order._sync_mxn_manual_for_company_currency()
        return order

    def write(self, vals):
        res = super().write(vals)
        # Si cambian actividad o rubro, volver a asegurar subpartida
        if any(k in vals for k in ("sec_activity_id", "sec_rubro_id")):
            for order in self:
                order._ensure_budget_line_for_activity_rubro()
        if {'currency_id', 'order_line', 'company_id'}.intersection(vals.keys()):
            self._sync_mxn_manual_for_company_currency()
        return res
