"""Import of many documents from Excel / CSV.

Example (hand-calculated):
  Дата        Док  Дебет            Кредит                    Сумма
  05.03.2026  1    26 [Аренда]      60 [Альфа, Договор №1]    400.00
  05.03.2026  1    19 [Альфа]       60 [Альфа, Договор №1]     72.00
  06.03.2026  2    50               51 [Kapital Bank]       1 000.00
-> 2 documents; 60 credit 472.00, 51 credit 1 000.00, 50 debit 1 000.00.
"""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.journal_import import check, header, parse_date, read_plan, run
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import list_documents, load_document
from modern_gl.domain.currency import parse_rate
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.table_files import from_clipboard, read_rows
from modern_gl.reporting.reports import trial_balance
from tests.helpers.excel import active_sheet
from tests.helpers.qt import running_app

HEAD = "Дата\tДокумент\tДебет\tСубконто\tКредит\tСубконто\tСубконто\tСумма\tСодержание"
TABLE = "\n".join(
    [
        HEAD,
        "05.03.2026\t1\t26\tаренда\t60\tальфа\tдоговор\t400\tАренда за март",
        "05.03.2026\t1\t19\tальфа\t60\tальфа\tдоговор\t72\tНДС",
        "06.03.2026\t2\t50\t\t51\tkapital bank\t\t1 000,00\tВ кассу",
    ]
)


@pytest.fixture
def books():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    for kind, name in (
        ("counterparty", "Альфа Трейд"),
        ("contract", "Договор №1"),
        ("cost_item", "Аренда офиса"),
        ("bank_account", "Kapital Bank"),
        ("bank_account", "Kapital Bank USD"),
        ("employee", "Мамедов Р."),
    ):
        ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), name)
    yield conn, ledger, cid, Catalog(conn, cid)
    conn.close()


def layers(conn, cid):
    from modern_gl.application.queries import list_layers

    return list_layers(conn, cid)


def test_header_and_dates():
    cols = header(HEAD.split("\t"))
    assert cols[2] == ("debit", 0) and cols[3] == ("debit", 1)
    assert cols[5] == ("credit", 1) and cols[6] == ("credit", 2)
    assert header(["Tarix", "Debet", "Kredit", "Məbləğ"])[3] == ("amount", 0)
    assert parse_date("05.03.2026") == date(2026, 3, 5)
    assert parse_date("5/3/26") == date(2026, 3, 5)
    assert parse_date("2026-03-05") == date(2026, 3, 5)
    assert parse_date("46086") == date(2026, 3, 5)  # Excel serial number
    assert parse_date("31.02.2026") is None


def test_rows_become_documents(books):
    conn, ledger, cid, cat = books
    plan = read_plan(from_clipboard(TABLE), cat, layers(conn, cid))
    assert plan.errors == 0, [r.errors for r in plan.rows]
    assert [len(d.postings) for d in plan.documents] == [2, 1]
    assert [d.doc_date for d in plan.documents] == ["2026-03-05", "2026-03-06"]
    assert plan.documents[0].memo == "Аренда за март"
    ids = run(ledger, cid, plan)
    assert len(ids) == 2
    osv = trial_balance(conn, cid, "2026-03-01", "2026-03-31")
    closing = {r.code: (r.closing_dt, r.closing_ct) for r in osv.rows}
    assert closing["60"] == (0, 47_200)
    assert closing["51"] == (0, 100_000)
    assert closing["50"] == (100_000, 0)
    assert load_document(conn, cid, ids[0]).status == "posted"


def test_problems_are_reported_per_row_and_nothing_is_written(books):
    conn, ledger, cid, cat = books
    table = "\n".join(
        [
            "Дата\tДебет\tСубконто\tКредит\tСумма",
            "31.02.2026\t50\t\t80\t10",
            "05.03.2026\t999\t\t80\t10",
            "05.03.2026\t26\tреклама\t50\t10",
            "05.03.2026\t50\t\t80\tabc",
            "05.03.2026\t71\t\t50\t10",  # employee missing: found by the ledger check
            "05.03.2026\t50\t\t80\t10",
        ]
    )
    plan = read_plan(from_clipboard(table), cat)
    problems = {r.row_no: r.errors for r in plan.rows if r.errors}
    assert "дата «31.02.2026» не понята" in problems[2]
    assert any("999" in e for e in problems[3])
    assert problems[4] == ["«реклама» нет в справочнике «Статьи затрат»"]
    assert any("не число" in e for e in problems[5])
    check(ledger, cid, plan)
    assert any("не заполнено «" in e for e in plan.rows[4].errors)
    assert not plan.rows[5].errors
    # even the good rows are not written while others have problems
    assert run(ledger, cid, plan) == []
    assert list_documents(conn, cid) == []


def test_missing_headers_are_named(books):
    _, _, _, cat = books
    plan = read_plan([["26", "60", "400"]], cat)
    assert "Дата" in plan.problem and "Сумма" in plan.problem


def test_new_elements_when_allowed(books):
    conn, ledger, cid, cat = books
    table = "Дата\tДебет\tСубконто\tКредит\tСумма\n05.03.2026\t26\tРеклама\t50\t10\n"
    plan = read_plan(from_clipboard(table), cat, add_new=True)
    assert plan.errors == 0
    assert plan.new_values == [(cat.by_code["26"].sc_kinds[0], "Реклама", None)]
    assert plan.rows[0].debit_names == ["+Реклама"]
    [doc_id] = run(ledger, cid, plan, post=False)
    doc = load_document(conn, cid, doc_id)
    assert doc.status == "draft"
    item = doc.postings[0].debit_subconto[0]
    assert item is not None and Catalog(conn, cid).value(item).name == "Реклама"


def test_currency_rows(books):
    _conn, ledger, cid, cat = books
    usd = ledger.currency_id(cid, "USD")
    bank_usd = next(v for v in cat.all_values(cat.by_code["52"].sc_kinds[0]) if "USD" in v.name)
    ledger.set_subconto_value_currency(cid, bank_usd.id, usd)
    cat.reload()
    table = "\n".join(
        [
            "Дата\tДебет\tСубконто\tКредит\tСубконто\tВ валюте\tКурс\tСумма",
            "05.03.2026\t52\tkapital bank usd\t51\tkapital bank\t100\t1,7\t",
            "06.03.2026\t52\tkapital bank usd\t51\tkapital bank\t50\t\t86",
            "07.03.2026\t52\tkapital bank usd\t51\tkapital bank\t10\t\t",
        ]
    )
    plan = read_plan(from_clipboard(table), cat, rate_for=lambda c, d: Fraction(172, 100))
    assert plan.errors == 0, [r.errors for r in plan.rows]
    assert [(r.currency, r.currency_amount, r.amount) for r in plan.rows] == [
        ("USD", 10_000, 17_000),  # 100 × 1.70 from the table
        ("USD", 5_000, 8_600),  # manat given
        ("USD", 1_000, 1_720),  # rate of the date
    ]
    assert len(run(ledger, cid, plan)) == 3


def test_excel_and_csv_files(books, tmp_path):
    from openpyxl import Workbook

    _conn, _ledger, _cid, cat = books
    book = Workbook()
    sheet = active_sheet(book)
    sheet.append(["Дата", "Дебет", "Кредит", "Сумма", "Содержание"])
    sheet.append([datetime(2026, 3, 5), 50, 80, 1180.5, "Взнос"])
    sheet.append([datetime(2026, 3, 6), "68.2", 80, 12, None])
    book.save(tmp_path / "journal.xlsx")
    rows = read_rows(tmp_path / "journal.xlsx")
    assert rows[1] == ["05.03.2026", "50", "80", "1180.5", "Взнос"]
    plan = read_plan(rows, cat)
    assert plan.errors == 0 and [r.amount for r in plan.rows] == [118_050, 1_200]

    csv = tmp_path / "journal.csv"
    csv.write_bytes("Дата;Дебет;Кредит;Сумма\n05.03.2026;50;80;1 180,50\n".encode("cp1251"))
    plan = read_plan(read_rows(csv), cat)
    assert plan.errors == 0 and plan.rows[0].amount == 118_050


def test_rates_are_not_needed_for_manat_rows(books):
    _, _, _, cat = books
    plan = read_plan([["Дата", "Дт", "Кт", "Сумма"], ["05.03.2026", "50", "80", "1"]], cat)
    assert plan.errors == 0
    assert parse_rate("1.7") == 1_700_000


@pytest.fixture
def import_page(qtbot, books):

    from modern_gl.desktop import theme
    from modern_gl.desktop.import_page import ImportPage
    from modern_gl.desktop.session import Session

    theme.apply(running_app())
    conn, ledger, cid, cat = books
    s = Session(conn, ledger, cid, "Firma", cat, notify=lambda m: None)
    page = ImportPage(s)
    qtbot.addWidget(page)
    return page


def test_page_previews_and_imports(import_page):
    page = import_page
    assert not page.run_button.isEnabled()
    page.paste(TABLE)
    assert page.model.rowCount() == 3
    assert page.run_button.isEnabled()
    assert "Документов: 2" in page.summary.text()
    assert page.model.index(0, 3).data() == "26  ·  Аренда офиса"
    imported = []
    page.imported.connect(imported.append)
    ids = page.run()
    assert len(ids) == 2 and imported == [ids]
    assert page.model.rowCount() == 0  # ready for the next table


def test_page_shows_problems_and_refuses(import_page):
    page = import_page
    page.paste("Дата\tДебет\tКредит\tСумма\n05.03.2026\t71\t50\t10\n05.03.2026\t50\t80\t10\n")
    assert not page.run_button.isEnabled()
    assert "не заполнено «" in page.model.index(0, 7).data()
    assert page.model.index(1, 7).data() == "✓"
    assert "Строк с ошибками: 1" in page.summary.text()
    assert page.run() == []
    assert list_documents(page.s.conn, page.s.company_id) == []


def test_page_drafts_and_new_elements(import_page):
    page = import_page
    page.paste("Дата\tДебет\tСубконто\tКредит\tСумма\n05.03.2026\t26\tРеклама\t50\t10\n")
    assert not page.run_button.isEnabled()
    page.add_new.setChecked(True)
    page.mode.setCurrentIndex(1)  # drafts
    assert page.run_button.isEnabled()
    [doc_id] = page.run()
    assert load_document(page.s.conn, page.s.company_id, doc_id).status == "draft"
    assert any(
        v.name == "Реклама"
        for v in page.s.catalog.all_values(page.s.catalog.by_code["26"].sc_kinds[0])
    )
