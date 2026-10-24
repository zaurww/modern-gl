"""Read-only viewing of a company file (D80): a snapshot in memory, the file untouched."""

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.domain.errors import NotFoundError, ReadOnlyError
from modern_gl.infrastructure.backup import BackupError
from modern_gl.infrastructure.db import Error, connect, is_read_only, latest_version
from modern_gl.reporting.reports import trial_balance
from tests.conftest import build_demo
from tests.test_workspace import file_at_version


def demo_file(path):
    conn = connect(path)
    demo = build_demo(Ledger(conn))
    total = trial_balance(conn, demo.company_id, "2026-01-01", "2026-12-31").total
    conn.close()
    return total


def test_viewing_shows_the_company_and_leaves_the_file_as_it_was(tmp_path):
    path = tmp_path / "Alfa.gl"
    total = demo_file(path)
    before = path.read_bytes()
    ws = Workspace(tmp_path / "data")

    conn, company_id = ws.view(path)

    assert is_read_only(conn)
    assert trial_balance(conn, company_id, "2026-01-01", "2026-12-31").total == total
    conn.close()
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Alfa.gl", "data"]  # no -wal, -shm
    assert list((tmp_path / "data").iterdir()) == []  # no backup either


def test_a_write_is_refused_with_a_message(tmp_path):
    path = tmp_path / "Alfa.gl"
    demo_file(path)
    conn, company_id = Workspace(tmp_path / "data").view(path)
    ledger = Ledger(conn)
    with pytest.raises(ReadOnlyError, match="только для просмотра"):
        ledger.rename_company(company_id, "Beta")
    with pytest.raises(ReadOnlyError):
        ledger.create_company("Beta")
    with pytest.raises(Error):  # a write outside a transaction is refused by the database
        conn.execute("UPDATE accounts SET name = 'x' WHERE company_id = ?", (company_id,))


def test_an_older_file_is_viewed_without_updating_it(tmp_path):
    path = tmp_path / "old.gl"
    file_at_version(path, latest_version() - 3, ["Alfa"])
    before = path.read_bytes()

    conn, company_id = Workspace(tmp_path / "data").view(path)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version()
    assert conn.execute("SELECT name FROM companies WHERE id = ?", (company_id,)).fetchone()[0]
    conn.close()
    assert path.read_bytes() == before


def test_viewing_sees_what_the_worker_saved_while_the_file_is_open(tmp_path):
    path = tmp_path / "Alfa.gl"
    demo_file(path)
    worker = connect(path)  # the worker keeps the company open; the change is in the WAL
    ledger = Ledger(worker)
    company_id = worker.execute("SELECT id FROM companies").fetchone()[0]
    ledger.rename_company(company_id, "Alfa 2")

    conn, viewed = Workspace(tmp_path / "data").view(path)

    assert conn.execute("SELECT name FROM companies WHERE id = ?", (viewed,)).fetchone()[0] == (
        "Alfa 2"
    )
    conn.close()
    worker.close()


def test_a_file_that_is_not_a_company_is_refused(tmp_path):
    path = tmp_path / "x.gl"
    path.write_text("garbage")
    with pytest.raises(BackupError):
        Workspace(tmp_path / "data").view(path)


def test_viewing_does_not_make_the_opening_account(tmp_path):
    path = tmp_path / "Alfa.gl"
    conn = connect(path)
    company_id = Ledger(conn).create_company("Alfa")
    conn.close()
    conn, company_id = Workspace(tmp_path / "data").view(path)
    with pytest.raises(NotFoundError):
        Ledger(conn).opening_account(company_id, create=False)
