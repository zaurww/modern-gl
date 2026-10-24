"""Карточка субконто (D126): one element's postings across every account, or on one.

On the travel agency of tests/test_travel_agency.py (June 2026, hand-calculated):
  S-002 on every account — the element is on both sides of the booking and the commission,
  so only the client's payment moves the balance:
    05.06  Dt 51 / Kt 62.1   500.00  on the Kt side → −500.00
    06.06  Dt 62.1 / Kt 60.1 950.00  both sides     → −500.00
    06.06  Dt 62.1 / Kt 90.1  50.00  both sides     → −500.00  (= 62.1 +500, 60.1 −950, 90.1 −50)
  S-002 on 62.1 only:  −500.00 → +450.00 → +500.00 — what the client still owes.
  Firma MMC (counterparty): the same three lines, 62.1 is the only account with it:
    −500.00 → +450.00 → +500.00.
  July: opening −500.00, no lines.
"""

from __future__ import annotations

import pytest

from modern_gl.domain.errors import NotFoundError
from modern_gl.reporting.reports import subconto_card
from tests.test_travel_agency import JUNE, _post_cases, make_agency


@pytest.fixture
def agency(ledger):
    _agency = make_agency(ledger)
    _post_cases(ledger, _agency)
    return _agency


def lines(card) -> list[tuple]:
    return [
        (ln.doc_date, ln.debit_code, ln.credit_code, ln.debit, ln.credit, ln.balance)
        for ln in card.lines
    ]


def test_an_order_across_every_account(conn, agency):
    cid, _, v, _, _ = agency
    card = subconto_card(conn, cid, v["S-002"], *JUNE)
    assert card.opening == 0
    assert lines(card) == [
        ("2026-06-05", "51", "62.1", 0, 50000, -50000),
        ("2026-06-06", "62.1", "60.1", 95000, 95000, -50000),
        ("2026-06-06", "62.1", "90.1", 5000, 5000, -50000),
    ]
    assert card.closing == -50000
    assert [ln.memo for ln in card.lines] == ["", "", ""]
    assert card.lines[0].document_id and card.lines[0].number


def test_an_order_on_one_account_and_a_counterparty(conn, agency):
    cid, acc, v, _, _ = agency
    on_62 = subconto_card(conn, cid, v["S-002"], *JUNE, account=acc["62.1"])
    assert lines(on_62) == [
        ("2026-06-05", "51", "62.1", 0, 50000, -50000),
        ("2026-06-06", "62.1", "60.1", 95000, 0, 45000),
        ("2026-06-06", "62.1", "90.1", 5000, 0, 50000),
    ]
    assert lines(subconto_card(conn, cid, v["Firma MMC"], *JUNE)) == lines(on_62)
    group = subconto_card(conn, cid, v["S-002"], *JUNE, account="62")  # with its subaccounts
    assert lines(group) == lines(on_62)


def test_the_opening_balance_and_a_missing_element(conn, agency):
    cid, _, v, _, _ = agency
    july = subconto_card(conn, cid, v["S-002"], "2026-07-01", "2026-07-31")
    assert (july.opening, july.closing, july.lines) == (-50000, -50000, [])
    with pytest.raises(NotFoundError):
        subconto_card(conn, cid, 999, *JUNE)


def test_the_page_opens_from_the_analysis_and_leads_to_the_document(ledger, conn, agency, qtbot):
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import (
        REPORTS,
        ReportParams,
        SubcontoAnalysisPage,
        SubcontoCardPage,
    )
    from modern_gl.desktop.session import Session

    cid, acc, v, _, order = agency
    session = Session(conn, ledger, cid, "Səyahət", Catalog(conn, cid))
    params = ReportParams(date(2026, 6, 1), date(2026, 6, 30))
    analysis = SubcontoAnalysisPage(session, params, kind_id=order)
    qtbot.addWidget(analysis)
    opened = []
    analysis.open_report.connect(lambda kind, account, p: opened.append((kind, account, p)))
    analysis.drill(analysis.model.rows[4])  # S-002 itself: every account
    analysis.drill(analysis.model.rows[6])  # its 62.1
    assert [(k, a, p.subconto) for k, a, p in opened] == [
        ("subconto_card", 0, (v["S-002"],)),
        ("subconto_card", acc["62.1"], (v["S-002"],)),
    ]

    page = REPORTS["subconto_card"](session, 0, opened[0][2])
    qtbot.addWidget(page)
    assert isinstance(page, SubcontoCardPage)
    assert page.title() == "Карточка субконто · S-002 Firma MMC, bilet"
    assert page.key == ("subconto_card", v["S-002"], 0)
    assert [r.memo for r in page.model.rows] == [
        "Сальдо на начало",
        "",
        "",
        "",
        "Обороты и сальдо на конец",
    ]
    assert (page.model.rows[-1].debit, page.model.rows[-1].credit) == (100000, 150000)
    assert page.footer.text() == "Сальдо на начало: 0.00      Сальдо на конец: 500.00 Кт"

    on_62 = REPORTS["subconto_card"](session, acc["62.1"], opened[1][2])
    qtbot.addWidget(on_62)
    assert on_62.title() == "Карточка субконто · S-002 Firma MMC, bilet · 62.1"
    assert on_62.model.rows[-1].balance == 50000
    documents = []
    on_62.open_document.connect(documents.append)
    on_62.drill(on_62.model.rows[1])
    on_62.drill(on_62.model.rows[0])  # the opening row: no document
    assert documents == [on_62.model.rows[1].document_id]
