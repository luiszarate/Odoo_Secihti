# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero
from odoo.tools.misc import formatLang


class SecBudgetTransfer(models.Model):
    _name = "sec.budget.transfer"
    _description = "Transferencia presupuestal"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia", default=lambda self: _("Nuevo"), copy=False, tracking=True
    )
    activity_id = fields.Many2one(
        "sec.activity", required=True, tracking=True, ondelete="cascade"
    )
    project_id = fields.Many2one(
        related="activity_id.project_id", store=True, readonly=True
    )
    stage_id = fields.Many2one(related="activity_id.stage_id", store=True, readonly=True)
    currency_id = fields.Many2one(
        related="activity_id.currency_id", store=True, readonly=True
    )
    line_from_id = fields.Many2one(
        "sec.activity.budget.line",
        string="Línea origen",
        required=True,
        tracking=True,
        domain="[('activity_id', '=', activity_id)]",
    )
    line_to_id = fields.Many2one(
        "sec.activity.budget.line",
        string="Línea destino",
        required=True,
        tracking=True,
        domain="[('activity_id', '=', activity_id)]",
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

    @api.onchange("line_from_id")
    def _onchange_line_from(self):
        if self.line_from_id:
            self.activity_id = self.line_from_id.activity_id

    @api.constrains("line_from_id", "line_to_id", "activity_id")
    def _check_activity_consistency(self):
        for transfer in self:
            if not transfer.line_from_id or not transfer.line_to_id or not transfer.activity_id:
                continue
            if transfer.line_from_id.activity_id != transfer.activity_id or transfer.line_to_id.activity_id != transfer.activity_id:
                raise ValidationError(
                    _(
                        "Las líneas seleccionadas deben pertenecer a la actividad indicada en la transferencia."
                    )
                )

    @api.depends("amount_programa", "amount_concurrente")
    def _compute_amount(self):
        for transfer in self:
            transfer.amount = (transfer.amount_programa or 0.0) + (
                transfer.amount_concurrente or 0.0
            )

    def _get_precision(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return currency.rounding or self.env.company.currency_id.rounding

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
            if transfer.line_from_id.activity_id != transfer.activity_id or transfer.line_to_id.activity_id != transfer.activity_id:
                raise ValidationError(
                    _(
                        "Las líneas seleccionadas deben pertenecer a la misma actividad que la transferencia."
                    )
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
        record = super().create(vals)
        if record.state == "confirmed":
            record.action_confirm()
        return record

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
