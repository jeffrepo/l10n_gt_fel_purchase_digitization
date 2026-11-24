"""Read explicitly labelled FEL identifiers, without guessing from a UUID."""

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
    return {"fel_serie": series.pop(), "fel_numero": numbers.pop()}


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
    for key, value in detected.items():
        current = existing.get(key)
        if current and str(current).strip().upper() != value:
            return {}
    return {key: value for key, value in detected.items() if not existing.get(key)}
