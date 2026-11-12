"""E-qaimə numbers: the electronic invoices of the tax portal (e-taxes.gov.az)."""

from __future__ import annotations

from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr

MAX_LENGTH = 40
MARK = "№"  # in the quick entry line: «… 1180 №MT2410123456 Оплата»
# What the number is: an e-qaimə (""), or the customs declaration of imported goods.
EQAIME, CUSTOMS = "", "customs"
KINDS = (EQAIME, CUSTOMS)


NOTE_LENGTH = 80


def basis_note(text: str | None) -> str | None:
    """The basis «Digər» as typed («Akt №5, 03.11»): free text, spaces trimmed; None for
    an empty text."""
    note = " ".join((text or "").split())
    if not note:
        return None
    if len(note) > NOTE_LENGTH:
        raise ValidationError(tr("основание длиннее {n} знаков: {text}", n=NOTE_LENGTH, text=note))
    return note


def normalize_invoice(text: str | None) -> str | None:
    """The number as the portal writes it: no spaces, upper case ("mt 2410 123" ->
    "MT2410123"); None for an empty text. A leading "№" is dropped."""
    number = "".join((text or "").split()).removeprefix(MARK).upper()
    if not number:
        return None
    if len(number) > MAX_LENGTH:
        raise ValidationError(
            tr("номер e-qaimə длиннее {n} знаков: {text}", n=MAX_LENGTH, text=number)
        )
    return number
