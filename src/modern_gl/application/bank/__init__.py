"""The bank (D47, D78): bank accounts and their statements, operations in and out, advances,
the ƏDV deposit account from the portal (D112), bank statement files (`files` — a module
per bank's form). Reading — `accounts`, `operations`, `statement(s)`, `places`,
`advances`, `deposit_*`, `file_import`; writing — `BankModule`, one object over the
ledger's connection (`ledger.bank`), assembled from `commands`, `account_commands`,
`import_commands`, `deposit_commands`, `file_commands`. Amounts are minor units of the
operation's currency (None = manat); the statement is read from postings, so every
document on the account is in it."""

from __future__ import annotations

from modern_gl.application.bank.accounts import (
    ACCOUNT_KINDS,
    CARD,
    CURRENCY,
    CURRENT,
    VAT_DEPOSIT,
    BankAccount,
    bank_accounts,
    default_kind,
)
from modern_gl.application.bank.advances import (
    SETTLES,
    AdvanceOffset,
    counterparty_balance,
    payment_lines,
)
from modern_gl.application.bank.check_commands import BankCheckCommands
from modern_gl.application.bank.deposit_commands import VatDepositCommands
from modern_gl.application.bank.file_commands import BankFileCommands
from modern_gl.application.bank.operations import (
    BANK_TYPES,
    CUSTOMER,
    FEE,
    IN,
    KIND_NAMES,
    KIND_TYPES,
    KINDS,
    OTHER,
    OUT,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    TYPE_KINDS,
    VAT_DEPOSIT_KINDS,
    BankLine,
    BankOperation,
    BankOperationInput,
    allocate,
    default_memo,
    find_bank_operation,
    kind_of_account,
    last_lines,
    latest_direction,
    load_bank_operation,
    load_bank_operations,
    next_to_check,
    split_by_deposit,
    vat_deposit_part,
)
from modern_gl.application.bank.places import (
    BankPlace,
    bank_places,
    transfer_targets,
)
from modern_gl.application.bank.statement import (
    Statement,
    StatementLine,
    place_balance,
    statement,
)
from modern_gl.application.bank.statements import (
    DIFF,
    OK,
    OPEN,
    BankStatement,
    bank_statements,
)


class BankModule(VatDepositCommands, BankFileCommands, BankCheckCommands):
    """The bank's write scenarios (D47, D78, D112, D146): one object per ledger,
    `ledger.bank`."""


__all__ = [
    "ACCOUNT_KINDS",
    "BANK_TYPES",
    "CARD",
    "CURRENCY",
    "CURRENT",
    "CUSTOMER",
    "DIFF",
    "FEE",
    "IN",
    "KINDS",
    "KIND_NAMES",
    "KIND_TYPES",
    "OK",
    "OPEN",
    "OTHER",
    "OUT",
    "SALARY",
    "SETTLES",
    "SUPPLIER",
    "TAX",
    "TRANSFER",
    "TYPE_KINDS",
    "VAT_DEPOSIT",
    "VAT_DEPOSIT_KINDS",
    "AdvanceOffset",
    "BankAccount",
    "BankLine",
    "BankModule",
    "BankOperation",
    "BankOperationInput",
    "BankPlace",
    "BankStatement",
    "Statement",
    "StatementLine",
    "allocate",
    "bank_accounts",
    "bank_places",
    "bank_statements",
    "counterparty_balance",
    "default_kind",
    "default_memo",
    "find_bank_operation",
    "kind_of_account",
    "last_lines",
    "latest_direction",
    "load_bank_operation",
    "load_bank_operations",
    "next_to_check",
    "payment_lines",
    "place_balance",
    "split_by_deposit",
    "statement",
    "transfer_targets",
    "vat_deposit_part",
]
