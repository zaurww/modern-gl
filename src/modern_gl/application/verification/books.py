"""The checks of the books themselves: the posting rules, the storno, the modules'
postings (D175). Each reads the copy of the company it is given and names the document."""

from __future__ import annotations

import json
from datetime import date

from modern_gl.application.ledger import Ledger
from modern_gl.application.ledger.posting_record import PostingRecord
from modern_gl.application.queries import document_owner
from modern_gl.application.rebuild import rebuild_postings
from modern_gl.application.verification import REBUILD, CheckResult, Finding
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row, dry_run


def posting_rules(ledger: Ledger, company_id: int) -> CheckResult:
    """Every posted document still passes the posting rules (an account closed since is
    no error: it was open when the document was posted)."""
    return CheckResult(
        tr("Проведённые документы соответствуют правилам проведения"),
        tuple(
            Finding(_about(doc, problem), doc["id"])
            for doc, problem in ledger.posted_against_rules(company_id)
        ),
    )


def storno(ledger: Ledger, company_id: int) -> CheckResult:
    """A red storno repeats its document line by line with the amounts negated, in the same
    layer, and the document it reverses stays posted (D5)."""
    conn = ledger.conn
    findings: list[Finding] = []
    for pair in conn.execute(
        "SELECT r.id, r.number, r.doc_date, r.layer_id, o.id AS original_id, "
        "o.number AS original_number, o.layer_id AS original_layer, "
        "o.status AS original_status "
        "FROM documents r JOIN documents o ON o.company_id = r.company_id "
        "AND o.id = r.reversal_of "
        "WHERE r.company_id = ? AND r.status = 'posted' ORDER BY r.doc_date, r.number",
        (company_id,),
    ).fetchall():
        problem = _storno_problem(conn, pair)
        if problem:
            findings.append(Finding(_about(pair, problem), pair["id"]))
    return CheckResult(tr("Сторно повторяют свои документы"), tuple(findings))


def _storno_problem(conn: Connection, pair: Row) -> str:
    n = pair["original_number"]
    if pair["original_status"] != "posted":
        return tr("документ №{n}, который оно сторнирует, не проведён", n=n)
    if pair["layer_id"] != pair["original_layer"]:
        return tr("сторно не в той книге, что документ №{n}", n=n)
    original = [PostingRecord.from_row(p).negated() for p in _postings(conn, pair["original_id"])]
    if original != [PostingRecord.from_row(p) for p in _postings(conn, pair["id"])]:
        return tr("проводки не повторяют документ №{n} с обратным знаком", n=n)
    return ""


def _postings(conn: Connection, document_id: int) -> list[Row]:
    return conn.execute(
        "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (document_id,)
    ).fetchall()


def module_postings(ledger: Ledger, company_id: int) -> CheckResult:
    """The GL documents of the modules (bank, conversion, warehouse) of the open period are
    what their documents make today (D101): built again and undone, compared. A change of
    a rule or a setting since, or a row written past the program, shows here."""
    title = tr("Проводки модулей совпадают с их документами")
    try:
        with dry_run(ledger.conn):
            changed = rebuild_postings(ledger, company_id, date.min)
    except LedgerError as e:
        return CheckResult(title, (Finding(tr("перестроить не удалось: {error}", error=e)),))
    findings = tuple(
        Finding(_about(doc, _owner_text(ledger.conn, company_id, doc)), doc["id"])
        for doc in _documents(ledger.conn, company_id, changed)
    )
    return CheckResult(title, findings, REBUILD if findings else "")


def _owner_text(conn: Connection, company_id: int, doc: Row) -> str:
    owner = document_owner(conn, company_id, doc["id"])
    # the modules' names in `document_owners`, as the accountant knows the sections
    titles = {"bank": tr("Банк"), "conversion": tr("Конвертация"), "inventory": tr("Склад")}
    module = owner.module if owner else ""
    return tr(
        "проводки отличаются от документа раздела «{module}»", module=titles.get(module, module)
    )


def _documents(conn: Connection, company_id: int, ids: list[int]) -> list[Row]:
    if not ids:
        return []
    return conn.execute(
        "SELECT id, number, doc_date FROM documents "
        "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?)) "
        "ORDER BY doc_date, number",
        (company_id, json.dumps(ids)),
    ).fetchall()


def _about(doc: Row, problem: str) -> str:
    return tr(
        "№{n} от {date}: {problem}", n=doc["number"], date=ru_date(doc["doc_date"]), problem=problem
    )
