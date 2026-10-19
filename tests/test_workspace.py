import sqlite3

from modern_gl.application.ledger import Ledger
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import TRASH, Workspace, open_company
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
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 37  # classic chart
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
