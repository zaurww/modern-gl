"""One counterparty is not entered twice (D231): a name typed as new that
the directory has — İ/I, case, quotes, «MMC» or the legal form in full apart — takes the
one there. Two names with different VÖEN stay two (a branch, a namesake)."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QWidget

from modern_gl.application.catalog import Catalog
from modern_gl.application.counterparties import entered_already, plain_name
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.directories_page import ValueDialog, new_value
from modern_gl.desktop.session import Session
from tests.helpers.bank_ui import setup_company
from tests.helpers.entry_keys import items, shown_list, type_text
from tests.helpers.uniform_entry import shown

ALFA_TIN = "1234567890"  # «ALFA MMC» of the bank helper


@pytest.fixture
def told():
    return []


@pytest.fixture
def session(conn, ledger, told):
    cid = setup_company(ledger)
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), notify=told.append)
    s.working_date = date(2026, 3, 5)
    return s


def partners(session) -> list[tuple[str, str | None]]:
    kind = session.ledger.subconto_kind_id(session.company_id, "counterparty")
    rows = session.conn.execute(
        "SELECT name, tax_id FROM subconto_values WHERE company_id = ? AND kind_id = ? ORDER BY id",
        (session.company_id, kind),
    )
    return [(r["name"], r["tax_id"]) for r in rows]


def alfa(session) -> int:
    return session.conn.execute(
        "SELECT id FROM subconto_values WHERE tax_id = ?", (ALFA_TIN,)
    ).fetchone()["id"]


def test_one_name_written_five_ways():
    same = {
        plain_name(text)
        for text in (
            "AUTOUNİVERSAL MMC",
            "AUTOUNIVERSAL MMC",
            "Autouniversal  mmc",
            '"AUTOUNİVERSAL" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ',
            "«Autouniversal» MMC",
        )
    }
    assert len(same) == 1
    assert plain_name("AUTOUNIVERSAL SERVIS MMC") not in same


def test_who_is_entered_already(session):
    conn, cid = session.conn, session.company_id
    assert entered_already(conn, cid, '"Alfa" MMC') == alfa(session)
    assert entered_already(conn, cid, "alfa mmc", ALFA_TIN) == alfa(session)
    assert entered_already(conn, cid, "ALFA MMC", "9999999999") is None  # another VÖEN
    assert entered_already(conn, cid, "ALFA") is None  # another name
    session.ledger.set_subconto_value_active(cid, alfa(session), False)
    assert entered_already(conn, cid, "ALFA MMC") is None  # hidden: not offered for entry


def test_a_name_added_from_the_list_takes_the_one_there(qtbot, session, told):
    """«"Alfa" MMC» typed in the bank form: the list does not find it with the quotes and
    offers to add — the directory's «ALFA MMC» is taken, nobody is added."""
    before = partners(session)
    page = shown(qtbot, BankOperationPage(session))
    box = page.counterparty_edit
    box.setFocus()
    type_text(box, '"Alfa" MMC')
    popup = shown_list(qtbot)
    assert items(popup) == ['+ Добавить «"Alfa" MMC»']
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert page.counterparty == alfa(session)
    assert partners(session) == before
    assert told == ["«ALFA MMC» уже есть в справочнике — взят он"]


def typed_in_the_window(monkeypatch, name: str, tin: str) -> None:
    def exec_(dialog):
        dialog.name.setText(name)
        dialog.tax_id.setText(tin)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", exec_)


def test_the_window_takes_the_one_there_and_gives_it_the_voen(qtbot, session, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)
    """«Beta MMC» is there without a VÖEN; entered again as «BETA MMC» with VÖEN
    2200000002: the same element, now with the VÖEN."""
    cid = session.company_id
    kind = session.ledger.subconto_kind_id(cid, "counterparty")
    beta = session.ledger.add_subconto_value(cid, kind, "Beta MMC")
    session.catalog.reload()
    before = len(partners(session))
    typed_in_the_window(monkeypatch, "BETA MMC", "2200000002")
    assert new_value(session, window, kind) == beta
    assert len(partners(session)) == before
    assert ("Beta MMC", "2200000002") in partners(session)


def test_a_namesake_with_another_voen_is_added(qtbot, session, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)
    cid = session.company_id
    kind = session.ledger.subconto_kind_id(cid, "counterparty")
    before = len(partners(session))
    typed_in_the_window(monkeypatch, "ALFA MMC", "9999999999")
    added = new_value(session, window, kind)
    assert added is not None and added != alfa(session)
    assert len(partners(session)) == before + 1


def test_the_directory_is_searched_by_name_and_voen(qtbot, session):
    """«Kontragentlər» with ALFA MMC (VÖEN 1234567890) and «AUTOUNİVERSAL MMC»: «autouni»
    finds the dotted İ, «12345» finds ALFA by its VÖEN, «zzz» — nothing; cleared — all."""
    from modern_gl.desktop.directories_page import DirectoriesPage
    from modern_gl.i18n import tr

    cid = session.company_id
    kind = session.ledger.subconto_kind_id(cid, "counterparty")
    session.ledger.add_subconto_value(cid, kind, "AUTOUNİVERSAL MMC")
    session.catalog.reload()
    page = DirectoriesPage(session)
    qtbot.addWidget(page)
    page.refresh(select_kind=kind)

    def shown_names() -> list[str]:
        return [page.model.index(r, 0).data().strip() for r in range(page.model.rowCount())]

    everyone = shown_names()
    assert {"ALFA MMC", "AUTOUNİVERSAL MMC"} <= set(everyone)
    type_text(page.search, "autouni")
    assert shown_names() == ["AUTOUNİVERSAL MMC"]
    page.search.clear()
    type_text(page.search, "12345")
    assert shown_names() == ["ALFA MMC"]
    page.search.clear()
    type_text(page.search, "zzz")
    assert shown_names() == []
    assert page.stack.currentWidget() is page.nothing
    page.search.clear()
    assert shown_names() == everyone
    assert page.search.placeholderText() == tr("Поиск по названию или VÖEN   Ctrl+F")
