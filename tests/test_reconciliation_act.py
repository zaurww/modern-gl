"""Акт сверки (üzləşmə aktı): the settlements with one counterparty, a line per document.

On the travel agency of tests/helpers/travel_agency.py (June 2026, hand-calculated):
  Firma MMC, a customer on 62.1:
    05.06  Dt 51 / Kt 62.1   500.00  Kt 500          → −500.00  (they paid ahead)
    06.06  Dt 62.1 / Kt 60.1 950.00  Dt 950          → +450.00  (Hava Yolları is on 60.1)
    06.06  Dt 62.1 / Kt 90.1  50.00  Dt 50           → +500.00
  closing +500.00: owed to the agency. Turnovers Dt 1 000.00, Kt 500.00.
  TurOp, a supplier on 60.1: 02.06 Kt 1 800.00 → −1 800.00; 03.06 Dt 1 800.00 → 0.
  Zaur: 01.06 Kt 2 000.00, 02.06 Dt 1 800.00 and Dt 200.00 → 0; Hava Yolları: 06.06 Kt 950 → −950.
Added here:
  10.06  one document, two lines Dt 62.1 (Firma) / Kt 90.1: 100.00 and 20.00 with e-qaimə
         INV-7 → one line of the act, Dt 120.00, «INV-7»     → +620.00
  11.06  Dt 62.1 (Firma) / Kt 90.1 (Firma — the revenue account carries the counterparty
         too) 30.00 → only the debit counts: revenue is no debt  → +650.00
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import set_document_language
from modern_gl.infrastructure.act_file import write_act_xlsx
from modern_gl.reporting.reconciliation_form import act_file_name, act_sheet, debt_text
from modern_gl.reporting.reports import act_partners, reconciliation_act
from tests.helpers.travel_agency import JUNE, _post_cases, make_agency

JULY = ("2026-07-01", "2026-07-31")


@pytest.fixture
def agency(ledger):
    _agency = make_agency(ledger)
    _post_cases(ledger, _agency)
    cid, acc, v, kind, order = _agency
    firma = (v["Firma MMC"], None, v["S-002"])
    ledger.post_new(
        cid,
        "2026-06-10",
        [
            PostingInput(acc["62.1"], acc["90.1"], "100", firma, (v["S-002"],)),
            PostingInput(acc["62.1"], acc["90.1"], "20", firma, (v["S-002"],), invoice="INV-7"),
        ],
        memo="Bilet satışı",
    )
    ledger.update_account(cid, "90.1", subconto=[order, kind["counterparty"]])
    ledger.post_new(
        cid,
        "2026-06-11",
        [PostingInput(acc["62.1"], acc["90.1"], "30", firma, (v["S-002"], v["Firma MMC"]))],
        memo="Xidmət",
    )
    ledger.set_company_tax_id(cid, "1234567890")
    ledger.set_subconto_value_tax(cid, v["Firma MMC"], "2000000001")
    ledger.set_subconto_value_legal_name(cid, v["Firma MMC"], "Firma MMC (tam adı)")
    return _agency


@pytest.fixture
def documents_in_az():
    set_document_language("az")
    yield
    set_document_language(None)


def lines(act) -> list[tuple]:
    return [(ln.doc_date, ln.debit, ln.credit, ln.balance) for ln in act.lines]


def test_a_customer_a_line_per_document(conn, agency):
    cid, _, v, _, _ = agency
    act = reconciliation_act(conn, cid, v["Firma MMC"], *JUNE)
    assert act.opening == 0
    assert lines(act) == [
        ("2026-06-05", 0, 50000, -50000),
        ("2026-06-06", 95000, 0, 45000),
        ("2026-06-06", 5000, 0, 50000),
        ("2026-06-10", 12000, 0, 62000),
        ("2026-06-11", 3000, 0, 65000),
    ]
    assert act.closing == 65000 and act.debit == 115000 and act.credit == 50000
    two_lines = act.lines[3]
    assert two_lines.memo == "Bilet satışı" and two_lines.invoice == "INV-7"
    assert two_lines.document_id and two_lines.number
    assert act.company.name == "Səyahət MMC" and act.company.tax_id == "1234567890"
    assert act.partner.title == "Firma MMC (tam adı)" and act.partner.tax_id == "2000000001"
    assert act.currency == "AZN"
    assert (act.date_from, act.date_to) == (date(2026, 6, 1), date(2026, 6, 30))


def test_a_supplier_the_next_period_and_an_unknown_element(conn, agency):
    cid, _, v, _, _ = agency
    turop = reconciliation_act(conn, cid, v["TurOp"], *JUNE)
    assert lines(turop) == [("2026-06-02", 0, 180000, -180000), ("2026-06-03", 180000, 0, 0)]
    assert turop.closing == 0
    july = reconciliation_act(conn, cid, v["Firma MMC"], *JULY)
    assert july.opening == 65000 and july.lines == [] and july.closing == 65000
    with pytest.raises(NotFoundError):
        reconciliation_act(conn, cid, 999_999, *JUNE)


def test_the_partners_an_act_is_worth_making_for(conn, agency):
    cid, _, v, kind, _ = agency
    partners = act_partners(conn, cid, kind["counterparty"], *JUNE)
    assert [(p.name, p.closing) for p in partners] == [
        ("Firma MMC", 65000),
        ("Hava Yolları", -95000),
        ("TurOp", 0),
        ("Zaur", 0),
    ]
    assert partners[0].value_id == v["Firma MMC"]
    assert act_partners(conn, cid, kind["counterparty"], "2026-05-01", "2026-05-31") == []


def test_the_form_in_the_language_of_documents(conn, agency, documents_in_az):
    cid, _, v, _, _ = agency
    act = reconciliation_act(conn, cid, v["Firma MMC"], *JUNE)
    sheet = act_sheet(act)
    assert sheet.title == "Qarşılıqlı hesablaşmaların üzləşmə aktı"
    assert sheet.heading == [
        "Səyahət MMC (VÖEN 1234567890) və Firma MMC (tam adı) (VÖEN 2000000001) arasında",
        "01.06.2026 — 30.06.2026 dövrü üçün",
    ]
    assert sheet.sides == (
        "Səyahət MMC məlumatlarına görə",
        "Firma MMC (tam adı) məlumatlarına görə",
    )
    assert sheet.columns == ["№", "Tarix", "Sənəd", "Debet", "Kredit", "Debet", "Kredit"]
    cells = [r.cells for r in sheet.rows]
    assert cells[0] == ["", "", "İlkin qalıq", None, None, None, None]
    assert cells[1] == [1, "05.06.2026", "Sənəd № 5", None, 50000, 50000, None]  # mirrored
    assert cells[4] == [4, "10.06.2026", "Bilet satışı (e-qaimə INV-7)", 12000, None, None, 12000]
    assert cells[-2] == ["", "", "Dövr üzrə dövriyyə", 115000, 50000, 50000, 115000]
    assert cells[-1] == ["", "", "Son qalıq", 65000, None, None, 65000]
    assert [r.bold for r in sheet.rows] == [True, False, False, False, False, False, True, True]
    assert sheet.summary == ["30.06.2026 tarixinə Səyahət MMC xeyrinə borc: 650.00 AZN"]
    assert sheet.signatures == ("Səyahət MMC adından", "Firma MMC (tam adı) adından")
    assert act_file_name(act) == "Üzləşmə aktı — Firma MMC 01.06-30.06.2026.xlsx"

    owed_to_them = reconciliation_act(conn, cid, v["Hava Yolları"], *JUNE)
    assert debt_text(owed_to_them) == "30.06.2026 tarixinə Hava Yolları xeyrinə borc: 950.00 AZN"
    assert debt_text(reconciliation_act(conn, cid, v["TurOp"], *JUNE)) == (
        "30.06.2026 tarixinə borc yoxdur"
    )


def test_the_file_is_one_printable_sheet(conn, agency, tmp_path: Path, documents_in_az):
    cid, _, v, _, _ = agency
    act = reconciliation_act(conn, cid, v["Firma MMC"], *JUNE)
    path = tmp_path / act_file_name(act)
    write_act_xlsx(act_sheet(act), path)
    sheet = openpyxl.load_workbook(path).worksheets[0]
    rows = [[c.value for c in row] for row in sheet.iter_rows()]
    assert rows[0][0] == "Qarşılıqlı hesablaşmaların üzləşmə aktı"
    assert str(rows[1][0]).startswith("Səyahət MMC (VÖEN 1234567890) və Firma MMC")
    header = rows.index(["№", "Tarix", "Sənəd", "Səyahət MMC məlumatlarına görə", None,
                         "Firma MMC (tam adı) məlumatlarına görə", None])  # fmt: skip
    assert rows[header + 1] == [None, None, None, "Debet", "Kredit", "Debet", "Kredit"]
    assert rows[header + 2] == [None, None, "İlkin qalıq", None, None, None, None]
    assert rows[header + 3] == ["1", "05.06.2026", "Sənəd № 5", None, 500, 500, None]
    assert rows[header + 9] == [None, None, "Son qalıq", 650, None, None, 650]
    first = header + 4  # rows are 0-based, cells 1-based: the first document's line
    assert sheet.cell(first, 5).number_format.startswith("#,##0.00")
    assert sheet.cell(first + 6, 4).font.bold and not sheet.cell(first, 4).font.bold
    assert [r[0] for r in rows if r[0] and "xeyrinə" in str(r[0])] == [
        "30.06.2026 tarixinə Səyahət MMC xeyrinə borc: 650.00 AZN"
    ]
    assert sheet.print_title_rows == f"${header + 1}:${header + 2}"
    assert sheet.page_setup.fitToWidth == 1


def test_the_page_chooses_the_partner_drills_and_saves(
    ledger, conn, agency, qtbot, monkeypatch, tmp_path: Path
):
    from PySide6.QtWidgets import QFileDialog

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReconciliationActPage, ReportParams, reconciliation
    from modern_gl.desktop.session import Session

    cid, _, v, _, _ = agency
    session = Session(conn, ledger, cid, "Səyahət", Catalog(conn, cid))
    page = ReconciliationActPage(
        session, ReportParams(date(2026, 6, 1), date(2026, 6, 30)), value_id=v["Firma MMC"]
    )
    qtbot.addWidget(page)
    assert page.title() == "Акт сверки · Firma MMC"
    assert [c.title for c in page.model.columns] == [
        "Дата", "№", "Содержание", "E-qaimə", "Дт", "Кт", "Сальдо"
    ]  # fmt: skip
    assert [r.balance for r in page.model.rows] == [0, -50000, 45000, 50000, 62000, 65000, 65000]
    assert page.model.rows[-1].debit == 115000 and page.model.rows[-1].credit == 50000
    assert page.footer.text() == "На 30.06.2026 задолженность в пользу Səyahət MMC: 650.00 AZN"

    opened = []
    page.open_document.connect(opened.append)
    page.drill(page.model.rows[4])
    page.drill(page.model.rows[0])  # the opening balance leads nowhere
    assert opened == [page.model.rows[4].document_id]

    page.partner.setCurrentIndex(page.partner.findData(v["TurOp"]))
    page.partner.activated.emit(page.partner.currentIndex())
    assert page.title() == "Акт сверки · TurOp"
    assert [r.balance for r in page.model.rows] == [0, -180000, 0, 0]
    assert page.footer.text() == "На 30.06.2026 задолженности нет"

    opened_urls = []
    monkeypatch.setattr(
        reconciliation.QDesktopServices, "openUrl", staticmethod(opened_urls.append)
    )
    target = tmp_path / "akt.xlsx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    page.save_act()
    assert target.exists() and len(opened_urls) == 1
    folder = tmp_path / "all"
    folder.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder))
    )
    page.save_all_acts()
    assert sorted(p.name for p in folder.iterdir()) == [
        "Акт сверки — Firma MMC 01.06-30.06.2026.xlsx",
        "Акт сверки — Hava Yolları 01.06-30.06.2026.xlsx",
        "Акт сверки — TurOp 01.06-30.06.2026.xlsx",
        "Акт сверки — Zaur 01.06-30.06.2026.xlsx",
    ]
    assert [t for t, *_ in (i for i in page.more_items() if i)][:2] == [
        "Акт в Excel…",
        "Акты всем контрагентам…",
    ]
