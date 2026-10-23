"""Write-side use cases: companies, chart of accounts, subconto, documents, posting.

All accounting rules live here (and are mirrored by DB constraints as defense in depth).
UI and importers call these methods; they never write ledger tables directly.
"""

from __future__ import annotations

from functools import cached_property

from modern_gl.application.ledger.account_form import AccountForm, AccountFormCommands
from modern_gl.application.ledger.bank_deposit import VatDepositCommands
from modern_gl.application.ledger.companies import CompanyCommands
from modern_gl.application.ledger.conversion import ConversionCommands
from modern_gl.application.ledger.currencies import CurrencyCommands
from modern_gl.application.ledger.document_import import DocumentImportCommands
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.eqaime import EqaimeCommands
from modern_gl.application.ledger.inputs import (
    DEFAULT_LAYERS,
    SIDES,
    ImportedDocument,
    ImportOutcome,
    PostingInput,
    TemplateLine,
)
from modern_gl.application.ledger.opening import OpeningBalanceCommands, opening_posting
from modern_gl.application.ledger.revaluation import RevaluationCommands
from modern_gl.application.ledger.subconto_details import (
    NO_TAX,
    SubcontoDetailCommands,
    ValueDetails,
)
from modern_gl.application.ledger.templates import TemplateCommands

__all__ = [
    "DEFAULT_LAYERS",
    "NO_TAX",
    "SIDES",
    "AccountForm",
    "BankModule",
    "ConversionModule",
    "EqaimeModule",
    "ImportOutcome",
    "ImportedDocument",
    "Ledger",
    "PostingInput",
    "TemplateLine",
    "ValueDetails",
    "opening_posting",
]


class BankModule(VatDepositCommands):
    """The bank (D47, D78): bank accounts, statements, operations, advances, the ƏDV
    deposit account from the portal (D110)."""


class ConversionModule(ConversionCommands):
    """Currency conversion (D44)."""


class EqaimeModule(EqaimeCommands):
    """E-qaimə of the portal: what it showed, and what was reconciled (D52)."""


class Ledger(
    CompanyCommands,
    CurrencyCommands,
    OpeningBalanceCommands,
    AccountFormCommands,
    TemplateCommands,
    DocumentImportCommands,
    RevaluationCommands,
    DocumentCommands,
    SubcontoDetailCommands,
):
    """The core's write use cases of one database (each group in its own module). The
    modules are objects of their own over the same connection — `ledger.bank`,
    `ledger.conversion`, `ledger.eqaime` (debt 2, D71): the core knows none of them, and
    a module can be left out of a company without touching the core."""

    @cached_property
    def bank(self) -> BankModule:
        return BankModule(self.conn, self.actor)

    @cached_property
    def conversion(self) -> ConversionModule:
        return ConversionModule(self.conn, self.actor)

    @cached_property
    def eqaime(self) -> EqaimeModule:
        return EqaimeModule(self.conn, self.actor)
