"""Columns of a report moved and widened with the mouse are remembered for its kind (D116,
`reports_page/column_choice`): a Dt/Kt pair moves whole, the first column stays first, a
column new in the report keeps its place; «Колонки по умолчанию» forgets it all."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.desktop import theme
from modern_gl.desktop.reports_page import ReportParams, SubcontoPage
from modern_gl.desktop.reports_page.column_choice import ColumnChoice
from modern_gl.desktop.reports_page.table import Column, GroupHeader
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.db import connect
from tests.helpers.qt import running_app


def col(title: str, group: str = "") -> Column:
    return Column(title, lambda r: r, group=group)


def titles(columns: list[Column]) -> list[str]:
    return [f"{c.group}:{c.title}" if c.group else c.title for c in columns]


def test_the_order_puts_the_known_columns_in_their_places():
    """Known ones fill the places of the known ones in the user's order; one the order
    does not know stays where the report puts it; a pair stays together."""
    choice = ColumnChoice("test", lambda: None)
    report = [col("Счёт"), col("A"), col("Dt", "Обороты"), col("Kt", "Обороты"), col("B")]
    assert choice.arrange(report) == report  # nothing moved
    choice.move(["B", "Обороты", "A"])
    assert titles(choice.arrange(report)) == ["Счёт", "B", "Обороты:Dt", "Обороты:Kt", "A"]
    choice.move(["B", "A"])  # «Обороты» unknown: it keeps its place, the rest swap
    assert titles(choice.arrange(report)) == ["Счёт", "B", "Обороты:Dt", "Обороты:Kt", "A"]


@pytest.fixture
def page(qtbot):
    theme.apply(running_app())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    s = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _: None)
    alfa = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "counterparty"), "Альфа")
    item = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    acc = s.catalog.by_code
    ledger.post_new(
        cid, "2026-03-05", [PostingInput(acc["26"].id, acc["60"].id, "400", (item,), (alfa,))]
    )
    s.catalog.reload()

    def make() -> SubcontoPage:
        made = SubcontoPage(s, acc["60"].id, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
        qtbot.addWidget(made)
        made.resize(1200, 600)
        made.build()
        made.table.layout_columns()
        return made

    yield make
    conn.close()


def groups(page: SubcontoPage) -> list[str]:
    return [c.group or c.title for c in page.model.columns]


def test_a_caption_dragged_moves_its_pair_and_is_remembered(page):
    first = page()
    before = groups(first)
    assert before[1:3] == ["Сальдо на начало"] * 2 and before[-2:] == ["Сальдо на конец"] * 2
    header = first.table.horizontalHeader()
    header.moveSection(len(before) - 1, 1)  # the end balance's Kt dragged to the front
    after = groups(first)
    assert after[1:3] == ["Сальдо на конец"] * 2  # with its Dt
    assert after[0] == before[0] and sorted(after) == sorted(before)
    assert [header.logicalIndex(v) for v in range(header.count())] == list(range(len(after)))
    assert groups(page()) == after  # another report of the kind: the same order

    header.moveSection(1, 0)  # the first column stays first
    assert groups(first) == after
    first.columns_choice().reset()
    first.build()
    assert groups(first) == before


def test_a_width_given_with_the_mouse_is_kept(page):
    first = page()
    header = first.table.horizontalHeader()
    assert isinstance(header, GroupHeader)
    header.resizeSection(1, 333)  # the program's own fitting is not remembered
    assert not first.columns_choice().widths()
    header.held = True  # the user drags the edge of the name column
    header.resizeSection(0, 90)
    header.held = False
    header.released.emit()
    assert first.columns_choice().widths() == {first.model.columns[0].title: 90}

    second = page()
    assert second.table.columnWidth(0) == 90  # not widened to its text
    second.resize(500, 600)  # a narrow window does not take it back either
    assert second.table.columnWidth(0) == 90
    title = second.model.headerData(0, Qt.Orientation.Horizontal)
    assert title == first.model.columns[0].title

    second.columns_choice().reset()
    assert not second.columns_choice().widths()
    assert page().table.columnWidth(0) != 90
