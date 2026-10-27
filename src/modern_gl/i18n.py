"""Interface language. Source strings in code are Russian and double as translation keys.

    tr("строка {line}: нулевая сумма", line=3)

A text the program writes into a company's documents (a posting's «Комиссия банка») is
`trd(...)`: in the company's language of documents (D152), whatever the interface is —
switched, it would make every document of a module look changed to a rebuild.

Missing translations fall back to Russian; tests/test_i18n.py checks none are missing.
"""

from __future__ import annotations

from modern_gl.i18n_az import AZ

LANGUAGES = {"az": "Azərbaycanca", "ru": "Русский"}
DEFAULT = "az"
_CATALOGS: dict[str, dict[str, str]] = {"az": AZ, "ru": {}}
_current = DEFAULT
_document: str | None = None  # the open company's language of documents; None — interface


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"unknown language {code!r}")
    _current = code


def language() -> str:
    return _current


def tr(source: str, /, **values) -> str:
    return _translate(_current, source, values)


def set_document_language(code: str | None) -> None:
    """The open company's language of documents (application.document_language)."""
    global _document
    if code is not None and code not in LANGUAGES:
        raise ValueError(f"unknown language {code!r}")
    _document = code


def document_language() -> str:
    return _document or _current


def trd(source: str, /, **values) -> str:
    """A text written into a document: in the company's language of documents."""
    return _translate(document_language(), source, values)


def _translate(code: str, source: str, values: dict) -> str:
    template = _CATALOGS[code].get(source, source)
    return template.format(**values) if values else template


_FOLD = str.maketrans(
    {
        "ı": "i",
        "ş": "s",
        "ç": "c",
        "ə": "e",
        "ö": "o",
        "ü": "u",
        "ğ": "g",
        "ё": "е",
        chr(0x307): None,
    }  # 0x307: dot left by casefold("İ")
)


def fold(text: str) -> str:
    """Search form: case-insensitive, and 'işçi' == 'isci' for keyboards without AZ letters."""
    return text.replace("İ", "i").replace("I", "i").casefold().translate(_FOLD)


def upper(text: str) -> str:
    """Capitals of the interface language: in Azerbaijani i -> İ (and ı -> I)."""
    return (text.replace("i", "İ") if _current == "az" else text).upper()


AZ_ALPHABET = "abcçdeəfgğhxıijkqlmnoöprsştuüvyz"
_AZ_ORDER = {ch: i for i, ch in enumerate(AZ_ALPHABET)}


def sort_key(text: str) -> tuple[int, ...]:
    """Alphabetical order that knows Azerbaijani letters (Ə after E, Ş after S, İ / I…).
    Other characters (digits, Cyrillic) keep their natural order after/among them."""
    lowered = text.replace("I", "ı").replace("İ", "i").lower()
    return tuple(_AZ_ORDER[ch] if ch in _AZ_ORDER else 100 + ord(ch) for ch in lowered)
