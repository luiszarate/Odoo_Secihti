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
    sec_effective_mxn = fields.Monetary(
        string="Total MXN efectivo",
        compute="_compute_sec_effective_mxn",
        store=True,
        currency_field="company_currency_id",
    )
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
    

    """@api.model
    def _setup_complete(self):
        super()._setup_complete()
        field = self._fields.get("x_payment_method")
        new_option = ("debito_secihti", "Tarjeta de Débito Secihti")
        if field and isinstance(field.selection, list) and new_option not in field.selection:
            field.selection.append(new_option)"""

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
            if not order.sec_project_id:
                order.sec_stage_id = False
                order.sec_activity_id = False
                order.sec_rubro_id = False
                continue
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

    """ @api.depends(
        "sec_project_id",
        "currency_id",
        "company_currency_id",
        "amount_total",
        "sec_total_mxn_manual",
    )
    def _compute_sec_effective_mxn(self):
        for order in self:
            if not order.sec_project_id:
                order.sec_effective_mxn = 0.0
                continue
            if order.currency_id == order.company_currency_id:
                order.sec_effective_mxn = order.amount_total
            else:
                order.sec_effective_mxn = order.sec_total_mxn_manual
    """

    @api.depends("currency_id", "company_currency_id", "amount_total", "sec_total_mxn_manual")
    def _compute_sec_effective_mxn(self):
        for order in self:
            if order.currency_id == order.company_currency_id:
                order.sec_effective_mxn = order.amount_total or 0.0
            else:
                order.sec_effective_mxn = order.sec_total_mxn_manual or 0.0

    def _sec_get_amount_mxn(self):
        """Mantén este helper por compatibilidad, pero delega al compute."""
        self.ensure_one()
        return self.sec_effective_mxn or 0.0


    def _sync_mxn_manual_if_needed(self):
        """Si la moneda de la OC es la moneda de la compañía, iguala el manual MXN al total."""
        for order in self:
            if order.currency_id == order.company_currency_id:
                # Evita bucles infinitos: solo escribe si cambia
                if (order.sec_total_mxn_manual or 0.0) != (order.amount_total or 0.0):
                    order.write({"sec_total_mxn_manual": order.amount_total})

    def _add_sec_bank_fee_line_if_needed(self):
        """Agrega una línea de comisión bancaria cuando aplique."""
        PurchaseOrderLine = self.env["purchase.order.line"]
        Product = self.env["product.product"]

        transfer_values = set()
        payment_field = self._fields.get("x_payment_method")
        if payment_field and getattr(payment_field, "selection", False):
            transfer_values = {
                value
                for value, label in payment_field.selection
                if (label or "").strip().lower() == "transferencia"
            }

        for order in self:
            if not order.sec_project_id:
                continue

            payment_value = getattr(order, "x_payment_method", False)
            if transfer_values:
                if payment_value not in transfer_values:
                    continue
            else:
                if (payment_value or "").strip().lower() != "transferencia":
                    continue

            bank_fee_product = False
            try:
                bank_fee_product = self.env.ref(
                    "product.product_product_bank_fees", raise_if_not_found=False
                )
            except ValueError:
                bank_fee_product = False
            if not bank_fee_product:
                bank_fee_product = Product.search(
                    [
                        ("name", "=", "Comisión Bancaria"),
                        ("purchase_ok", "=", True),
                    ],
                    limit=1,
                )
            if not bank_fee_product:
                continue

            existing_line = order.order_line.filtered(
                lambda line: line.product_id == bank_fee_product
            )
            if existing_line:
                continue

            taxes = bank_fee_product.supplier_taxes_id
            PurchaseOrderLine.create(
                {
                    "order_id": order.id,
                    "name": bank_fee_product.get_product_multiline_description_purchase(),
                    "product_id": bank_fee_product.id,
                    "product_qty": 1.0,
                    "product_uom": (bank_fee_product.uom_po_id or bank_fee_product.uom_id).id,
                    "price_unit": 7.5,
                    "taxes_id": [(6, 0, taxes.ids)],
                }
            )

    @api.onchange("currency_id", "company_currency_id", "order_line")
    def _onchange_sync_mxn_manual(self):
        """En el formulario: si está en MXN, refleja aquí el total."""
        for order in self:
            if order.currency_id == order.company_currency_id:
                order.sec_total_mxn_manual = order.amount_total

    @api.model
    def create(self, vals):
        order = super().create(vals)
        # Asegura subpartida (tu lógica existente)
        order._ensure_budget_line_for_activity_rubro()
        # Sincroniza manual MXN si aplica
        order._sync_mxn_manual_if_needed()
        order._add_sec_bank_fee_line_if_needed()
        return order

    def write(self, vals):
        res = super().write(vals)
        # Si cambió moneda o líneas, sincroniza en MXN
        if any(k in vals for k in ("currency_id", "order_line")):
            for order in self:
                order._sync_mxn_manual_if_needed()
        # Si cambió actividad/rubro, asegura subpartida (tu lógica existente)
        if any(k in vals for k in ("sec_activity_id", "sec_rubro_id")):
            for order in self:
                order._ensure_budget_line_for_activity_rubro()
        if any(
            k in vals
            for k in (
                "sec_project_id",
                "order_line",
                "x_payment_method",
            )
        ):
            for order in self:
                order._add_sec_bank_fee_line_if_needed()
        return res


    