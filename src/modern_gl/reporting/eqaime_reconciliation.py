"""Reconciliation of the books with the tax portal (D53): the e-qaimə of a period on the
portal against the posted postings with their numbers (D38), purchases or sales.

In the books an e-qaimə is its accrual and the ƏDV of it (`application/book_invoices`,
D120). Customs declarations are left out: the portal has none of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.book_invoices import BookInvoice, book_invoices, digest
from modern_gl.application.books import COMMON
from modern_gl.application.document_kinds import name_rows
from modern_gl.domain.dates import iso_date, next_day
from modern_gl.domain.eqaime import ON_APPROVAL, TURNOVER, PortalInvoice, status_group
from modern_gl.infrastructure.db import Connection, Row

# the groups of the report, the problems first
MISSING = "missing"  # on the portal, not in the books: forgotten
VOID_IN_BOOKS = "void"  # in the books, cancelled (deleted, rejected…) on the portal
NOT_ON_PORTAL = "absent"  # in the books, no such number on the portal: a typo?
AMOUNTS = "amounts"
PERIOD = "period"
PARTY = "party"
PENDING = "pending"  # awaiting approval or being corrected or cancelled: for information
MATCHED = "matched"
GROUPS = (MISSING, VOID_IN_BOOKS, NOT_ON_PORTAL, AMOUNTS, PERIOD, PARTY, PENDING, MATCHED)
PROBLEMS = frozenset(GROUPS) - {PENDING, MATCHED}


@dataclass(frozen=True)
class PortalChange:
    seen_at: str
    old_status: str
    new_status: str
    old_date: str
    new_date: str
    old_tin: str
    new_tin: str
    old_total: int
    new_total: int
    old_vat: int
    new_vat: int

    @property
    def significant(self) -> bool:
        """Anything but an approval (on approval -> approved) can change the books."""
        if (self.old_date, self.old_tin, self.old_total, self.old_vat) != (
            self.new_date,
            self.new_tin,
            self.new_total,
            self.new_vat,
        ):
            return True
        quiet = {(ON_APPROVAL, status) for status in TURNOVER}
        return (
            status_group(self.old_status) != status_group(self.new_status)
            and (self.old_status, self.new_status) not in quiet
        )


@dataclass
class ReconciliationRow:
    group: str
    number: str
    portal: PortalInvoice | None = None
    book: BookInvoice | None = None
    party_tin: bool = True  # the VÖEN on the portal is the counterparty's in the books
    changes: list[PortalChange] = field(default_factory=list)  # significant, oldest first

    @property
    def doc_date(self) -> str:
        return self.portal.doc_date if self.portal else self.book.doc_date if self.book else ""

    @property
    def difference(self) -> int:
        """Portal - books, with ƏDV."""
        return (self.portal.total if self.portal else 0) - (self.book.total if self.book else 0)

    @property
    def vat_difference(self) -> int:
        return (self.portal.vat if self.portal else 0) - (self.book.vat if self.book else 0)


@dataclass
class Reconciliation:
    outgoing: bool
    date_from: str
    date_to: str
    rows: list[ReconciliationRow]
    portal_total: int = 0  # approved and awaiting approval, dated in the period
    portal_vat: int = 0
    book_total: int = 0  # accruals dated in the period
    book_vat: int = 0

    def group(self, name: str) -> list[ReconciliationRow]:
        return [r for r in self.rows if r.group == name]

    @property
    def problems(self) -> int:
        return sum(1 for r in self.rows if r.group in PROBLEMS)

    @property
    def agrees(self) -> bool:
        return (
            not self.problems
            and self.portal_total == self.book_total
            and self.portal_vat == self.book_vat
        )


def known_on_portal(conn: Connection, company_id: int, outgoing: bool) -> dict[str, PortalInvoice]:
    """What the portal showed of each number the last time it was read."""
    return {
        r["number"]: _portal(r)
        for r in conn.execute(
            "SELECT * FROM eqaime_portal WHERE company_id = ? AND outgoing = ?",
            (company_id, int(outgoing)),
        )
    }


def _portal(r: Row) -> PortalInvoice:
    return PortalInvoice(
        r["number"],
        bool(r["outgoing"]),
        r["doc_date"],
        r["status"],
        r["party_tin"],
        r["party_name"],
        r["total"],
        r["vat"],
        r["portal_id"],
        r["source_system"],
        r["kind"],
        r["type"],
    )


def portal_changes(
    conn: Connection, company_id: int, outgoing: bool, after: str = ""
) -> dict[str, list[PortalChange]]:
    """Significant changes seen on the portal (after a moment), by number, oldest first."""
    result: dict[str, list[PortalChange]] = {}
    for r in conn.execute(
        "SELECT e.number, c.* FROM eqaime_portal_changes c "
        "JOIN eqaime_portal e ON e.id = c.portal_id "
        "WHERE c.company_id = ? AND e.outgoing = ? AND c.seen_at > ? ORDER BY c.seen_at, c.id",
        (company_id, int(outgoing), after),
    ):
        change = PortalChange(
            r["seen_at"],
            r["old_status"],
            r["new_status"],
            r["old_date"],
            r["new_date"],
            r["old_tin"],
            r["new_tin"],
            r["old_total"],
            r["new_total"],
            r["old_vat"],
            r["new_vat"],
        )
        if change.significant:
            result.setdefault(r["number"], []).append(change)
    return result


def reconcile(
    conn: Connection,
    company_id: int,
    outgoing: bool,
    date_from: date | str,
    date_to: date | str,
    portal: Sequence[PortalInvoice],
    layers: Sequence[str] = COMMON,
) -> Reconciliation:
    """`portal`: the portal's list of the period in every status (`fetch_list`)."""
    start, end = iso_date(date_from), iso_date(date_to)

    def inside(day: str) -> bool:
        return start <= day <= end

    books = book_invoices(conn, company_id, outgoing, layers)
    name_rows(conn, company_id, books.values())
    listed = {p.number: p for p in portal if p.outgoing == outgoing}
    known = known_on_portal(conn, company_id, outgoing)
    changes = portal_changes(conn, company_id, outgoing)

    def day_of(book: BookInvoice) -> str:
        """The day an e-qaimə of the books counts on: the portal's, when it is in the same
        month (posted a day later is no matter), else the posting's."""
        p = listed.get(book.number) or known.get(book.number)
        return (
            p.doc_date if p is not None and p.doc_date[:7] == book.doc_date[:7] else book.doc_date
        )

    rows: list[ReconciliationRow] = []
    for number, p in listed.items():
        book = books.get(number)
        group = _group(p, book)
        if group:
            rows.append(_row(group, number, p, book, changes))
    for number, book in books.items():
        if number in listed or not inside(day_of(book)):
            continue
        p = known.get(number)  # read before, in another period
        rows.append(_row(_group(p, book) if p else NOT_ON_PORTAL, number, p, book, changes))
    rows.sort(key=lambda r: (GROUPS.index(r.group), r.doc_date, r.number))
    counted = [
        p
        for p in listed.values()
        if status_group(p.status) in ("turnover", "pending") and inside(p.doc_date)
    ]
    in_books = [b for b in books.values() if inside(day_of(b))]
    return Reconciliation(
        outgoing,
        start,
        end,
        rows,
        sum(p.total for p in counted),
        sum(p.vat for p in counted),
        sum(b.total for b in in_books),
        sum(b.vat for b in in_books),
    )


def _row(
    group: str,
    number: str,
    portal: PortalInvoice | None,
    book: BookInvoice | None,
    changes: dict[str, list[PortalChange]],
) -> ReconciliationRow:
    same_party = (
        portal is None or book is None or not book.tax_ids or (portal.party_tin in book.tax_ids)
    )
    return ReconciliationRow(group, number, portal, book, same_party, changes.get(number, []))


def _group(portal: PortalInvoice, book: BookInvoice | None) -> str:
    """Where an e-qaimə of the portal goes; '' — not shown (cancelled and not in the
    books, or a status the program does not know). The period that matters is the month:
    the ƏDV declaration is monthly."""
    status = status_group(portal.status)
    if status == "void":
        return VOID_IN_BOOKS if book is not None else ""
    if book is None:
        return {"turnover": MISSING, "pending": MISSING, "progress": PENDING}.get(status, "")
    if status == "progress":
        return PENDING
    if book.tax_ids and portal.party_tin not in book.tax_ids:
        return PARTY
    if (portal.total, portal.vat) != (book.total, book.vat):
        return AMOUNTS
    if book.doc_date[:7] != portal.doc_date[:7]:
        return PERIOD
    return PENDING if status == "pending" else MATCHED


@dataclass(frozen=True)
class Mark:
    """A period marked reconciled."""

    date_from: str
    date_to: str
    reconciled_at: str
    book_digest: str | None = None  # the books it agreed with; None: marked before (0051)


def reconciled_periods(conn: Connection, company_id: int, outgoing: bool) -> list[Mark]:
    return [
        Mark(r["date_from"], r["date_to"], r["reconciled_at"], r["book_digest"])
        for r in conn.execute(
            "SELECT date_from, date_to, reconciled_at, book_digest FROM eqaime_reconciled "
            "WHERE company_id = ? AND outgoing = ? ORDER BY date_from, date_to",
            (company_id, int(outgoing)),
        )
    ]


def reconciled_through(conn: Connection, company_id: int, outgoing: bool) -> str | None:
    """The last day reconciled without a gap from the first mark: «сверено по …»."""
    through: str | None = None
    for mark in reconciled_periods(conn, company_id, outgoing):
        if through is not None and mark.date_from > next_day(through):
            break
        through = max(through or mark.date_to, mark.date_to)
    return through


@dataclass(frozen=True)
class ChangedMonth:
    outgoing: bool
    month: str  # YYYY-MM
    numbers: tuple[str, ...]


def changed_after_reconciliation(conn: Connection, company_id: int) -> list[ChangedMonth]:
    """E-qaimə that changed on the portal after the period of their date (old or new) was
    marked reconciled — and was not reconciled again since: the books may no longer
    agree. By month, purchases then sales."""
    result = []
    for outgoing in (False, True):
        marks = reconciled_periods(conn, company_id, outgoing)
        if not marks:
            continue
        found: dict[str, list[str]] = {}
        for number, changes in portal_changes(conn, company_id, outgoing).items():
            for change in changes:
                for day in {change.old_date, change.new_date}:
                    covering = [m for m in marks if m.date_from <= day <= m.date_to]
                    latest = max(covering, key=lambda m: m.reconciled_at, default=None)
                    if latest is None or latest.reconciled_at >= change.seen_at:
                        continue
                    numbers = found.setdefault(day[:7], [])
                    if number not in numbers:
                        numbers.append(number)
        result += [ChangedMonth(outgoing, m, tuple(n)) for m, n in sorted(found.items())]
    return result


def books_changed(conn: Connection, company_id: int, outgoing: bool) -> list[Mark]:
    """Periods marked reconciled whose e-qaimə changed in the books since (a correction,
    D140): the mark is no longer true. A mark made before the books were remembered is
    taken as it is."""
    marks = [m for m in reconciled_periods(conn, company_id, outgoing) if m.book_digest]
    if not marks:
        return []
    books = list(book_invoices(conn, company_id, outgoing).values())
    return [m for m in marks if m.book_digest != digest(books, m.date_from, m.date_to)]


def portal_status(
    conn: Connection, company_id: int, outgoing: bool, number: str | None
) -> str | None:
    """The e-qaimə's status on the portal the last time it was read; None if never."""
    if not number:
        return None
    row = conn.execute(
        "SELECT status FROM eqaime_portal WHERE company_id = ? AND outgoing = ? AND number = ?",
        (company_id, int(outgoing), number),
    ).fetchone()
    return row["status"] if row else None
