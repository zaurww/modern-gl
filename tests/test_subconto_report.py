"""ОСВ по субконто down to the second subconto, and its drill-down to the card of one
counterparty or contract — then to the document.

Example (hand-calculated), 60 = [Контрагенты, Договоры], report for March 2026:
  1  20.02  Dt 26 [Аренда]          Ct 60 [Альфа, Д1]   1 000.00   e-qaimə MM001
  2  05.03  Dt 26 [Аренда]          Ct 60 [Альфа, Д2]     400.00   e-qaimə MM002
  3  10.03  Dt 60 [Альфа, Д1]       Ct 26 [Аренда]        300.00   paid on MM001
  4  12.03  Dt 26 [Аренда]          Ct 60 [Бета, —]       200.00   no e-qaimə
            opening Dt/Ct     turnover Dt/Ct     closing Dt/Ct
  Альфа          0 / 1 000.00     300.00 / 400.00     0 / 1 100.00
    Д1           0 / 1 000.00     300.00 / 0          0 /   700.00
    Д2           0 / 0                 0 / 400.00     0 /   400.00
  Бета           0 / 0                 0 / 200.00     0 /   200.00
    <не указано> 0 / 0                 0 / 200.00     0 /   200.00
Card of 60 [Альфа, Д1]: opening 1 000.00 Ct, 10.03 Dt 300.00 -> 700.00 Ct.
Card of 60 [Альфа]: opening 1 000.00 Ct, 05.03 Ct 400.00 -> 1 400.00 Ct,
  10.03 Dt 300.00 -> 1 100.00 Ct.
Down to the e-qaimə (D110): under Д1 — MM001 0 / 1 000.00, 300.00 / 0, 0 / 700.00; under
Д2 — MM002 0 / 0, 0 / 400.00, 0 / 400.00; under Бета <не указано> — <без e-qaimə> 200.00.
Card of MM001: opening 1 000.00 Ct, 10.03 Dt 300.00 -> 700.00 Ct.
"""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.desktop import theme
from modern_gl.desktop.reports_page import CardPage, ReportParams, SubcontoPage
from modern_gl.desktop.session import Session
from modern_gl.reporting.reports import account_card, subconto_balance
from tests.helpers.contract_books import contract_books
from tests.helpers.qt import running_app

MARCH = ("2026-03-01", "2026-03-31")


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
def books():
    conn, ledger, cid, v = contract_books()
    yield conn, ledger, cid, v
    conn.close()


def test_subconto_balance_by_counterparty_and_contract(books):
    conn, _, cid, _ = books
    rows = subconto_balance(conn, cid, "60", *MARCH, levels=2)
    assert [(r.name, r.depth, cols(r)) for r in rows] == [
        ("Альфа", 0, (0, 100_000, 30_000, 40_000, 0, 110_000)),
        ("Д1", 1, (0, 100_000, 30_000, 0, 0, 70_000)),
        ("Д2", 1, (0, 0, 0, 40_000, 0, 40_000)),
        ("Бета", 0, (0, 0, 0, 20_000, 0, 20_000)),
        ("<не указано>", 1, (0, 0, 0, 20_000, 0, 20_000)),
    ]


def test_subconto_balance_down_to_the_e_qaime(books):
    conn, _, cid, v = books
    rows = subconto_balance(conn, cid, "60", *MARCH, levels=2, invoices=True)
    assert [(r.name, r.depth, cols(r)) for r in rows] == [
        ("Альфа", 0, (0, 100_000, 30_000, 40_000, 0, 110_000)),
        ("Д1", 1, (0, 100_000, 30_000, 0, 0, 70_000)),
        ("MM001", 2, (0, 100_000, 30_000, 0, 0, 70_000)),
        ("Д2", 1, (0, 0, 0, 40_000, 0, 40_000)),
        ("MM002", 2, (0, 0, 0, 40_000, 0, 40_000)),
        ("Бета", 0, (0, 0, 0, 20_000, 0, 20_000)),
        ("<не указано>", 1, (0, 0, 0, 20_000, 0, 20_000)),
        ("<без e-qaimə>", 2, (0, 0, 0, 20_000, 0, 20_000)),
    ]
    first = rows[2]
    assert (first.path, first.invoice, first.value_id) == ((v["Альфа"], v["Д1"]), "MM001", None)
    assert rows[1].invoice is None  # a contract is no e-qaimə row
    card = account_card(conn, cid, "60", *MARCH, subconto=first.path, invoice="MM001")
    assert card.opening == -100_000
    assert [(ln.debit, ln.balance) for ln in card.lines] == [(30_000, -70_000)]
    none = account_card(conn, cid, "60", *MARCH, subconto=(v["Бета"], None), invoice="")
    assert [(ln.credit, ln.balance) for ln in none.lines] == [(20_000, -20_000)]


def test_trial_balance_opens_into_every_subconto_level(books):
    """«Развернуть по субконто» in ОСВ, as in 1C: counterparties and their contracts."""
    from modern_gl.reporting.reports import trial_balance

    conn, _, cid, v = books
    osv = trial_balance(conn, cid, *MARCH)
    sixty = osv.subconto[Ledger(conn).account_id(cid, "60")]
    assert [(r.name, r.depth, r.path, r.closing_ct) for r in sixty] == [
        ("Альфа", 0, (v["Альфа"],), 110_000),
        ("Д1", 1, (v["Альфа"], v["Д1"]), 70_000),
        ("Д2", 1, (v["Альфа"], v["Д2"]), 40_000),
        ("Бета", 0, (v["Бета"],), 20_000),
        ("<не указано>", 1, (v["Бета"], None), 20_000),
    ]
    rent = osv.subconto[Ledger(conn).account_id(cid, "26")]
    assert [(r.name, r.depth) for r in rent] == [("Аренда", 0)]  # one subconto: one level


def test_one_level_stays_as_it_was(books):
    conn, _, cid, v = books
    rows = subconto_balance(conn, cid, "60", *MARCH)
    assert [(r.name, r.depth, r.path, r.closing_ct) for r in rows] == [
        ("Альфа", 0, (v["Альфа"],), 110_000),
        ("Бета", 0, (v["Бета"],), 20_000),
    ]


def test_card_of_one_contract_and_of_one_counterparty(books):
    conn, _, cid, v = books
    card = account_card(conn, cid, "60", *MARCH, subconto=(v["Альфа"], v["Д1"]))
    assert card.opening == -100_000
    assert [(ln.debit, ln.credit, ln.balance) for ln in card.lines] == [(30_000, 0, -70_000)]
    card = account_card(conn, cid, "60", *MARCH, subconto=(v["Альфа"],))
    assert card.opening == -100_000
    assert [(ln.debit, ln.credit, ln.balance) for ln in card.lines] == [
        (0, 40_000, -140_000),
        (30_000, 0, -110_000),
    ]
    card = account_card(conn, cid, "60", *MARCH, subconto=(v["Бета"], None))  # «не указано»
    assert [(ln.credit, ln.balance) for ln in card.lines] == [(20_000, -20_000)]


@pytest.fixture
def session(qtbot, books):
    theme.apply(running_app())
    conn, ledger, cid, _ = books
    return Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _: None)


def test_report_shows_contracts_and_drills_to_their_card(session, qtbot, books):
    *_, v = books
    acc = session.catalog.by_code["60"]
    page = SubcontoPage(session, acc.id, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    assert page.levels.currentText() == "E-qaimə"  # down to the e-qaimə, as in 1C
    assert [r.name for r in page.model.rows] == [
        "Альфа",
        "Д1",
        "MM001",
        "Д2",
        "MM002",
        "Бета",
        "<не указано>",
        "<без e-qaimə>",
        "Итого",
    ]
    opened = []
    page.open_report.connect(lambda kind, account, params: opened.append((kind, account, params)))
    page.drill(page.model.rows[2])
    ((_, _, params),) = opened
    assert (params.subconto, params.invoice) == ((v["Альфа"], v["Д1"]), "MM001")
    card = CardPage(session, acc.id, params)
    qtbot.addWidget(card)
    assert card.title() == "Карточка счёта 60 · MM001"
    assert len(card.model.rows) == 3  # opening balance, the 10.03 payment, closing
    page.levels.setCurrentIndex(1)  # down to the contracts
    page.refresh()
    assert [r.name for r in page.model.rows] == [
        "Альфа",
        "Д1",
        "Д2",
        "Бета",
        "<не указано>",
        "Итого",
    ]
    assert page.model.rows[-1].closing_ct == 130_000  # top rows only, not the contracts too
    page.levels.setCurrentIndex(0)  # counterparties only
    page.refresh()
    assert [r.name for r in page.model.rows] == ["Альфа", "Бета", "Итого"]
    page.levels.setCurrentIndex(1)
    page.refresh()

    opened.clear()
    page.drill(page.model.rows[-1])  # the total opens nothing
    assert opened == []
    page.drill(page.model.rows[1])
    ((kind, account, params),) = opened
    assert (kind, account, params.subconto) == ("card", acc.id, (v["Альфа"], v["Д1"]))

    card = CardPage(session, acc.id, params)
    qtbot.addWidget(card)
    assert card.title() == "Карточка счёта 60 · Д1"
    assert "Альфа · Д1" in card.header.subtitle.text()
    assert len(card.model.rows) == 3  # opening balance, the 10.03 line, closing
    card.refresh()  # «Сформировать» keeps the filter
    assert len(card.model.rows) == 3
    docs = []
    card.open_document.connect(docs.append)
    card.drill(card.model.rows[1])
    assert len(docs) == 1


def test_osv_opens_into_contracts_and_a_contract_leads_to_its_card(session, qtbot, books):
    """«Развернуть по субконто»: under 60 its counterparties and their contracts (D110);
    a double click on a contract — the card of that contract."""
    from modern_gl.desktop.reports_page import OsvPage

    *_, v = books
    page = OsvPage(session, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    page.expand.setChecked(True)
    sixty = session.catalog.by_code["60"].id
    under = [r for r in page.model.rows if r.account_id == sixty and r.subconto]
    assert [(r.name.strip(), r.subconto) for r in under] == [
        ("Альфа", (v["Альфа"],)),
        ("Д1", (v["Альфа"], v["Д1"])),
        ("Д2", (v["Альфа"], v["Д2"])),
        ("Бета", (v["Бета"],)),
        ("<не указано>", (v["Бета"], None)),
    ]
    opened = []
    page.open_report.connect(lambda kind, account, params: opened.append((kind, account, params)))
    page.drill(under[1])
    ((kind, account, params),) = opened
    assert (kind, account, params.subconto) == ("card", sixty, (v["Альфа"], v["Д1"]))
