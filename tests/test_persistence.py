from pathlib import Path

import pytest

from modern_gl.application.chart_csv import import_chart_csv
from modern_gl.application.ledger import Ledger
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect, schema_version
from modern_gl.reporting.reports import trial_balance
from tests.conftest import build_demo

DEMO_CHART = Path(__file__).parent.parent / "examples" / "demo_chart.csv"


def test_posted_data_survives_restart(tmp_path):
    path = tmp_path / "ledger.db"
    conn = connect(path)
    demo = build_demo(Ledger(conn))
    expected = trial_balance(conn, demo.company_id, "2026-01-01", "2026-02-28")
    conn.close()

    conn = connect(path)
    assert schema_version(conn) == len(list(MIGRATIONS_DIR.glob("*.sql")))
    assert trial_balance(conn, demo.company_id, "2026-01-01", "2026-02-28") == expected
    conn.close()


def test_import_demo_chart(ledger, conn):
    cid = ledger.create_company("Импорт")
    ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    ledger.add_subconto_kind(cid, "contract", "Договоры")
    assert import_chart_csv(ledger, cid, DEMO_CHART) == 7
    row = conn.execute(
        "SELECT a.account_class, p.code AS parent "
        "FROM accounts a LEFT JOIN accounts p ON p.id = a.parent_id "
        "WHERE a.company_id = ? AND a.code = '221'",
        (cid,),
    ).fetchone()
    assert (row["account_class"], row["parent"]) == ("asset", "22")
    sc = conn.execute(
        "SELECT sc1_kind_id, sc2_kind_id, sc3_kind_id FROM accounts WHERE code = '531'"
    ).fetchone()
    assert sc[0] is not None and sc[1] is not None and sc[2] is None


def test_import_is_atomic(ledger, conn, tmp_path):
    cid = ledger.create_company("Импорт")
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "code;name;parent;kind;group;subconto\n10;Ок;;A;;\n11;Плохой;99;A;;\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="строка 3"):
        import_chart_csv(ledger, cid, bad)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_import_names_the_line_of_a_bad_value(ledger, tmp_path):
    cid = ledger.create_company("Импорт")
    bad = tmp_path / "bad.csv"
    bad.write_text("code;name;parent;group;subconto;currency\n10;Ок;;;;x\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="строка 2"):
        import_chart_csv(ledger, cid, bad)


def test_import_does_not_hide_a_program_error(ledger, tmp_path, monkeypatch):
    """A bug is not a mistake in the file: it must not turn into "file, line N"."""
    cid = ledger.create_company("Импорт")
    good = tmp_path / "good.csv"
    good.write_text("code;name;parent;group;subconto\n10;Ок;;;\n", encoding="utf-8")

    def broken(*args, **kwargs):
        raise TypeError("bug")

    monkeypatch.setattr(ledger, "add_account", broken)
    with pytest.raises(TypeError):
        import_chart_csv(ledger, cid, good)
