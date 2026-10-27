"""Fixing mistakes: unpost, delete (open period only), storno order, audit copies."""

import json
import sqlite3
from typing import Any

import pytest

from modern_gl.domain.errors import PeriodClosedError, ValidationError
from modern_gl.reporting.reports import trial_balance


def audit(conn, doc_id, action) -> dict[str, Any]:
    """The copy the action left in the journal of actions (it must be there)."""
    row = conn.execute(
        "SELECT details FROM audit_events WHERE entity = 'document' AND entity_id = ? "
        "AND action = ?",
        (doc_id, action),
    ).fetchone()
    assert row is not None, (doc_id, action)
    return json.loads(row[0])


def osv_721(conn, cid):
    rows = {r.code: r for r in trial_balance(conn, cid, "2026-02-01", "2026-03-31").rows}
    return rows["721"].closing_dt if "721" in rows else 0


def test_mistaken_storno_can_be_deleted(demo, conn):
    led, cid = demo.ledger, demo.company_id
    original = demo.docs[5]  # Dt 721 Ct 201 300
    storno = led.reverse(cid, original, "2026-02-25")
    assert osv_721(conn, cid) == 0
    led.delete_document(cid, storno)
    assert osv_721(conn, cid) == 30000  # the original counts again
    copy = audit(conn, storno, "delete")
    assert copy["reversal_of"] == original and copy["postings"][0]["amount"] == -30000
    led.reverse(cid, original, "2026-02-26")  # and can be reversed again if needed


def test_reversed_document_needs_its_storno_removed_first(demo):
    led, cid = demo.ledger, demo.company_id
    storno = led.reverse(cid, demo.docs[5], "2026-02-25")
    with pytest.raises(ValidationError, match="сначала удалите сторно"):
        led.delete_document(cid, demo.docs[5])
    with pytest.raises(ValidationError, match="сначала удалите сторно"):
        led.unpost(cid, demo.docs[5])
    with pytest.raises(ValidationError, match="только удалить"):
        led.unpost(cid, storno)


def test_unpost_edit_and_post_again(demo, conn):
    led, cid = demo.ledger, demo.company_id
    doc = demo.docs[5]
    led.unpost(cid, doc)
    assert osv_721(conn, cid) == 0  # drafts are not in reports
    led.update_draft(cid, doc, "2026-02-20", [demo.p("721", "201", "250")], memo="исправлено")
    led.post(cid, doc)
    assert osv_721(conn, cid) == 25000
    assert audit(conn, doc, "unpost")["postings"][0]["amount"] == 30000  # what it was


def test_posted_document_is_edited_in_place(demo, conn):
    """1C way: open, change, post again — one step, the number stays."""
    led, cid = demo.ledger, demo.company_id
    doc = demo.docs[5]  # Dt 721 Ct 201 300
    number = conn.execute("SELECT number FROM documents WHERE id = ?", (doc,)).fetchone()[0]
    led.repost(cid, doc, "2026-02-21", [demo.p("721", "201", "250")], memo="исправлено")
    assert osv_721(conn, cid) == 25000
    row = conn.execute("SELECT number, status, memo FROM documents WHERE id = ?", (doc,)).fetchone()
    assert tuple(row) == (number, "posted", "исправлено")
    assert audit(conn, doc, "repost")["postings"][0]["amount"] == 30000  # what it was


def test_failed_repost_keeps_the_posted_document(demo, conn):
    led, cid = demo.ledger, demo.company_id
    doc = demo.docs[5]
    with pytest.raises(ValidationError):
        led.repost(cid, doc, "2026-02-21", [demo.p("721", "201", "0")])
    assert osv_721(conn, cid) == 30000
    status = conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0]
    assert status == "posted"


def test_storno_and_closed_period_cannot_be_edited_in_place(demo):
    led, cid = demo.ledger, demo.company_id
    storno = led.reverse(cid, demo.docs[5], "2026-02-25")
    with pytest.raises(ValidationError, match="сначала удалите сторно"):
        led.repost(cid, demo.docs[5], "2026-02-21", [demo.p("721", "201", "250")])
    with pytest.raises(ValidationError, match="нельзя изменить"):
        led.repost(cid, storno, "2026-02-25", [demo.p("721", "201", "-250")])
    led.set_closed_through(cid, "2026-02-28")
    with pytest.raises(PeriodClosedError):
        led.repost(cid, demo.docs[0], "2026-03-05", [demo.p("721", "201", "250")])


def test_closed_period_still_allows_only_storno(demo):
    led, cid = demo.ledger, demo.company_id
    led.set_closed_through(cid, "2026-02-28")
    # dates as the user reads them, not ISO
    with pytest.raises(PeriodClosedError, match=r"\d\d\.02\.2026: период закрыт по 28\.02\.2026"):
        led.delete_document(cid, demo.docs[5])
    with pytest.raises(PeriodClosedError, match=r"28\.02\.2026\. Исправьте его сторно"):
        led.unpost(cid, demo.docs[5])
    led.reverse(cid, demo.docs[5], "2026-03-01")


def test_numbers_are_not_reused_after_delete(demo, conn):
    led, cid = demo.ledger, demo.company_id
    last = led.post_new(cid, "2026-03-01", [demo.p("721", "221", "1")])
    led.delete_document(cid, last)
    new = led.post_new(cid, "2026-03-02", [demo.p("721", "221", "2")])
    number = conn.execute("SELECT number FROM documents WHERE id = ?", (new,)).fetchone()[0]
    assert number == 8  # 1..6 demo, 7 deleted, then 8


def test_database_still_refuses_other_changes_to_posted(demo, conn):
    doc = demo.docs[0]
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE documents SET status = 'draft', memo = 'x' WHERE id = ?", (doc,))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM documents WHERE id = ?", (doc,))
