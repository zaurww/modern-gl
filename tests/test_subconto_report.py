"""ОСВ по субконто down to the second subconto, and its drill-down to the card of one
counterparty or contract — then to the document.

Example (hand-calculated), 60 = [Контрагенты, Договоры], report for March 2026:
  1  20.02  Dt 26 [Аренда]          Ct 60 [Альфа, Д1]   1 000.00
  2  05.03  Dt 26 [Аренда]          Ct 60 [Альфа, Д2]     400.00
  3  10.03  Dt 60 [Альфа, Д1]       Ct 26 [Аренда]        300.00
  4  12.03  Dt 26 [Аренда]          Ct 60 [Бета, —]       200.00
            opening Dt/Ct     turnover Dt/Ct     closing Dt/Ct
  Альфа          0 / 1 000.00     300.00 / 400.00     0 / 1 100.00
    Д1           0 / 1 000.00     300.00 / 0          0 /   700.00
    Д2           0 / 0                 0 / 400.00     0 /   400.00
  Бета           0 / 0                 0 / 200.00     0 /   200.00
    <не указано> 0 / 0                 0 / 200.00     0 /   200.00
Card of 60 [Альфа, Д1]: opening 1 000.00 Ct, 10.03 Dt 300.00 -> 700.00 Ct.
Card of 60 [Альфа]: opening 1 000.00 Ct, 05.03 Ct 400.00 -> 1 400.00 Ct,
  10.03 Dt 300.00 -> 1 100.00 Ct.
"""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.desktop import theme
from modern_gl.desktop.reports_page import CardPage, ReportParams, SubcontoPage
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.reports import account_card, subconto_balance

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
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    cp = ledger.subconto_kind_id(cid, "counterparty")
    contract = ledger.subconto_kind_id(cid, "contract")
    v = {name: ledger.add_subconto_value(cid, cp, name) for name in ("Альфа", "Бета")}
    v["Аренда"] = ledger.add_subconto_value(
        cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"
    )
    for name in ("Д1", "Д2"):
        v[name] = ledger.add_subconto_value(cid, contract, name, owner_id=v["Альфа"])
    acc = {code: ledger.account_id(cid, code) for code in ("26", "60")}
    rent = (v["Аренда"],)
    for day, dt, ct, amount, dt_sc, ct_sc in (
        ("2026-02-20", "26", "60", "1000", rent, (v["Альфа"], v["Д1"])),
        ("2026-03-05", "26", "60", "400", rent, (v["Альфа"], v["Д2"])),
        ("2026-03-10", "60", "26", "300", (v["Альфа"], v["Д1"]), rent),
        ("2026-03-12", "26", "60", "200", rent, (v["Бета"],)),
    ):
        ledger.post_new(cid, day, [PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)])
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
    theme.apply(QApplication.instance())
    conn, ledger, cid, _ = books
    return Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _: None)


def test_report_shows_contracts_and_drills_to_their_card(session, qtbot, books):
    *_, v = books
    acc = session.catalog.by_code["60"]
    page = SubcontoPage(session, acc.id, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
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

    opened = []
    page.open_report.connect(lambda kind, account, params: opened.append((kind, account, params)))
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
