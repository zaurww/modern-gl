"""«Поступления и e-qaimə»: the money from each buyer set against the e-qaimə issued to
them — a bank statement seldom says which e-qaimə is paid, and one advance may close
several, so the check is by buyer (REPORTING.md, stage 3a). For the period: received to a
bank account or the cash desk (naming an e-qaimə or not) and to the ƏDV deposit, the
e-qaimə issued, the ƏDV owed (D142). At the period's end, from the beginning: an advance
no e-qaimə closes, e-qaimə not paid, and more ƏDV owed than the e-qaimə and the open
advance carry — an advance without a number owes 18% for good, so an e-qaimə without ƏDV
after it, or ƏDV paid to the settlement account with the value, leaves too much owed;
money naming an e-qaimə beyond its value while its ƏDV is short on the deposit is that ƏDV
come to the settlement account too.
Money naming an e-qaimə pays it, and owes no more than its ƏDV (D142); the rest — the
advance — pays the buyer's e-qaimə oldest first, as the bank lays a payment out (D62), and
carries their ƏDV in the share paid; what it leaves open carries the rate. The payments to
suppliers are checked the same way (`reporting/vat_payments`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.book_invoices import BookInvoice, book_invoices
from modern_gl.application.vat import (
    SaleFacts,
    liability_events,
    liability_rule_for,
    payer_from,
    sale_facts,
)
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor, round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

# why a counterparty wants a look
FREE_AFTER_ADVANCE = "free_after_advance"  # a sale: the advance's 18% on an e-qaimə without ƏDV
OWED_BEYOND = "owed_beyond"  # a sale: the advance owes more than its e-qaimə carry
VAT_TO_ACCOUNT = "vat_to_account"  # a sale: the e-qaimə's ƏDV came to the settlement account
NO_NUMBER = "no_number"  # a purchase: paid without its number — its ƏDV is not credited
NOT_TO_DEPOSIT = "not_to_deposit"  # a purchase: paid, but its ƏDV not to the deposit


@dataclass
class ReceiptLine:
    """One e-qaimə of a counterparty, or their money without a number (`invoice` None), in
    the period."""

    invoice: str | None = None
    doc_date: str = ""  # the e-qaimə's day
    document_id: int | None = None  # its first document
    by_invoice: int = 0  # the money naming the e-qaimə, the value
    no_number: int = 0  # the money without a number, the value
    deposit: int = 0  # the money to or from the ƏDV deposit
    amount: int = 0  # the e-qaimə's value, out in the period
    vat: int = 0  # its ƏDV
    tax: int = 0  # the ƏDV of the period by the rule: owed (D142) or credited (D138)

    def add(self, other: ReceiptLine) -> None:
        for name in ("by_invoice", "no_number", "deposit", "amount", "vat", "tax"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def moved(self) -> bool:
        return any((self.by_invoice, self.no_number, self.deposit, self.amount, self.vat))


@dataclass
class Issued:
    """An e-qaimə out by the period's end, from the beginning."""

    day: str
    number: str
    total: int  # with ƏDV
    vat: int
    got: int  # the money naming it, with ƏDV
    credited: int = 0  # a purchase: its ƏDV credited by the period's end
    named: int = 0  # a purchase: its value paid naming it, an advance set against it too
    extra: int = 0  # the advance laid on it (`lay_out`)


@dataclass
class PartyRow(ReceiptLine):
    """A counterparty: the period's figures of their lines; the balances from the
    beginning."""

    counterparty_id: int | None = None
    name: str = ""
    advance: int = 0  # the money beyond the e-qaimə, with ƏDV
    unpaid: int = 0  # the e-qaimə beyond the money
    excess: int = 0  # the ƏDV owed too much, or not credited though paid
    reason: str = ""  # FREE_AFTER_ADVANCE … NOT_TO_DEPOSIT, "" — nothing to look at
    lines: list[ReceiptLine] = field(default_factory=list)
    # from the beginning: the money not naming an e-qaimə out by then, with ƏDV, and the
    # ƏDV it owes (a sale); the e-qaimə out
    free_money: int = 0
    free_tax: int = 0
    issued: list[Issued] = field(default_factory=list)


@dataclass
class VatReceipts:
    parties: list[PartyRow] = field(default_factory=list)
    total: PartyRow = field(default_factory=PartyRow)  # of the period and the balances
    warnings: int = 0
    payer_from: str = ""  # the company pays ƏDV since (D145); "" — all along


class Parties(dict[int | None, PartyRow]):
    """The rows by counterparty, named from the company's subconto."""

    def __init__(self, conn: Connection, company_id: int) -> None:
        super().__init__()
        self.names = {
            r["id"]: r["name"]
            for r in conn.execute(
                "SELECT id, name FROM subconto_values WHERE company_id = ?", (company_id,)
            )
        }

    def of(self, who: int | None) -> PartyRow:
        if who not in self:
            self[who] = PartyRow(counterparty_id=who, name=self.names.get(who or 0, ""))
        return self[who]


def period(date_from: date | str, date_to: date | str) -> tuple[str, str]:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    return date_from, date_to


def vat_receipts(
    conn: Connection, company_id: int, date_from: date | str, date_to: date | str
) -> VatReceipts:
    date_from, date_to = period(date_from, date_to)
    liability_rule_for(date_from)  # a period before the known rules is refused
    rate = liability_rule_for(date_to).rate
    sales = book_invoices(conn, company_id, outgoing=True)
    parties = Parties(conn, company_id)
    since = payer_from(conn, company_id)
    numbers = set()
    for facts in sale_facts(conn, company_id, date_to):
        numbers.add(facts.invoice)
        row = parties.of(facts.counterparty_id)
        sale = sales.get(facts.invoice) if facts.invoice is not None else None
        line, received = money_line(facts, date_from)
        owed = 0
        for e in liability_events(facts):
            if e.day >= since:  # nothing is owed before the company pays ƏDV
                owed += e.amount
                line.tax += e.amount if e.day >= date_from else 0
        if issue(row, line, sale, received, date_from, date_to):
            assert sale is not None
            if _to_account(facts, sale):
                row.reason = row.reason or VAT_TO_ACCOUNT
        else:
            row.free_money += received
            row.free_tax += owed
        keep(row, line)
    for number, sale in sales.items():
        if number not in numbers:
            line = ReceiptLine(number)
            row = parties.of(sale.parties[0] if sale.parties else None)
            issue(row, line, sale, 0, date_from, date_to)
            keep(row, line)
    return collect(parties, lambda row: _close(row, rate), since)


def money_line(facts: SaleFacts, date_from: str) -> tuple[ReceiptLine, int]:
    """The money of one e-qaimə or of the advance: the line of the period, and the money
    from the beginning with ƏDV."""
    line, money = ReceiptLine(facts.invoice), 0
    for r in facts.receipts:
        money += r.main + r.vat
        if r.day >= date_from:
            if facts.invoice is None:
                line.no_number += r.main
            else:
                line.by_invoice += r.main
            line.deposit += r.vat
    return line, money


def issue(
    row: PartyRow,
    line: ReceiptLine,
    invoice: BookInvoice | None,
    money: int,
    date_from: str,
    date_to: str,
    credited: int = 0,
    named: int = 0,
) -> bool:
    """The e-qaimə of the line, when it is out by the period's end."""
    if invoice is None or invoice.doc_date > date_to:
        return False
    total, vat = invoice.total, invoice.vat
    row.issued.append(
        Issued(invoice.doc_date, invoice.number, total, vat, money, credited, named=named)
    )
    line.doc_date = invoice.doc_date
    line.document_id = invoice.documents[0][0] if invoice.documents else None
    if invoice.doc_date >= date_from:
        line.amount, line.vat = invoice.amount, invoice.vat
    return True


def keep(row: PartyRow, line: ReceiptLine) -> None:
    if line.moved or line.tax:
        row.lines.append(line)
        row.add(line)


def collect(parties: Parties, close: Callable[[PartyRow], None], since: str = "") -> VatReceipts:
    """The rows with something in the period or open at its end, by name; the total."""
    result = VatReceipts(payer_from=since)
    for row in sorted(parties.values(), key=lambda b: (b.name == "", b.name)):
        lay_out(row)
        close(row)
        if row.lines or row.advance or row.unpaid or row.excess or row.reason:
            row.lines.sort(key=lambda ln: (ln.invoice is None, ln.doc_date, ln.invoice or ""))
            result.parties.append(row)
            result.total.add(row)
            result.total.advance += row.advance
            result.total.unpaid += row.unpaid
            result.total.excess += row.excess
            result.warnings += bool(row.reason)
    return result


def lay_out(row: PartyRow) -> None:
    """The money naming an e-qaimə pays it; the rest — and what names one beyond it, or a
    refund beyond what came — pays the e-qaimə oldest first (`Issued.extra`); what is
    left is the advance."""
    issued = sorted(row.issued, key=lambda i: (i.day, i.number))
    pool = row.free_money + sum(i.got - min(max(i.got, 0), i.total) for i in issued)
    unpaid = 0
    for i in issued:
        paid = min(max(i.got, 0), i.total)
        i.extra = min(max(pool, 0), i.total - paid)
        pool -= i.extra
        unpaid += i.total - paid - i.extra
    row.advance, row.unpaid = max(pool, 0), unpaid + max(-pool, 0)


def _to_account(facts: SaleFacts, sale: BookInvoice) -> bool:
    """The value received naming the e-qaimə beyond its value, while its ƏDV is short on
    the deposit."""
    main = sum(r.main for r in facts.receipts)
    vat = sum(r.vat for r in facts.receipts)
    return min(max(main - sale.amount, 0), max(sale.vat - vat, 0)) > 0


def _close(row: PartyRow, rate: int) -> None:
    """The advance owing beyond the ƏDV of the e-qaimə it pays and the rate of what it
    leaves open — a warning."""
    carried = sum(round_ratio(i.vat * i.extra, i.total) for i in row.issued if i.total)
    carried += round_ratio(row.advance * rate, 100)
    row.excess = max(row.free_tax - carried, 0)
    if row.excess:
        free = any(i.vat == 0 and i.extra > 0 for i in row.issued)
        row.reason = FREE_AFTER_ADVANCE if free else OWED_BEYOND


def warning(row: PartyRow) -> str | None:
    """Why the counterparty's ƏDV wants a look, or None."""
    x = format_minor(row.excess)
    texts = {
        FREE_AFTER_ADVANCE: tr(
            "ƏDV начислен с аванса, а e-qaimə без ƏDV: начислено лишнее {x}", x=x
        ),
        OWED_BEYOND: tr("ƏDV больше, чем в e-qaimə, на {x}: ƏDV пришёл на расчётный счёт?", x=x),
        VAT_TO_ACCOUNT: tr("ƏDV e-qaimə пришёл на расчётный счёт, не на депозит"),
        NO_NUMBER: tr(
            "ƏDV {x} не зачтён: оплачено без номера e-qaimə — укажите номер в банке", x=x
        ),
        NOT_TO_DEPOSIT: tr("ƏDV {x} не зачтён: оплачено, но ƏDV не перечислен на депозит", x=x),
    }
    return texts.get(row.reason)
