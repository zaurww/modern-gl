"""VÖEN — the tax number of an Azerbaijani taxpayer."""

from __future__ import annotations

from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr


def resident_tax_id(text: str | None) -> str | None:
    """A resident's VÖEN as typed: 10 digits, spaces dropped; None for an empty text."""
    tax_id = "".join((text or "").split()) or None
    if tax_id is not None and not (tax_id.isdigit() and len(tax_id) == 10):
        raise ValidationError(tr("VÖEN — 10 цифр, а не «{text}»", text=tax_id))
    return tax_id
