"""A bank's statement file in the bank module: what each line is, which bank account it
is of, what the books know already, and whether it can be posted unseen.

What a line is — by its other side: the company's own account (a transfer, or a
conversion when the currencies differ), the bank itself (its fee, salary to the cards),
the State Treasury (taxes; the ƏDV deposit account — the ƏDV of a supplier's e-qaimə),
anyone else — a supplier (money out) or a customer (money in).

Posted unseen is only what is sure: a fee, a transfer, a payment whose e-qaimə the
counterparty has unpaid and which it does not exceed. Anything else is a draft and says
why — no number, a number not found, more than owed, a new counterparty (the user
agreed: "в любом случае нужен review")."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from modern_gl.application.bank.deposit_import import invoices_in
from modern_gl.application.bank.files import BankFile, FileLine
from modern_gl.application.bank.operations import (
    CUSTOMER,
    FEE,
    IN,
    OTHER,
    OUT,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
)
from modern_gl.application.bank.places import BankPlace, bank_places
from modern_gl.application.invoices import open_invoices
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection

CONVERSION = "conversion"  # a line's kind: to or from the company's account in another currency
TREASURY = "CTRE"  # the State Treasury's code in an IBAN: the budget
# the ƏDV deposit accounts' account at the Treasury (the IBAN without its check digits)
VAT_DEPOSITS = "CTRE00000000000000014001"
# words of a purpose, folded (`i18n.fold`): the bank's fee, salary to the cards, a POS
FEE_WORDS = ("xidmet haqqi", "abune haqqi", "konvertasiya")
SALARY_WORDS = ("emek haqqi", "amak haqqi")
POS_WORDS = ("pos-terminal", "pos terminal")
BUDGET_CODE = re.compile(r"^(\d{7})\d{4}")  # «41211112026 IYUL DSMF»: code, then the year


@dataclass(frozen=True)
class FileOperation:
    """A line of a file and what it is: `kind` (SUPPLIER… or CONVERSION), the company's
    other account of a transfer or a conversion (`target`; None — not known), the ƏDV to
    a supplier's deposit (`pays_vat`), the e-qaimə its purpose names; `fees` — the bank's
    fee lines of a conversion, taken into it."""

    line: FileLine
    place: BankPlace
    kind: str
    target: BankPlace | None = None
    pays_vat: bool = False
    fees: tuple[FileLine, ...] = ()

    @property
    def day(self) -> str:
        return self.line.day

    @property
    def direction(self) -> str:
        return IN if self.line.amount > 0 else OUT

    @property
    def amount(self) -> int:
        return abs(self.line.amount)

    @property
    def net(self) -> int:
        return self.line.amount

    @property
    def tin(self) -> str:
        return self.line.tin

    @property
    def name(self) -> str:
        return self.line.name

    @property
    def memo(self) -> str:
        return self.line.memo

    @property
    def reference(self) -> str:
        return self.line.reference

    @property
    def invoices(self) -> tuple[tuple[str, int | None], ...]:
        return tuple((number, None) for number in invoices_in(self.line.memo))


def iban_places(conn: Connection, company_id: int) -> dict[str, BankPlace]:
    """IBAN -> the company's bank account it is of (as its details say)."""
    places = {p.key: p for p in bank_places(conn, company_id)}
    found = {}
    for r in conn.execute(
        "SELECT account_id, value_id, iban FROM bank_account_details "
        "WHERE company_id = ? AND iban <> ''",
        (company_id,),
    ):
        place = places.get((r["account_id"], r["value_id"]))
        if place is not None:
            found[r["iban"]] = place
    return found


def account_choices(conn: Connection, company_id: int, currency: str) -> list[BankPlace]:
    """The bank accounts a file in `currency` can be loaded into: of that currency (a
    manat account has none of its own), not the ƏDV deposit account."""
    base = conn.execute("SELECT base_currency FROM companies WHERE id = ?", (company_id,))
    manat = base.fetchone()["base_currency"]
    return [
        p
        for p in bank_places(conn, company_id)
        if p.account_type != "vat_deposit" and (p.currency or manat) == currency
    ]


def file_operations(
    files: Sequence[BankFile], places: Mapping[str, BankPlace], own_tin: str
) -> list[FileOperation]:
    """The lines of the files that have a bank account (`places`: IBAN -> account), each
    with what it is, in the order of the files; a conversion's fee lines go into it."""
    found: list[FileOperation] = []
    for file in files:
        place = places.get(file.iban)
        if place is None:
            continue
        ops = [_operation(line, file, place, places, own_tin) for line in file.lines]
        groups = {op.line.group for op in ops if op.kind == CONVERSION}
        fees = [op for op in ops if op.kind == FEE and op.line.group in groups]
        for op in ops:
            if op in fees:
                continue
            if op.kind == CONVERSION:
                taken = tuple(f.line for f in fees if f.line.group == op.line.group)
                found.append(FileOperation(op.line, op.place, op.kind, op.target, fees=taken))
            else:
                found.append(op)
    return found


def _operation(
    line: FileLine,
    file: BankFile,
    place: BankPlace,
    places: Mapping[str, BankPlace],
    own_tin: str,
) -> FileOperation:
    words = fold(line.memo)
    out = line.amount < 0
    if line.iban in places or (own_tin and line.tin == own_tin):
        target = places.get(line.iban)
        if target is not None and target.currency_id != place.currency_id:
            return FileOperation(line, place, CONVERSION, target)
        return FileOperation(line, place, TRANSFER, target)
    if line.tin == file.bank_tin:
        if out and any(w in words for w in FEE_WORDS):
            return FileOperation(line, place, FEE)
        if out and any(w in words for w in SALARY_WORDS):
            return FileOperation(line, place, SALARY)
        return FileOperation(line, place, OTHER)  # paid through the bank, money from it
    if line.iban[4:] == VAT_DEPOSITS:
        return FileOperation(line, place, SUPPLIER if out else CUSTOMER, pays_vat=True)
    if line.iban[4:8] == TREASURY:
        return FileOperation(line, place, TAX)
    if any(w in words for w in POS_WORDS):
        return FileOperation(line, place, OTHER)  # cards paid: the shop's takings
    return FileOperation(line, place, SUPPLIER if out else CUSTOMER)


def known_references(conn: Connection, company_id: int) -> set[str]:
    """The statement references the books have: of bank operations and conversions."""
    return {
        r[0]
        for r in conn.execute(
            "SELECT reference FROM bank_operations WHERE company_id = :c AND reference <> '' "
            "UNION SELECT from_reference FROM currency_conversions "
            "WHERE company_id = :c AND from_reference <> '' "
            "UNION SELECT to_reference FROM currency_conversions "
            "WHERE company_id = :c AND to_reference <> ''",
            {"c": company_id},
        )
    }


def payment_check(
    conn: Connection, company_id: int, op: FileOperation, counterparty: int | None, new: bool
) -> tuple[tuple[tuple[str, int | None], ...], str]:
    """The e-qaimə a supplier's (customer's) payment pays, with what each still owes —
    for `payment_lines` — and why it is not posted unseen ("" — it is): the numbers the
    purpose names, all unpaid and not exceeded; no number — the unpaid ones, oldest first,
    as a suggestion. The ƏDV to a deposit is checked against the ƏDV still owed."""
    why = tr("новый контрагент — проверьте") if new or counterparty is None else ""
    unpaid = (
        open_invoices(conn, company_id, counterparty, op.direction == OUT, op.day)
        if counterparty is not None
        else []
    )
    owed = {i.invoice: (i.vat if op.pays_vat else i.amount) for i in unpaid}
    named = [number for number, _ in op.invoices]
    if named:
        missing = [n for n in named if n not in owed]
        if missing:
            return tuple((n, None) for n in named), why or tr(
                "e-qaimə {n} нет среди неоплаченных у контрагента", n=missing[0]
            )
        invoices = tuple((n, owed[n]) for n in named)
        total = sum(owed[n] for n in named)
        if op.amount > total:
            return invoices, why or tr(
                "сумма больше долга по e-qaimə на {diff}", diff=format_minor(op.amount - total)
            )
        return invoices, why
    suggested = tuple((n, still) for n, still in owed.items() if still > 0)
    if suggested:
        return suggested, why or tr("в назначении нет e-qaimə — разложено по старым")
    return (), why or tr("в назначении нет e-qaimə и долга нет — аванс?")


def budget_code(memo: str) -> str:
    """The budget classification code a tax payment begins with ("" — none)."""
    found = BUDGET_CODE.match(memo)
    return found.group(1) if found else ""


def tax_lines_before(conn: Connection, company_id: int, code: str) -> list[BankLine]:
    """What a tax with this budget code was paid to last time from the bank: the account
    and subconto of the latest posted tax operation whose purpose begins with the code (a
    draft's account is only a guess)."""
    if not code:
        return []
    row = conn.execute(
        "SELECT l.account_id, l.sc1, l.sc2, l.sc3 FROM bank_operations o "
        "JOIN documents d ON d.id = o.document_id AND d.status = 'posted' "
        "JOIN bank_operation_lines l ON l.operation_id = o.id AND l.account_id IS NOT NULL "
        "WHERE o.company_id = ? AND o.kind = ? AND o.direction = ? AND d.memo LIKE ? "
        "ORDER BY d.doc_date DESC, d.number DESC, l.line_no LIMIT 1",
        (company_id, TAX, OUT, f"{code}%"),
    ).fetchone()
    if row is None:
        return []
    return [BankLine(row["account_id"], 0, (row["sc1"], row["sc2"], row["sc3"]))]
