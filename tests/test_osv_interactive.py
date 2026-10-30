"""The trial balance opened by place (D-new-interactive-osv), as «Интерактивная ОСВ» for
1C 7.7: → splits the row under the cursor, Shift+→ asks by what, ← folds it, Ctrl+→
opens every account; a click on a caption sorts; «⋯» — one column, in thousands.

The books of test_subconto_report (60 = [Контрагенты, Договоры], 26 = [Статьи затрат]):
  1  20.02  Dt 26 [Аренда]      Ct 60 [Альфа, Д1]   1 000.00
  2  05.03  Dt 26 [Аренда]      Ct 60 [Альфа, Д2]     400.00
  3  10.03  Dt 60 [Альфа, Д1]   Ct 26 [Аренда]        300.00
  4  12.03  Dt 26 [Аренда]      Ct 60 [Бета, —]       200.00
March: 60 opening Ct 1 000, Dt 300 / Ct 600, closing Ct 1 300.
  by counterparty: Альфа 0/1 000 · 300/400 · 0/1 100;  Бета 0/0 · 0/200 · 0/200
  Альфа by corr: 26 — Dt 300 / Ct 400 (turnovers only)
  by corr: 26 — Dt 300 / Ct 600
February–March by months: февраль 0/0 · 0/1 000 · 0/1 000; март 0/1 000 · 300/600 · 0/1 300
"""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.catalog import Catalog
from modern_gl.desktop import theme
from modern_gl.desktop.reports_page import OsvPage, ReportParams
from modern_gl.desktop.reports_page.osv_tree import ExpandedRow
from modern_gl.desktop.session import Session
from tests.helpers.qt import running_app
from tests.test_subconto_report import books  # noqa: F401 the fixture

MARCH = ReportParams(date(2026, 3, 1), date(2026, 3, 31))
FEB_MARCH = ReportParams(date(2026, 2, 1), date(2026, 3, 31))


def cols(row):
    return (
        row.opening_dt,
        row.opening_ct,
        row.turnover_dt,
        row.turnover_ct,
        row.closing_dt,
        row.closing_ct,
    )


@pytest.fixture
def session(qtbot, books):  # noqa: F811 the fixture
    theme.apply(running_app())
    conn, ledger, cid, _ = books
    return Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _: None)


@pytest.fixture
def values(books) -> dict[str, int]:  # noqa: F811 the fixture
    *_, v = books
    return v


@pytest.fixture
def page(qtbot, session):
    page = OsvPage(session, MARCH)
    qtbot.addWidget(page)
    page.show()
    page.table.setFocus()  # the keys of the table reach it when it has the focus
    return page


def shown(page) -> list[tuple[str, str, tuple[int, ...]]]:
    """(code, name, figures) of every row as the table shows it."""
    return [(r.code, r.name.strip(), cols(r)) for r in page.model.rows]


def go(page, code: str) -> None:
    """The cursor on the row of an account."""
    for i, r in enumerate(page.model.rows):
        if r.code == code and not isinstance(r, ExpandedRow):
            page.table.setCurrentIndex(page.model.index(i, 0))
            return
    raise AssertionError(code)


def test_right_opens_an_account_by_its_counterparties_and_left_folds_it(page, qtbot, values):
    v = values
    go(page, "60")
    qtbot.keyClick(page.table, Qt.Key.Key_Right)
    assert shown(page)[2:5] == [
        ("", "Альфа", (0, 100_000, 30_000, 40_000, 0, 110_000)),
        ("", "Бета", (0, 0, 0, 20_000, 0, 20_000)),
        ("", "Итого", (100_000, 100_000, 90_000, 90_000, 130_000, 130_000)),
    ]
    alpha = page.model.rows[2]
    assert isinstance(alpha, ExpandedRow)
    assert (alpha.steps, alpha.subconto, alpha.depth) == ((("sc1", v["Альфа"]),), (v["Альфа"],), 1)
    assert page.table.currentIndex().row() == 1  # the cursor stays on 60
    # → on an open row steps onto its first row; ← on that row goes back up
    qtbot.keyClick(page.table, Qt.Key.Key_Right)
    assert page.table.currentIndex().row() == 2
    qtbot.keyClick(page.table, Qt.Key.Key_Left)
    assert page.table.currentIndex().row() == 1
    qtbot.keyClick(page.table, Qt.Key.Key_Left)
    assert [name for _, name, _ in shown(page)] == [
        "Общехозяйственные расходы",
        "Расчёты с поставщиками и подрядчиками",
        "Итого",
    ]


def test_a_row_opens_again_by_the_next_kind_down_to_the_corr_accounts(page, qtbot, values):
    v = values
    sixty = page.s.catalog.by_code["60"].id
    page.open_node((sixty, ()), "sc1")
    page.select((sixty, (("sc1", v["Альфа"]),)))
    qtbot.keyClick(page.table, Qt.Key.Key_Right)  # the contracts of Альфа
    assert shown(page)[2:6] == [
        ("", "Альфа", (0, 100_000, 30_000, 40_000, 0, 110_000)),
        ("", "Д1", (0, 100_000, 30_000, 0, 0, 70_000)),
        ("", "Д2", (0, 0, 0, 40_000, 0, 40_000)),
        ("", "Бета", (0, 0, 0, 20_000, 0, 20_000)),
    ]
    page.select((sixty, (("sc1", v["Альфа"]), ("sc2", v["Д1"]))))
    qtbot.keyClick(page.table, Qt.Key.Key_Right)  # no subconto left: the corr accounts
    row = page.model.rows[4]
    assert (row.code, row.name.strip(), cols(row)) == (
        "26",
        "Общехозяйственные расходы",
        (0, 0, 30_000, 0, 0, 0),
    )
    assert row.depth == 3 and row.name.startswith("   " * 3)
    # a corr row has nothing more to split by in a one-month period
    page.select(row.key)
    assert page.kinds_at(row.key, page.s.catalog.by_code["60"]) == []


def test_the_menu_of_kinds_names_the_directories(page):
    sixty = page.s.catalog.by_code["60"]
    assert page.kinds_at((sixty.id, ()), sixty) == [
        ("sc1", "Контрагенты"),
        ("sc2", "Договоры"),
        ("corr", "Корсчета"),
    ]
    menu = page.kinds_menu((sixty.id, ()), sixty)
    assert menu is not None
    assert [a.text() for a in menu.actions()] == ["Контрагенты", "Договоры", "Корсчета"]
    menu.actions()[2].trigger()  # by the corr accounts at once
    assert shown(page)[2:3] == [("26", "Общехозяйственные расходы", (0, 0, 30_000, 60_000, 0, 0))]
    menu.deleteLater()


def test_two_months_split_by_months_and_a_month_row_opens_its_card(qtbot, session):
    page = OsvPage(session, FEB_MARCH)
    qtbot.addWidget(page)
    sixty = session.catalog.by_code["60"]
    assert page.months() == 2
    assert page.kinds_at((sixty.id, ()), sixty)[-1] == ("month", "По месяцам")
    page.open_node((sixty.id, ()), "month")
    assert shown(page)[2:4] == [
        ("", "февраль 2026", (0, 0, 0, 100_000, 0, 100_000)),
        ("", "март 2026", (0, 100_000, 30_000, 60_000, 0, 130_000)),
    ]
    opened = []
    page.open_report.connect(lambda kind, account, params: opened.append((kind, account, params)))
    page.drill(page.model.rows[3])
    ((kind, account, params),) = opened
    assert (kind, account, params.date_from, params.date_to) == (
        "card",
        sixty.id,
        date(2026, 3, 1),
        date(2026, 3, 31),
    )


def test_ctrl_right_opens_every_account_and_ctrl_left_folds_all(page, qtbot):
    qtbot.keyClick(page.table, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert [name for _, name, _ in shown(page)] == [
        "Общехозяйственные расходы",
        "Аренда",
        "Расчёты с поставщиками и подрядчиками",
        "Альфа",
        "Бета",
        "Итого",
    ]
    qtbot.keyClick(page.table, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert [name for _, name, _ in shown(page)] == [
        "Общехозяйственные расходы",
        "Расчёты с поставщиками и подрядчиками",
        "Итого",
    ]


def test_what_is_open_stays_open_through_a_refresh_and_a_subconto_view(page, values):
    v = values
    sixty = page.s.catalog.by_code["60"].id
    page.open_node((sixty, (("sc1", v["Альфа"]),)), "corr")
    page.expand.setChecked(True)  # the «Субконто» view: the whole tree, Альфа by corr
    assert [name for _, name, _ in shown(page)] == [
        "Общехозяйственные расходы",
        "Аренда",
        "Расчёты с поставщиками и подрядчиками",
        "Альфа",
        "Общехозяйственные расходы",
        "Бета",
        "<не указано>",
        "Итого",
    ]
    page.refresh()  # read again: the same rows
    assert len(page.model.rows) == 8
    assert page.model.rows[4].code == "26"


def test_a_click_on_a_caption_sorts_siblings_up_then_down_then_as_the_chart(page, qtbot):
    page.expand.setChecked(True)
    captions = page.table.horizontalHeader()
    closing_ct = len(page.model.columns) - 1
    captions.sectionClicked.emit(closing_ct)
    assert [name for _, name, _ in shown(page)] == [
        "Общехозяйственные расходы",
        "Аренда",
        "Расчёты с поставщиками и подрядчиками",
        "Бета",
        "<не указано>",
        "Альфа",
        "Д2",
        "Д1",
        "Итого",
    ]
    assert captions.sortIndicatorSection() == closing_ct
    captions.sectionClicked.emit(closing_ct)  # down: the largest first
    assert [name for _, name, _ in shown(page)][:3] == [
        "Расчёты с поставщиками и подрядчиками",
        "Альфа",
        "Д1",
    ]
    assert captions.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    captions.sectionClicked.emit(closing_ct)  # off
    assert [name for _, name, _ in shown(page)][:3] == [
        "Общехозяйственные расходы",
        "Аренда",
        "Расчёты с поставщиками и подрядчиками",
    ]
    assert captions.sortIndicatorSection() == -1
    captions.sectionClicked.emit(1)  # by name
    assert [name for _, name, _ in shown(page)][:3] == [
        "Общехозяйственные расходы",
        "Аренда",
        "Расчёты с поставщиками и подрядчиками",
    ]
    captions.sectionClicked.emit(0)  # the account column: the chart's order
    assert page.sort is None


def test_one_column_of_balances_and_figures_in_thousands(page, qtbot):
    page.toggle_net()
    titles = [c.title for c in page.model.columns]
    assert titles == ["Счёт", "Наименование", "Сальдо на начало", "Дт", "Кт", "Сальдо на конец"]
    sixty = next(i for i, r in enumerate(page.model.rows) if r.code == "60")
    texts = [page.model.index(sixty, c).data() for c in range(2, 6)]
    assert texts == ["(1 000.00)", "300.00", "600.00", "(1 300.00)"]  # a credit in brackets
    page.set_scale(1000)
    assert [page.model.index(sixty, c).data() for c in range(2, 6)] == ["(1)", "", "1", "(1)"]
    page.set_scale(1)
    page.toggle_net()
    assert len(page.model.columns) == 8
    # remembered for the next time
    again = OsvPage(page.s, MARCH)
    qtbot.addWidget(again)
    assert (again.net, again.model.scale) == (False, 1)


def test_the_more_menu_marks_the_view(page):
    texts = [item[0] for item in page.more_items() if item]
    assert texts[:5] == [
        "    По разделам",
        "    Одной колонкой",
        "✓  С копейками",
        "    В тысячах",
        "    В миллионах",
    ]
    assert page.footer.text().endswith("Ctrl+→ — развернуть все")
