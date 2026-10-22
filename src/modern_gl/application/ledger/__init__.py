"""Write-side use cases: companies, chart of accounts, subconto, documents, posting.

All accounting rules live here (and are mirrored by DB constraints as defense in depth).
UI and importers call these methods; they never write ledger tables directly.
"""

from __future__ import annotations

from modern_gl.application.ledger.account_form import AccountForm, AccountFormCommands
from modern_gl.application.ledger.bank import BankCommands
from modern_gl.application.ledger.bank_statements import BankStatementCommands
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
    BankCommands,
    BankStatementCommands,
    ConversionCommands,
    EqaimeCommands,
    OpeningBalanceCommands,
    AccountFormCommands,
    TemplateCommands,
    DocumentImportCommands,
    RevaluationCommands,
    DocumentCommands,
    SubcontoDetailCommands,
):
    """All write use cases of one database; each group lives in its own module."""
