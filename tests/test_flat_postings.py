"""«Проводки для Excel»: the flat lines of a period with their subconto by kind and the
balances before it; the sheets a pivot is built on; the page with its one blue button.
Figures — the golden example of `conftest.py`, February 2026."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest
from PySide6.QtCore import Qt

from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.reports_page import FlatPostingsPage, export
from modern_gl.infrastructure.report_file import write_xlsx
from modern_gl.reporting.flat_excel import flat_tables
from modern_gl.reporting.flat_postings import Side, flat_postings
from tests.helpers.qt import running_app

FEBRUARY = ("2026-02-01", "2026-02-28")
# closing balances of February, Dt + / Kt − (conftest: hand-calculated ОСВ)
CLOSING = {
    "201": 140000,
    "221": 700000,
    "222": 200000,
    "301": -1000000,
    "531": -70000,
    "721": 30000,
}


def value_name(side: Side, kind_id: int) -> str:
    value = side.value(kind_id)
    return value.name if value else ""


def test_the_lines_of_the_period_with_subconto_by_kind(demo):
    flat = flat_postings(demo.ledger.conn, demo.company_id, *FEBRUARY)
    assert [k.name for k in flat.kinds] == ["Контрагенты"]
    kind = flat.kinds[0]
    assert [(line.doc_date, line.number, line.amount) for line in flat.lines] == [
        ("2026-02-03", 4, 50000),
        ("2026-02-04", 5, 200000),
        ("2026-02-20", 6, 30000),
    ]
    first = flat.lines[0]
    assert (first.debit.code, first.debit.name, first.debit.account_class) == (
        "201",
        "Материалы",
        "asset",
    )
    assert first.credit.code == "531" and value_name(first.credit, kind.id) == "Поставщик B"
    assert first.debit.value(kind.id) is None
    assert first.source == "Проводка" and first.author == "test"
    transfer = flat.lines[1]  # 222 and 221 are under the group 22
    assert (transfer.debit.top_code, transfer.debit.top_name) == ("22", "Банковские счета")
    assert flat.total == 280000  # the turnover of February


def test_the_balances_before_the_period_by_account_and_subconto(demo):
    flat = flat_postings(demo.ledger.conn, demo.company_id, *FEBRUARY)
    kind = flat.kinds[0].id
    opening = {(o.side.code, value_name(o.side, kind)): o.net for o in flat.opening}
    # 531 by supplier A: 1 200 came in, 1 000 was paid → 200 owed
    assert opening == {
        ("201", ""): 120000,
        ("221", ""): 900000,
        ("301", ""): -1000000,
        ("531", "Поставщик A"): -20000,
    }
    assert sum(o.net for o in flat.opening) == 0


def test_a_pivot_over_the_sides_gives_the_closing_balances(demo):
    """What a pivot does: sum «Сумма» by «Счёт» over «Стороны» — the ОСВ closing balances."""
    flat = flat_postings(demo.ledger.conn, demo.company_id, *FEBRUARY)
    postings, sides = flat_tables(flat, [])
    assert len(postings.rows) == 3
    assert len(sides.rows) == 4 + 2 * 3  # the balances, then both sides of each posting
    captions = [c.caption for c in sides.columns]
    account, amount = captions.index("Счёт"), captions.index("Сумма")
    by_account: dict[str, int] = defaultdict(int)
    for r in sides.rows:
        cell = r.cells[amount]
        by_account[str(r.cells[account])] += cell if isinstance(cell, int) else 0
    assert dict(by_account) == CLOSING
    assert sum(by_account.values()) == 0
    kind_column = captions.index("Контрагенты")
    suppliers = sorted({str(r.cells[kind_column]) for r in sides.rows} - {""})
    assert suppliers == ["Поставщик A", "Поставщик B"]
    # the balance lines: the day before the period, no document, Dt or Kt by the sign
    first = dict(zip(captions, sides.rows[0].cells, strict=True))
    assert (first["Дата"], first["№"], first["Вид строки"]) == ("2026-01-31", None, "Остаток")
    assert (first["Счёт"], first["Сумма"], first["Дт"], first["Кт"]) == (
        "201",
        120000,
        120000,
        None,
    )
    capital = dict(zip(captions, sides.rows[2].cells, strict=True))
    assert (capital["Счёт"], capital["Сумма"], capital["Дт"], capital["Кт"]) == (
        "301",
        -1000000,
        None,
        1000000,
    )


def test_the_file_is_two_flat_sheets_for_a_pivot(demo, tmp_path):
    flat = flat_postings(demo.ledger.conn, demo.company_id, *FEBRUARY)
    tables = flat_tables(flat, [("Период", "01.02 — 28.02.2026")])
    path = tmp_path / "flat.xlsx"
    write_xlsx(tables[0], path, tables[1:])
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == ["Проводки", "Стороны", "Параметры"]
    postings, sides = book.worksheets[:2]
    header = [c.value for c in postings[1]]
    assert header[:5] == ["Дата", "Год", "Месяц", "Квартал", "№"]
    assert {"Дт · Счёт", "Дт · Контрагенты", "Кт · Контрагенты", "Сумма", "Провёл"} <= set(header)
    assert "Уровень" not in header  # flat: no outline, nothing to group
    row = dict(zip(header, [c.value for c in postings[2]], strict=True))
    assert row["Дата"] == datetime(2026, 2, 3)
    assert postings.cell(2, 1).number_format == "DD.MM.YYYY"
    assert (row["Год"], row["Месяц"], row["Квартал"], row["№"]) == (2026, "2026-02", "2026-Q1", 4)
    assert row["Сумма"] == Decimal("500") and row["Дт · Счёт"] == "201"
    assert row["Кт · Контрагенты"] == "Поставщик B" and row["Дт · Контрагенты"] is None
    # an Excel table on each sheet: a pivot on it grows with the next export
    assert list(postings.tables) == ["Проводки"] and list(sides.tables) == ["Стороны"]
    assert postings.tables["Проводки"].ref == postings.dimensions
    assert postings.freeze_panes == "A2" and not postings.merged_cells.ranges
    amounts = [c.value for c in sides["Q"][1:]]  # «Сумма» of «Стороны»
    assert sides["Q1"].value == "Сумма" and sum(amounts) == 0
    about = book.worksheets[2]
    assert [about.cell(r, 2).value for r in (1, 2)] == ["Проводки", "01.02 — 28.02.2026"]


def test_a_folder_and_a_tag_get_columns_of_their_own(demo):
    led, cid = demo.ledger, demo.company_id
    kind = flat_postings(led.conn, cid, *FEBRUARY).kinds[0].id
    folder = led.add_subconto_group(cid, kind, "Местные")
    led.set_subconto_value_parent(cid, demo.supplier_b, folder)
    tag = led.add_tag(cid, "ƏDV")
    led.set_subconto_value_tags(cid, demo.supplier_b, [tag])
    flat = flat_postings(led.conn, cid, *FEBRUARY)
    assert (flat.kinds[0].folders, flat.kinds[0].tags) == (True, True)
    _, sides = flat_tables(flat, [])
    captions = [c.caption for c in sides.columns]
    assert captions[captions.index("Контрагенты") : captions.index("Контрагенты") + 3] == [
        "Контрагенты",
        "Контрагенты · папка",
        "Контрагенты · теги",
    ]
    credit_b = dict(zip(captions, sides.rows[5].cells, strict=True))  # Kt 531 [B] of №4
    assert (credit_b["Контрагенты"], credit_b["Контрагенты · папка"]) == ("Поставщик B", "Местные")
    assert credit_b["Контрагенты · теги"] == "ƏDV"


@pytest.fixture
def window(qtbot, tmp_path, make_demo):
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


def test_the_page_lists_the_postings_checks_them_and_saves_the_file(
    window, qtbot, tmp_path, monkeypatch
):
    window.open_catalog_report("flat_postings")
    page = window.stack.currentWidget()
    assert isinstance(page, FlatPostingsPage)
    qtbot.waitUntil(lambda: bool(page.model.rows))
    assert page.data is not None
    assert "✓" in page.footer.text() and page.footer.text().startswith("Проводок:")
    assert page.save_button.text() == "В Excel" and page.save_button.isEnabled()
    assert [i[0] for i in page.more_items() if i] == ["Колонки…", "Копировать для Excel  Ctrl+C"]
    assert page.header.subtitle.text()  # the period
    target = tmp_path / "out.xlsx"
    offered = []
    monkeypatch.setattr(
        export.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda _w, _t, path, _f: (offered.append(path) or str(target), "")),
    )
    monkeypatch.setattr(export.QDesktopServices, "openUrl", staticmethod(lambda url: True))
    qtbot.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
    assert offered[0].endswith(".xlsx") and "Проводки для Excel" in offered[0]
    book = openpyxl.load_workbook(target)
    assert book.sheetnames == ["Проводки", "Стороны", "Параметры"]
    postings = book.worksheets[0]
    assert postings.max_row == len(page.data.lines) + 1
    sides = book.worksheets[1]
    header = [c.value for c in sides[1]]
    amount = header.index("Сумма") + 1
    values = [sides.cell(r, amount).value for r in range(2, sides.max_row + 1)]
    assert sum(Decimal(str(v)) for v in values if v is not None) == 0
    # a double click: the document (a module's own page when a module made it)
    page.drill(page.model.rows[0])
    assert window.stack.currentWidget() is not page
