"""The ƏDV deposit account from the tax portal (D112).

The portal's operations of 01–03.10.2026 (as `vatacc/…/operation/find.outbox` gives them),
the balance on the portal now 1 000.00. Hand-calculated:

  01.10  in   594.00  Beta (new, VÖEN 2222222222), e-qaimə MT260411000001 ƏDV 540.00
                      and MT260812000002 ƏDV 54.00          → 62.1: 540.00 + 54.00
  02.10  out   12.44  Alfa, e-qaimə MT261011000003 ƏDV 12.4369 → 60.1: 12.44
  02.10  out  940.00  to the budget                           → 68.2 (ƏDV by its role)
  03.10  in    90.00  Beta from its bank ("nb"), the purpose names MT260912 395884
  03.10  in   200.00  the company's own bank (its VÖEN)       → a transfer: a draft
  03.10  in    50.00  status REJECTED                         → not loaded

  end of 03.10: 1 000.00 (the portal now)
  end of 02.10: 1 000.00 − 90.00 − 200.00     =   710.00
  end of 01.10:   710.00 + 12.44 + 940.00     = 1 662.44
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from modern_gl.application.bank import (
    CUSTOMER,
    IN,
    OUT,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    bank_statements,
    load_bank_operation,
)
from modern_gl.application.bank.deposit_import import (
    PortalLoad,
    day_closings,
    fetch_deposit,
    invoices_in,
    loaded_already,
    loaded_spans,
    portal_loads,
)
from modern_gl.application.bank.imported import DRAFT, POSTED
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient, TokenExpiredError
from tests.helpers.qt import tree_item
from tests.helpers.vat_deposit import OWN_TIN, PORTAL, FakeDepositPortal, as_json, operations, raw


@pytest.fixture
def firm(deposit_firm):
    return deposit_firm


def test_an_operation_of_the_portal():
    ops = operations()
    assert [(o.day, o.direction, o.amount, o.kind, o.done) for o in ops] == [
        ("2026-10-01", IN, 59400, CUSTOMER, True),
        ("2026-10-02", OUT, 1244, SUPPLIER, True),
        ("2026-10-02", OUT, 94000, TAX, True),
        ("2026-10-03", IN, 9000, CUSTOMER, True),
        ("2026-10-03", IN, 20000, TRANSFER, True),
        ("2026-10-03", IN, 5000, CUSTOMER, False),
    ]
    # the e-qaimə oldest first, the ƏDV in minor units (12.4369 → 12.44)
    assert ops[0].invoices == (("MT260411000001", 54000), ("MT260812000002", 5400))
    assert ops[1].invoices == (("MT261011000003", 1244),)
    # a payment from a bank: no receipt number, the portal's id; the purpose's e-qaimə
    assert (ops[3].reference, ops[3].invoices) == ("id20261003100000", (("MT260912395884", None),))
    assert ops[0].reference == "2619000000000001"
    assert ops[3].memo == "29.09.26 TARIXLI MT260912395884 QAIMEYE ESASEN"


def test_invoice_numbers_in_a_purpose():
    assert invoices_in("ƏDV köçürməsi-MT260411863435  ve  MT2604 11644581, mt260411863435") == [
        "MT260411863435",
        "MT260411644581",
    ]


def test_the_balance_of_each_day_counted_back_from_now():
    assert day_closings(operations(), 100000) == {
        "2026-10-03": 100000,
        "2026-10-02": 71000,
        "2026-10-01": 166244,
    }


def lines(ledger, cid, operation_id):
    op = load_bank_operation(ledger.conn, cid, operation_id)
    codes = {r["id"]: r["code"] for r in ledger.conn.execute("SELECT id, code FROM accounts")}
    return op, [(codes.get(x.account_id), x.amount, x.invoice) for x in op.lines]


def by_reference(ledger, cid):
    return {
        r["reference"]: r["id"]
        for r in ledger.conn.execute(
            "SELECT id, reference FROM bank_operations WHERE company_id = ?", (cid,)
        )
    }


def test_the_import_posts_what_is_known_and_drafts_the_rest(ledger, firm):
    cid, place = firm["cid"], firm["place"]
    done = ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    assert (done.posted, len(done.drafts), done.linked, done.known) == (4, 1, 0, 0)
    assert done.counterparties == 1  # Beta, by its VÖEN
    ids = by_reference(ledger, cid)

    beta, beta_lines = lines(ledger, cid, ids["2619000000000001"])
    assert (beta.status, beta.direction, beta.kind) == ("posted", IN, CUSTOMER)
    assert beta_lines == [("62.1", 54000, "MT260411000001"), ("62.1", 5400, "MT260812000002")]
    name, tin = ledger.conn.execute(
        "SELECT name, tax_id FROM subconto_values WHERE id = ?", (beta.counterparty_id,)
    ).fetchone()
    assert (name, tin) == ("BETA MMC", "2222222222")

    alfa, alfa_lines = lines(ledger, cid, ids["2619000000000002"])
    assert (alfa.status, alfa.counterparty_id) == ("posted", firm["alfa"])
    assert alfa_lines == [("60.1", 1244, "MT261011000003")]

    advance, advance_lines = lines(ledger, cid, ids["id20261003100000"])
    assert advance.counterparty_id == beta.counterparty_id  # the same Beta, not a second one
    assert advance_lines == [("62.1", 9000, "MT260912395884")]

    tax, tax_lines = lines(ledger, cid, ids["2619000000000003"])
    assert (tax.kind, tax.counterparty_id, tax_lines) == (TAX, None, [("68.2", 94000, "")])

    [(op, _why)] = done.drafts
    own, own_lines = lines(ledger, cid, ids["id20261003110000"])
    assert (op.kind, own.status, own_lines) == (TRANSFER, "draft", [(None, 20000, "")])


def test_the_preview_shows_what_the_import_does_and_writes_nothing(ledger, firm):
    cid, place = firm["cid"], firm["place"]
    before = ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    seen = ledger.bank.preview_vat_deposit(cid, place, operations(), 100000)
    assert [(r.op.reference, r.state, r.lines, r.document_id) for r in seen.rows] == [
        (
            "2619000000000001",
            POSTED,
            (("62.1", "MT260411000001", 54000), ("62.1", "MT260812000002", 5400)),
            None,
        ),
        ("2619000000000002", POSTED, (("60.1", "MT261011000003", 1244),), None),
        ("2619000000000003", POSTED, (("68.2", "", 94000),), None),
        ("id20261003100000", POSTED, (("62.1", "MT260912395884", 9000),), None),
        ("id20261003110000", DRAFT, (("", "", 20000),), None),
    ]
    assert seen.rows[-1].reason  # why the transfer is a draft
    assert ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before
    assert by_reference(ledger, cid) == {}
    assert portal_loads(ledger.conn, cid, place) == []
    # the import does the same and names the documents
    done = ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    assert [(r.op.reference, r.state) for r in done.rows] == [
        (r.op.reference, r.state) for r in seen.rows
    ]
    assert all(r.document_id for r in done.rows)


def test_only_the_operations_taken_are_loaded_as_drafts(ledger, firm):
    """Alfa's 12.44 and the budget's 940.00 of 02.10 taken, as drafts: the period is not
    remembered — Beta's 594.00 of 01.10 was left out."""
    cid, place = firm["cid"], firm["place"]
    take = {"2619000000000002", "2619000000000003"}
    done = ledger.bank.import_vat_deposit(
        cid, place, operations(), 100000, ("2026-10-01", "2026-10-02"), take=take, post=False
    )
    assert (done.posted, len(done.drafts), done.counterparties) == (0, 2, 0)
    assert set(by_reference(ledger, cid)) == take
    statuses = {
        r["status"]
        for r in ledger.conn.execute("SELECT status FROM documents WHERE company_id = ?", (cid,))
    }
    assert statuses == {"draft"}
    assert portal_loads(ledger.conn, cid, place) == []
    # all of the period taken: remembered
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000, ("2026-10-01", "2026-10-02"))
    assert loaded_spans(portal_loads(ledger.conn, cid, place)) == [("2026-10-01", "2026-10-02")]


def test_every_day_gets_the_balance_by_the_portal(ledger, firm):
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    days = {s.date_from: s for s in bank_statements(ledger.conn, cid, place)}
    assert {d: (s.bank_closing, s.closing) for d, s in days.items()} == {
        # the books start from zero: the opening 1 068.44 is not in them yet
        "2026-10-01": (166244, 59400),
        "2026-10-02": (71000, 59400 - 1244 - 94000),
        "2026-10-03": (100000, 59400 - 1244 - 94000 + 9000),  # the transfer is a draft
    }


def test_loading_again_adds_nothing(ledger, firm):
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    count = ledger.conn.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0]
    again = ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    assert (again.posted, again.drafts, again.known, again.counterparties) == (0, [], 5, 0)
    assert ledger.conn.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == count


def test_a_payment_entered_by_hand_is_marked_not_doubled(ledger, firm):
    """The ƏDV part of a payment to Alfa typed in the bank form (D69) on the same day."""
    cid, place, acc = firm["cid"], firm["place"], firm["acc"]
    typed = ledger.bank.save_bank_operation(
        cid,
        BankOperationInput(
            doc_date="2026-10-02",
            direction=OUT,
            account_id=place.account_id,
            subconto=place.subconto,
            kind=SUPPLIER,
            counterparty_id=firm["alfa"],
            lines=(BankLine(acc["60.1"], 1244, (), "MT261011000003"),),
        ),
        post=True,
    )
    done = ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    assert (done.posted, done.linked) == (3, 1)
    assert by_reference(ledger, cid)["2619000000000002"] == typed


# ---- the portal ---------------------------------------------------------------------


def test_the_client_pages_the_operations():
    rows = [raw(f"202610010{i:05d}", 1, None) for i in range(60)]
    portal = FakeDepositPortal(as_json(rows))
    client = EtaxesClient("good", send=portal)
    got = list(client.vat_deposit_operations(date(2026, 10, 1), date(2026, 10, 23)))
    assert len(got) == 60 and len(portal.calls) == 2
    first = portal.calls[0]
    assert first[1].endswith("/vatacc/public/v1/operation/find.outbox")
    assert (first[2]["creationDateFrom"], first[2]["creationDateTo"]) == (
        "2026-10-01",
        "2026-10-23",
    )
    assert client.vat_deposit_balance() == (Decimal("1000.0"), "2026-10-03T23:00:00.123456789")
    with pytest.raises(TokenExpiredError):
        EtaxesClient("old", send=portal).vat_deposit_balance()


def test_an_operation_after_the_balance_waits_for_next_time():
    """The balance was read at 03.10 10:30: the operations of 11:00 and 12:00 are not in it."""
    portal = FakeDepositPortal(as_json(PORTAL), "710", "2026-10-03T10:30:00")
    fetched = fetch_deposit(
        EtaxesClient("good", send=portal), date(2026, 10, 1), date(2026, 10, 3), OWN_TIN, print
    )
    assert [op.moment for op in fetched.operations] == [
        "20261001101500",
        "20261002090000",
        "20261002120000",
        "20261003100000",
    ]
    assert (fetched.balance, fetched.operations[1].amount) == (71000, 1244)


def test_the_vat_paid_to_a_supplier_from_the_bank_is_not_on_the_deposit():
    """The portal's file of 26.10.2026 (shortened): «Hesabın növü: Cari hesabı» — the ƏDV
    paid from the company's current account, the deposit's balance does not count it.

      31.07  in   1 666.80  a customer from its bank ("nb")   on the deposit
      10.08  out    720.00  a supplier, from the current account  not on the deposit
      11.08  out  1 666.80  to the budget, from the deposit       on the deposit
      balance on the portal: 1 666.80 − 1 666.80 = 0.00; end of 31.07: 0 + 1 666.80"""
    rows = [
        raw("20260731100000", Decimal("1666.80"), None, kind="CURRENT_TO_SUB", receipt="nb"),
        {
            **raw("20260810100000", None, Decimal("720"), receipt="nb"),
            "account": "CURRENT",
            "operationType": "CURRENT_TO_SUB",
        },
        raw("20260811100000", None, Decimal("1666.80"), kind="SUB_TO_BUDGET", destination="BUDGET"),
    ]
    portal = FakeDepositPortal(as_json(rows), "0", "2026-10-26T15:18:00")
    fetched = fetch_deposit(
        EtaxesClient("good", send=portal), date(2026, 7, 1), date(2026, 10, 26), OWN_TIN, print
    )
    assert [(op.day, op.net) for op in fetched.operations] == [
        ("2026-07-31", 166680),
        ("2026-08-11", -166680),
    ]
    assert day_closings(fetched.operations, fetched.balance) == {
        "2026-08-11": 0,
        "2026-07-31": 166680,
    }


def test_only_the_period_is_loaded_and_remembered(ledger, firm):
    """02.10 alone: Alfa's 12.44 and the budget's 940.00; the later operations only count
    the balance back — the end of 02.10 is 710.00 (see the top)."""
    cid, place = firm["cid"], firm["place"]
    done = ledger.bank.import_vat_deposit(
        cid, place, operations(), 100000, ("2026-10-02", "2026-10-02")
    )
    assert (done.posted, done.drafts, done.counterparties) == (2, [], 0)
    assert set(by_reference(ledger, cid)) == {"2619000000000002", "2619000000000003"}
    days = {s.date_from: s.bank_closing for s in bank_statements(ledger.conn, cid, place)}
    assert days == {"2026-10-02": 71000}
    [load] = portal_loads(ledger.conn, cid, place)
    assert (load.date_from, load.date_to, load.operations) == ("2026-10-02", "2026-10-02", 2)

    # then 01–03.10: the two of 02.10 are known, the rest is new
    again = ledger.bank.import_vat_deposit(
        cid, place, operations(), 100000, ("2026-10-01", "2026-10-03")
    )
    assert (again.known, again.posted, len(again.drafts)) == (2, 2, 1)
    loads = portal_loads(ledger.conn, cid, place)
    assert loaded_spans(loads) == [("2026-10-01", "2026-10-03")]


def a_load(first: str, last: str) -> PortalLoad:
    return PortalLoad(first, last, "2026-10-23T10:00:00", 0)


def test_loaded_periods_are_joined():
    loads = [
        a_load("2026-10-05", "2026-10-09"),
        a_load("2026-09-01", "2026-09-30"),
        a_load("2026-10-01", "2026-10-03"),
    ]
    # 30.09 and 01.10 go on; between 03.10 and 05.10 the 4th is missing
    assert loaded_spans(loads) == [("2026-09-01", "2026-10-03"), ("2026-10-05", "2026-10-09")]
    assert loaded_already(loads, "2026-09-15", "2026-10-02")
    assert not loaded_already(loads, "2026-10-01", "2026-10-05")  # 04.10 was not loaded
    assert not loaded_already([], "2026-10-01", "2026-10-01")


def test_a_day_loaded_on_that_day_is_not_closed():
    """Loaded on 23.10 at 15:00 for 20–23.10: 23.10 had not ended, a later operation of it
    may come — only 20–22.10 count as loaded; loaded on 24.10 — the whole period."""
    same_day = PortalLoad("2026-10-20", "2026-10-23", "2026-10-23T15:00:00", 0)
    assert loaded_spans([same_day]) == [("2026-10-20", "2026-10-22")]
    assert not loaded_already([same_day], "2026-10-23", "2026-10-23")
    assert loaded_already([same_day], "2026-10-21", "2026-10-22")
    next_day = PortalLoad("2026-10-20", "2026-10-23", "2026-10-24T09:00:00", 0)
    assert loaded_spans([next_day]) == [("2026-10-20", "2026-10-23")]
    only_today = PortalLoad("2026-10-23", "2026-10-23", "2026-10-23T15:00:00", 0)
    assert loaded_spans([only_today]) == []


def test_the_sign_in_window_says_what_it_waits_for():
    from modern_gl.desktop.portal_login import waiting_for
    from tests.helpers.eqaime import fake_token

    assert waiting_for(None) == tr("Ждём входа на портал…")
    assert waiting_for(fake_token(lifetime=-10)) == tr(
        "Вход на портал устарел — войдите ещё раз или обновите страницу"
    )
    assert waiting_for(fake_token(voen="")) == tr("Вход выполнен — выберите на портале компанию")
    assert waiting_for(fake_token(OWN_TIN), "1500000000") == tr(
        "На портале выбрана фирма с VÖEN {tin}, а нужна VÖEN {own} — выберите её",
        tin=OWN_TIN,
        own="1500000000",
    )
    assert waiting_for(fake_token(OWN_TIN), OWN_TIN) == ""
    assert waiting_for(fake_token(OWN_TIN)) == ""  # the company's VÖEN not known yet


def test_the_window_loads_the_period_chosen(qtbot, firm, deposit_session):
    """02.10: Alfa's 12.44 and the budget's 940.00 shown before anything is written; the
    budget's left out — only Alfa's posted, the period not remembered."""
    from PySide6.QtCore import Qt

    from modern_gl.desktop.bank_page.portal import DONE, PREVIEW, DepositDialog

    s, _messages, token, portal = deposit_session
    place = firm["place"]
    dialog = DepositDialog(s, place, sign_in=lambda _parent: token, today=date(2026, 10, 3))
    qtbot.addWidget(dialog)
    assert dialog.period() == (date(2026, 10, 1), date(2026, 10, 3))  # this month to today
    assert dialog.loaded.text() == tr("С портала в этот счёт ещё ничего не загружалось.")
    dialog.period_field.set_period(date(2026, 10, 2), date(2026, 10, 2))
    dialog.load()
    qtbot.waitUntil(lambda: dialog.step == PREVIEW, timeout=5000)
    # the operations asked from the period's first day up to today: the balance of 02.10
    # is counted back from now
    asked = portal.calls[1][2]
    assert (asked["creationDateFrom"], asked["creationDateTo"]) == ("2026-10-02", "2026-10-03")
    assert by_reference(s.ledger, s.company_id) == {}  # nothing written yet
    assert [(r.op.amount, r.state) for r in dialog.rows.rows()] == [(1244, POSTED), (94000, POSTED)]
    # the books have nothing yet: after 02.10 they would be 0 − 12.44 − 940.00 = −952.44
    assert (
        dialog.balances.text()
        == tr(
            "На портале сейчас {portal} ₼, в программе {books} ₼", portal="1 000.00", books="0.00"
        )
        + tr(", после загрузки будет {after} ₼", after="-952.44")
        + tr(" — разница {diff} ₼", diff="1 952.44")
        + "."
    )

    tree_item(dialog.rows, 1).setCheckState(0, Qt.CheckState.Unchecked)
    assert tr(", после загрузки будет {after} ₼", after="-12.44") in dialog.balances.text()
    dialog.post_button.click()
    assert dialog.step == DONE  # what became of them: in the window, not closed
    assert dialog.imported is not None and dialog.imported.posted == 1
    assert set(by_reference(s.ledger, s.company_id)) == {"2619000000000002"}
    assert portal_loads(s.conn, s.company_id, place) == []  # the budget's was left out
    [row] = dialog.rows.rows()
    assert row.document_id is not None
    item = dialog.rows.topLevelItem(0)
    dialog.rows.itemDoubleClicked.emit(item, 0)
    assert (
        dialog.chosen_document == row.document_id and dialog.result() == dialog.DialogCode.Accepted
    )


def test_a_period_loaded_already_is_asked_about(qtbot, ledger, firm, deposit_session, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from modern_gl.desktop.bank_page import portal as module

    s, _messages, token, portal = deposit_session
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000, ("2026-10-01", "2026-10-02"))
    dialog = module.DepositDialog(s, place, sign_in=lambda _parent: token, today=date(2026, 10, 3))
    qtbot.addWidget(dialog)
    # the next period suggested: from the day after the last one loaded up to today
    assert dialog.period() == (date(2026, 10, 3), date(2026, 10, 3))
    assert dialog.loaded.text() == tr(
        "Уже загружено с портала: {periods}.", periods="01.10–02.10.2026"
    )
    dialog.period_field.set_period(date(2026, 10, 1), date(2026, 10, 2))
    assert tr("Выбранный период уже загружен.") in dialog.loaded.text()
    asked: list[str] = []

    def no(*args):
        asked.append(args[2])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(module.QMessageBox, "question", no)
    dialog.load()
    assert len(asked) == 1 and portal.calls == []  # not loaded: the portal not asked


def test_a_day_loaded_before_it_ended_is_suggested_again(qtbot, ledger, firm, deposit_session):
    """Loaded on 03.10 for 01–03.10: next day the window starts from 03.10 and says why."""
    from modern_gl.desktop.bank_page.portal import DepositDialog

    s, _messages, token, _portal = deposit_session
    cid, place = firm["cid"], firm["place"]
    ledger.conn.execute(
        "INSERT INTO bank_portal_loads (company_id, account_id, value_id, date_from, date_to, "
        "loaded_at, operations) VALUES (?, ?, ?, '2026-10-01', '2026-10-03', "
        "'2026-10-03T14:00:00', 4)",
        (cid, place.account_id, place.value_id),
    )
    dialog = DepositDialog(s, place, sign_in=lambda _parent: token, today=date(2026, 10, 4))
    qtbot.addWidget(dialog)
    assert dialog.period() == (date(2026, 10, 3), date(2026, 10, 4))
    assert dialog.loaded.text() == " ".join(
        [
            tr("Уже загружено с портала: {periods}.", periods="01.10–02.10.2026"),
            tr(
                "{days} загружено, пока день не кончился: поздние операции этого дня "
                "возьмутся при следующей загрузке.",
                days="03.10.2026",
            ),
        ]
    )


def test_the_bank_page_has_one_menu_with_the_portal(qtbot, firm, deposit_session, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from modern_gl.application.bank import BankAccount
    from modern_gl.desktop.bank_page import BankPage
    from modern_gl.desktop.bank_page import portal as module

    s, messages, token, _portal = deposit_session
    page = BankPage(s)
    qtbot.addWidget(page)
    more = [b for b in page.header.findChildren(QPushButton) if b.toolTip() == tr("Ещё")]
    assert len(more) == 1  # D86: one «⋯» — the bank's actions and the report's together
    model = page.table.model()
    row = next(
        model.index(r, 0)
        for r in range(model.rowCount())
        if isinstance(account := model.index(r, 0).data(Qt.ItemDataRole.UserRole), BankAccount)
        and account.place.key == firm["place"].key
    )
    page.table.setCurrentIndex(row)  # at the list of accounts: the deposit under the cursor
    titles = [item[0] for item in page.more_items() if item]
    assert tr("Загрузить с портала…") in titles and tr("В Excel…") in titles

    def run(dialog):
        dialog.fetch.sign_in = lambda _parent: token
        dialog.load()
        qtbot.waitUntil(lambda: dialog.step == module.PREVIEW, timeout=5000)
        dialog.post_button.click()
        dialog.rows.itemDoubleClicked.emit(dialog.rows.topLevelItem(0), 0)  # Beta's 594.00
        return dialog.result()

    monkeypatch.setattr(module.DepositDialog, "exec", run)
    monkeypatch.setattr(
        module.DepositDialog, "period", lambda _self: (date(2026, 10, 1), date(2026, 10, 3))
    )
    opened: list[int] = []
    page.open_document.connect(opened.append)
    told = len(messages)
    page.load_from_portal()
    assert len(messages) == told  # what the import did is said in the window, not a toast
    beta = by_reference(s.ledger, s.company_id)["2619000000000001"]
    document = s.conn.execute("SELECT document_id FROM bank_operations WHERE id = ?", (beta,))
    assert opened == [document.fetchone()[0]]


def test_the_window_warns_of_a_reconciled_period_changed(qtbot, ledger, firm, deposit_session):
    """01–03.10 marked reconciled when the portal had no 90.00 of 03.10 (in 794.00, now
    910.00); then a fee of 5.00 on 02.10 typed by hand. Opened: the change in the books is
    said at once (out 952.44 → 957.44, closing −268.44 → −273.44); loaded from 01.10: the
    portal's too (in 794.00 → 884.00, closing 910.00 → 1 000.00) — D118."""
    from modern_gl.application.bank.deposit_reconciliation import reconcile_deposit
    from modern_gl.desktop.bank_page.portal import PREVIEW, DepositDialog
    from tests.helpers.deposit import fee

    s, _messages, token, _portal = deposit_session
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    fewer = [op for op in operations() if op.amount != 9000]
    seen = reconcile_deposit(ledger.conn, cid, place, fewer, 91000, "2026-10-01", "2026-10-03")
    ledger.bank.mark_deposit_reconciled(cid, place, seen)
    dialog = DepositDialog(s, place, sign_in=lambda _parent: token, today=date(2026, 10, 3))
    qtbot.addWidget(dialog)
    assert dialog.changes.isHidden()  # nothing changed since

    fee(ledger, firm, "2026-10-02")
    dialog = DepositDialog(s, place, sign_in=lambda _parent: token, today=date(2026, 10, 3))
    qtbot.addWidget(dialog)
    changed = tr(
        "{period} сверен, но {side} изменилось: приход {was_in} → {now_in}, расход "
        "{was_out} → {now_out}, на конец {was_end} → {now_end}",
        period="01.10.2026–03.10.2026",
        side=tr("в программе"),
        was_in="684.00",
        now_in="684.00",
        was_out="952.44",
        now_out="957.44",
        was_end="-268.44",
        now_end="-273.44",
    )
    assert not dialog.changes.isHidden() and dialog.changes.text() == changed + "."

    dialog.period_field.set_period(date(2026, 10, 1), date(2026, 10, 3))
    dialog.load()
    qtbot.waitUntil(lambda: dialog.step == PREVIEW, timeout=5000)
    on_portal = tr(
        "{period} сверен, но {side} изменилось: приход {was_in} → {now_in}, расход "
        "{was_out} → {now_out}, на конец {was_end} → {now_end}",
        period="01.10.2026–03.10.2026",
        side=tr("на портале"),
        was_in="794.00",
        now_in="884.00",
        was_out="952.44",
        now_out="952.44",
        was_end="910.00",
        now_end="1 000.00",
    )
    assert dialog.changes.text() == f"{changed}. {on_portal}."
