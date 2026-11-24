import importlib.util
from pathlib import Path
import unittest


# Also runnable without installing Odoo; never import the addon's __init__.
spec = importlib.util.spec_from_file_location(
    "fel_parser", Path(__file__).resolve().parents[1] / "fel_parser.py"
)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class TestFelParser(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
