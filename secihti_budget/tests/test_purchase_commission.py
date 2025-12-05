# -*- coding: utf-8 -*-
from odoo.tests.common import SavepointCase


class TestPurchaseCommission(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.currency = cls.company.currency_id

        cls.project = cls.env["sec.project"].create(
            {"name": "Proyecto Test", "code": "TST", "currency_id": cls.currency.id}
        )

        cls.vendor = cls.env["res.partner"].create(
            {"name": "Proveedor Test", "supplier_rank": 1}
        )

        cls.main_product = cls.env["product.product"].create(
            {
                "name": "Producto Principal",
                "type": "consu",
                "purchase_ok": True,
                "list_price": 100.0,
            }
        )

        cls.bank_fee_product = cls.env["product.product"].create(
            {
                "name": "Comisión Bancaria",
                "type": "service",
                "purchase_ok": True,
                "list_price": 7.5,
            }
        )

        cls.iva_tax = cls.env["account.tax"].create(
            {
                "name": "IVA Test 16%",
                "amount_type": "percent",
                "amount": 16.0,
                "type_tax_use": "purchase",
                "company_id": cls.company.id,
            }
        )

    def _set_transfer_payment_method(self, purchase_order):
        if "x_payment_method" in purchase_order._fields:
            purchase_order.x_payment_method = "transferencia"
        else:
            purchase_order = purchase_order.with_context(
                sec_payment_method="transferencia"
            )
        return purchase_order

    def test_bank_fee_monthly_order_created_on_confirmation(self):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "currency_id": self.currency.id,
                "company_id": self.company.id,
                "sec_project_id": self.project.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.main_product.id,
                            "name": self.main_product.name,
                            "product_qty": 1.0,
                            "product_uom": self.main_product.uom_id.id,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )

        order = self._set_transfer_payment_method(order)

        order.button_confirm()

        bank_partner = self.env["res.partner"].search(
            [("name", "=", "BANCO DEL BAJIO")], limit=1
        )
        self.assertTrue(bank_partner, "Should resolve BANCO DEL BAJIO partner")

        commission_orders = self.env["purchase.order"].search(
            [
                ("partner_id", "=", bank_partner.id),
                ("company_id", "=", self.company.id),
                ("currency_id", "=", self.currency.id),
                ("state", "in", ["draft", "sent"]),
            ]
        )
        self.assertEqual(len(commission_orders), 1)
        commission_order = commission_orders[0]

        commission_lines = commission_order.order_line.filtered(
            lambda line: line.sec_source_purchase_id == order
        )
        self.assertEqual(len(commission_lines), 1, "Commission line should exist once")
        self.assertEqual(commission_lines.product_id, self.bank_fee_product)

        # No debe duplicarse si se vuelve a intentar
        order._sec_handle_bank_commission()
        commission_lines = commission_order.order_line.filtered(
            lambda line: line.sec_source_purchase_id == order
        )
        self.assertEqual(len(commission_lines), 1)

        original_fee_lines = order.order_line.filtered(
            lambda line: line.product_id == self.bank_fee_product
        )
        self.assertFalse(original_fee_lines, "Original PO must not get bank fee line")

        self.assertAlmostEqual(
            commission_order.sec_total_mxn_manual,
            commission_order.amount_total,
            msg="Commission order should sync MXN totals",
        )
