import sqlite3
from pathlib import Path

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import TRASH, Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.infrastructure.company_file import open_company
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect, latest_version
from modern_gl.reporting.reports import trial_balance
from tests.conftest import build_demo


def test_one_file_per_company(tmp_path):
    ws = Workspace(tmp_path / "data")
    a = ws.create("Alfa MMC")
    b = ws.create("Beta / Gamma: test")  # characters Windows forbids in file names
    ws.create("Alfa MMC")  # same name: a second, separate file
    assert a.name == "Alfa MMC.gl"
    assert b.name == "Beta Gamma test.gl"
    assert [c.name for c in ws.companies()] == ["Alfa MMC", "Alfa MMC", "Beta / Gamma: test"]
    conn, _cid = open_company(a)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 42  # classic, D128
    conn.close()


def test_delete_moves_file_to_trash(tmp_path):
    ws = Workspace(tmp_path)
    path = ws.create("Test")
    moved = ws.delete(path)
    assert not path.exists()
    assert moved.parent.name == TRASH and moved.exists()
    assert ws.companies() == []
    (tmp_path / "not a company.gl").write_text("garbage")
    assert ws.companies() == []  # foreign files don't break the list


def test_add_file_splits_an_old_shared_file(tmp_path):
    shared = tmp_path / "old.db"
    conn = connect(shared)
    one = build_demo(Ledger(conn), "Компания 1")
    two = build_demo(Ledger(conn), "Компания 2")
    two.ledger.post_new(two.company_id, "2026-03-01", [two.p("721", "221", "99")])
    expected = {
        name: trial_balance(conn, d.company_id, "2026-01-01", "2026-03-31").total
        for name, d in (("Компания 1", one), ("Компания 2", two))
    }
    conn.close()

    ws = Workspace(tmp_path / "data")
    paths = ws.add_file(shared)
    assert sorted(p.name for p in paths) == ["Компания 1.gl", "Компания 2.gl"]
    for path in paths:
        c, cid = open_company(path)
        assert c.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
        name = c.execute("SELECT name FROM companies").fetchone()[0]
        assert trial_balance(c, cid, "2026-01-01", "2026-03-31").total == expected[name]
        # immutability triggers are back in the extracted file
        try:
            c.execute("DELETE FROM documents")
            raise AssertionError("posted documents must stay protected")
        except sqlite3.DatabaseError:
            pass
        c.close()
    assert shared.exists()  # the source file is left as it was


def test_add_file_opens_a_company_file_in_place(tmp_path):
    elsewhere = tmp_path / "Clients" / "Alfa.gl"
    elsewhere.parent.mkdir()
    Workspace(tmp_path / "other").create("Alfa", chart=None, path=elsewhere)
    ws = Workspace(tmp_path / "data")
    assert ws.add_file(elsewhere) == [elsewhere]
    assert list((tmp_path / "data").glob("*.gl")) == []  # not copied
    assert ws.files == [elsewhere] and [c.name for c in ws.companies()] == ["Alfa"]
    ws.add_file(elsewhere)  # adding it again changes nothing
    assert ws.files == [elsewhere]
    conn, cid = ws.open(elsewhere)  # and it is worked on right there
    Ledger(conn).rename_company(cid, "Alfa MMC")
    conn.close()
    assert [c.name for c in ws.companies()] == ["Alfa MMC"]


def company_ids_by_table(path: Path) -> dict[str, set[int]]:
    """Which companies each table of a file holds rows of."""
    conn = sqlite3.connect(path)
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if r[0] != "companies"
        ]
        found = {}
        for table in tables:
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "company_id" in columns:
                ids = {r[0] for r in conn.execute(f"SELECT DISTINCT company_id FROM {table}")}
                found[table] = ids - {None}
        return found
    finally:
        conn.close()


def test_split_leaves_no_row_of_another_company(tmp_path):
    """Every table, the modules' too (stock, bank, conversions, tags…), keeps only its
    own company's rows in the file split off a shared one."""
    shared = tmp_path / "old.db"
    conn = connect(shared)
    first = create_demo_company(Ledger(conn), "Alfa")
    second = create_demo_company(Ledger(conn), "Beta")
    conn.close()
    held = company_ids_by_table(shared)
    assert {t for t, ids in held.items() if second in ids} - {"audit_events"} >= {
        "inventory_items",
        "inventory_documents",
    }  # the demo company has module data to leave behind

    paths = Workspace(tmp_path / "data").add_file(shared)
    by_name = {p.stem: p for p in paths}
    for name, cid in (("Alfa", first), ("Beta", second)):
        others = {t: ids - {cid} for t, ids in company_ids_by_table(by_name[name]).items()}
        assert {t: ids for t, ids in others.items() if ids} == {}, name


def file_at_version(path: Path, version: int, companies: list[str]) -> None:
    """A shared file as an older program left it: the migrations up to `version`."""
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("PRAGMA foreign_keys = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = int(migration.name.split("_", 1)[0])
        if number > version:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    for name in companies:
        old.execute("INSERT INTO companies (name, created_at) VALUES (?, 'now')", (name,))
    old.close()


@pytest.mark.parametrize("version", range(1, latest_version() + 1))
def test_shared_file_of_every_version_is_split(tmp_path, version):
    """A shared file of any older schema is brought up to date before it is split; each
    company gets a current file of its own, and nothing is left half-written."""
    shared = tmp_path / "old.db"
    file_at_version(shared, version, ["Alfa", "Beta"])
    ws = Workspace(tmp_path / "data")
    paths = ws.add_file(shared)
    assert sorted(p.name for p in paths) == ["Alfa.gl", "Beta.gl"]
    for path in paths:
        conn, _cid = open_company(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version()
        assert [r[0] for r in conn.execute("SELECT name FROM companies")] == [path.stem]
        conn.close()
    assert list(ws.folder.glob("*.part")) == []


def test_failed_split_leaves_no_file(tmp_path, monkeypatch):
    shared = tmp_path / "old.db"
    file_at_version(shared, latest_version(), ["Alfa", "Beta"])
    ws = Workspace(tmp_path / "data")

    def broken(*_args):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("modern_gl.application.workspace.connect", broken)
    with pytest.raises(sqlite3.OperationalError):
        ws.add_file(shared)
    assert sorted(p.name for p in ws.folder.iterdir()) == []
