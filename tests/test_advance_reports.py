"""Accountable persons and advance reports (D-new-advance-reports). Hand-calculated, March
2026, the 1C 7.7 chart (71 «Расчёты с подотчётными лицами», subconto — the employee):

01.03  journal: Dt 50 / Ct 80 [Учредитель]                       1 000.00
02.03  cash out to Rəşad: Dt 71 [Rəşad] / Ct 50                     500.00
05.03  advance report №1 of Rəşad:
         fuel, «Çek 0012»: Dt 26 [Yanacaq] / Ct 71 [Rəşad]          320.00
         ALFA paid:        Dt 60.1 [ALFA, Договор 1] / Ct 71 [Rəşad] 100.00
       Rəşad owes 500.00 − 420.00 = 80.00
06.03  cash in from Rəşad: Dt 50 / Ct 71 [Rəşad]                     80.00  → 0.00
10.03  advance report №2: Dt 26 [Yanacaq] / Ct 71 [Rəşad]            50.00  → −50.00
       (the company owes him: pay out of the cash desk)
"""

from __future__ import annotations

import pytest

from modern_gl.application.accountable import (
    AccountableModule,
    AdvanceLine,
    AdvanceReportInput,
    accountable_account,
    accountable_people,
    employee_balance,
    load_advance_report,
    person_statement,
)
from modern_gl.application.bank import IN, OTHER, OUT, BankLine, BankOperationInput
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import document_owner, load_document
from modern_gl.application.rebuild import rebuild_postings
from modern_gl.domain.errors import ValidationError


@pytest.fixture
def firm(bank_firm, ledger):
    f = bank_firm
    cid, kind = f["cid"], f["kind"]
    for code in ("50", "71"):
        f["acc"][code] = ledger.account_id(cid, code)
    f["v"]["rashad"] = ledger.add_subconto_value(cid, kind["employee"], "Rəşad")
    f["v"]["fuel"] = ledger.add_subconto_value(cid, kind["cost_item"], "Yanacaq")
    acc, v = f["acc"], f["v"]
    ledger.post_new(
        cid, "2026-03-01", [PostingInput(acc["50"], acc["80"], "1000", (), [v["owner"]])]
    )
    return f


@pytest.fixture
def module(ledger):
    return AccountableModule(ledger.conn, ledger.actor, ledger=ledger)


def cash(ledger, f, day: str, direction: str, amount: int) -> None:
    acc, v = f["acc"], f["v"]
    ledger.bank.save_bank_operation(
        f["cid"],
        BankOperationInput(
            doc_date=day,
            direction=direction,
            account_id=acc["50"],
            kind=OTHER,
            lines=(BankLine(acc["71"], amount, (v["rashad"],)),),
        ),
        post=True,
    )


def first_report(f) -> AdvanceReportInput:
    acc, v = f["acc"], f["v"]
    return AdvanceReportInput(
        doc_date="2026-03-05",
        employee_id=v["rashad"],
        lines=(
            AdvanceLine(acc["26"], 32000, (v["fuel"],), "Çek 0012"),
            AdvanceLine(acc["60.1"], 10000, (v["alfa"], v["contract"])),
        ),
    )


def test_the_accountable_account_is_71(ledger, firm):
    found = accountable_account(ledger.conn, firm["cid"])
    assert found is not None and (found.code, found.position) == ("71", 1)
    # an old company without the role: the first account of the employees — 71, not 73
    ledger.conn.execute("DELETE FROM account_roles WHERE role = 'accountable'")
    found = accountable_account(ledger.conn, firm["cid"])
    assert found is not None and found.code == "71"


def test_a_report_spends_what_was_given(ledger, firm, module):
    cid, acc, v = firm["cid"], firm["acc"], firm["v"]
    cash(ledger, firm, "2026-03-02", OUT, 50000)
    report_id = module.save_advance_report(cid, first_report(firm), post=True)
    report = load_advance_report(ledger.conn, cid, report_id)
    assert report.status == "posted" and report.account_id == acc["71"]
    postings = load_document(ledger.conn, cid, report.document_id).postings
    assert [
        (p.debit_account_id, p.credit_account_id, p.amount, p.credit_subconto[0], p.memo)
        for p in postings
    ] == [
        (acc["26"], acc["71"], 32000, v["rashad"], "Çek 0012"),
        (acc["60.1"], acc["71"], 10000, v["rashad"], "Авансовый отчёт: Rəşad"),
    ]
    account = accountable_account(ledger.conn, cid)
    assert account is not None
    assert employee_balance(ledger.conn, cid, account, v["rashad"], "2026-03-05") == 8000
    # what he had before the report: the form shows it
    assert (
        employee_balance(
            ledger.conn, cid, account, v["rashad"], "2026-03-05", without=report.document_id
        )
        == 50000
    )
    owner = document_owner(ledger.conn, cid, report.document_id)
    assert owner is not None and owner.module == "accountable"


def test_the_person_and_his_movements(ledger, firm, module):
    cid, v = firm["cid"], firm["v"]
    cash(ledger, firm, "2026-03-02", OUT, 50000)
    module.save_advance_report(cid, first_report(firm), post=True)
    cash(ledger, firm, "2026-03-06", IN, 8000)
    account = accountable_account(ledger.conn, cid)
    assert account is not None
    people = accountable_people(ledger.conn, cid, account, "2026-03-31")
    assert [(p.name, p.balance, p.last_day) for p in people] == [("Rəşad", 0, "2026-03-06")]
    st = person_statement(ledger.conn, cid, account, v["rashad"], "2026-03-03", "2026-03-31")
    assert st.opening == 50000
    assert [(line.kind, line.issued, line.settled, line.balance) for line in st.lines] == [
        ("advance_report", 0, 42000, 8000),
        ("cash_in", 0, 8000, 0),
    ]
    # a report beyond what was given: the company owes him 50.00
    acc = firm["acc"]
    module.save_advance_report(
        cid,
        AdvanceReportInput(
            "2026-03-10", v["rashad"], (AdvanceLine(acc["26"], 5000, (v["fuel"],)),)
        ),
        post=True,
    )
    [person] = accountable_people(ledger.conn, cid, account, "2026-03-31")
    assert person.balance == -5000


def test_a_draft_keeps_what_was_typed_and_posts_later(ledger, firm, module):
    cid = firm["cid"]
    data = AdvanceReportInput("2026-03-05", None, (AdvanceLine(None, 0),))
    report_id = module.save_advance_report(cid, data, post=False)
    report = load_advance_report(ledger.conn, cid, report_id)
    assert report.status == "draft" and report.memo == "Авансовый отчёт"
    with pytest.raises(ValidationError, match="сотрудник"):
        module.save_advance_report(cid, data, report_id, post=True)
    module.save_advance_report(cid, first_report(firm), report_id, post=True)
    assert load_advance_report(ledger.conn, cid, report_id).status == "posted"


def test_posted_is_changed_in_place_unposted_and_deleted(ledger, firm, module):
    cid, acc, v = firm["cid"], firm["acc"], firm["v"]
    report_id = module.save_advance_report(cid, first_report(firm), post=True)
    number = load_advance_report(ledger.conn, cid, report_id).number
    changed = AdvanceReportInput(
        "2026-03-05", v["rashad"], (AdvanceLine(acc["26"], 30000, (v["fuel"],)),)
    )
    module.save_advance_report(cid, changed, report_id, post=True)
    report = load_advance_report(ledger.conn, cid, report_id)
    assert report.number == number and report.total == 30000
    with pytest.raises(ValidationError, match="отмените проведение"):
        module.save_advance_report(cid, changed, report_id, post=False)
    module.unpost_advance_report(cid, report_id)
    report = load_advance_report(ledger.conn, cid, report_id)
    assert report.status == "draft"
    assert not load_document(ledger.conn, cid, report.document_id).postings
    module.delete_advance_report(cid, report_id)
    assert not ledger.conn.execute("SELECT 1 FROM advance_reports").fetchall()


def test_a_line_is_not_on_the_accountable_account(ledger, firm, module):
    acc, v = firm["acc"], firm["v"]
    data = AdvanceReportInput("2026-03-05", v["rashad"], (AdvanceLine(acc["71"], 100),))
    with pytest.raises(ValidationError, match="подотчётных"):
        module.save_advance_report(firm["cid"], data, post=True)


def test_a_rebuild_of_what_was_posted_changes_nothing(ledger, firm, module):
    module.save_advance_report(firm["cid"], first_report(firm), post=True)
    assert rebuild_postings(ledger, firm["cid"], "2026-01-01") == []
