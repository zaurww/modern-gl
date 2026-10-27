"""Shared from test_statements.py (moved here: other test modules use it too)."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from tests.helpers.qt import running_app


@pytest.fixture(name="statements_books")
def books(ledger: Ledger):
    cid = ledger.create_company("Тест")
    cp = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    a, b, c = (ledger.add_subconto_value(cid, cp, n) for n in ("A", "B", "C"))
    acc = {}
    for code, kind, extra in [
        ("50", "cash", {}),
        ("51", "bank", {}),
        ("01", "fixed_asset", {}),
        ("02", "fixed_asset", {"contra": True}),
        ("41", "inventory", {}),
        ("60", "payable", {"subconto": [cp], "two_sided": True}),
        ("62", "receivable", {"subconto": [cp], "two_sided": True}),
        ("80", "share_capital", {}),
        ("90.1", "sales", {}),
        ("90.2", "cost_of_sales", {}),
        ("26", "operating_expense", {}),
        ("91.1", "other_income", {}),
        ("99", "profit_loss", {}),
    ]:
        acc[code] = ledger.add_account(cid, code, code, account_type=kind, **extra)
    acc["76"] = ledger.add_account(cid, "76", "76", account_class="liability")

    def p(dt, ct, amount, dt_sc=(), ct_sc=()):
        return PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)

    for day, posting in [
        ("2026-01-15", p("51", "80", "10000")),
        ("2026-01-20", p("01", "60", "3000", ct_sc=[a])),
        ("2026-01-25", p("60", "51", "500", dt_sc=[b])),
        ("2026-02-01", p("41", "60", "2000", ct_sc=[a])),
        ("2026-02-10", p("62", "90.1", "4000", dt_sc=[c])),
        ("2026-02-10", p("90.2", "41", "1500")),
        ("2026-02-12", p("51", "62", "1000", ct_sc=[c])),
        ("2026-02-15", p("26", "02", "100")),
        ("2026-02-20", p("26", "76", "300")),
        ("2026-02-25", p("50", "91.1", "50")),
        ("2026-02-28", p("90.1", "99", "4000")),
        ("2026-02-28", p("99", "90.2", "1500")),
    ]:
        ledger.post_new(cid, day, [posting])
    return ledger.conn, cid


def shown(statement) -> list[tuple[str, int | None]]:
    return [(ln.title, ln.amount if ln.kind != "heading" else None) for ln in statement.lines]


def code(line) -> str:
    """An account line by its code («62  62» — the test accounts are named by code)."""
    return line.title.split()[0] if line.kind == "account" else line.title


@pytest.fixture(name="statements_window")
def window(qtbot, tmp_path, monkeypatch, make_demo):

    from PySide6.QtWidgets import QMessageBox

    from modern_gl.application.workspace import Workspace
    from modern_gl.desktop import theme
    from modern_gl.desktop.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(running_app())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    assert win.session is not None
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()
