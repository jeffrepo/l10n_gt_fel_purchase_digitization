"""Read labelled FEL identifiers and invoice issue dates from PDF text."""

from datetime import date
from io import BytesIO
import re
import unicodedata


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_TEXT_CHARS = 2_000_000

SERIES_PATTERN = re.compile(
    r"\bSERIE(?:\s+(?:DE(?:L)?\s+)?(?:DTE|DOCUMENTO|FACTURA))?"
    r"\s*[:#-]?\s*([0-9A-F]{8})\b"
)
NUMBER_PATTERN = re.compile(
    r"\b(?:NUMERO|NO\.?|N[°º])"
    r"\s*(?:(?:DE(?:L)?\s+)?(?:DTE|DOCUMENTO|FACTURA))?"
    r"\s*[:#]\s*([0-9]{1,20})\b"
)
DATE_LABEL_PATTERN = re.compile(
    r"\bFECHA(?:\s+Y\s+HORA)?\s+(?:(?:DE|DEL)\s+)?"
    r"(?:EMISION|FACTURA)\b\s*[:#]?\s*"
)
DATE_PATTERN = re.compile(
    r"(?:"
    r"(?P<iso_year>[0-9]{4})-(?P<iso_month>[0-9]{2})-(?P<iso_day>[0-9]{2})"
    r"|(?P<day>[0-9]{1,2})\s*(?P<separator>[-/])\s*"
    r"(?P<month>[0-9]{1,2}|[A-Z]{3,10})\s*(?P=separator)\s*(?P<year>[0-9]{4})"
    r"|(?P<word_day>[0-9]{1,2})\s+(?:DE\s+)?"
    r"(?P<word_month>[A-Z]{3,10})\s+(?:DE\s+)?(?P<word_year>[0-9]{4})"
    r")(?![0-9A-Z/-])|(?P<iso_timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2})(?=T[0-9]{2}:)"
)
MONTHS = {
    "ENE": 1, "ENERO": 1, "FEB": 2, "FEBRERO": 2,
    "MAR": 3, "MARZO": 3, "ABR": 4, "ABRIL": 4,
    "MAY": 5, "MAYO": 5, "JUN": 6, "JUNIO": 6,
    "JUL": 7, "JULIO": 7, "AGO": 8, "AGOSTO": 8,
    "SEP": 9, "SEPT": 9, "SET": 9, "SEPTIEMBRE": 9, "SETIEMBRE": 9,
    "OCT": 10, "OCTUBRE": 10, "NOV": 11, "NOVIEMBRE": 11,
    "DIC": 12, "DICIEMBRE": 12,
}


def _extract_invoice_date(normalized):
    """Keep the printed calendar date; never use certification/due dates."""
    dates = set()
    for label in DATE_LABEL_PATTERN.finditer(normalized):
        match = DATE_PATTERN.match(normalized, label.end())
        if not match:
            return None
        try:
            if match["iso_timestamp"]:
                parsed = date.fromisoformat(match["iso_timestamp"])
            elif match["iso_year"]:
                parsed = date(int(match["iso_year"]), int(match["iso_month"]), int(match["iso_day"]))
            else:
                month = match["month"] or match["word_month"]
                month_number = int(month) if month.isdigit() else MONTHS[month]
                parsed = date(
                    int(match["year"] or match["word_year"]),
                    month_number,
                    int(match["day"] or match["word_day"]),
                )
        except (KeyError, ValueError):
            return None
        dates.add(parsed)
    if len(dates) == 1:
        return dates.pop().isoformat()
    return None


def extract_fel_identifiers(text):
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(char)
    ).upper()
    series = set(SERIES_PATTERN.findall(normalized))
    numbers = set(NUMBER_PATTERN.findall(normalized))
    # Repeated page headers are fine; distinct invoices or references are not.
    if len(series) != 1 or len(numbers) != 1:
        return {}
    values = {"fel_serie": series.pop(), "fel_numero": numbers.pop()}
    invoice_date = _extract_invoice_date(normalized)
    if invoice_date:
        values["invoice_date"] = invoice_date
    return values


def extract_from_pdf(raw, reader_class):
    if not raw or not raw.startswith(b"%PDF-"):
        return {}
    if len(raw) > MAX_PDF_BYTES:
        return {}
    reader = reader_class(BytesIO(raw), strict=False)
    if getattr(reader, "is_encrypted", False):
        return {}
    if len(reader.pages) > MAX_PDF_PAGES:
        return {}
    pages = []
    text_length = 0
    for page in reader.pages:
        extract = getattr(page, "extract_text", None) or page.extractText
        text = extract() or ""
        text_length += len(text)
        if text_length > MAX_TEXT_CHARS:
            return {}
        pages.append(text)
    return extract_fel_identifiers("\n".join(pages))


def missing_fel_values(existing, detected):
    """Never combine a new identifier with a conflicting existing one."""
    if not all(detected.get(key) for key in ("fel_serie", "fel_numero")):
        return {}
    for key in ("fel_serie", "fel_numero"):
        value = detected[key]
        current = existing.get(key)
        if current and str(current).strip().upper() != value:
            return {}
    # An existing invoice date can have been entered manually or by Odoo OCR.
    # Preserve it without blocking the completion of matching FEL identifiers.
    return {
        key: detected[key] for key in ("fel_serie", "fel_numero", "invoice_date")
        if detected.get(key) and not existing.get(key)
    }
