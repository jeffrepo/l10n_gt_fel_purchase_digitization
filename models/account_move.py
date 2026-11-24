import logging

from odoo import models, _
from odoo.exceptions import UserError
from odoo.tools.pdf import PdfReader

from ..fel_parser import extract_from_pdf, missing_fel_values


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _extend_with_attachments(self, files_data, new=False):
        # Odoo 19 calls this from purchase.order.action_create_invoice as well
        # as the Accounting upload and invoice chatter flows. Keep its decoder
        # and asynchronous OCR behavior intact.
        result = super()._extend_with_attachments(files_data, new=new)
        self._fel_complete_from_files(files_data)
        return result

    def _fel_complete_from_files(self, files_data):
        self.ensure_one()
        if self.state != "draft" or self.move_type not in ("in_invoice", "in_refund"):
            return "ineligible"
        if self.fel_serie and self.fel_numero and self.invoice_date:
            return "complete"

        pdf_files = [
            data for data in files_data
            if data.get("mimetype") == "application/pdf"
            or (data.get("name") or "").lower().endswith(".pdf")
        ]
        # An unreadable second PDF may be another bill. Do not pick one at
        # random or associate identifiers from different attachments.
        if len(pdf_files) != 1:
            return "ambiguous" if pdf_files else "missing_pdf"
        try:
            detected = extract_from_pdf(pdf_files[0].get("raw"), PdfReader)
        except Exception:
            # Invalid/encrypted PDFs must not interrupt Odoo's upload/OCR.
            _logger.warning("No se pudo leer el PDF FEL de account.move %s", self.id)
            return "unreadable"
        if not detected:
            return "unreadable"

        existing = {key: self[key] for key in ("fel_serie", "fel_numero", "invoice_date")}
        values = missing_fel_values(existing, detected)
        if not values:
            if any(
                existing[key] and str(existing[key]).strip().upper() != detected[key]
                for key in ("fel_serie", "fel_numero")
            ):
                return "conflict"
            return "missing_date"
        # No sudo: retain the user's/company's normal write restrictions.
        self.write(values)
        return "updated" if self.invoice_date else "partial"

    def action_extract_fel_identifiers(self):
        self.ensure_one()
        if self.state != "draft" or self.move_type not in ("in_invoice", "in_refund"):
            raise UserError(_("Esta acción requiere una factura de proveedor en borrador."))
        attachments = self.message_main_attachment_id
        if not attachments:
            attachments = self.env["ir.attachment"].search([
                ("res_model", "=", "account.move"),
                ("res_id", "=", self.id),
                ("mimetype", "=", "application/pdf"),
            ])
        status = self._fel_complete_from_files(self._to_files_data(attachments))
        messages = {
            "updated": _("Se completaron los campos vacíos de serie, número FEL y fecha de factura desde el PDF."),
            "complete": _("La serie, el número FEL y la fecha de factura ya tienen valores."),
            "partial": _("Se completaron la serie y el número FEL. No se identificó una fecha de emisión única y válida; revise la fecha de factura."),
            "missing_date": _("La serie y el número coinciden, pero no se identificó una fecha de emisión única y válida. Complete la fecha de factura manualmente."),
            "conflict": _("Los datos del PDF no coinciden con los ya ingresados. Revise la factura."),
            "ambiguous": _("Hay varios PDF. Seleccione la factura original como adjunto principal y reintente."),
            "missing_pdf": _("Adjunte la factura original en PDF o selecciónela como adjunto principal."),
            "unreadable": _(
                "No se identificaron una serie y un número únicos. Use el PDF original con texto "
                "seleccionable o complete los campos manualmente. Los escaneos necesitan OCR."
            ),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Datos FEL del proveedor"),
                "message": messages[status],
                "type": "success" if status in ("updated", "complete") else "warning",
                "sticky": status not in ("updated", "complete"),
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
