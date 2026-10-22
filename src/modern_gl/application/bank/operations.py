"""What a bank operation is and what was entered (D47): its kinds, lines, loading one,
the lines paid last time, the purpose of payment by default."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

IN, OUT = "in", "out"  # mədaxil: money comes to the bank account; məxaric: it leaves
SUPPLIER, CUSTOMER, TAX, SALARY, FEE, TRANSFER, OTHER = (
    "supplier",
    "customer",
    "tax",
    "salary",
    "fee",
    "transfer",
    "other",
)
# what an operation is (Russian name — a translation key); the order of the form's list
KINDS = (
    (SUPPLIER, "Поставщик"),
    (CUSTOMER, "Покупатель"),
    (TAX, "Налоги"),
    (SALARY, "Зарплата"),
    (FEE, "Комиссия банка"),
    (TRANSFER, "Перевод между своими счетами"),
    (OTHER, "Прочее"),
)
KIND_NAMES = dict(KINDS)
# A line's account when nothing was paid to the counterparty before: the first account
# of the type (60, 62, 68.1, 70; another bank account for a transfer). A bank fee goes to
# the account of the settings (role bank_fee).
KIND_TYPES = {
    SUPPLIER: "payable",
    CUSTOMER: "receivable",
    TAX: "tax_payable",
    SALARY: "payroll",
    TRANSFER: "bank",
}
# Bank accounts of the module: money on current accounts, and the ƏDV deposit account
BANK_TYPES = ("bank", "vat_deposit")
# The ƏDV deposit account pays and receives only ƏDV (D41): to a supplier's deposit
# account, from a customer, to the budget, or between deposit accounts.
VAT_DEPOSIT_KINDS = (SUPPLIER, CUSTOMER, TAX, TRANSFER)


@dataclass(frozen=True)
class BankLine:
    """Where the money goes (məxaric) or comes from (mədaxil): an account, its subconto
    (a contract, a tax, an employee…) and the e-qaimə the payment closes."""

    account_id: int | None  # None only in a draft
    amount: int  # minor units of the operation's currency; 0 only in a draft
    subconto: Sequence[int | None] = ()
    invoice: str = ""


@dataclass(frozen=True)
class BankOperationInput:
    doc_date: str
    direction: str  # IN or OUT
    account_id: int | None  # the bank account's GL account; None only in a draft
    lines: Sequence[BankLine] = ()
    kind: str = OTHER
    subconto: Sequence[int | None] = ()  # of the bank account (Kapital Bank AZN)
    currency_id: int | None = None  # None: manat
    counterparty_id: int | None = None  # fills the counterparty of every line
    memo: str = ""  # the purpose of payment
    reference: str = ""  # reference of the bank statement line

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines)


@dataclass(frozen=True)
class BankOperation(BankOperationInput):
    id: int = 0
    document_id: int = 0
    number: int = 0
    status: str = "draft"


def load_bank_operation(conn: Connection, company_id: int, operation_id: int) -> BankOperation:
    r = conn.execute(
        "SELECT o.*, d.number, d.doc_date, d.memo, d.status FROM bank_operations o "
        "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
        "WHERE o.company_id = ? AND o.id = ?",
        (company_id, operation_id),
    ).fetchone()
    if r is None:
        raise NotFoundError(tr("документ {id} не найден", id=operation_id))
    lines = tuple(
        BankLine(x["account_id"], x["amount"], (x["sc1"], x["sc2"], x["sc3"]), x["invoice"])
        for x in conn.execute(
            "SELECT * FROM bank_operation_lines WHERE company_id = ? AND operation_id = ? "
            "ORDER BY line_no",
            (company_id, operation_id),
        )
    )
    return BankOperation(
        doc_date=r["doc_date"],
        direction=r["direction"],
        account_id=r["account_id"],
        lines=lines,
        kind=r["kind"],
        subconto=(r["sc1"], r["sc2"], r["sc3"]),
        currency_id=r["currency_id"],
        counterparty_id=r["counterparty_id"],
        memo=r["memo"],
        reference=r["reference"],
        id=r["id"],
        document_id=r["document_id"],
        number=r["number"],
        status=r["status"],
    )


def bank_operation_of_document(conn: Connection, company_id: int, document_id: int) -> int | None:
    """The bank operation whose postings these are."""
    row = conn.execute(
        "SELECT id FROM bank_operations WHERE company_id = ? AND document_id = ?",
        (company_id, document_id),
    ).fetchone()
    return row[0] if row else None


def find_bank_operation(conn: Connection, company_id: int, reference: str) -> int | None:
    """An operation already entered for a bank statement line (future statement import)."""
    reference = reference.strip()
    if not reference:
        return None
    row = conn.execute(
        "SELECT id FROM bank_operations WHERE company_id = ? AND reference = ? ORDER BY id LIMIT 1",
        (company_id, reference),
    ).fetchone()
    return row[0] if row else None


def last_lines(
    conn: Connection, company_id: int, direction: str, counterparty_id: int
) -> list[BankLine]:
    """What the money of this counterparty went to (came from) last time: the accounts and
    subconto of its latest operation of the same direction, without amounts and e-qaimə.
    Payments made through the journal count too: the latest posting between a bank
    account and an account with this counterparty."""
    row = conn.execute(
        "SELECT o.id FROM bank_operations o JOIN documents d ON d.id = o.document_id "
        "WHERE o.company_id = ? AND o.direction = ? AND o.counterparty_id = ? "
        "ORDER BY d.doc_date DESC, d.number DESC LIMIT 1",
        (company_id, direction, counterparty_id),
    ).fetchone()
    if row is not None:
        return [
            BankLine(r["account_id"], 0, (r["sc1"], r["sc2"], r["sc3"]))
            for r in conn.execute(
                "SELECT account_id, sc1, sc2, sc3 FROM bank_operation_lines "
                "WHERE operation_id = ? AND account_id IS NOT NULL ORDER BY line_no",
                (row[0],),
            )
        ]
    # out: the bank account is credited, the counterparty's account debited
    bank_col, other_col, other = (
        ("credit_account_id", "debit_account_id", "dt")
        if direction == OUT
        else ("debit_account_id", "credit_account_id", "ct")
    )
    found = conn.execute(
        f"""
        SELECT p.{other_col} AS account_id, p.{other}_sc1 AS sc1, p.{other}_sc2 AS sc2,
               p.{other}_sc3 AS sc3
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN accounts b ON b.id = p.{bank_col}
        WHERE p.company_id = :c AND b.account_type IN ('bank', 'vat_deposit')
          AND :v IN (p.{other}_sc1, p.{other}_sc2, p.{other}_sc3)
        ORDER BY d.doc_date DESC, d.number DESC, p.line_no LIMIT 1
        """,
        {"c": company_id, "v": counterparty_id},
    ).fetchone()
    if found is None:
        return []
    return [BankLine(found["account_id"], 0, (found["sc1"], found["sc2"], found["sc3"]))]


# ---- bank accounts and their statements -------------------------------------------------


def default_memo(direction: str, kind: str, counterparty: str = "") -> str:
    """The purpose of payment when none is typed: what it is, and to whom."""
    out, name = direction == OUT, counterparty
    if kind == SUPPLIER:
        text = (
            tr("Оплата поставщику {name}", name=name)
            if out
            else tr("Возврат от поставщика {name}", name=name)
        )
    elif kind == CUSTOMER:
        text = (
            tr("Возврат покупателю {name}", name=name)
            if out
            else tr("Оплата от покупателя {name}", name=name)
        )
    elif kind == TAX:
        text = tr("Уплата налогов") if out else tr("Возврат налогов")
    elif kind == SALARY:
        text = tr("Выплата зарплаты") if out else tr("Возврат зарплаты")
    elif kind == FEE:
        text = tr("Комиссия банка") if out else tr("Возврат комиссии банка")
    elif kind == TRANSFER:
        text = tr("Перевод между своими счетами")
    elif name:
        text = tr("Платёж {name}", name=name) if out else tr("Поступление от {name}", name=name)
    else:
        text = tr("Прочий расход") if out else tr("Прочий приход")
    return text.strip()


def allocate(total: int, owed: Sequence[int]) -> tuple[list[int], int]:
    """One payment over several e-qaimə, oldest first: each is paid in full while the
    money lasts, the last one partly. (Per e-qaimə, what is left over.) An overpayment
    is left over: an advance, a line without an e-qaimə."""
    paid = []
    for amount in owed:
        part = min(amount, total)
        paid.append(part)
        total -= part
    return paid, total
