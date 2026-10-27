"""Анализ субконто (D125): one directory's elements across every account that carries it.

On the travel agency of tests/test_travel_agency.py (June 2026, hand-calculated):
  by order                      Dt turnover / Ct turnover → closing Dt / Ct
  S-001 (closed)                3 800 / 4 000 → 0 / 200
    60.1                        1 800 / 1 800 → 0
    62.1                        2 000 / 2 000 → 0
    90.1                            0 /   200 → 200 Ct   (the commission stays: revenue)
  S-002 (open)                  1 000 / 1 500 → 500 Dt / 1 000 Ct
    60.1                            0 /   950 → 950 Ct
    62.1                        1 000 /   500 → 500 Dt
    90.1                            0 /    50 →  50 Ct
  «Только с остатком» keeps S-002 alone: S-001 owes nothing on 60.1 and 62.1.
  by counterparty: Firma MMC 62.1 500 Dt; Hava Yolları 60.1 950 Ct; TurOp 60.1 0;
  Zaur 62.1 0 — with a balance: Firma MMC and Hava Yolları.
"""

from __future__ import annotations

import pytest

from modern_gl.reporting.reports import subconto_analysis
from tests.helpers.travel_agency import JUNE, _post_cases, make_agency


@pytest.fixture
def agency(ledger):
    return make_agency(ledger)


def shape(rows) -> list[tuple]:
    return [
        (
            r.depth,
            r.name if r.depth == 0 else r.code,
            r.turnover_dt,
            r.turnover_ct,
            r.closing_dt,
            r.closing_ct,
        )
        for r in rows
    ]


def test_orders_across_the_client_the_suppliers_and_the_revenue(ledger, conn, agency):
    cid, acc, v, _, order = agency
    _post_cases(ledger, agency)
    rows = subconto_analysis(conn, cid, order, *JUNE)
    assert shape(rows) == [
        (0, "S-001 Zaur, Antalya", 380000, 400000, 0, 20000),
        (1, "60.1", 180000, 180000, 0, 0),
        (1, "62.1", 200000, 200000, 0, 0),
        (1, "90.1", 0, 20000, 0, 20000),
        (0, "S-002 Firma MMC, bilet", 100000, 150000, 50000, 100000),
        (1, "60.1", 0, 95000, 0, 95000),
        (1, "62.1", 100000, 50000, 50000, 0),
        (1, "90.1", 0, 5000, 0, 5000),
    ]
    assert [r.account_id for r in rows[1:4]] == [acc["60.1"], acc["62.1"], acc["90.1"]]
    assert rows[0].value_id == v["S-001"] and rows[0].account_id is None
    open_only = subconto_analysis(conn, cid, order, *JUNE, only_open=True)
    assert [r.name for r in open_only if r.depth == 0] == ["S-002 Firma MMC, bilet"]


def test_counterparties_across_60_and_62(ledger, conn, agency):
    cid, _, v, kind, _ = agency
    _post_cases(ledger, agency)
    rows = subconto_analysis(conn, cid, kind["counterparty"], *JUNE)
    assert shape(rows) == [
        (0, "Firma MMC", 100000, 50000, 50000, 0),
        (1, "62.1", 100000, 50000, 50000, 0),
        (0, "Hava Yolları", 0, 95000, 0, 95000),
        (1, "60.1", 0, 95000, 0, 95000),
        (0, "TurOp", 180000, 180000, 0, 0),
        (1, "60.1", 180000, 180000, 0, 0),
        (0, "Zaur", 200000, 200000, 0, 0),
        (1, "62.1", 200000, 200000, 0, 0),
    ]
    with_balance = subconto_analysis(conn, cid, kind["counterparty"], *JUNE, only_open=True)
    assert [r.name for r in with_balance if r.depth == 0] == ["Firma MMC", "Hava Yolları"]
    one = subconto_analysis(conn, cid, kind["counterparty"], *JUNE, value_id=v["Zaur"])
    assert shape(one) == [(0, "Zaur", 200000, 200000, 0, 0), (1, "62.1", 200000, 200000, 0, 0)]


def test_opening_balance_and_the_period(ledger, conn, agency):
    """July: everything of June is the opening; nothing moves."""
    cid, _, _, _, order = agency
    _post_cases(ledger, agency)
    rows = subconto_analysis(conn, cid, order, "2026-07-01", "2026-07-31", only_open=True)
    assert [(r.depth, r.opening_dt, r.opening_ct, r.closing_dt, r.closing_ct) for r in rows] == [
        (0, 50000, 100000, 50000, 100000),
        (1, 0, 95000, 0, 95000),
        (1, 50000, 0, 50000, 0),
        (1, 0, 5000, 0, 5000),
    ]
    assert subconto_analysis(conn, cid, order, "2026-05-01", "2026-05-31") == []


def test_a_contract_is_named_with_its_owner(ledger, conn, agency):
    from modern_gl.application.ledger import PostingInput

    cid, acc, v, kind, _ = agency
    deal = ledger.add_subconto_value(cid, kind["contract"], "Müqavilə 7", owner_id=v["TurOp"])
    ledger.post_new(
        cid,
        "2026-06-10",
        [
            PostingInput(
                acc["62.1"],
                acc["60.1"],
                "100",
                (v["Zaur"], None, v["S-001"]),
                (v["TurOp"], deal, v["S-001"]),
            )
        ],
    )
    rows = subconto_analysis(conn, cid, kind["contract"], *JUNE)
    assert [(r.depth, r.name) for r in rows] == [
        (0, "<не указано>"),
        (1, "Alıcılar və sifarişçilərlə hesablaşmalar"),
        (0, "Müqavilə 7 (TurOp)"),
        (1, "Malsatan və podratçılarla hesablaşmalar"),
    ]


def test_the_page_chooses_the_directory_and_drills_to_the_account(ledger, conn, agency, qtbot):
    """The page: «Справочник» offers the directories some account carries, «Sifarişlər»
    among them; its rows are the report's; «Только с остатком» leaves S-002; a double
    click on an account row opens the account's card."""
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReportParams, SubcontoAnalysisPage
    from modern_gl.desktop.session import Session

    cid, acc, v, kind, order = agency
    _post_cases(ledger, agency)
    session = Session(conn, ledger, cid, "Səyahət", Catalog(conn, cid))
    page = SubcontoAnalysisPage(
        session, ReportParams(date(2026, 6, 1), date(2026, 6, 30)), kind_id=order
    )
    qtbot.addWidget(page)
    offered = [page.kind.itemText(i) for i in range(page.kind.count())]
    assert "Sifarişlər" in offered and "Kontragentlər" in offered
    assert page.kind_id == order and page.title() == "Анализ субконто · Sifarişlər"
    assert [page._name(r) for r in page.model.rows] == [
        "S-001 Zaur, Antalya",
        "      60.1 Malsatan və podratçılarla hesablaşmalar",
        "      62.1 Alıcılar və sifarişçilərlə hesablaşmalar",
        "      90.1 Satışdan gəlir",
        "S-002 Firma MMC, bilet",
        "      60.1 Malsatan və podratçılarla hesablaşmalar",
        "      62.1 Alıcılar və sifarişçilərlə hesablaşmalar",
        "      90.1 Satışdan gəlir",
        "Итого",
    ]
    assert page.model.rows[-1].closing_ct == 120000  # 200 + 950 + 50
    assert page.footer.text() == "Элементов: 2"

    def elements() -> list[str]:  # the depth-0 rows but the total
        return [r.name for r in page.model.rows[:-1] if r.depth == 0]

    page.only_open.setChecked(True)
    assert elements() == ["S-002 Firma MMC, bilet"]
    assert page.footer.text() == "Элементов с остатком: 1"

    opened = []
    page.open_report.connect(lambda kind, account, params: opened.append((kind, account)))
    page.drill(page.model.rows[0])  # the element: its card across every account (D126)
    page.drill(page.model.rows[2])  # one account of it
    assert opened == [("subconto_card", 0), ("subconto_card", acc["62.1"])]

    page.kind.setCurrentIndex(page.kind.findData(kind["counterparty"]))
    page.kind.activated.emit(page.kind.currentIndex())
    assert elements() == ["Firma MMC", "Hava Yolları"]
    page.element.setCurrentIndex(page.element.findData(v["Zaur"]))
    page.only_open.setChecked(False)
    assert elements() == ["Zaur"]
