"""Faster entry in the document form: recent elements first, the memo of the last
posting with the same pair, "#template" in the Dt cell, arithmetic in amounts,
Ctrl+Shift+Enter posts and starts the next document."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import last_memo, recent_subconto
from modern_gl.desktop import theme
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.postings import AMOUNT, CT, DT, MEMO
from modern_gl.desktop.session import Session
from modern_gl.domain import formula
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import connect


@pytest.fixture
def s(qtbot):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    kind = ledger.subconto_kind_id(cid, "counterparty")
    contract = ledger.subconto_kind_id(cid, "contract")
    ids = {name: ledger.add_subconto_value(cid, kind, name) for name in ("Альфа", "Бета", "Гамма")}
    ids["Договор"] = ledger.add_subconto_value(cid, contract, "Договор")
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda m: None)
    session.working_date = date(2026, 3, 5)
    session.ids = ids  # type: ignore[attr-defined]
    yield session
    conn.close()


def pay(s, who: str, memo: str = "", doc_memo: str = "") -> None:
    cat = s.catalog
    s.ledger.post_new(
        s.company_id,
        "2026-03-01",
        [
            PostingInput(
                cat.by_code["80"].id,
                cat.by_code["60"].id,
                "10",
                (None,),
                (s.ids[who], s.ids["Договор"]),
                memo,
            )
        ],
        doc_memo,
    )


def test_recent_elements_and_last_memo(s):
    cat = s.catalog
    acc60, acc80 = cat.by_code["60"].id, cat.by_code["80"].id
    pay(s, "Гамма", doc_memo="Услуги")
    pay(s, "Альфа", memo="Аренда")
    assert recent_subconto(s.conn, s.company_id, acc60, 1) == [s.ids["Альфа"], s.ids["Гамма"]]
    assert last_memo(s.conn, s.company_id, acc80, acc60) == "Аренда"
    assert last_memo(s.conn, s.company_id, acc60, acc80) == ""


def test_subconto_list_starts_with_recent_ones(s, qtbot):
    pay(s, "Гамма")
    page = DocumentPage(s)
    qtbot.addWidget(page)
    m = page.model
    m.setData(m.index(0, CT), s.catalog.by_code["60"].id)
    items = page.delegate._subconto_items(m, 0, CT + 1)
    assert items == ["Гамма", "Альфа", "Бета"]


def test_memo_cell_offers_the_last_memo(s, qtbot):
    pay(s, "Альфа", memo="Аренда офиса")
    page = DocumentPage(s)
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    qtbot.waitUntil(page.isActiveWindow)
    m = page.model
    m.setData(m.index(0, DT), s.catalog.by_code["80"].id)
    m.setData(m.index(0, CT), s.catalog.by_code["60"].id)
    page.table.setCurrentIndex(m.index(0, MEMO))
    page.table.edit(m.index(0, MEMO))
    editor = QApplication.focusWidget()
    assert editor.text() == "Аренда офиса" and editor.selectedText() == "Аренда офиса"
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert m.rows[0].memo == "Аренда офиса"


def test_amount_may_be_arithmetic(s, qtbot):
    assert formula.evaluate("1180*18/118") == 18_000
    assert formula.evaluate("=1000+180") == 118_000
    with pytest.raises(ValidationError):
        formula.evaluate("S*2")
    page = DocumentPage(s)
    qtbot.addWidget(page)
    assert page.model.parse(0, AMOUNT, "1180*18/118") == 18_000


def test_hash_in_dt_cell_inserts_a_template(s, qtbot):
    page = DocumentPage(s)
    qtbot.addWidget(page)
    m = page.model
    page.delegate.template_chosen.disconnect()  # call directly, not through the timer
    page.insert_template(0, template_id("Реализация с НДС", s))
    assert [r.formula for r in m.rows] == ["S", "S*18/118"]
    assert page.amount.isVisibleTo(page)
    page.amount.setText("1180")
    page.amount.textEdited.emit("1180")
    assert [r.amount for r in m.rows] == [118_000, 18_000]


def test_template_after_other_lines_keeps_its_references(s, qtbot):
    page = DocumentPage(s)
    qtbot.addWidget(page)
    m = page.model
    m.setData(m.index(0, DT), s.catalog.by_code["50"].id)
    m.setData(m.index(0, CT), s.catalog.by_code["80"].id)
    m.setData(m.index(0, AMOUNT), 500)
    m.insert_row()
    page.insert_template(1, template_id("Покупка товаров с НДС", s))
    assert [r.formula for r in m.rows] == ["", "S-L3", "S*18/118"]  # L2 -> L3
    page.amount.setText("1180")
    page.amount.textEdited.emit("1180")
    assert [r.amount for r in m.rows] == [500, 100_000, 18_000]


def test_typing_hash_picks_the_template(s, qtbot):
    page = DocumentPage(s)
    qtbot.addWidget(page)
    chosen = []
    page.delegate.template_chosen.disconnect()
    page.delegate.template_chosen.connect(lambda row, tid: chosen.append((row, tid)))
    editor = page.delegate.createEditor(page.table.viewport(), None, page.model.index(0, DT))
    editor.setText("#реализ")
    page.delegate.setModelData(editor, page.model, page.model.index(0, DT))
    assert chosen == [(0, template_id("Реализация с НДС", s))]


def test_ctrl_shift_enter_posts_and_asks_for_the_next(s, qtbot):
    page = DocumentPage(s)
    qtbot.addWidget(page)
    m = page.model
    m.setData(m.index(0, DT), s.catalog.by_code["50"].id)
    m.setData(m.index(0, CT), s.catalog.by_code["80"].id)
    m.setData(m.index(0, AMOUNT), 500)
    m.setData(m.index(0, MEMO), "Взнос")
    asked = []
    page.new_requested.connect(lambda: asked.append(True))
    page.post_and_new()
    assert page.doc.status == "posted" and asked == [True]
    assert page.doc.memo == "Взнос"  # an empty title takes the first posting's memo


def template_id(name: str, s) -> int:
    from modern_gl.application.queries import list_templates

    return next(t.id for t in list_templates(s.conn, s.company_id) if t.name == name)
