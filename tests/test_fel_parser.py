import importlib.util
from datetime import date
from pathlib import Path
import unittest


# Also runnable without installing Odoo; never import the addon's __init__.
spec = importlib.util.spec_from_file_location(
    "fel_parser", Path(__file__).resolve().parents[1] / "fel_parser.py"
)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class TestFelParser(unittest.TestCase):
    HEADER = "Serie: ABCDEF12 Número de DTE: 4294967295\n"

    def test_sat_header(self):
        text = (
            "NÚMERO DE AUTORIZACIÓN: ABCDEF12-1234-5678-90AB-1234567890AB\n"
            "Serie: ABCDEF12 Número de DTE: 4294967295\n"
            "Numero Acceso: \nPO: PO00001\nTotal: 900.00"
        )
        self.assertEqual(parser.extract_fel_identifiers(text), {
            "fel_serie": "ABCDEF12", "fel_numero": "4294967295",
        })

    def test_accents_newlines_and_leading_zeroes(self):
        self.assertEqual(parser.extract_fel_identifiers(
            "serie:\nabcdef12\nNu\u0301mero de DTE:\n000123"
        ), {"fel_serie": "ABCDEF12", "fel_numero": "000123"})

    def test_repeated_headers(self):
        text = "Serie: ABCDEF12 Número de DTE: 123\n"
        self.assertEqual(parser.extract_fel_identifiers(text * 3)["fel_numero"], "123")

    def test_multiple_bills_rejected(self):
        for second in ("Serie: ABCDEF12 Número de DTE: 456", "Serie: ABCDEF34 Número de DTE: 123"):
            with self.subTest(second=second):
                self.assertEqual(parser.extract_fel_identifiers(
                    "Serie: ABCDEF12 Número de DTE: 123\n" + second
                ), {})

    def test_no_guessing_from_authorization_or_po(self):
        for text in (
            "ABCDEF12-1234-5678-90AB-1234567890AB",
            "Serie: ABCDEF12 NÚMERO DE AUTORIZACIÓN: 12345678",
            "Serie: ABCDEF12 PO: PO00001 Total: 900.00",
            "Número de DTE: 4294967295",
            "Serie: ABCDEF120 Número de DTE: 4294967295",
            "",
        ):
            with self.subTest(text=text):
                self.assertEqual(parser.extract_fel_identifiers(text), {})

    def test_do_not_mix_conflicting_values(self):
        detected = {"fel_serie": "ABCDEF12", "fel_numero": "000123"}
        self.assertEqual(parser.missing_fel_values({"fel_serie": "87654321"}, detected), {})
        self.assertEqual(parser.missing_fel_values({"fel_numero": "123"}, detected), {})
        self.assertEqual(parser.missing_fel_values({"fel_serie": "abcdef12"}, detected), {
            "fel_numero": "000123",
        })

    def test_no_overwrite_and_no_incomplete_pair(self):
        detected = {"fel_serie": "ABCDEF12", "fel_numero": "000123"}
        self.assertEqual(parser.missing_fel_values(detected, detected), {})
        self.assertEqual(parser.missing_fel_values({}, {"fel_serie": "ABCDEF12"}), {})

    def test_issue_date_instead_of_certification_due_or_service_date(self):
        values = parser.extract_fel_identifiers(self.HEADER + (
            "Fecha y hora de emisión: 23-nov-2026 23:59:23\n"
            "Fecha y hora de certificación: 24-nov-2026 00:01:00\n"
            "Fecha de vencimiento: 23-dic-2026\n"
            "Flete realizado 17/11/2026"
        ))
        self.assertEqual(values["invoice_date"], "2026-11-23")

    def test_supported_issue_date_formats(self):
        for value in (
            "23-nov-2026 14:39:23", "23/11/2026", "23-11-2026",
            "2026-11-23", "2026-11-23T23:59:23-06:00",
            "23 de noviembre de 2026", "23 NOVIEMBRE 2026", "23/nov/2026",
        ):
            with self.subTest(value=value):
                values = parser.extract_fel_identifiers(self.HEADER + "Fecha de emisión: " + value)
                self.assertEqual(values["invoice_date"], "2026-11-23")

    def test_date_labels_accents_and_line_breaks(self):
        for label in (
            "Fecha y hora de emisión", "Fecha de emision", "Fecha emisión",
            "Fecha de factura", "Fecha factura", "Fecha del documento de emisión",
        ):
            with self.subTest(label=label):
                values = parser.extract_fel_identifiers(self.HEADER + label + ":\n23-nov-2026")
                if label == "Fecha del documento de emisión":
                    self.assertNotIn("invoice_date", values)
                else:
                    self.assertEqual(values["invoice_date"], "2026-11-23")

    def test_all_spanish_month_names(self):
        for name, month in parser.MONTHS.items():
            with self.subTest(name=name):
                values = parser.extract_fel_identifiers(self.HEADER + "Fecha de emisión: 01-%s-2026" % name)
                self.assertEqual(values["invoice_date"], "2026-%02d-01" % month)

    def test_numeric_dates_are_day_first(self):
        values = parser.extract_fel_identifiers(self.HEADER + "Fecha de factura: 03/04/2026")
        self.assertEqual(values["invoice_date"], "2026-04-03")

    def test_invalid_or_unsupported_dates_do_not_discard_identifiers(self):
        for value in (
            "31/02/2026", "29/02/2025", "00/11/2026", "23/13/2026",
            "11/23/2026", "23/11/26", "23-xyz-2026", "23/11-2026",
            "23/11/20260", "23/11/2026/01", "", "ilegible",
        ):
            with self.subTest(value=value):
                values = parser.extract_fel_identifiers(self.HEADER + "Fecha de emisión: " + value)
                self.assertNotIn("invoice_date", values)
                self.assertEqual(values["fel_numero"], "4294967295")

    def test_valid_leap_day(self):
        values = parser.extract_fel_identifiers(self.HEADER + "Fecha de emisión: 29/02/2024")
        self.assertEqual(values["invoice_date"], "2024-02-29")

    def test_never_substitute_other_dates(self):
        values = parser.extract_fel_identifiers(self.HEADER + (
            "Fecha y hora de certificación: 23-nov-2026\n"
            "Fecha de vencimiento: 23-dic-2026\nServicio: 17/11/2026"
        ))
        self.assertNotIn("invoice_date", values)

    def test_repeated_issue_date_and_conflicting_dates(self):
        first = "Fecha de emisión: 23-nov-2026\n"
        repeated = parser.extract_fel_identifiers(self.HEADER + first * 2)
        self.assertEqual(repeated["invoice_date"], "2026-11-23")
        for second in ("Fecha de factura: 24-nov-2026", "Fecha de emisión: ilegible"):
            with self.subTest(second=second):
                values = parser.extract_fel_identifiers(self.HEADER + first + second)
                self.assertNotIn("invoice_date", values)

    def test_date_filled_when_fel_fields_already_complete(self):
        existing = {"fel_serie": "ABCDEF12", "fel_numero": "4294967295"}
        detected = dict(existing, invoice_date="2026-11-23")
        self.assertEqual(parser.missing_fel_values(existing, detected), {"invoice_date": "2026-11-23"})

    def test_preserve_existing_date_and_complete_identifiers(self):
        detected = {"fel_serie": "ABCDEF12", "fel_numero": "4294967295", "invoice_date": "2026-11-23"}
        for existing_date in ("2026-11-20", date(2026, 11, 20)):
            with self.subTest(existing_date=existing_date):
                self.assertEqual(parser.missing_fel_values({"invoice_date": existing_date}, detected), {
                    "fel_serie": "ABCDEF12", "fel_numero": "4294967295",
                })

    def test_conflicting_identifiers_prevent_date_from_other_bill(self):
        detected = {"fel_serie": "ABCDEF12", "fel_numero": "4294967295", "invoice_date": "2026-11-23"}
        self.assertEqual(parser.missing_fel_values({"fel_serie": "87654321"}, detected), {})
        self.assertEqual(parser.extract_fel_identifiers("Fecha de emisión: 23-nov-2026"), {})


if __name__ == "__main__":
    unittest.main()
