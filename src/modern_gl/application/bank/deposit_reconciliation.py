"""The ƏDV deposit account reconciled with the tax portal for a period (D118), as the
e-qaimə are (D53): each operation of the portal against the account's statement — the
same, different, only on the portal, only in the books — and the period's figures by
both (opening, in, out, closing). A period marked reconciled keeps its figures: a change
seen later, on the portal or in the books, is warned about."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.bank.deposit_import import (
    DepositOperation,
    deposit_references,
    same_line,
)
from modern_gl.application.bank.operations import IN
from modern_gl.application.bank.places import BankPlace
from modern_gl.application.bank.statement import StatementLine, statement
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

SAME, DIFFERENT, PORTAL_ONLY, BOOKS_ONLY = "same", "different", "portal", "books"


@dataclass(frozen=True)
class Figures:
    """A period of the account by one side, minor units."""

    opening: int = 0
    money_in: int = 0
    money_out: int = 0

    @property
    def closing(self) -> int:
        return self.opening + self.money_in - self.money_out


@dataclass(frozen=True)
class ReconciledRow:
    """An operation of the portal and the statement's line it is (either may be missing);
    `note` — what differs."""

    state: str
    op: DepositOperation | None = None
    line: StatementLine | None = None
    note: str = ""

    @property
    def day(self) -> str:
        return self.op.day if self.op is not None else self.line.doc_date if self.line else ""


@dataclass
class DepositReconciliation:
    date_from: str
    date_to: str
    portal: Figures
    books: Figures
    rows: list[ReconciledRow] = field(default_factory=list)

    @property
    def difference(self) -> int:
        """The portal's closing less the books'."""
        return self.portal.closing - self.books.closing

    @property
    def agreed(self) -> bool:
        return self.difference == 0 and all(row.state == SAME for row in self.rows)

    def missing(self) -> list[DepositOperation]:
        """The portal's operations the books do not have: to load."""
        return [row.op for row in self.rows if row.state == PORTAL_ONLY and row.op is not None]


def portal_figures(
    operations: Sequence[DepositOperation], balance: int, date_from: str, date_to: str
) -> Figures:
    """The period by the portal: its closing counted back from the balance now (the
    operations after the period undone), the opening — back over the period's own."""
    done = [op for op in operations if op.done]
    later = sum(op.net for op in done if op.day > date_to)
    period = [op for op in done if date_from <= op.day <= date_to]
    money_in = sum(op.amount for op in period if op.direction == IN)
    money_out = sum(op.amount for op in period if op.direction != IN)
    closing = balance - later
    return Figures(closing - money_in + money_out, money_in, money_out)


def reconcile_deposit(
    conn: Connection,
    company_id: int,
    place: BankPlace,
    operations: Sequence[DepositOperation],
    balance: int,
    date_from: str,
    date_to: str,
) -> DepositReconciliation:
    """`operations` — the portal's from `date_from` up to now, `balance` — its balance now.
    An operation is the line with its reference, else a line of the same day, amount and
    direction (entered by hand: the same money, the reference not yet written)."""
    booked = statement(conn, company_id, place, date_from, date_to)
    posted = [line for line in booked.lines if line.status == "posted"]
    books = Figures(
        booked.opening,
        sum(line.money_in for line in posted),
        sum(line.money_out for line in posted),
    )  # as books_figures, the statement read once
    result = DepositReconciliation(
        date_from, date_to, portal_figures(operations, balance, date_from, date_to), books
    )
    references = deposit_references(conn, company_id, place)
    free = list(booked.lines)
    by_reference = {references[x.document_id]: x for x in free if references.get(x.document_id)}
    period = [op for op in operations if op.done and date_from <= op.day <= date_to]
    for op in sorted(period, key=lambda x: x.moment):
        line = by_reference.get(op.reference)
        if line is None:
            line = same_line([x for x in free if not references.get(x.document_id)], op)
        if line is None:
            day = _booked_on(conn, company_id, references, op.reference)
            if day is None:
                result.rows.append(ReconciledRow(PORTAL_ONLY, op))
            else:
                note = tr("в программе от {day}", day=ru_date(day))
                result.rows.append(ReconciledRow(DIFFERENT, op, note=note))
            continue
        free.remove(line)
        note = _difference(op, line)
        result.rows.append(ReconciledRow(DIFFERENT if note else SAME, op, line, note))
    result.rows += [ReconciledRow(BOOKS_ONLY, line=line) for line in free]
    result.rows.sort(key=lambda row: (row.day, row.op.moment if row.op else "99"))
    return result


def _booked_on(
    conn: Connection, company_id: int, references: dict[int, str], reference: str
) -> str | None:
    """The day of the document with the reference outside the period; None — no such."""
    document = next((d for d, r in references.items() if r == reference), None)
    if document is None:
        return None
    row = conn.execute(
        "SELECT doc_date FROM documents WHERE company_id = ? AND id = ?", (company_id, document)
    ).fetchone()
    return row["doc_date"] if row else None


def _difference(op: DepositOperation, line: StatementLine) -> str:
    """What the books have otherwise than the portal; "" — nothing."""
    notes = []
    amount = line.money_in if op.direction == IN else line.money_out
    if amount == 0:
        notes.append(tr("в программе в другую сторону"))
    elif amount != op.amount:
        notes.append(tr("в программе {amount}", amount=format_minor(amount)))
    if line.doc_date != op.day:
        notes.append(tr("в программе от {day}", day=ru_date(line.doc_date)))
    if line.status != "posted":
        notes.append(tr("в программе черновик — не проведён"))
    return "; ".join(notes)


@dataclass(frozen=True)
class ReconciledPeriod:
    """A period marked reconciled, with both sides' figures as they were then."""

    date_from: str
    date_to: str
    reconciled_at: str
    portal: Figures
    books: Figures


def reconciled_periods(
    conn: Connection, company_id: int, place: BankPlace
) -> list[ReconciledPeriod]:
    """The periods of the account marked reconciled, the earliest first."""
    return [
        ReconciledPeriod(
            r["date_from"],
            r["date_to"],
            r["reconciled_at"],
            Figures(r["portal_opening"], r["portal_in"], r["portal_out"]),
            Figures(r["books_opening"], r["books_in"], r["books_out"]),
        )
        for r in conn.execute(
            "SELECT * FROM bank_portal_reconciled WHERE company_id = ? AND account_id = ? "
            "AND COALESCE(value_id, 0) = ? ORDER BY date_from, date_to",
            (company_id, place.account_id, place.value_id or 0),
        )
    ]


def books_figures(
    conn: Connection, company_id: int, place: BankPlace, date_from: str, date_to: str
) -> Figures:
    """The period by the books: the posted lines of the statement."""
    booked = statement(conn, company_id, place, date_from, date_to)
    posted = [line for line in booked.lines if line.status == "posted"]
    return Figures(
        booked.opening,
        sum(line.money_in for line in posted),
        sum(line.money_out for line in posted),
    )


def changed_since(
    conn: Connection,
    company_id: int,
    place: BankPlace,
    operations: Sequence[DepositOperation] | None = None,
    balance: int = 0,
    fetched_from: str = "",
) -> list[str]:
    """What changed in the reconciled periods since: in the books always; on the portal —
    when `operations` (the portal's from `fetched_from` up to now) cover the period."""
    found = []
    for period in reconciled_periods(conn, company_id, place):
        name = f"{ru_date(period.date_from)}–{ru_date(period.date_to)}"
        books = books_figures(conn, company_id, place, period.date_from, period.date_to)
        if books != period.books:
            found.append(_changed(tr("в программе"), name, period.books, books))
        if operations is not None and fetched_from <= period.date_from:
            portal = portal_figures(operations, balance, period.date_from, period.date_to)
            if portal != period.portal:
                found.append(_changed(tr("на портале"), name, period.portal, portal))
    return found


def _changed(side: str, name: str, was: Figures, now: Figures) -> str:
    return tr(
        "{period} сверен, но {side} изменилось: приход {was_in} → {now_in}, расход {was_out} → "
        "{now_out}, на конец {was_end} → {now_end}",
        period=name,
        side=side,
        was_in=format_minor(was.money_in),
        now_in=format_minor(now.money_in),
        was_out=format_minor(was.money_out),
        now_out=format_minor(now.money_out),
        was_end=format_minor(was.closing),
        now_end=format_minor(now.closing),
    )
