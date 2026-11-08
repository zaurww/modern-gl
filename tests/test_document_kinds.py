"""One document in the user's eyes (D213): a document is named by its kind
and the number the user knows. The demo company (`demo_data`), by hand:
GL №2 is the warehouse's purchase №1, GL №9 — write-off №3, GL №10 — sale №4; GL №1 and
№13 were entered in the journal. The bank pays ALFA 1 180.00 on 05.03 (`test_bank`)."""

from __future__ import annotations

from modern_gl.application.bank import (
    OUT,
    SUPPLIER,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.document_kinds import DocumentName, document_names, document_title
from modern_gl.application.journal import JournalFilter, documents_before
from modern_gl.application.queries import document_by_number
from modern_gl.infrastructure.db import connect


def _names(conn, cid, numbers):
    ids = {n: document_by_number(conn, cid, n) for n in numbers}
    names = document_names(conn, cid, ids.values())
    return {n: names[ids[n]] for n in numbers}


def test_a_module_document_is_named_by_its_own_kind_and_number(make_demo, tmp_path):
    conn = connect(make_demo(tmp_path / "demo.gl"))
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    assert _names(conn, cid, [1, 2, 9, 10, 13]) == {
        1: DocumentName("journal", 1),
        2: DocumentName("receipt", 1),
        9: DocumentName("issue", 3),
        10: DocumentName("sale", 4),
        13: DocumentName("journal", 13),
    }
    assert document_title("receipt", 1) == "Покупка №1"
    conn.close()


def test_the_journal_shows_and_finds_the_documents_kind_and_number(make_demo, tmp_path):
    conn = connect(make_demo(tmp_path / "demo.gl"))
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    docs = documents_before(conn, JournalFilter(cid), None).docs
    shown = {d.number: (d.kind, d.shown_number) for d in docs}
    assert shown[2] == ("receipt", 1)
    assert shown[10] == ("sale", 4)
    assert shown[13] == ("journal", 13)
    # «покупк» finds the two purchases (GL №2 and №4), not the payments to suppliers
    found = documents_before(conn, JournalFilter(cid, text="покупк"), None).docs
    assert [d.number for d in found] == [2, 4]
    conn.close()


def test_a_bank_operation_is_named_by_its_direction(ledger, bank_firm):
    f = bank_firm
    acc, v = f["acc"], f["v"]
    pay = BankOperationInput(
        doc_date="2026-03-05",
        direction=OUT,
        account_id=acc["51"],
        subconto=(v["azn"],),
        kind=SUPPLIER,
        counterparty_id=v["alfa"],
        lines=(BankLine(acc["60.1"], 118000, (None, v["contract"]), "MT001"),),
        memo="Оплата по счёту MT001",
    )
    op_id = ledger.bank.save_bank_operation(f["cid"], pay, post=True)
    op = load_bank_operation(ledger.conn, f["cid"], op_id)
    name = document_names(ledger.conn, f["cid"], [op.document_id])[op.document_id]
    assert name == DocumentName("bank_out", op.number)
    assert name.title == f"Банк, расход №{op.number}"
