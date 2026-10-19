"""Interface language. Source strings in code are Russian and double as translation keys.

    tr("строка {line}: нулевая сумма", line=3)

Missing translations fall back to Russian; tests/test_i18n.py checks none are missing.
"""

from __future__ import annotations

from modern_gl.i18n_az import AZ

LANGUAGES = {"az": "Azərbaycanca", "ru": "Русский"}
DEFAULT = "az"
_CATALOGS: dict[str, dict[str, str]] = {"az": AZ, "ru": {}}
_current = DEFAULT


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"unknown language {code!r}")
    _current = code


def language() -> str:
    return _current


def tr(source: str, /, **values) -> str:
    template = _CATALOGS[_current].get(source, source)
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
