"""Reconciliation with the tax portal (D53): the portal's list, what is kept of it, the
books against it, the months marked reconciled. Figures worked out by hand in comments."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.eqaime_portal import fetch_list, rechecks, usual_span
from modern_gl.application.inventory import ReceiptLine
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.eqaime import ALL, ON_APPROVAL, PortalInvoice, portal_invoice
from modern_gl.domain.period_input import describe
from modern_gl.domain.periods import (
    DAY,
    LAST_MONTH,
    LAST_WEEK,
    MONTH,
    WEEK,
    full_month,
    month_bounds,
    span_of,
    span_period,
    up_to,
)
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.etaxes import EtaxesClient, PortalError, Response
from modern_gl.reporting.eqaime_reconciliation import (
    AMOUNTS,
    MATCHED,
    MISSING,
    NOT_ON_PORTAL,
    PARTY,
    PENDING,
    PERIOD,
    VOID_IN_BOOKS,
    book_invoices,
    changed_after_reconciliation,
    reconcile,
    reconciled_through,
)
from tests.test_eqaime_import import FakePortal

ALFA_TIN, BETA_TIN = "1111111111", "2222222222"


@pytest.fixture
def firm():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    kind = ledger.subconto_kind_id(cid, "counterparty")
    alfa = ledger.add_subconto_value(cid, kind, "Alfa")
    beta = ledger.add_subconto_value(cid, kind, "Beta")
    ledger.set_subconto_value_tax(cid, alfa, ALFA_TIN)
    ledger.set_subconto_value_tax(cid, beta, BETA_TIN)
    cost = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Xərc")
    bank = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "bank_account"), "Bank")
    acc = {code: a.id for code, a in Catalog(conn, cid).by_code.items()}
    yield Firm(conn, ledger, cid, acc, {"alfa": alfa, "beta": beta, "cost": cost, "bank": bank})
    conn.close()


class Firm:
    def __init__(self, conn, ledger: Ledger, cid: int, acc: dict, v: dict) -> None:
        self.conn, self.ledger, self.cid, self.acc, self.v = conn, ledger, cid, acc, v

    def purchase(self, day: str, number: str, amount: str, vat: str, party: str = "alfa") -> int:
        """Dt 26 / Kt 60 the amount, Dt 19 / Kt 60 the ƏDV, both with the e-qaimə."""
        who = (self.v[party],)
        return self.ledger.post_new(
            self.cid,
            day,
            [
                PostingInput(
                    self.acc["26"], self.acc["60"], amount, (self.v["cost"],), who, invoice=number
                ),
                PostingInput(self.acc["19"], self.acc["60"], vat, who, who, invoice=number),
            ],
        )

    def pay(self, day: str, number: str, amount: str, party: str = "alfa") -> int:
        who = (self.v[party],)
        return self.ledger.post_new(
            self.cid,
            day,
            [
                PostingInput(
                    self.acc["60"], self.acc["51"], amount, who, (self.v["bank"],), invoice=number
                )
            ],
        )


def on_portal(
    number: str,
    day: str,
    total: int,
    vat: int,
    status: str = "approved",
    tin: str = ALFA_TIN,
    outgoing: bool = False,
) -> PortalInvoice:
    return PortalInvoice(number, outgoing, day, status, tin, "Alfa MMC", total, vat)


def test_a_list_row_is_read_with_its_totals():
    """`amount` is the total with ƏDV; a row without it: costWithoutVat + vat."""
    row = {
        "id": "x1",
        "serialNumber": "mt 26 03 001",
        "status": "onApproval",
        "createdAt": "2026-03-31T23:10:00",
        "costWithoutVat": 100.5,
        "vat": 18.09,
        "amount": 118.59,
        "type": "current",
        "receiver": {"tin": BETA_TIN, "name": "Beta"},
        "sender": {"tin": ALFA_TIN, "name": "Alfa"},
    }
    sent = portal_invoice(row, outgoing=True)
    assert sent is not None
    assert (sent.number, sent.doc_date, sent.party_tin, sent.total, sent.vat, sent.amount) == (
        "MT2603001",
        "2026-03-31",
        BETA_TIN,
        11_859,
        1_809,
        10_050,
    )
    received = portal_invoice({**row, "amount": None}, outgoing=False)
    assert received is not None and (received.party_tin, received.total) == (ALFA_TIN, 11_859)
    assert portal_invoice({"status": "approved"}, outgoing=False) is None


def test_the_list_is_read_in_every_status():
    """One request per status (14), every row tagged with the status it was asked in."""
    rows = {
        "approved": [{"id": "1", "serialNumber": "MT1", "amount": 10}],
        "canceled": [{"id": "2", "serialNumber": "MT2", "amount": 5}],
    }
    portal = FakePortal(rows, {})
    got = fetch_list(EtaxesClient("good", send=portal), False, date(2026, 3, 1), date(2026, 3, 31))
    assert [(p.number, p.status, p.total) for p in got] == [
        ("MT1", "approved", 1_000),
        ("MT2", "canceled", 500),
    ]
    assert len(portal.calls) == len(ALL) == 13  # not «rejected»: the portal refuses it


def test_a_status_the_portal_refuses_is_skipped_and_named():
    """The portal answers 400 «Sorğu məlumatları yanlışdır» to a status its filter does not
    know: the rest of the list still comes, the status is named. An imported status (here
    «approved») refused is an error, the error in the interface language."""
    refusal = (
        '{"applicationErrorCode":"User error","message":{"az":"Sorğu məlumatları yalnışdır"}}'
    ).encode()

    def portal(method, url, headers, body):
        status = json.loads(body)["statuses"][0]
        if status in ("canceled", "approved"):
            return Response(400, refusal)
        rows = [{"id": "1", "serialNumber": "MT1", "amount": 10}] if status == "deleted" else []
        return Response(200, json.dumps({"invoices": rows, "hasMore": False}).encode())

    client = EtaxesClient("good", send=portal)
    skipped: list[str] = []
    statuses = ("deleted", "canceled")
    got = fetch_list(
        client, False, date(2026, 3, 1), date(2026, 3, 31), statuses=statuses, skipped=skipped
    )
    assert [(p.number, p.status) for p in got] == [("MT1", "deleted")]
    assert skipped == ["canceled"]
    with pytest.raises(PortalError, match="портал ответил 400: Sorğu məlumatları yalnışdır"):
        fetch_list(client, False, date(2026, 3, 1), date(2026, 3, 31), statuses=("approved",))


def test_book_invoice_is_the_accrual_not_the_payment(firm):
    """MT01: 1 000 + ƏDV 180 = 1 180 accrued; the payment of 1 180 (Dt 60 / Kt 51) with the
    same number is not the e-qaimə's amount. MT12 posted and reversed: not in the books."""
    firm.purchase("2026-03-05", "MT01", "1000", "180")
    firm.pay("2026-03-20", "MT01", "1180")
    reversed_doc = firm.purchase("2026-03-06", "MT12", "50", "9")
    firm.ledger.reverse(firm.cid, reversed_doc, "2026-03-07")
    books = book_invoices(firm.conn, firm.cid, outgoing=False)
    assert set(books) == {"MT01"}
    mt01 = books["MT01"]
    assert (mt01.doc_date, mt01.total, mt01.vat, mt01.amount) == (
        "2026-03-05",
        118_000,
        18_000,
        100_000,
    )
    assert mt01.tax_ids == [ALFA_TIN]
    assert book_invoices(firm.conn, firm.cid, outgoing=True) == {}  # not a sale


def test_reconcile_a_month_of_purchases(firm):
    """March 2026, purchases. Books (posted):
    MT01 05.03 Alfa 1 180 (ƏDV 180)    portal approved 1 180 / 180   -> matched
    MT02 07.03 Alfa   590 (90)         portal approved   708 / 108   -> amounts (118, ƏDV 18)
    MT03 10.03 Beta   236 (36)         portal canceled               -> cancelled, in the books
    MT04 12.03 Alfa   118 (18)         not on the portal             -> not on the portal
    MT05 27.02 Alfa   354 (54)         portal 01.03 354 / 54         -> other period
    MT06 15.03 Beta    59 (9)          portal: from Alfa's VÖEN      -> other counterparty
    MT09 25.03 Alfa    11.80 (1.80)    portal on approval            -> pending
    Portal only: MT07 approved 1 180 / 180, MT08 on approval 472 / 72 -> missing;
    MT10 returned for correction -> pending; MT11 deleted -> not shown.

    Portal total (approved and on approval, March): 1 180 + 708 + 354 + 59 + 1 180 + 472
    + 11.80 = 3 964.80; ƏDV 180 + 108 + 54 + 9 + 180 + 72 + 1.80 = 604.80.
    Books (accrued in March): 1 180 + 590 + 236 + 118 + 59 + 11.80 = 2 194.80;
    ƏDV 180 + 90 + 36 + 18 + 9 + 1.80 = 334.80."""
    firm.purchase("2026-03-05", "MT01", "1000", "180")
    firm.pay("2026-03-20", "MT01", "1180")
    firm.purchase("2026-03-07", "MT02", "500", "90")
    firm.purchase("2026-03-10", "MT03", "200", "36", party="beta")
    firm.purchase("2026-03-12", "MT04", "100", "18")
    firm.purchase("2026-02-27", "MT05", "300", "54")
    firm.purchase("2026-03-15", "MT06", "50", "9", party="beta")
    firm.purchase("2026-03-25", "MT09", "10", "1.80")
    portal = [
        on_portal("MT01", "2026-03-05", 118_000, 18_000),
        on_portal("MT02", "2026-03-07", 70_800, 10_800),
        on_portal("MT03", "2026-03-10", 23_600, 3_600, "canceled", BETA_TIN),
        on_portal("MT05", "2026-03-01", 35_400, 5_400, "approvedBySystem"),
        on_portal("MT06", "2026-03-15", 5_900, 900),
        on_portal("MT07", "2026-03-18", 118_000, 18_000),
        on_portal("MT08", "2026-03-30", 47_200, 7_200, ON_APPROVAL),
        on_portal("MT09", "2026-03-25", 1_180, 180, ON_APPROVAL),
        on_portal("MT10", "2026-03-28", 2_360, 360, "updateRequested"),
        on_portal("MT11", "2026-03-29", 9_999, 0, "deleted"),
        on_portal("MS01", "2026-03-05", 1_000, 0, outgoing=True),  # a sale: not here
    ]
    result = reconcile(firm.conn, firm.cid, False, "2026-03-01", "2026-03-31", portal)
    groups = {g: [r.number for r in result.group(g)] for g in {r.group for r in result.rows}}
    assert groups == {
        MISSING: ["MT07", "MT08"],
        VOID_IN_BOOKS: ["MT03"],
        NOT_ON_PORTAL: ["MT04"],
        AMOUNTS: ["MT02"],
        PERIOD: ["MT05"],
        PARTY: ["MT06"],
        PENDING: ["MT09", "MT10"],
        MATCHED: ["MT01"],
    }
    (mt02,) = result.group(AMOUNTS)
    assert (mt02.difference, mt02.vat_difference) == (11_800, 1_800)
    (mt06,) = result.group(PARTY)
    assert not mt06.party_tin
    assert (result.portal_total, result.portal_vat) == (396_480, 60_480)
    assert (result.book_total, result.book_vat) == (219_480, 33_480)
    assert result.problems == 7 and not result.agrees


def test_a_month_that_agrees(firm):
    firm.purchase("2026-03-05", "MT01", "1000", "180")
    portal = [on_portal("MT01", "2026-03-05", 118_000, 18_000)]
    result = reconcile(firm.conn, firm.cid, False, "2026-03-01", "2026-03-31", portal)
    assert result.agrees and [r.group for r in result.rows] == [MATCHED]


def test_a_number_known_from_before_explains_the_books(firm):
    """Not in this month's list, but read before: on the portal in April -> other period;
    cancelled -> cancelled, in the books."""
    firm.purchase("2026-03-30", "MT20", "100", "18")
    firm.purchase("2026-03-31", "MT21", "100", "18")
    firm.ledger.eqaime.remember_portal(
        firm.cid,
        [
            on_portal("MT20", "2026-04-01", 11_800, 1_800),
            on_portal("MT21", "2026-03-31", 11_800, 1_800, "canceled"),
        ],
    )
    result = reconcile(firm.conn, firm.cid, False, "2026-03-01", "2026-03-31", [])
    assert [(r.number, r.group) for r in result.rows] == [
        ("MT21", VOID_IN_BOOKS),
        ("MT20", PERIOD),
    ]


def test_the_portal_is_remembered_with_its_changes(firm):
    """Seen on approval, then approved: a change, but a quiet one. Then the supplier
    corrects the amount: 118.00 -> 236.00 — shown with the row."""
    ledger = firm.ledger
    first = on_portal("MT01", "2026-03-05", 11_800, 1_800, ON_APPROVAL)
    assert ledger.eqaime.remember_portal(firm.cid, [first], "2026-03-06T10:00:00") == 0
    approved = on_portal("MT01", "2026-03-05", 11_800, 1_800)
    assert ledger.eqaime.remember_portal(firm.cid, [approved], "2026-03-11T10:00:00") == 1
    assert ledger.eqaime.remember_portal(firm.cid, [approved], "2026-03-12T10:00:00") == 0
    firm.purchase("2026-03-05", "MT01", "100", "18")
    result = reconcile(firm.conn, firm.cid, False, "2026-03-01", "2026-03-31", [approved])
    assert result.rows[0].group == MATCHED and result.rows[0].changes == []

    corrected = on_portal("MT01", "2026-03-05", 23_600, 3_600)
    assert ledger.eqaime.remember_portal(firm.cid, [corrected], "2026-04-02T09:00:00") == 1
    row = reconcile(firm.conn, firm.cid, False, "2026-03-01", "2026-03-31", [corrected]).rows[0]
    assert row.group == AMOUNTS
    assert [(c.old_total, c.new_total) for c in row.changes] == [(11_800, 23_600)]
    stored = firm.conn.execute("SELECT status, total, first_seen, last_seen FROM eqaime_portal")
    assert tuple(stored.fetchone()) == (
        "approved",
        23_600,
        "2026-03-06T10:00:00",
        "2026-04-02T09:00:00",
    )


def test_changes_after_the_month_is_marked_reconciled(firm):
    """March purchases reconciled on 5 April. On 20 April MT01 is cancelled: March is
    warned about. A change before the mark, or in a month not marked, is not."""
    ledger = firm.ledger
    ledger.eqaime.remember_portal(
        firm.cid,
        [on_portal("MT01", "2026-03-05", 100, 0), on_portal("MT02", "2026-03-06", 100, 0)],
        "2026-04-01T09:00:00",
    )
    ledger.eqaime.remember_portal(
        firm.cid, [on_portal("MT02", "2026-03-06", 200, 0)], "2026-04-02T09:00:00"
    )
    ledger.eqaime.mark_reconciled(
        firm.cid, False, "2026-03-01", "2026-03-31", "2026-04-05T09:00:00"
    )
    ledger.eqaime.remember_portal(
        firm.cid,
        [
            on_portal("MT01", "2026-03-05", 100, 0, "canceled"),
            on_portal("MT30", "2026-04-07", 100, 0),
        ],
        "2026-04-20T09:00:00",
    )
    ledger.eqaime.remember_portal(
        firm.cid, [on_portal("MT30", "2026-04-07", 300, 0)], "2026-04-21T09:00:00"
    )
    (changed,) = changed_after_reconciliation(firm.conn, firm.cid)
    assert (changed.outgoing, changed.month, changed.numbers) == (False, "2026-03", ("MT01",))

    ledger.eqaime.mark_reconciled(
        firm.cid, False, "2026-03-01", "2026-03-31", "2026-04-22T09:00:00"
    )
    assert changed_after_reconciliation(firm.conn, firm.cid) == []
    ledger.eqaime.unmark_reconciled(firm.cid, False, "2026-03-01", "2026-03-31")
    assert firm.conn.execute("SELECT COUNT(*) FROM eqaime_reconciled").fetchone()[0] == 0


def test_reconciled_months_are_read_again(firm):
    """Purchases: January and March 2026 reconciled -> 1 Jan .. 31 Mar read again; a month
    of over a year ago is not."""
    for month in ("2025-03", "2026-01", "2026-03"):
        firm.ledger.eqaime.mark_reconciled(firm.cid, False, *month_bounds(month))
    firm.ledger.eqaime.mark_reconciled(firm.cid, True, *month_bounds("2026-02"))
    got = [
        (r.outgoing, r.date_from, r.date_to)
        for r in rechecks(firm.conn, firm.cid, date(2026, 4, 10))
    ]
    assert got == [
        (False, date(2026, 1, 1), date(2026, 3, 31)),
        (True, date(2026, 2, 1), date(2026, 2, 28)),
    ]
    assert full_month(date(2026, 2, 1), date(2026, 2, 28)) == "2026-02"
    assert full_month(date(2026, 2, 1), date(2026, 2, 27)) is None


def test_a_sale_in_the_classic_chart(conn):
    """A sale with e-qaimə MS2601001 (see test_sales): Dt 62 / Kt 46 70.80 + 29.50 = 100.30
    with ƏDV; the ƏDV is Dt 46 / Kt 68.2 15.30 — not on the customer's account. Paid
    later (Dt 51 / Kt 62) with the same number: not the e-qaimə's amount."""
    from tests.test_sales import make_shop, two_lines

    shop = make_shop(conn, "classic")
    shop.receipt("2026-01-10", "10", "120")
    shop.sale("2026-01-20", two_lines(shop), invoice="MS2601001")
    books = book_invoices(conn, shop.company_id, outgoing=True)
    sale = books["MS2601001"]
    assert (sale.doc_date, sale.total, sale.vat, sale.amount) == (
        "2026-01-20",
        10_030,
        1_530,
        8_500,
    )
    assert "MS2601001" not in book_invoices(conn, shop.company_id, outgoing=False)


def listed(number: str, day: str, amount: float, vat: float, tin: str = ALFA_TIN) -> dict:
    """A row of the portal's list of received e-qaimə."""
    return {
        "id": number,
        "sourceSystem": "avis",
        "serialNumber": number,
        "createdAt": f"{day}T12:00:00",
        "amount": amount,
        "vat": vat,
        "sender": {"tin": tin, "name": "Alfa MMC"},
    }


def test_reconciliation_dialog(firm, qtbot, monkeypatch):
    """March: MT01 1 180 (ƏDV 180) in the books and approved on the portal; MT04 118 (18)
    only in the books; MT08 472 (72) on approval only on the portal.
    Portal: 1 180 + 472 = 1 652.00, ƏDV 252.00, without 1 400.00.
    Books: 1 180 + 118 = 1 298.00, ƏDV 198.00, without 1 100.00.
    The month is marked reconciled; a double click opens MT04's document."""
    from modern_gl.desktop import eqaime_reconciliation_page
    from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog
    from modern_gl.desktop.session import Session
    from modern_gl.reporting.eqaime_reconciliation import reconciled_periods
    from tests.test_eqaime_import import fake_token

    firm.purchase("2026-03-05", "MT01", "1000", "180")
    mt04 = firm.purchase("2026-03-12", "MT04", "100", "18")
    portal = FakePortal(
        {
            "approved": [listed("MT01", "2026-03-05", 1180, 180)],
            ON_APPROVAL: [listed("MT08", "2026-03-30", 472, 72)],
        },
        {},
    )
    monkeypatch.setattr(
        eqaime_reconciliation_page,
        "EtaxesClient",
        lambda token: EtaxesClient("good", send=portal),
    )
    session = Session(
        firm.conn,
        firm.ledger,
        firm.cid,
        "Firma",
        Catalog(firm.conn, firm.cid),
        working_date=date(2026, 3, 20),
        notify=lambda _text: None,
    )
    firm.ledger.set_company_tax_id(firm.cid, "1402375141")  # the portal's firm (D113)
    dialog = EqaimeReconciliationDialog(
        session, sign_in=lambda parent: fake_token(), today=date(2026, 4, 1)
    )
    qtbot.addWidget(dialog)
    field = dialog.period_field
    # nothing marked yet: this month, up to yesterday — on the 1st, today alone
    assert field.period() == (date(2026, 4, 1), date(2026, 4, 1))
    field.show_presets()
    assert field.window_shown.preset_buttons[MONTH].isChecked()
    field.window_shown.preset_buttons[LAST_MONTH].click()
    assert field.period() == (date(2026, 3, 1), date(2026, 3, 31))
    assert field.edit.text() == describe(field.period())
    dialog.load()
    qtbot.waitUntil(lambda: dialog.outcome is not None, timeout=5000)
    heads = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
    assert [h.text(0) for h in heads if h is not None] == [
        "Есть на портале, нет в книге  1",
        "В книге, на портале не найдена  1",
        "Совпадает  1",
    ]
    assert dialog.verdict.text() == "Требуют внимания: 2"
    figures = [[dialog.totals[r, c].text() for c in (1, 2, 3)] for r in (1, 2, 3)]
    assert figures == [
        ["1 400.00", "252.00", "1 652.00"],
        ["1 100.00", "198.00", "1 298.00"],
        ["300.00", "54.00", "354.00"],
    ]
    assert dialog.import_button.isVisibleTo(dialog)
    count = firm.conn.execute("SELECT COUNT(*) FROM eqaime_portal").fetchone()[0]
    assert count == 2  # what the portal showed is kept

    assert dialog.mark_button.text() == "Сверено: март 2026"
    dialog.mark_button.click()
    marks = reconciled_periods(firm.conn, firm.cid, False)
    assert [(m.date_from, m.date_to) for m in marks] == [("2026-03-01", "2026-03-31")]
    assert dialog.through.text() == "Сверено по 31.03.2026"
    assert dialog.mark_button.text() == "Снять отметку «сверено»"

    absent = heads[1].child(0) if heads[1] is not None else None
    assert absent is not None and absent.text(1) == "MT04"
    dialog.tree.itemDoubleClicked.emit(absent, 1)
    assert dialog.chosen_document == mt04


def test_a_document_shows_its_status_on_the_portal(conn, qtbot):
    """A purchase draft of an e-qaimə awaiting approval shows it next to the number;
    once approved, nothing; cancelled — in red."""
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.session import Session
    from tests.test_sales import make_shop

    shop = make_shop(conn, "classic")
    doc = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-05",
        [ReceiptLine(shop.item, shop.main, "1", "10")],
        shop.acc["60"],
        shop.supplier,
        "",
        invoice="MT01",
    )
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))

    def chip(status: str | None) -> str | None:
        if status is not None:
            shop.ledger.eqaime.remember_portal(
                shop.company_id, [on_portal("MT01", "2026-03-05", 1180, 180, status)]
            )
        page = InventoryDocumentPage(session, doc_type="receipt")
        qtbot.addWidget(page)
        page.load(doc)
        return page.portal_status.text() if page.portal_status.isVisibleTo(page) else None

    assert chip(None) is None
    assert chip(ON_APPROVAL) == "Ожидает подтверждения"
    assert chip("approved") is None
    assert chip("canceled") == "Аннулирована"


def test_import_takes_e_qaime_awaiting_approval_and_warns_of_changes(conn, qtbot, monkeypatch):
    """The import asks for «Təsdiq gözləyir» too and marks it; what it saw is kept. March
    was reconciled with MT2603000111 at 118.00; now the portal shows it at 170.00 + ƏDV
    30.60 (the received() lines): March is warned about."""
    from modern_gl.desktop import eqaime_import_page
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
    from modern_gl.desktop.session import Session
    from tests.test_eqaime_import import fake_token, received
    from tests.test_sales import make_shop

    shop = make_shop(conn, "classic")
    shop.ledger.eqaime.remember_portal(
        shop.company_id,
        [on_portal("MT2603000111", "2026-03-05", 11_800, 1_800, tin="1700000001")],
        "2026-04-01T09:00:00",
    )
    shop.ledger.eqaime.mark_reconciled(
        shop.company_id, False, "2026-03-01", "2026-03-31", "2026-04-02T09:00:00"
    )
    row, detail = received()
    row = {**row, "status": ON_APPROVAL, "amount": 200.60, "vat": 30.60}
    portal = FakePortal({ON_APPROVAL: [row]}, {"a1": detail})
    monkeypatch.setattr(
        eqaime_import_page, "EtaxesClient", lambda token: EtaxesClient("good", send=portal)
    )
    session = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        working_date=date(2026, 3, 20),
    )
    shop.ledger.set_company_tax_id(shop.company_id, "1402375141")  # the portal's firm (D113)
    dialog = EqaimeImportDialog(session, sign_in=lambda parent: fake_token(), direction="receipt")
    qtbot.addWidget(dialog)
    dialog.load()
    qtbot.waitUntil(lambda: dialog.tree.topLevelItemCount() == 1, timeout=5000)
    item = dialog.tree.topLevelItem(0)
    assert item is not None and item.text(8).startswith("ожидает подтверждения")
    stored = conn.execute("SELECT status, total, vat FROM eqaime_portal").fetchone()
    assert tuple(stored) == (ON_APPROVAL, 20_060, 3_060)
    assert dialog.warning.isVisibleTo(dialog)
    assert "март 2026, покупки: 1" in dialog.warning.text()


@pytest.mark.parametrize(
    ("today", "span", "period"),
    [
        (date(2026, 10, 21), DAY, (date(2026, 10, 20), date(2026, 10, 20))),  # Wednesday
        (date(2026, 10, 19), DAY, (date(2026, 10, 16), date(2026, 10, 18))),  # Monday: Fri-Sun
        (date(2026, 10, 21), WEEK, (date(2026, 10, 19), date(2026, 10, 20))),
        (date(2026, 10, 19), WEEK, (date(2026, 10, 19), date(2026, 10, 19))),  # Monday: today
        (date(2026, 10, 21), LAST_WEEK, (date(2026, 10, 12), date(2026, 10, 18))),
        (date(2026, 10, 19), LAST_WEEK, (date(2026, 10, 12), date(2026, 10, 18))),
        (date(2026, 10, 21), MONTH, (date(2026, 10, 1), date(2026, 10, 20))),
        (date(2026, 11, 1), MONTH, (date(2026, 11, 1), date(2026, 11, 1))),  # the 1st: today
        (date(2026, 10, 21), LAST_MONTH, (date(2026, 9, 1), date(2026, 9, 30))),
        (date(2026, 1, 15), LAST_MONTH, (date(2025, 12, 1), date(2025, 12, 31))),
    ],
)
def test_quick_periods_of_a_morning_check(today, span, period):
    """The reconciliation's periods end yesterday: it looks at finished days."""
    assert up_to(span_period(span, today), today - timedelta(days=1)) == period


def test_quick_periods_of_the_import_take_today():
    today = date(2026, 10, 21)
    assert span_period(WEEK, today) == (date(2026, 10, 19), date(2026, 10, 25))
    assert up_to(span_period(WEEK, today), today) == (date(2026, 10, 19), today)
    assert up_to(span_period(MONTH, today), today) == (date(2026, 10, 1), today)
    assert up_to(span_period(DAY, today), today) == (date(2026, 10, 20),) * 2


@pytest.mark.parametrize(
    ("first", "last", "span"),
    [
        (date(2026, 10, 20), date(2026, 10, 20), DAY),
        (date(2026, 10, 16), date(2026, 10, 18), DAY),  # Friday to Sunday
        (date(2026, 10, 19), date(2026, 10, 20), WEEK),
        (date(2026, 10, 12), date(2026, 10, 18), LAST_WEEK),
        (date(2026, 10, 1), date(2026, 10, 20), MONTH),
        (date(2026, 10, 1), date(2026, 10, 31), MONTH),  # the month, still going
        (date(2026, 9, 1), date(2026, 9, 30), LAST_MONTH),
        (date(2026, 10, 5), date(2026, 10, 25), None),  # by hand
    ],
)
def test_the_span_a_mark_was_made_with(first, last, span):
    assert span_of(first, last, date(2026, 10, 21)) == span


def test_a_day_is_reconciled_by_the_portal_date(firm):
    """MT01 is dated 20.10 on the portal and posted on 21.10: the same month, so it agrees
    on the 20th (its totals counted there: 118.00 / 18.00 both sides) and is not on the
    21st at all. Posted in November it would be «другой период»."""
    firm.purchase("2026-10-21", "MT01", "100", "18")
    portal = [on_portal("MT01", "2026-10-20", 11_800, 1_800)]
    day = reconcile(firm.conn, firm.cid, False, "2026-10-20", "2026-10-20", portal)
    assert [r.group for r in day.rows] == [MATCHED] and day.agrees
    assert (day.book_total, day.book_vat) == (11_800, 1_800)
    firm.ledger.eqaime.remember_portal(firm.cid, portal)
    next_day = reconcile(firm.conn, firm.cid, False, "2026-10-21", "2026-10-21", [])
    assert next_day.rows == [] and next_day.agrees

    firm.purchase("2026-11-02", "MT02", "100", "18")
    late = [on_portal("MT02", "2026-10-31", 11_800, 1_800)]
    assert [
        r.group
        for r in reconcile(firm.conn, firm.cid, False, "2026-10-31", "2026-10-31", late).rows
    ] == [PERIOD]


def test_reconciled_days_are_warned_about_until_reconciled_again(firm):
    """The 20th marked on the 21st; on the 22nd MT01 (of the 20th) is cancelled: warned.
    A change in MT05 (of the 5th, never marked) is not. October marked on the 23rd: the
    warning goes. Marks 01-19, 20, 22: reconciled through the 20th (the 21st is a gap)."""
    ledger = firm.ledger
    ledger.eqaime.remember_portal(
        firm.cid,
        [on_portal("MT01", "2026-10-20", 100, 0), on_portal("MT05", "2026-10-05", 100, 0)],
        "2026-10-21T08:00:00",
    )
    ledger.eqaime.mark_reconciled(
        firm.cid, False, "2026-10-20", "2026-10-20", "2026-10-21T08:30:00"
    )
    ledger.eqaime.remember_portal(
        firm.cid,
        [
            on_portal("MT01", "2026-10-20", 100, 0, "canceled"),
            on_portal("MT05", "2026-10-05", 300, 0),
        ],
        "2026-10-22T08:00:00",
    )
    (changed,) = changed_after_reconciliation(firm.conn, firm.cid)
    assert (changed.month, changed.numbers) == ("2026-10", ("MT01",))
    assert usual_span(firm.conn, firm.cid, False) == DAY

    ledger.eqaime.mark_reconciled(
        firm.cid, False, "2026-10-01", "2026-10-31", "2026-10-23T08:00:00"
    )
    assert changed_after_reconciliation(firm.conn, firm.cid) == []
    assert usual_span(firm.conn, firm.cid, False) == MONTH

    ledger.eqaime.unmark_reconciled(firm.cid, False, "2026-10-01", "2026-10-31")
    ledger.eqaime.mark_reconciled(firm.cid, False, "2026-10-01", "2026-10-19")
    ledger.eqaime.mark_reconciled(firm.cid, False, "2026-10-22", "2026-10-22")
    assert reconciled_through(firm.conn, firm.cid, False) == "2026-10-20"


def test_period_text():
    from modern_gl.desktop.eqaime_reconciliation_page import period_text

    assert period_text("2026-03-01", "2026-03-31") == "март 2026"
    assert period_text("2026-10-20", "2026-10-20") == "20.10.2026"
    assert period_text("2026-10-12", "2026-10-18") == "12.10–18.10.2026"
    assert period_text("2025-12-29", "2026-01-04") == "29.12.2025–04.01.2026"


def test_the_portal_period_field(qtbot):
    """The portal's windows have the reports' field (D105) with their own usual periods;
    a period ends today at the latest, ‹ › step from the whole month. Today: Wednesday
    21 October 2026."""
    from modern_gl.desktop.period_field import portal_period

    today = date(2026, 10, 21)
    field = portal_period(today, LAST_WEEK)
    qtbot.addWidget(field)
    assert field.period() == (date(2026, 10, 12), date(2026, 10, 18))
    assert field.edit.text() == "12.10 — 18.10.2026"
    field.edit.setText("м")
    field.edit.setModified(True)
    field.edit.editingFinished.emit()
    assert field.period() == (date(2026, 10, 1), today)  # not to the 31st
    assert field.edit.text() == "01.10 — 21.10.2026"
    field.step(-1)
    assert field.period() == (date(2026, 9, 1), date(2026, 9, 30))  # the whole September
    field.step(1)
    field.show_presets()
    window = field.window_shown
    assert list(window.preset_buttons) == [DAY, WEEK, LAST_WEEK, MONTH, LAST_MONTH]
    assert window.preset_buttons[MONTH].isChecked()
    assert (window.first.date().toPython(), window.last.date().toPython()) == (
        date(2026, 10, 1),
        today,
    )
    window.preset_buttons[WEEK].click()
    assert field.period() == (date(2026, 10, 19), today)
    field.set_period(date(2026, 10, 5), date(2026, 10, 30))
    assert field.period() == (date(2026, 10, 5), today)
