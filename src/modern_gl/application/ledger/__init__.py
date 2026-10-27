"""Write-side use cases: companies, chart of accounts, subconto, documents, posting.

All accounting rules live here (and are mirrored by DB constraints as defense in depth).
UI and importers call these methods; they never write ledger tables directly.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from modern_gl.application.ledger.account_form import AccountForm, AccountFormCommands
from modern_gl.application.ledger.companies import CompanyCommands
from modern_gl.application.ledger.currencies import CurrencyCommands
from modern_gl.application.ledger.document_import import DocumentImportCommands
from modern_gl.application.ledger.documents import DocumentCommands
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

if TYPE_CHECKING:
    from modern_gl.application.bank import BankModule
    from modern_gl.application.conversion import ConversionModule
    from modern_gl.application.eqaime import EqaimeModule

__all__ = [
    "DEFAULT_LAYERS",
    "NO_TAX",
    "SIDES",
    "AccountForm",
    "ImportOutcome",
    "ImportedDocument",
    "Ledger",
    "PostingInput",
    "TemplateLine",
    "ValueDetails",
    "opening_posting",
]


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
    a module can be left out of a company without touching the core. A module holds the
    ledger and calls it (`ledger/module.py`, D-new); it is not the ledger."""

    @cached_property
    def bank(self) -> BankModule:
        """The bank module (statements, operations, ƏDV deposit) over this ledger."""
        from modern_gl.application.bank import BankModule

        return BankModule(self.conn, self.actor, ledger=self)

    @cached_property
    def conversion(self) -> ConversionModule:
        """The currency conversion module over this ledger."""
        from modern_gl.application.conversion import ConversionModule

        return ConversionModule(self.conn, self.actor, ledger=self)

    @cached_property
    def eqaime(self) -> EqaimeModule:
        """The e-qaimə module (portal drafts, invoices) over this ledger."""
        from modern_gl.application.eqaime import EqaimeModule

        return EqaimeModule(self.conn, self.actor, ledger=self)
