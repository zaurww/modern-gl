"""Which postings of an invoice number count, and as what (D120) — one rule for the e-qaimə
report (`invoices.py`) and the reconciliation with the portal (`eqaime_reconciliation.py`).

A settlement account is one of a settlement type, or one without a type but with the
counterparty directory. On a number:

- the turnover of the settlement accounts is everything they post, the accrual and the
  payment (an advance set against it is paid by the settlement side only) — what is left
  to pay; the ƏDV is every line on an ƏDV account. The e-qaimə report counts so, customs
  declarations too;
- the accrual is the e-qaimə itself: a settlement account against anything but money or
  another settlement (Dt 41 / Kt 60, Dt 62 / Kt 46); its ƏDV — an ƏDV account against
  anything but money or ƏDV (Dt 19 / Kt 60, Dt 46 / Kt 68.2; not Dt 68.2 / Kt 51). The
  reconciliation counts so, e-qaimə only: the portal has no customs declarations.
"""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.domain.accounts import SETTLEMENT_TYPES, VAT_TYPES
from modern_gl.infrastructure.db import Connection

MONEY_TYPES = frozenset({"cash", "bank", "vat_deposit"})
ADVANCE_TYPES = frozenset({"advance_paid", "advance_received"})


@dataclass(frozen=True)
class InvoiceAccount:
    """What an account is to an invoice: its type and the positions of its counterparty
    and contract (1–3, None: not on it)."""

    account_type: str | None
    partner_at: int | None
    contract_at: int | None

    @property
    def settlement(self) -> bool:
        kind = self.account_type
        return kind in SETTLEMENT_TYPES or (kind is None and self.partner_at is not None)

    @property
    def money(self) -> bool:
        return self.account_type in MONEY_TYPES

    @property
    def vat(self) -> bool:
        return self.account_type in VAT_TYPES


def invoice_accounts(conn: Connection, company_id: int) -> dict[int, InvoiceAccount]:
    """Every account of the company, by id, as an invoice sees it."""
    kinds = {
        r["code"]: r["id"]
        for r in conn.execute(
            "SELECT id, code FROM subconto_kinds WHERE company_id = ? "
            "AND code IN ('counterparty', 'contract')",
            (company_id,),
        )
    }

    def at(row, kind: int | None) -> int | None:
        if kind is None:
            return None
        return next((i for i in (1, 2, 3) if row[f"sc{i}_kind_id"] == kind), None)

    return {
        r["id"]: InvoiceAccount(
            r["account_type"], at(r, kinds.get("counterparty")), at(r, kinds.get("contract"))
        )
        for r in conn.execute(
            "SELECT id, account_type, sc1_kind_id, sc2_kind_id, sc3_kind_id "
            "FROM accounts WHERE company_id = ?",
            (company_id,),
        )
    }


def turnover_sides(debit: InvoiceAccount, credit: InvoiceAccount) -> tuple[bool, bool]:
    """Whether the debit and the credit of a posting are a settlement turnover. An advance
    set against the e-qaimə (D78: Dt 60.1 [e-qaimə] / Ct 60.2): only the settlement side
    pays it, the advance side is no turnover of the e-qaimə."""
    types = {debit.account_type, credit.account_type}
    offset = bool(types & ADVANCE_TYPES) and bool(types & {"payable", "receivable"})

    def counts(side: InvoiceAccount) -> bool:
        return side.settlement and not (offset and side.account_type in ADVANCE_TYPES)

    return counts(debit), counts(credit)


def is_accrual(side: InvoiceAccount, other: InvoiceAccount) -> bool:
    """The settlement `side` accrues the e-qaimə: against anything but money or another
    settlement (a payment or an offset carries the number, but is not its amount)."""
    return side.settlement and not other.settlement and not other.money


def is_vat_accrual(tax: InvoiceAccount, against: InvoiceAccount) -> bool:
    """The ƏDV of the e-qaimə: an ƏDV account against anything but money or ƏDV (paying
    it to the budget is not)."""
    return tax.vat and not against.money and not against.vat
