"""Saved views of the trial balance (D190): the page as it is — how
deep, the splits under the accounts, the order, one column, the precision — kept under a
name in the company's file; «⋯ → Вид „…“» puts it back. The books of
test_subconto_report."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QInputDialog

from modern_gl.application import queries
from modern_gl.application.catalog import Catalog
from modern_gl.desktop import theme
from modern_gl.desktop.reports_page import OsvPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import NotFoundError, ValidationError
from tests.helpers.contract_books import contract_books
from tests.helpers.qt import running_app


@pytest.fixture
def books():
    conn, ledger, cid, v = contract_books()
    yield conn, ledger, cid, v
    conn.close()


MARCH = ReportParams(date(2026, 3, 1), date(2026, 3, 31))


def test_a_view_is_saved_replaced_by_name_and_deleted(books):
    conn, ledger, cid, _ = books
    first = ledger.save_report_view(cid, "osv", "Клиенты", {"net": True, "opened": []})
    ledger.save_report_view(cid, "osv", "Банки", {"net": False})
    assert [(v.name, v.settings) for v in queries.report_views(conn, cid, "osv")] == [
        ("Банки", {"net": False}),
        ("Клиенты", {"net": True, "opened": []}),
    ]
    same = ledger.save_report_view(cid, "osv", "клиенты", {"net": False})  # the same name
    assert same == first
    assert [v.name for v in queries.report_views(conn, cid, "osv")] == ["Банки", "клиенты"]
    assert queries.report_views(conn, cid, "card") == []  # of another report
    ledger.delete_report_view(cid, first)
    assert [v.name for v in queries.report_views(conn, cid, "osv")] == ["Банки"]
    with pytest.raises(NotFoundError):
        ledger.delete_report_view(cid, first)
    with pytest.raises(ValidationError, match="пустым"):
        ledger.save_report_view(cid, "osv", "  ", {})


@pytest.fixture
def session(qtbot, books):
    theme.apply(running_app())
    conn, ledger, cid, _ = books
    return Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _: None)


def names(page) -> list[str]:
    return [r.name.strip() for r in page.model.rows]


def test_the_page_is_saved_as_a_view_and_put_back(qtbot, session, monkeypatch, books):
    *_, v = books
    page = OsvPage(session, MARCH)
    qtbot.addWidget(page)
    sixty = session.catalog.by_code["60"].id
    page.open_node((sixty, ()), "sc1")
    page.open_node((sixty, (("sc1", v["Альфа"]),)), "corr")
    page.toggle_net()
    page.sort_by(len(page.model.columns) - 1)  # by the closing balance, up: credits first
    page.set_scale(1000)
    before = names(page)
    assert before == [
        "Расчёты с поставщиками и подрядчиками",
        "Альфа",
        "Общехозяйственные расходы",
        "Бета",
        "Общехозяйственные расходы",
        "Итого",
    ]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Клиенты", True)))
    page.views.save()
    assert page.views.current == "Клиенты"
    assert page.header.subtitle.text().endswith("вид «Клиенты»")
    assert queries.report_views(session.conn, session.company_id, "osv")[0].settings == {
        "detail": "sub",
        "currency": False,
        "sections": False,
        "net": True,
        "scale": 1000,
        "sort": ["closing", False],
        "opened": [[sixty, [], "sc1"], [sixty, [["sc1", v["Альфа"]]], "corr"]],
    }
    # another page, as made: nothing open; the view puts everything back
    again = OsvPage(session, MARCH)
    qtbot.addWidget(again)
    again.toggle_net()  # the one-column choice is remembered on its own: back to pairs
    assert names(again) == [
        "Общехозяйственные расходы",
        "Расчёты с поставщиками и подрядчиками",
        "Итого",
    ]
    items = [item for item in again.more_items() if item]
    texts = [text for text, _ in items]
    assert "    Вид «Клиенты»" in texts and "Сохранить вид…" in texts
    assert not any(text.startswith("Удалить вид") for text in texts)
    next(fn for text, fn in items if text == "    Вид «Клиенты»")()
    assert names(again) == before
    assert (again.net, again.model.scale, again.sort) == (True, 1000, ("closing", False))
    assert again.views.current == "Клиенты"
    texts = [item[0] for item in again.more_items() if item]
    assert "✓  Вид «Клиенты»" in texts and "Удалить вид «Клиенты»" in texts
    again.views.delete()
    assert queries.report_views(session.conn, session.company_id, "osv") == []
    assert again.views.current is None
    assert not again.header.subtitle.text().endswith("»")


def test_viewing_only_lists_the_views_without_saving(qtbot, session, books):
    _conn, ledger, cid, _ = books
    ledger.save_report_view(cid, "osv", "Клиенты", {"detail": "top"})
    session.read_only = True
    page = OsvPage(session, MARCH)
    qtbot.addWidget(page)
    texts = [item[0] for item in page.views.items() if item]
    assert texts == ["    Вид «Клиенты»"]
