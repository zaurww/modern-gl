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
carries their ƏDV in the share paid; what it leaves open carries the rate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.book_invoices import BookInvoice, book_invoices
from modern_gl.application.vat import SaleFacts, liability_events, liability_rule_for, sale_facts
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


@dataclass
class ReceiptLine:
    """One e-qaimə of a buyer, or their money without a number (`invoice` None), in the
    period."""

    invoice: str | None = None
    doc_date: str = ""  # the e-qaimə's day
    document_id: int | None = None  # its first document
    by_invoice: int = 0  # received naming the e-qaimə, the value
    no_number: int = 0  # received without a number, the value
    deposit: int = 0  # received to the ƏDV deposit
    amount: int = 0  # the e-qaimə's value, issued in the period
    vat: int = 0  # its ƏDV
    owed: int = 0  # the ƏDV owed in the period (D142)

    def add(self, other: ReceiptLine) -> None:
        for name in ("by_invoice", "no_number", "deposit", "amount", "vat", "owed"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def moved(self) -> bool:
        return any((self.by_invoice, self.no_number, self.deposit, self.amount, self.vat))


@dataclass
class BuyerRow(ReceiptLine):
    """A buyer: the period's figures of their lines; the balances from the beginning."""

    counterparty_id: int | None = None
    name: str = ""
    advance: int = 0  # received beyond the e-qaimə issued, with ƏDV
    unpaid: int = 0  # the e-qaimə issued beyond what was received
    excess: int = 0  # the advance's ƏDV owed beyond what the e-qaimə and the rate carry
    free_after_advance: bool = False  # an e-qaimə without ƏDV took the excess
    to_account: int = 0  # the ƏDV of e-qaimə paid with their value, not to the deposit
    lines: list[ReceiptLine] = field(default_factory=list)
    # from the beginning: the money not naming an e-qaimə out by then, with ƏDV, and the
    # ƏDV it owes; each e-qaimə out — (day, number, total, ƏDV, received naming it)
    free_money: int = 0
    free_owed: int = 0
    issued: list[tuple[str, str, int, int, int]] = field(default_factory=list)


@dataclass
class VatReceipts:
    buyers: list[BuyerRow] = field(default_factory=list)
    total: BuyerRow = field(default_factory=BuyerRow)  # of the period and the balances
    warnings: int = 0


def vat_receipts(
    conn: Connection, company_id: int, date_from: date | str, date_to: date | str
) -> VatReceipts:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    liability_rule_for(date_from)  # a period before the known rules is refused
    rate = liability_rule_for(date_to).rate
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values WHERE company_id = ?", (company_id,)
        )
    }
    sales = book_invoices(conn, company_id, outgoing=True)
    buyers: dict[int | None, BuyerRow] = {}

    def buyer(who: int | None) -> BuyerRow:
        name = names.get(who or 0, "")
        return buyers.setdefault(who, BuyerRow(counterparty_id=who, name=name))

    paid_numbers = set()
    for facts in sale_facts(conn, company_id, date_to):
        paid_numbers.add(facts.invoice)
        row = buyer(facts.counterparty_id)
        sale = sales.get(facts.invoice) if facts.invoice is not None else None
        line, received, owed = _receipts(facts, date_from)
        if _issue(row, line, sale, received, date_from, date_to):
            assert sale is not None
            row.to_account += _to_account(facts, sale)
        else:
            row.free_money += received
            row.free_owed += owed
        _keep(row, line)
    for number, sale in sales.items():
        if number not in paid_numbers:
            row = buyer(sale.parties[0] if sale.parties else None)
            line = ReceiptLine(number)
            _issue(row, line, sale, 0, date_from, date_to)
            _keep(row, line)
    result = VatReceipts()
    for row in sorted(buyers.values(), key=lambda b: (b.name == "", b.name)):
        _close(row, rate)
        if row.lines or row.advance or row.unpaid or row.excess or row.to_account:
            row.lines.sort(key=lambda ln: (ln.invoice is None, ln.doc_date, ln.invoice or ""))
            result.buyers.append(row)
            result.total.add(row)
            result.total.advance += row.advance
            result.total.unpaid += row.unpaid
            result.total.excess += row.excess
            result.warnings += bool(row.excess or row.to_account)
    return result


def _receipts(facts: SaleFacts, date_from: str) -> tuple[ReceiptLine, int, int]:
    """The money of one e-qaimə or of the advance and its ƏDV owed (D142): the line of the
    period; received and owed from the beginning."""
    line, received, owed = ReceiptLine(facts.invoice), 0, 0
    for r in facts.receipts:
        received += r.main + r.vat
        if r.day >= date_from:
            if facts.invoice is None:
                line.no_number += r.main
            else:
                line.by_invoice += r.main
            line.deposit += r.vat
    for e in liability_events(facts):
        owed += e.amount
        if e.day >= date_from:
            line.owed += e.amount
    return line, received, owed


def _issue(
    row: BuyerRow,
    line: ReceiptLine,
    sale: BookInvoice | None,
    received: int,
    date_from: str,
    date_to: str,
) -> bool:
    """The e-qaimə of the line, when it is out by the period's end."""
    if sale is None or sale.doc_date > date_to:
        return False
    row.issued.append((sale.doc_date, sale.number, sale.total, sale.vat, received))
    line.doc_date = sale.doc_date
    line.document_id = sale.documents[0][0] if sale.documents else None
    if sale.doc_date >= date_from:
        line.amount, line.vat = sale.amount, sale.vat
    return True


def _to_account(facts: SaleFacts, sale: BookInvoice) -> int:
    """The value received naming the e-qaimə beyond its value, as far as its ƏDV is short
    on the deposit."""
    main = sum(r.main for r in facts.receipts)
    vat = sum(r.vat for r in facts.receipts)
    return min(max(main - sale.amount, 0), max(sale.vat - vat, 0))


def _keep(row: BuyerRow, line: ReceiptLine) -> None:
    if line.moved or line.owed:
        row.lines.append(line)
        row.add(line)


def _close(row: BuyerRow, rate: int) -> None:
    """The balances at the period's end, the advance laid out on the e-qaimə; the advance
    owing beyond the ƏDV it pays and the rate of what is left open — a warning."""
    issued = sorted(row.issued)
    # what names an e-qaimə beyond it, or a refund beyond what came, is the buyer's
    pool = row.free_money + sum(got - min(max(got, 0), t) for _d, _n, t, _v, got in issued)
    carried = unpaid = 0
    free = False
    for _day, _number, total, vat, got in issued:
        paid = min(max(got, 0), total)
        extra = min(max(pool, 0), total - paid)
        pool -= extra
        carried += round_ratio(vat * extra, total) if total else 0
        unpaid += total - paid - extra
        free |= vat == 0 and extra > 0
    row.advance, row.unpaid = max(pool, 0), unpaid + max(-pool, 0)
    carried += round_ratio(row.advance * rate, 100)
    row.excess = max(row.free_owed - carried, 0)
    row.free_after_advance = row.excess > 0 and free


def warning(row: BuyerRow) -> str | None:
    """Why the buyer's ƏDV owed wants a look, or None."""
    if row.free_after_advance:
        return tr("ƏDV начислен с аванса, а e-qaimə без ƏDV: начислено лишнее")
    if row.excess:
        return tr("ƏDV больше, чем в e-qaimə: ƏDV пришёл на расчётный счёт?")
    if row.to_account:
        return tr("ƏDV e-qaimə пришёл на расчётный счёт, не на депозит")
    return None
