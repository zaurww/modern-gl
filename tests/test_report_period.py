"""The period a report opens with (D203): the working date's whole year,
and after a period was chosen in a report — that one, in every report, until the program
is closed (1C 7.7's «период итогов»). The ƏDV reports are monthly and keep to themselves."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.reports_page import CardPage, OsvPage, ReportParams, usual_period
from modern_gl.desktop.reports_page.vat_credit import VatCreditPage
from modern_gl.desktop.session import Session

YEAR = (date(2026, 1, 1), date(2026, 12, 31))
FEBRUARY = (date(2026, 2, 1), date(2026, 2, 28))
MARCH = (date(2026, 3, 1), date(2026, 3, 31))


@pytest.fixture
def session(demo) -> Session:
    cid = demo.company_id
    s = Session(demo.ledger.conn, demo.ledger, cid, "ООО Тест", Catalog(demo.ledger.conn, cid))
    s.working_date = date(2026, 2, 10)
    return s


def shown(page) -> tuple[date, date]:
    return page.params.date_from, page.params.date_to


def test_a_report_opens_on_the_whole_year_of_the_working_date(session, demo, qtbot):
    osv = OsvPage(session)
    qtbot.addWidget(osv)
    assert shown(osv) == YEAR
    assert osv.period.period() == YEAR
    card = CardPage(session, demo.acc["201"], usual_period(session))
    qtbot.addWidget(card)
    assert shown(card) == YEAR


def test_the_period_chosen_in_a_report_is_the_next_report_s(session, demo, qtbot):
    osv = OsvPage(session)
    qtbot.addWidget(osv)
    osv.period.set_period(*FEBRUARY)
    assert shown(osv) == FEBRUARY
    card = CardPage(session, demo.acc["201"], usual_period(session))
    qtbot.addWidget(card)
    assert shown(card) == FEBRUARY
    # a report opened from another with its period (a number of the ОСВ) chooses nothing
    drilled = CardPage(session, demo.acc["201"], ReportParams(*MARCH))
    qtbot.addWidget(drilled)
    assert shown(drilled) == MARCH
    again = OsvPage(session)
    qtbot.addWidget(again)
    assert shown(again) == FEBRUARY


def test_the_choice_lasts_until_the_program_is_closed(session, demo, qtbot):
    osv = OsvPage(session)
    qtbot.addWidget(osv)
    osv.period.set_period(*FEBRUARY)
    cid = demo.company_id
    started_again = Session(
        demo.ledger.conn, demo.ledger, cid, "ООО Тест", Catalog(demo.ledger.conn, cid)
    )
    started_again.working_date = date(2026, 2, 10)
    fresh = OsvPage(started_again)
    qtbot.addWidget(fresh)
    assert shown(fresh) == YEAR


def test_the_vat_reports_are_monthly_and_keep_to_themselves(session, qtbot):
    osv = OsvPage(session)
    qtbot.addWidget(osv)
    vat = VatCreditPage(session)
    qtbot.addWidget(vat)
    assert shown(vat) == FEBRUARY  # the month of the working date: ƏDV is declared monthly
    vat.period.set_period(*MARCH)
    assert shown(vat) == MARCH
    after = OsvPage(session)
    qtbot.addWidget(after)
    assert shown(after) == YEAR
    osv.period.set_period(*MARCH)
    another = VatCreditPage(session)
    qtbot.addWidget(another)
    assert shown(another) == FEBRUARY
