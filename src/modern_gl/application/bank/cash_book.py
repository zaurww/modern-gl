"""The papers of a cash desk (D216): a cash order for a document that moved the
cash — «Kassa mədaxil / məxaric orderi» — and the cash book, a sheet per day with its
opening, lines, totals and closing. Read from the statement of the cash desk, so a
journal entry on 50 gets its order as a cash operation does; drafts are not on paper."""

from __future__ import annotations

from modern_gl.application.bank.places import BankPlace
from modern_gl.application.bank.statement import statement
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.cash_file import CashBook, CashDay, CashDesk, CashLine, CashOrder
from modern_gl.infrastructure.db import Connection


def cash_desk(conn: Connection, company_id: int, place: BankPlace) -> CashDesk:
    """The company and its cash desk, as the head of a paper names them."""
    row = conn.execute("SELECT name, tax_id FROM companies WHERE id = ?", (company_id,)).fetchone()
    return CashDesk(
        row["name"], row["tax_id"] or "", place.name, place.account_code, place.currency
    )


def cash_order(conn: Connection, company_id: int, place: BankPlace, document_id: int) -> CashOrder:
    """The order of a posted document that moved the cash desk: money in or out of it."""
    found = conn.execute(
        "SELECT doc_date FROM documents WHERE company_id = ? AND id = ? AND status = 'posted'",
        (company_id, document_id),
    ).fetchone()
    day = found["doc_date"] if found else None
    lines = statement(conn, company_id, place, day, day).lines if day else []
    line = next((x for x in lines if x.document_id == document_id and x.status == "posted"), None)
    if line is None:
        raise NotFoundError(tr("документ {id} не двигал кассу", id=document_id))
    net = line.money_in - line.money_out
    return CashOrder(
        cash_desk(conn, company_id, place),
        line.number,
        line.doc_date,
        net >= 0,
        line.corr,
        line.counterparty,
        line.memo,
        abs(net),
    )


def cash_book(
    conn: Connection, company_id: int, place: BankPlace, date_from: str, date_to: str
) -> CashBook:
    """The sheets of the period: each day money moved, posted documents only."""
    st = statement(conn, company_id, place, date_from, date_to)
    days: list[CashDay] = []
    balance = st.opening
    for line in st.lines:
        if line.status != "posted":
            continue
        if not days or days[-1].day != line.doc_date:
            days.append(CashDay(line.doc_date, balance))
        days[-1].lines.append(
            CashLine(line.number, line.counterparty, line.corr, line.money_in, line.money_out)
        )
        balance = days[-1].closing
    return CashBook(cash_desk(conn, company_id, place), days)
