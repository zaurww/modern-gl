"""An update of the schema must leave the books as they were (D-new-upgrade-check): the
turnover of every account in every month and every item's stock are read before the
pending migrations and after them; a difference undoes the update."""

from __future__ import annotations

import sqlite3

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.workspace import UpgradeError, Workspace
from modern_gl.infrastructure import books_digest, db
from modern_gl.infrastructure.db import close, latest_version
from tests.helpers.backup import company
from tests.helpers.upgrade import migrations_up_to, version_of

# what a careless rebuild of a table would do: a kopeck more on every posting
SPOILS = "DROP TRIGGER postings_posted_no_update;\nUPDATE postings SET amount = amount + 1;"


def books_of(path) -> dict:
    conn = sqlite3.connect(path)
    try:
        return books_digest.books(conn)
    finally:
        conn.close()


@pytest.fixture
def firm(tmp_path):
    """50 «Касса» and 80 «Капитал»: 100.00 and 250.00 in March, 40.00 back in April."""
    ws = Workspace(tmp_path / "data")
    path, conn, ledger, cid, (cash, capital) = company(ws)
    ledger.post_new(cid, "2026-03-01", [PostingInput(cash, capital, "100")])
    ledger.post_new(cid, "2026-03-05", [PostingInput(cash, capital, "250")])
    ledger.post_new(cid, "2026-04-02", [PostingInput(capital, cash, "40")])
    ledger.create_draft(cid, "2026-04-03", [PostingInput(cash, capital, "999")])
    close(conn)
    return ws, path, cid, cash, capital


def test_the_digest_is_the_turnover_of_posted_documents_by_month(firm):
    _ws, path, cid, cash, capital = firm
    assert books_of(path) == {
        ("account", cid, cash, "2026-03"): (35000, 0),  # 100.00 + 250.00
        ("account", cid, capital, "2026-03"): (0, 35000),
        ("account", cid, cash, "2026-04"): (0, 4000),  # the draft of 999.00 is not counted
        ("account", cid, capital, "2026-04"): (4000, 0),
    }


def test_an_update_that_would_change_a_turnover_is_undone(firm, tmp_path, monkeypatch):
    ws, path, _cid, _cash, _capital = firm
    before = books_of(path)
    spoiled = migrations_up_to(tmp_path / "spoiled", latest_version(), extra=SPOILS)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", spoiled)
    with pytest.raises(UpgradeError) as failed:
        ws.open(path)
    said = str(failed.value)
    assert "цифры учёта" in said and "счёта 50 за 2026-03" in said
    assert "расхождений — 4" in said and "не изменён" in said
    assert version_of(path) == latest_version() - 1 and books_of(path) == before
    with pytest.raises(sqlite3.DatabaseError):  # viewing reads the same update
        db.open_snapshot(path)


def test_an_update_that_leaves_the_books_alone_goes_through(firm, tmp_path, monkeypatch):
    ws, path, cid, cash, capital = firm
    before = books_of(path)
    harmless = "CREATE TABLE extra (id INTEGER PRIMARY KEY);"
    monkeypatch.setattr(
        db, "MIGRATIONS_DIR", migrations_up_to(tmp_path / "more", latest_version(), harmless)
    )
    conn, _ = ws.open(path)
    Ledger(conn).post_new(cid, "2026-04-05", [PostingInput(cash, capital, "1")])
    close(conn)
    assert version_of(path) == db.latest_version()
    assert books_of(path) == before | {
        ("account", cid, cash, "2026-04"): (100, 4000),
        ("account", cid, capital, "2026-04"): (4000, 100),
    }


def test_a_migration_that_means_to_change_the_books_says_so(firm, tmp_path, monkeypatch):
    ws, path, cid, cash, _capital = firm
    meant = f"-- books-change: a test of the mark\n{SPOILS}"
    monkeypatch.setattr(
        db, "MIGRATIONS_DIR", migrations_up_to(tmp_path / "meant", latest_version(), meant)
    )
    conn, _ = ws.open(path)
    close(conn)
    assert books_of(path)["account", cid, cash, "2026-03"] == (35002, 0)  # two postings, +0.01


def test_stock_is_compared_too():
    """Quantity and cost of an item in a warehouse: 5 in at 50.00, 2 out at 20.00."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE stock_movements (company_id, item_id, warehouse_id, quantity, amount)"
    )
    conn.executemany(
        "INSERT INTO stock_movements VALUES (1, 7, 2, ?, ?)", [(5000, 5000), (-2000, -2000)]
    )
    before = books_digest.books(conn)
    assert before == {("stock", 1, 7, "2"): (3000, 3000)}
    assert books_digest.difference(conn, before, before) == ""
    conn.execute("UPDATE stock_movements SET amount = amount * 2")
    said = books_digest.difference(conn, before, books_digest.books(conn))
    assert "товар № 7" in said and "расхождений — 1" in said
    conn.close()
