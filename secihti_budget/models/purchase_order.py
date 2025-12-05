# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools import float_round


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    sec_project_id = fields.Many2one("sec.project", string="Proyecto SECIHTI")
    sec_stage_id = fields.Many2one("sec.stage", string="Etapa SECIHTI")
    sec_activity_id = fields.Many2one("sec.activity", string="Actividad SECIHTI")
    sec_rubro_id = fields.Many2one("sec.rubro", string="Rubro SECIHTI")
    sec_bank_statement_verified = fields.Boolean(
        string="Gasto verificado en estado de cuenta",
        help="Indica si el gasto ya fue contrastado contra el estado de cuenta bancario.",
    )

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
    sec_total_mxn_concurrente = fields.Monetary(
        string="Total MXN concurrente (30%)",
        compute="_compute_sec_allocations",
        store=True,
        currency_field="company_currency_id",
    )
    sec_total_mxn_programa = fields.Monetary(
        string="Total MXN programa (70%)",
        compute="_compute_sec_allocations",
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

    @api.depends("sec_effective_mxn")
    def _compute_sec_allocations(self):
        for order in self:
            total = order.sec_effective_mxn or 0.0
            concurrente = float_round(total * 0.30, precision_digits=2)
            programa = float_round(total - concurrente, precision_digits=2)
            order.sec_total_mxn_concurrente = concurrente
            order.sec_total_mxn_programa = programa

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


    def _sec_is_transfer_payment(self):
        self.ensure_one()
        transfer_values = set()
        payment_field = self._fields.get("x_payment_method")
        if payment_field and getattr(payment_field, "selection", False):
            transfer_values = {
                value
                for value, label in payment_field.selection
                if (label or "").strip().lower() == "transferencia"
            }

        if payment_field:
            payment_value = getattr(self, "x_payment_method", False)
        else:
            payment_value = self._context.get("x_payment_method") or self._context.get(
                "sec_payment_method"
            )

        if transfer_values:
            return payment_value in transfer_values
        return (payment_value or "").strip().lower() == "transferencia"

    def _sec_get_bank_fee_product(self):
        Product = self.env["product.product"]
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
        return bank_fee_product

    def _sec_get_bank_fee_partner(self, company=None):
        Partner = self.env["res.partner"]
        domain = [("name", "=", "BANCO DEL BAJIO")]
        if company:
            domain = ["|", ("company_id", "=", False), ("company_id", "=", company.id)] + domain
        partner = Partner.search(domain, limit=1)
        if partner:
            return partner
        return Partner.create(
            {
                "name": "BANCO DEL BAJIO",
                "supplier_rank": 1,
                "company_id": company.id if company else False,
            }
        )

    def _sec_get_iva_tax(self, company):
        Tax = self.env["account.tax"]
        return Tax.search(
            [
                ("name", "ilike", "IVA"),
                ("type_tax_use", "in", ["purchase", "none"]),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )

    def _sec_get_monthly_commission_order(self, company, currency, partner, now=None):
        self.ensure_one()
        PurchaseOrder = self.env["purchase.order"]
        now = now or fields.Datetime.now()
        current_date = fields.Datetime.context_timestamp(self, fields.Datetime.from_string(now))
        month_start = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        month_end = next_month

        monthly_order = PurchaseOrder.search(
            [
                ("partner_id", "=", partner.id),
                ("company_id", "=", company.id),
                ("currency_id", "=", currency.id),
                ("state", "in", ["draft", "sent"]),
                ("date_order", ">=", fields.Datetime.to_string(month_start)),
                ("date_order", "<", fields.Datetime.to_string(month_end)),
            ],
            limit=1,
        )
        if monthly_order:
            return monthly_order

        return PurchaseOrder.with_company(company).create(
            {
                "partner_id": partner.id,
                "currency_id": currency.id,
                "date_order": fields.Datetime.to_string(current_date),
                "origin": _("Comisiones bancarias %s/%s")
                % (month_start.month, month_start.year),
                "company_id": company.id,
            }
        )

    def _sec_add_bank_fee_line(self, commission_order, source_order, product):
        PurchaseOrderLine = self.env["purchase.order.line"]
        company = commission_order.company_id
        taxes = product.supplier_taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == company
        )
        iva_tax = self._sec_get_iva_tax(company)
        if iva_tax:
            taxes |= iva_tax
        if commission_order.fiscal_position_id:
            taxes = commission_order.fiscal_position_id.map_tax(taxes)

        existing_line = commission_order.order_line.filtered(
            lambda line: line.sec_source_purchase_id == source_order
        )
        if existing_line:
            return existing_line

        description = (
            product.get_product_multiline_description_purchase()
            if hasattr(product, "get_product_multiline_description_purchase")
            else product.display_name or product.name
        )

        new_line = PurchaseOrderLine.create(
            {
                "order_id": commission_order.id,
                "name": description,
                "product_id": product.id,
                "product_qty": 1.0,
                "product_uom": (product.uom_po_id or product.uom_id).id,
                "price_unit": 7.5,
                "taxes_id": [(6, 0, taxes.ids)],
                "sec_source_purchase_id": source_order.id,
            }
        )

        commission_order._sync_mxn_manual_if_needed()
        return new_line

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
        return res

    def button_confirm(self):
        res = super().button_confirm()
        self._sec_handle_bank_commission()
        return res

    def _sec_handle_bank_commission(self):
        bank_fee_product = self._sec_get_bank_fee_product()
        if not bank_fee_product:
            return
        bank_partners = {}
        for order in self:
            if not order.sec_project_id or not order._sec_is_transfer_payment():
                continue
            if order.state not in ("purchase", "done"):
                continue
            bank_partner = bank_partners.get(order.company_id.id)
            if not bank_partner:
                bank_partner = order._sec_get_bank_fee_partner(order.company_id)
                bank_partners[order.company_id.id] = bank_partner
            commission_order = order._sec_get_monthly_commission_order(
                order.company_id, order.currency_id, bank_partner
            )
            order._sec_add_bank_fee_line(commission_order, order, bank_fee_product)


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    sec_source_purchase_id = fields.Many2one(
        "purchase.order",
        string="OC origen para comisión",
        help="OC que generó esta línea de comisión bancaria.",
    )


    
