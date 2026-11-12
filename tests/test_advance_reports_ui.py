"""«Подотчётные лица» and the advance report form (D218). Kapital AZN has
10 000.00 from 01.03; 02.03 Rəşad is given 500.00 from it (Dt 71 [Rəşad] / Kt 51). His
report of 05.03: 26 «Yanacaq» 320.00 — 180.00 is left to return."""

from __future__ import annotations

import pytest

from modern_gl.application.accountable import load_advance_report
from modern_gl.application.bank import IN, OTHER, OUT, BankLine, BankOperationInput
from modern_gl.desktop.accountable_page import AccountablePage, AdvanceReportPage
from modern_gl.desktop.postings import AMOUNT, DT, MEMO
from tests.helpers.bank_ui import acc, value


@pytest.fixture
def session(bank_session):
    s = bank_session
    cid = s.company_id
    employees = s.ledger.subconto_kind_id(cid, "employee")
    rashad = s.ledger.add_subconto_value(cid, employees, "Rəşad")
    s.ledger.add_subconto_value(cid, s.ledger.subconto_kind_id(cid, "cost_item"), "Yanacaq")
    s.ledger.bank.save_bank_operation(
        cid,
        BankOperationInput(
            doc_date="2026-03-02",
            direction=OUT,
            account_id=acc(s, "51"),
            subconto=(value(s, "Kapital AZN"),),
            kind=OTHER,
            lines=(BankLine(acc(s, "71"), 50000, (rashad,)),),
        ),
        post=True,
    )
    s.catalog.reload()
    s.working_date = s.working_date.replace(day=31)
    return s


def test_the_person_and_what_moved_for_him(qtbot, session):
    page = AccountablePage(session)
    qtbot.addWidget(page)
    qtbot.waitUntil(lambda: page.model.rowCount() == 1)
    [person] = page.model.rows
    assert (person.name, person.balance) == ("Rəşad", 50000)
    page.drill(person)
    qtbot.waitUntil(lambda: page.level == "person" and page.data.statement is not None)
    assert page.header.title.text() == "Rəşad"
    [line] = page.model.rows
    assert (line.issued, line.balance) == (50000, 50000)
    asked: list = []
    page.new_cash.connect(asked.append)
    menu = dict(i for i in page.more_items() if i is not None)
    menu["Принять возврат в кассу…"]()
    [cash] = asked
    assert (cash.direction, cash.lines[0].account_id, cash.lines[0].amount) == (
        IN,
        acc(session, "71"),
        50000,
    )
    page.up()
    qtbot.waitUntil(lambda: page.level == "people")


def test_a_report_typed_and_posted(qtbot, session):
    rashad = value(session, "Rəşad")
    page = AdvanceReportPage(session, employee_id=rashad)
    qtbot.addWidget(page)
    page.date.setDate(page.date.date().addDays(-26))  # 05.03
    assert page.figures["given"][1].text() == "500.00"
    m = page.model
    m.setData(m.index(0, DT), acc(session, "26"))
    m.setData(m.index(0, DT + 1), value(session, "Yanacaq"))
    m.setData(m.index(0, AMOUNT), 32000)
    m.setData(m.index(0, MEMO), "Çek 0012")
    assert page.figures["spent"][1].text() == "320.00"
    assert page.figures["left"][0].text() == "Остаток — вернуть в кассу"
    assert page.figures["left"][1].text() == "180.00"
    assert page.save(post=True), page.error.text()
    assert page.doc is not None and page.posted
    report = load_advance_report(session.conn, session.company_id, page.doc.id)
    assert [(line.account_id, line.amount, line.memo) for line in report.lines] == [
        (acc(session, "26"), 32000, "Çek 0012")
    ]
    asked: list = []
    page.new_cash.connect(asked.append)
    menu = dict(i for i in page.menu_items() if i is not None)
    menu["Принять остаток в кассу…"]()
    [cash] = asked
    assert (cash.direction, cash.lines[0].amount) == (IN, 18000)
