"""`db.transaction` inside an open transaction is a savepoint (D160): a block that fails
is undone alone, the outer transaction goes on. `dry_run` undoes a block that succeeded."""

from __future__ import annotations

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import dry_run, transaction


def names(conn) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM companies ORDER BY id")]


def create_and_fail(ledger: Ledger, conn, name: str) -> None:
    """A block that writes a company and then fails."""
    with transaction(conn):
        ledger.create_company(name)
        raise LedgerError("no")


def test_a_failed_inner_block_is_undone_alone(ledger: Ledger, conn):
    with transaction(conn):
        ledger.create_company("A")
        with pytest.raises(LedgerError, match="no"):
            create_and_fail(ledger, conn, "B")
        ledger.create_company("C")
    assert names(conn) == ["A", "C"]
    assert not conn.in_transaction


def test_a_failed_outer_block_takes_the_inner_with_it(ledger: Ledger, conn):
    def outer() -> None:
        with transaction(conn):
            with transaction(conn):
                ledger.create_company("B")
            raise LedgerError("no")

    with pytest.raises(LedgerError, match="no"):
        outer()
    assert names(conn) == []


def test_a_dry_run_leaves_nothing_but_tells_what_it_did(ledger: Ledger, conn):
    with dry_run(conn):
        cid = ledger.create_company("Preview")
        assert names(conn) == ["Preview"]
    assert cid >= 1 and names(conn) == []
    with transaction(conn):
        ledger.create_company("A")
        with dry_run(conn):
            ledger.create_company("B")
        ledger.create_company("C")
    assert names(conn) == ["A", "C"]


def test_posting_all_drafts_keeps_the_ones_that_posted(demo, conn, monkeypatch):
    """«Провести все» inside an outer transaction (a module's own scenario): a draft that
    fails halfway through posting — after its status was written — goes back to a draft
    and is named; the others are posted."""
    ledger, cid = demo.ledger, demo.company_id
    good = ledger.create_draft(cid, "2026-03-01", [demo.p("221", "301", "10.00")])
    bad = ledger.create_draft(cid, "2026-03-02", [demo.p("221", "301", "20.00")])
    later = ledger.create_draft(cid, "2026-03-03", [demo.p("221", "301", "30.00")])
    audit = ledger._audit

    def failing_audit(company_id, entity, entity_id, action, details):
        if action == "post" and entity_id == bad:
            raise LedgerError("журнал недоступен")
        audit(company_id, entity, entity_id, action, details)

    monkeypatch.setattr(ledger, "_audit", failing_audit)
    with transaction(conn):
        posted, left = ledger.post_drafts(cid, "2026-03-31")
    assert posted == [good, later]
    assert left == [(ledger._document(cid, bad)["number"], "журнал недоступен")]
    status = {
        r["id"]: r["status"]
        for r in conn.execute("SELECT id, status FROM documents WHERE company_id = ?", (cid,))
    }
    assert (status[good], status[bad], status[later]) == ("posted", "draft", "posted")


def test_a_failed_commit_leaves_no_transaction_open(conn):
    """A commit the database refuses (here: a deferred reference checked only at COMMIT;
    in life also a file another program keeps locked) must not leave the transaction
    open: the next `transaction()` would join it as a savepoint and never be saved."""
    conn.execute("CREATE TABLE t_parent (id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE t_child (parent_id INTEGER"
        " REFERENCES t_parent (id) DEFERRABLE INITIALLY DEFERRED)"
    )

    def orphan() -> None:
        with transaction(conn):
            conn.execute("INSERT INTO t_child (parent_id) VALUES (99)")

    with pytest.raises(Exception, match="FOREIGN KEY"):
        orphan()
    assert not conn.in_transaction
    with transaction(conn):
        conn.execute("INSERT INTO t_parent (id) VALUES (1)")
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM t_parent").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM t_child").fetchone()[0] == 0
