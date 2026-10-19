import sqlite3

import pytest

from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.reporting.reports import trial_balance
from tests.conftest import build_demo


def doc_status(conn, doc_id):
    return conn.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]


def audit_actions(conn, doc_id):
    return [
        r[0]
        for r in conn.execute(
            "SELECT action FROM audit_events "
            "WHERE entity = 'document' AND entity_id = ? ORDER BY id",
            (doc_id,),
        )
    ]


def test_draft_edit_then_post(demo, conn):
    led, cid = demo.ledger, demo.company_id
    doc = led.create_draft(cid, "2026-03-01", [demo.p("721", "221", "10")], memo="черновик")
    led.update_draft(cid, doc, "2026-03-02", [demo.p("721", "221", "15.50")])
    assert doc_status(conn, doc) == "draft"
    led.post(cid, doc)
    assert doc_status(conn, doc) == "posted"
    assert audit_actions(conn, doc) == ["create_draft", "update_draft", "post"]
    amount = conn.execute("SELECT amount FROM postings WHERE document_id = ?", (doc,)).fetchone()
    assert amount[0] == 1550


def test_documents_numbered_sequentially(demo, conn):
    numbers = [
        r[0]
        for r in conn.execute(
            "SELECT number FROM documents WHERE company_id = ? ORDER BY id", (demo.company_id,)
        )
    ]
    assert numbers == [1, 2, 3, 4, 5, 6]


def test_draft_can_be_deleted_posted_cannot(demo):
    led, cid = demo.ledger, demo.company_id
    doc = led.create_draft(cid, "2026-03-01", [demo.p("721", "221", "10")])
    led.delete_draft(cid, doc)
    with pytest.raises(NotFoundError):
        led.post(cid, doc)
    with pytest.raises(ValidationError):
        led.delete_draft(cid, demo.docs[0])


@pytest.mark.parametrize(
    ("dt", "ct", "amount", "dt_sc", "ct_sc", "message"),
    [
        ("22", "301", "1", (), (), "группу"),  # group account
        ("721", "531", "1", (), (), "не заполнено"),  # missing subconto
        ("721", "221", "1", (1,), (), "нет субконто"),  # subconto on account without it
        ("721", "221", "-1", (), (), "положительной"),  # negative amount
    ],
)
def test_invalid_posting_rejected_atomically(demo, conn, dt, ct, amount, dt_sc, ct_sc, message):
    led, cid = demo.ledger, demo.company_id
    before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    with pytest.raises(ValidationError, match=message):
        led.post_new(cid, "2026-03-01", [demo.p(dt, ct, amount, dt_sc, ct_sc)])
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before


def test_zero_amount_rejected(demo):
    with pytest.raises(ValidationError, match="нулевая"):
        demo.ledger.post_new(demo.company_id, "2026-03-01", [demo.p("721", "221", "0")])


def test_subconto_of_wrong_kind_rejected(demo):
    led, cid = demo.ledger, demo.company_id
    other_kind = led.add_subconto_kind(cid, "contract", "Договоры")
    contract = led.add_subconto_value(cid, other_kind, "Договор 1")
    with pytest.raises(ValidationError, match="не того вида"):
        led.post_new(cid, "2026-03-01", [demo.p("201", "531", "1", ct_sc=[contract])])


def test_failed_post_leaves_draft_untouched(demo, conn):
    led, cid = demo.ledger, demo.company_id
    doc = led.create_draft(cid, "2026-03-01", [demo.p("721", "531", "5")])  # no subconto
    with pytest.raises(ValidationError):
        led.post(cid, doc)
    assert doc_status(conn, doc) == "draft"
    assert audit_actions(conn, doc) == ["create_draft"]


def test_posted_document_immutable_at_db_level(demo, conn):
    doc = demo.docs[0]
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE postings SET amount = 1 WHERE document_id = ?", (doc,))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM postings WHERE document_id = ?", (doc,))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE documents SET memo = 'x' WHERE id = ?", (doc,))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM documents WHERE id = ?", (doc,))
    with pytest.raises(ValidationError):
        demo.ledger.update_draft(demo.company_id, doc, "2026-01-05", [demo.p("721", "221", "1")])


def test_audit_trail_append_only(demo, conn):
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit_events")


def test_reverse_is_red_storno(demo, conn):
    led, cid = demo.ledger, demo.company_id
    rev = led.reverse(cid, demo.docs[5], "2026-02-25")
    assert (
        conn.execute("SELECT amount FROM postings WHERE document_id = ?", (rev,)).fetchone()[0]
        == -30000
    )
    assert doc_status(conn, demo.docs[5]) == "posted"  # original untouched
    rows = {r.code: r for r in trial_balance(conn, cid, "2026-02-01", "2026-02-28").rows}
    assert "721" not in rows  # 300 - 300 = nothing left
    assert (rows["201"].turnover_dt, rows["201"].turnover_ct) == (50000, 0)


def test_reverse_twice_or_reverse_storno_rejected(demo):
    led, cid = demo.ledger, demo.company_id
    rev = led.reverse(cid, demo.docs[5], "2026-02-25")
    with pytest.raises(ValidationError, match="уже сторнирован"):
        led.reverse(cid, demo.docs[5], "2026-02-26")
    with pytest.raises(ValidationError, match="сам является сторно"):
        led.reverse(cid, rev, "2026-02-26")


def test_closed_period_blocks_posting_and_reversal(demo):
    led, cid = demo.ledger, demo.company_id
    led.set_closed_through(cid, "2026-01-31")
    with pytest.raises(PeriodClosedError):
        led.post_new(cid, "2026-01-31", [demo.p("721", "221", "1")])
    with pytest.raises(PeriodClosedError):
        led.reverse(cid, demo.docs[0], "2026-01-20")
    led.reverse(cid, demo.docs[0], "2026-02-01")  # correction in an open period is fine
    led.set_closed_through(cid, None)
    led.post_new(cid, "2026-01-31", [demo.p("721", "221", "1")])


def test_companies_are_isolated(ledger, conn):
    a = build_demo(ledger, "Компания A")
    b = ledger.create_company("Компания B")
    assert trial_balance(conn, b, "2026-01-01", "2026-12-31").rows == []
    b_cash = ledger.add_account(b, "221", "Банк", kind="A")
    with pytest.raises(ValidationError, match="другой компании"):
        ledger.post_new(b, "2026-03-01", [PostingInput(a.acc["721"], b_cash, "1")])
    with pytest.raises(NotFoundError):
        ledger.reverse(b, a.docs[0], "2026-03-01")
