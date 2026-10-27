"""Shared from test_deposit_reconciliation.py (moved here: other test modules use it too)."""

from __future__ import annotations

from modern_gl.application.bank import OUT, TAX, BankLine, BankOperationInput


def fee(ledger, firm, day: str = "2026-10-03", amount: int = 500) -> int:
    place = firm["place"]
    return ledger.bank.save_bank_operation(
        firm["cid"],
        BankOperationInput(
            doc_date=day,
            direction=OUT,
            account_id=place.account_id,
            subconto=place.subconto,
            kind=TAX,
            lines=(BankLine(firm["acc"]["68.2"], amount),),
        ),
        post=True,
    )
