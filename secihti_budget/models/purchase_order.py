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

