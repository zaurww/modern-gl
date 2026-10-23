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

import json
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
    BankPlace,
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
    parse_operation,
    portal_loads,
)
from modern_gl.i18n import tr
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.etaxes import EtaxesClient, Response, TokenExpired

OWN_TIN = "1400000001"


def raw(
    moment: str,
    income: object,
    expense: object,
    *,
    tin: str = "1100000001",
    name: str = '"ALFA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ',
    kind: str = "SUB_TO_SUB",
    destination: str = "TAXPAYER",
    receipt: str = "2619000000000000",
    explanation: str = "ƏDV köçürməsi",
    invoices: list | None = None,
    status: str = "SUCCESS",
) -> dict:
    return {
        "id": f"id{moment}",
        "tin": tin,
        "name": name,
        "operationDate": moment,
        "operationType": kind,
        "paymentType": "INCOME" if income is not None else "EXPENSE",
        "account": "CURRENT" if kind == "CURRENT_TO_SUB" else "MAIN",
        "destination": destination,
        "income": income,
        "expense": expense,
        "receiptNumber": receipt,
        "explanation": explanation,
        "operationStatus": status,
        "documentKind": "INVOICE" if invoices else "ADVANCE",
        "invoices": invoices,
    }


BETA = "2222222222"
BETA_NAME = '"BETA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ'
PORTAL = [
    raw(
        "20261001101500",
        Decimal("594"),
        None,
        receipt="2619000000000001",
        invoices=[
            {"serialNumber": "MT260812000002", "vat": Decimal("54")},
            {"serialNumber": "MT260411000001", "vat": Decimal("540")},
        ],
        tin=BETA,
        name=BETA_NAME,
    ),
    raw(
        "20261002090000",
        None,
        Decimal("12.44"),
        receipt="2619000000000002",
        invoices=[{"serialNumber": "MT261011000003", "vat": Decimal("12.4369")}],
    ),
    raw(
        "20261002120000",
        None,
        Decimal("940"),
        tin="1602473621",
        name="MİLLİ GƏLİRLƏR BAŞ İDARƏSİ",
        kind="SUB_TO_BUDGET",
        destination="BUDGET",
        receipt="2619000000000003",
    ),
    raw(
        "20261003100000",
        Decimal("90"),
        None,
        kind="CURRENT_TO_SUB",
        destination="BANK",
        receipt="nb",
        explanation="29.09.26 TARIXLI MT260912\n395884 QAIMEYE ESASEN",
        tin=BETA,
        name=BETA_NAME,
    ),
    raw(
        "20261003110000",
        Decimal("200"),
        None,
        tin=OWN_TIN,
        name="ÖZÜMÜZ MMC",
        kind="CURRENT_TO_SUB",
        destination="BANK",
        receipt="nb",
    ),
    raw("20261003120000", Decimal("50"), None, receipt="2619000000000004", status="REJECTED"),
]


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Депозит")
    apply_chart_template(ledger, cid, "1c77", "ru")
    acc = {code: ledger.account_id(cid, code) for code in ("55", "60.1", "62.1", "68.2", "51")}
    ledger.set_account_type(cid, acc["55"], "vat_deposit")
    deposit = ledger.bank.add_bank_account(cid, "ƏDV depozit", acc["55"], "vat_deposit")
    place = BankPlace(acc["55"], deposit, "ƏDV depozit", "55", None, "", "vat_deposit")
    alfa = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "counterparty"), "Альфа")
    ledger.set_subconto_value_tax(cid, alfa, "1100000001")
    return {"cid": cid, "acc": acc, "place": place, "alfa": alfa}


def operations():
    return [parse_operation(r, OWN_TIN) for r in PORTAL]


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


class FakeDepositPortal:
    """Answers like new.e-taxes.gov.az: the balance, the operations in pages of 50."""

    def __init__(
        self, rows: list[dict], balance: str = "1000", read_at: str = "", token: str = "good"
    ) -> None:
        self.rows, self.balance, self.token, self.calls = rows, balance, token, []
        self.read_at = read_at or "2026-10-03T23:00:00.123456789"

    def __call__(self, method, url, headers, body):
        request = json.loads(body) if body else None
        self.calls.append((method, url, request))
        if headers["x-authorization"] != f"Bearer {self.token}":
            return Response(401, b"")
        if url.endswith("/accountInfo"):
            answer = {"mainAccount": float(self.balance), "informationOn": self.read_at}
            return Response(200, json.dumps(answer).encode())
        page = self.rows[request["offset"] : request["offset"] + request["maxCount"]]
        more = request["offset"] + request["maxCount"] < len(self.rows)
        return Response(200, json.dumps({"operations": page, "hasMore": more}).encode())


def as_json(rows: list[dict]) -> list[dict]:
    """The rows as the portal sends them: numbers, not Decimal."""
    return json.loads(json.dumps(rows, default=float))


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
    with pytest.raises(TokenExpired):
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


def test_the_sign_in_window_says_what_it_waits_for():
    from modern_gl.desktop.portal_login import waiting_for
    from tests.test_eqaime_import import fake_token

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


@pytest.fixture
def deposit_session(ledger, firm, monkeypatch):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import portal_login
    from modern_gl.desktop.bank_page import portal as module
    from modern_gl.desktop.session import Session
    from tests.test_eqaime_import import fake_token

    cid = firm["cid"]
    messages: list[str] = []
    s = Session(
        ledger.conn, ledger, cid, "ООО Депозит", Catalog(ledger.conn, cid), notify=messages.append
    )
    s.working_date = date(2026, 10, 5)
    ledger.set_company_tax_id(cid, OWN_TIN)  # the portal's firm (D113)
    token = fake_token(OWN_TIN)
    portal = FakeDepositPortal(as_json(PORTAL), token=token)
    monkeypatch.setattr(module, "EtaxesClient", lambda token: EtaxesClient(token, send=portal))
    portal_login.forget_token()
    return s, messages, token, portal


def test_the_window_loads_the_period_chosen(qtbot, firm, deposit_session):
    from modern_gl.desktop.bank_page.portal import DepositDialog

    s, _messages, token, portal = deposit_session
    dialog = DepositDialog(s, firm["place"], sign_in=lambda _parent: token, today=date(2026, 10, 3))
    qtbot.addWidget(dialog)
    assert dialog.period() == (date(2026, 10, 1), date(2026, 10, 3))  # this month to today
    assert dialog.loaded.text() == tr("С портала в этот счёт ещё ничего не загружалось.")
    dialog.period_bar.set_period(date(2026, 10, 2), date(2026, 10, 2))
    with qtbot.waitSignal(dialog.accepted, timeout=5000):
        dialog.load()
    # the operations asked from the period's first day up to today: the balance of 02.10
    # is counted back from now
    asked = portal.calls[1][2]
    assert (asked["creationDateFrom"], asked["creationDateTo"]) == ("2026-10-02", "2026-10-03")
    assert dialog.imported is not None and dialog.imported.posted == 2
    assert loaded_spans(portal_loads(s.conn, s.company_id, firm["place"])) == [
        ("2026-10-02", "2026-10-02")
    ]


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
    dialog.period_bar.set_period(date(2026, 10, 1), date(2026, 10, 2))
    assert tr("Выбранный период уже загружен.") in dialog.loaded.text()
    asked: list[str] = []

    def no(*args):
        asked.append(args[2])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(module.QMessageBox, "question", no)
    dialog.load()
    assert len(asked) == 1 and portal.calls == []  # not loaded: the portal not asked


def test_the_bank_page_has_one_menu_with_the_portal(qtbot, firm, deposit_session, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QPushButton

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
        dialog.sign_in = lambda _parent: token
        with qtbot.waitSignal(dialog.accepted, timeout=5000):
            dialog.load()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(module.DepositDialog, "exec", run)
    monkeypatch.setattr(
        module.DepositDialog, "period", lambda _self: (date(2026, 10, 1), date(2026, 10, 3))
    )
    page.load_from_portal()
    assert messages[-1] == tr(
        "С портала: проведено {posted}, не разнесено {drafts}", posted=4, drafts=1
    ) + tr(", новых контрагентов {n}", n=1)
