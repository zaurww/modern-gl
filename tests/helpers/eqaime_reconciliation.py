"""Shared from test_eqaime_reconciliation.py (moved here: other test modules use it too)."""

from __future__ import annotations

from modern_gl.domain.eqaime import PortalInvoice

ALFA_TIN, BETA_TIN = "1111111111", "2222222222"


def on_portal(
    number: str,
    day: str,
    total: int,
    vat: int,
    status: str = "approved",
    tin: str = ALFA_TIN,
    outgoing: bool = False,
) -> PortalInvoice:
    return PortalInvoice(number, outgoing, day, status, tin, "Alfa MMC", total, vat)
