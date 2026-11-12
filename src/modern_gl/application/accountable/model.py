"""What an advance report is (D-new-advance-reports): the employee, the day and the
lines — what the money went on, with the receipt — and loading what was entered."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modern_gl.application.common import batches
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class AdvanceLine:
    """What the money went on: an account and its subconto (an expense and its item, a
    supplier paid…), how much, and the receipt it is spent by."""

    account_id: int | None  # None only in a draft
    amount: int  # minor units; 0 only in a draft
    subconto: Sequence[int | None] = ()
    memo: str = ""  # «Çek №0012, yanacaq»


@dataclass(frozen=True)
class AdvanceReportInput:
    doc_date: str
    employee_id: int | None  # None only in a draft
    lines: Sequence[AdvanceLine] = ()
    memo: str = ""  # empty: «Авансовый отчёт: {employee}»

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines)


@dataclass(frozen=True)
class AdvanceReport(AdvanceReportInput):
    id: int = 0
    document_id: int = 0
    number: int = 0
    status: str = "draft"
    account_id: int | None = None  # the accountable account it was posted on (71)


def load_advance_report(conn: Connection, company_id: int, report_id: int) -> AdvanceReport:
    found = load_advance_reports(conn, company_id, [report_id])
    if report_id not in found:
        raise NotFoundError(tr("документ {id} не найден", id=report_id))
    return found[report_id]


def load_advance_reports(
    conn: Connection, company_id: int, ids: Sequence[int]
) -> dict[int, AdvanceReport]:
    """The reports with their lines, a part of the ids at a time."""
    result: dict[int, AdvanceReport] = {}
    for part in batches(list(ids)):
        marks = ", ".join("?" * len(part))
        heads = conn.execute(
            f"SELECT r.id, r.document_id, r.account_id, r.employee_id, d.number, d.doc_date, "
            f"d.memo, d.status FROM advance_reports r "
            f"JOIN documents d ON d.company_id = r.company_id AND d.id = r.document_id "
            f"WHERE r.company_id = ? AND r.id IN ({marks})",
            (company_id, *part),
        ).fetchall()
        lines: dict[int, list[AdvanceLine]] = {}
        for row in conn.execute(
            f"SELECT report_id, account_id, sc1, sc2, sc3, amount, memo "
            f"FROM advance_report_lines WHERE company_id = ? AND report_id IN ({marks}) "
            f"ORDER BY report_id, line_no",
            (company_id, *part),
        ):
            lines.setdefault(row["report_id"], []).append(
                AdvanceLine(
                    row["account_id"],
                    row["amount"],
                    (row["sc1"], row["sc2"], row["sc3"]),
                    row["memo"],
                )
            )
        for h in heads:
            result[h["id"]] = AdvanceReport(
                h["doc_date"],
                h["employee_id"],
                tuple(lines.get(h["id"], [])),
                h["memo"],
                h["id"],
                h["document_id"],
                h["number"],
                h["status"],
                h["account_id"],
            )
    return result


def report_of_document(conn: Connection, company_id: int, document_id: int) -> int | None:
    """The advance report that made a GL document (to open it from the journal)."""
    row = conn.execute(
        "SELECT id FROM advance_reports WHERE company_id = ? AND document_id = ?",
        (company_id, document_id),
    ).fetchone()
    return row[0] if row else None
