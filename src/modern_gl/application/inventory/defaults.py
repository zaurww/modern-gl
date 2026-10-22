"""What a new warehouse document starts with (debt 9): its VAT rate, and a line's VAT
following its amount — rules, not the window's."""

from __future__ import annotations

from modern_gl.application.inventory.amounts import vat_of
from modern_gl.application.inventory.model import STANDARD_VAT_RATE, VAT_DOCUMENTS
from modern_gl.application.ledger import Ledger
from modern_gl.domain.accounts import INPUT_VAT, OUTPUT_VAT


def default_vat_rate(ledger: Ledger, company_id: int, doc_type: str) -> int | None:
    """A new receipt (sale) has the standard VAT when the company has an account to post
    its VAT to; else none."""
    if doc_type not in VAT_DOCUMENTS:
        return None
    role = OUTPUT_VAT if doc_type == "sale" else INPUT_VAT
    return STANDARD_VAT_RATE if ledger.account_role(company_id, role) is not None else None


def line_vat(doc_type: str, amount: int | None, rate: int | None) -> int | None:
    """A line's VAT from its amount and the document's rate (until typed by hand); None:
    no VAT on such a document, or nothing to take it from."""
    if doc_type not in VAT_DOCUMENTS or amount is None or rate is None:
        return None
    return vat_of(amount, rate)
