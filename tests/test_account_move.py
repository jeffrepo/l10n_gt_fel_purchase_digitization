from io import BytesIO
from unittest.mock import patch
from reportlab.pdfgen import canvas

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestFelPurchaseDigitization(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(50, 750, "Serie: ABCDEF12 Numero de DTE: 4294967295")
        pdf.drawString(50, 730, "Fecha y hora de emision: 23-nov-2026 23:59:23")
        pdf.drawString(50, 710, "Fecha y hora de certificacion: 24-nov-2026 00:01:00")
        pdf.save()
        cls.pdf_raw = buffer.getvalue()

    def _bill(self, **values):
        return self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "journal_id": self.company_data["default_journal_purchase"].id,
            "invoice_date": False,
            **values,
        })

    def _attachment(self, bill=None):
        return self.env["ir.attachment"].create({
            "name": "factura.pdf",
            "mimetype": "application/pdf",
            "raw": self.pdf_raw,
            "res_model": "account.move" if bill else False,
            "res_id": bill.id if bill else 0,
        })

    def test_attachment_import_hook_and_idempotence(self):
        bill = self._bill(ref="REFERENCIA-EXISTENTE")
        files = bill._to_files_data(self._attachment(bill))
        # Disable external decoders for this test, not our import hook.
        for data in files:
            data["decoder_info"] = None
        bill._extend_with_attachments(files)
        bill._extend_with_attachments(files)
        self.assertEqual(bill.fel_serie, "ABCDEF12")
        self.assertEqual(bill.fel_numero, "4294967295")
        self.assertEqual(bill.invoice_date, fields.Date.to_date("2026-11-23"))
        self.assertEqual(bill.ref, "REFERENCIA-EXISTENTE")

    def test_conflicting_partial_values_not_mixed(self):
        bill = self._bill(fel_serie="87654321")
        self.assertEqual(bill._fel_complete_from_files(
            bill._to_files_data(self._attachment(bill))
        ), "conflict")
        self.assertFalse(bill.fel_numero)
        self.assertFalse(bill.invoice_date)
        self.assertEqual(bill.fel_serie, "87654321")

    def test_customer_invoice_not_modified(self):
        bill = self._bill(
            move_type="out_invoice",
            journal_id=self.company_data["default_journal_sale"].id,
        )
        bill._fel_complete_from_files(bill._to_files_data(self._attachment(bill)))
        self.assertFalse(bill.fel_serie)
        self.assertFalse(bill.fel_numero)
        self.assertFalse(bill.invoice_date)

    def test_posted_bill_not_modified(self):
        bill = self._bill(
            invoice_date=fields.Date.today(),
            invoice_line_ids=[Command.create({
                "name": "Servicio", "quantity": 1, "price_unit": 100,
                "account_id": self.company_data["default_account_expense"].id,
                "tax_ids": [Command.clear()],
            })],
        )
        bill.action_post()
        status = bill._fel_complete_from_files(bill._to_files_data(self._attachment(bill)))
        self.assertEqual(status, "ineligible")
        self.assertFalse(bill.fel_serie)
        self.assertFalse(bill.fel_numero)
        self.assertEqual(bill.invoice_date, fields.Date.today())

    def test_matching_partial_value_completes_only_missing_field(self):
        bill = self._bill(fel_serie="ABCDEF12")
        status = bill._fel_complete_from_files(bill._to_files_data(self._attachment(bill)))
        self.assertEqual(status, "updated")
        self.assertEqual(bill.fel_serie, "ABCDEF12")
        self.assertEqual(bill.fel_numero, "4294967295")
        self.assertEqual(bill.invoice_date, fields.Date.to_date("2026-11-23"))

    def test_date_completed_when_serie_and_number_already_exist(self):
        bill = self._bill(fel_serie="ABCDEF12", fel_numero="4294967295")
        self.assertFalse(bill.invoice_date)
        status = bill._fel_complete_from_files(bill._to_files_data(self._attachment(bill)))
        self.assertEqual(status, "updated")
        self.assertEqual(bill.invoice_date, fields.Date.to_date("2026-11-23"))

    def test_retry_button_completes_date_on_existing_bill(self):
        bill = self._bill(fel_serie="ABCDEF12", fel_numero="4294967295")
        bill.message_main_attachment_id = self._attachment(bill)
        action = bill.action_extract_fel_identifiers()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(bill.invoice_date, fields.Date.to_date("2026-11-23"))

    def test_existing_invoice_date_preserved(self):
        bill = self._bill(invoice_date="2026-11-20")
        status = bill._fel_complete_from_files(bill._to_files_data(self._attachment(bill)))
        self.assertEqual(status, "updated")
        self.assertEqual(bill.fel_serie, "ABCDEF12")
        self.assertEqual(bill.invoice_date, fields.Date.to_date("2026-11-20"))

    def test_missing_issue_date_returns_warning(self):
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(50, 750, "Serie: ABCDEF12 Numero de DTE: 4294967295")
        pdf.drawString(50, 730, "Fecha de certificacion: 24-nov-2026")
        pdf.save()
        bill = self._bill()
        file_data = [{"name": "factura.pdf", "mimetype": "application/pdf", "raw": buffer.getvalue()}]
        self.assertEqual(bill._fel_complete_from_files(file_data), "partial")
        self.assertFalse(bill.invoice_date)
        self.assertEqual(bill.fel_serie, "ABCDEF12")
        self.assertEqual(bill._fel_complete_from_files(file_data), "missing_date")

    def test_multiple_pdfs_not_selected_arbitrarily(self):
        bill = self._bill()
        attachments = self._attachment(bill) | self._attachment(bill)
        self.assertEqual(bill._fel_complete_from_files(bill._to_files_data(attachments)), "ambiguous")
        self.assertFalse(bill.fel_serie)

    def test_invalid_pdf_keeps_invoice_editable(self):
        bill = self._bill()
        status = bill._fel_complete_from_files([{
            "name": "invalido.pdf", "mimetype": "application/pdf", "raw": b"%PDF-invalid",
        }])
        self.assertEqual(status, "unreadable")
        self.assertEqual(bill.state, "draft")

    def test_purchase_upload(self):
        product = self.env["product.product"].create({
            "name": "Servicio de prueba FEL", "type": "service", "purchase_method": "purchase",
        })
        order = self.env["purchase.order"].create({
            "partner_id": self.partner_a.id,
            "order_line": [Command.create({
                "product_id": product.id, "product_qty": 1, "price_unit": 100,
            })],
        })
        order.button_confirm()
        # Keep the real purchase/import flow, without requesting paid OCR.
        with patch.object(type(self.env["account.move"]), "_get_edi_decoder", return_value=None):
            order.action_create_invoice(attachment_ids=self._attachment().ids)
        self.assertEqual(len(order.invoice_ids), 1)
        self.assertEqual(order.invoice_ids.fel_serie, "ABCDEF12")
        self.assertEqual(order.invoice_ids.fel_numero, "4294967295")
        self.assertEqual(order.invoice_ids.invoice_date, fields.Date.to_date("2026-11-23"))
