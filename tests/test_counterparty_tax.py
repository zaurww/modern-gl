"""VÖEN of a counterparty; a non-resident has a country and its own tax number instead."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.quick_entry import suggest
from modern_gl.desktop import theme
from modern_gl.desktop.directories_page import DirectoriesPage, ValueDialog
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect


@pytest.fixture
def books():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    cp = ledger.subconto_kind_id(cid, "counterparty")
    yield conn, ledger, cid, cp
    conn.close()


def test_resident_vöen_is_ten_digits(books):
    conn, ledger, cid, cp = books
    alfa = ledger.add_subconto_value(cid, cp, "Альфа MMC")
    ledger.set_subconto_value_tax(cid, alfa, " 1234 567 890 ")
    assert Catalog(conn, cid).value(alfa).tax_id == "1234567890"
    for wrong in ("123456789", "12345678901", "12345A7890"):
        with pytest.raises(ValidationError, match="VÖEN"):
            ledger.set_subconto_value_tax(cid, alfa, wrong)
    ledger.set_subconto_value_tax(cid, alfa, None)  # an individual without a VÖEN
    assert Catalog(conn, cid).value(alfa).tax_id is None


def test_nonresident_keeps_its_own_number_and_country(books):
    conn, ledger, cid, cp = books
    acme = ledger.add_subconto_value(cid, cp, "Acme Inc")
    ledger.set_subconto_value_tax(cid, acme, "  12-3456789 ", nonresident=True, country="ABŞ")
    v = Catalog(conn, cid).value(acme)
    assert (v.tax_id, v.nonresident, v.country) == ("12-3456789", True, "ABŞ")
    ledger.set_subconto_value_tax(cid, acme, "1234567890", country="ABŞ")  # resident again
    v = Catalog(conn, cid).value(acme)
    assert (v.tax_id, v.nonresident, v.country) == ("1234567890", False, None)


def test_counterparty_is_found_by_its_vöen(books):
    conn, ledger, cid, cp = books
    alfa = ledger.add_subconto_value(cid, cp, "Альфа MMC")
    beta = ledger.add_subconto_value(cid, cp, "Бета")
    ledger.set_subconto_value_tax(cid, alfa, "1234567890")
    ledger.set_subconto_value_tax(cid, beta, "9876543210")
    cat = Catalog(conn, cid)
    assert cat.value(alfa).label == "Альфа MMC  ·  1234567890"
    assert cat.resolve_value(cp, "1234567890") == alfa
    assert cat.resolve_value(cp, "98765") == beta
    assert cat.resolve_value(cp, "Альфа MMC  ·  1234567890") == alfa  # picked from the list
    assert cat.resolve_value(cp, "альфа") == alfa
    assert cat.same_tax_id(cp, "1234567890") == ["Альфа MMC"]
    assert cat.same_tax_id(cp, "1234567890", except_id=alfa) == []
    # the quick entry line finds it by the VÖEN and puts the name
    found = suggest("60 98765", 8, cat)
    assert [i.insert for i in found.items][:1] == ["Бета, "]


@pytest.fixture
def session(qtbot, books, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    theme.apply(QApplication.instance())
    conn, ledger, cid, _ = books
    messages: list[str] = []
    return Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=messages.append)


def test_directory_dialog_asks_vöen_or_country(session, qtbot, monkeypatch):
    page = DirectoriesPage(session)
    qtbot.addWidget(page)
    cp = session.ledger.subconto_kind_id(session.company_id, "counterparty")
    page.refresh(select_kind=cp)

    def foreign(dialog: ValueDialog) -> int:
        assert dialog.nonresident is not None and dialog.tax_id and dialog.country
        dialog.name.setText("Acme Inc")
        assert dialog.country.isHidden()  # a resident has no country
        dialog.nonresident.setChecked(True)
        assert not dialog.country.isHidden()
        dialog.tax_id.setText("DE 123456789")
        dialog.country.setText("Almaniya")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", foreign)
    page.add_value(cp)
    acme = next(v for v in session.catalog.all_values(cp) if v.name == "Acme Inc")
    assert (acme.tax_id, acme.nonresident, acme.country) == ("DE 123456789", True, "Almaniya")
    row = next(
        r for r in range(page.model.rowCount()) if page.model.index(r, 0).data() == "Acme Inc"
    )
    assert page.model.index(row, 1).data() == "Almaniya  ·  DE 123456789"

    def resident(dialog: ValueDialog) -> int:
        assert dialog.tax_id is not None
        dialog.name.setText("Альфа")
        dialog.tax_id.setText("1234 567 890")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", resident)
    page.add_value(cp)
    alfa = next(v for v in session.catalog.all_values(cp) if v.name == "Альфа")
    assert (alfa.tax_id, alfa.nonresident) == ("1234567890", False)


def test_same_vöen_twice_is_asked_about(session, qtbot, monkeypatch):
    page = DirectoriesPage(session)
    qtbot.addWidget(page)
    cid = session.company_id
    cp = session.ledger.subconto_kind_id(cid, "counterparty")
    alfa = session.ledger.add_subconto_value(cid, cp, "Альфа")
    session.ledger.set_subconto_value_tax(cid, alfa, "1234567890")
    session.catalog.reload()
    asked: list[str] = []

    def no(_parent, _title, text, *a, **k):
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(no))

    def branch(dialog: ValueDialog) -> int:
        assert dialog.tax_id is not None
        dialog.name.setText("Альфа, филиал")
        dialog.tax_id.setText("1234567890")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", branch)
    page.add_value(cp)
    assert asked and "Альфа" in asked[0]
    assert all(v.name != "Альфа, филиал" for v in session.catalog.all_values(cp))


def test_subconto_report_shows_vöen_once_there_is_one(session, qtbot):
    from datetime import date

    from modern_gl.application.ledger import PostingInput
    from modern_gl.desktop.reports_page import ReportParams, SubcontoPage

    s, cid = session, session.company_id
    cp = s.ledger.subconto_kind_id(cid, "counterparty")
    rent = s.ledger.add_subconto_value(cid, s.ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    alfa = s.ledger.add_subconto_value(cid, cp, "Альфа")
    deal = s.ledger.add_subconto_value(
        cid, s.ledger.subconto_kind_id(cid, "contract"), "Д1", owner_id=alfa
    )
    acc = s.catalog.by_code
    s.ledger.post_new(
        cid, "2026-03-05", [PostingInput(acc["26"].id, acc["60"].id, "400", (rent,), (alfa, deal))]
    )
    s.catalog.reload()
    params = ReportParams(date(2026, 3, 1), date(2026, 3, 31))
    page = SubcontoPage(s, acc["60"].id, params)
    qtbot.addWidget(page)
    page.build()
    assert page.model.headerData(1, Qt.Orientation.Horizontal) != "VÖEN"  # nobody has one
    s.ledger.set_subconto_value_tax(cid, alfa, "1234567890")
    s.catalog.reload()
    page.build()
    assert page.model.headerData(1, Qt.Orientation.Horizontal) == "VÖEN"
    assert page.model.index(0, 1).data() == "1234567890"
