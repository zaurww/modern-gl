"""The unpaid list counts the money without a number (D-new-unpaid-free-money): a payment
made before its e-qaimə was known pays it, whatever came first — laid out oldest first, as
the ƏDV module lays it out (D185). Nothing is written: the postings stay as they are.

Alfa, hand-calculated: e-qaimə A 20.03 for 500.00, B 21.03 for 300.00 (Kt 60.1); 10.03 paid
600.00 without a number. On 25.03: A paid (500.00), B has 100.00 of it — still 200.00.
"""

from __future__ import annotations

import pytest

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.bank.file_import import iban_places
from modern_gl.application.bank.files import read_bank_file
from modern_gl.application.bank.operations import IN, OUT, SUPPLIER, BankLine, BankOperationInput
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.free_money import unpaid_invoices
from modern_gl.application.invoices import open_invoices
from modern_gl.application.ledger.inputs import PostingInput
from tests.helpers.kapital import AZN_IBAN, OWN_TIN, kapital_file

A, B = "MT260300000001", "MT260300000002"
ALFA_TIN = "1100000001"
ALFA = f"AZ33UBAZ00000000000000000001 / ALFA MMC / {ALFA_TIN}"


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Деньги без номера")
    ledger.set_company_tax_id(cid, OWN_TIN)
    apply_chart_template(ledger, cid, "1c77", "ru")
    acc = {c: ledger.account_id(cid, c) for c in ("26", "51", "60.1", "62.1", "80", "90.1")}
    bank = ledger.bank.add_bank_account(cid, "Kapital AZN", acc["51"], "current", iban=AZN_IBAN)
    kind = ledger.subconto_kind_id(cid, "counterparty")
    alfa = ledger.add_subconto_value(cid, kind, "Альфа")
    ledger.set_subconto_value_tax(cid, alfa, ALFA_TIN)
    owner = ledger.add_subconto_value(cid, kind, "Учредитель")
    cost = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    ledger.post_new(
        cid, "2026-03-01", [PostingInput(acc["51"], acc["80"], "5000", [bank], [owner])]
    )
    place = iban_places(ledger.conn, cid)[AZN_IBAN]
    return {"cid": cid, "acc": acc, "alfa": alfa, "cost": cost, "place": place}


def bought(ledger, firm, day: str, amount: str, number: str | None) -> None:
    acc = firm["acc"]
    posting = PostingInput(
        acc["26"], acc["60.1"], amount, [firm["cost"]], [firm["alfa"]], invoice=number or ""
    )
    ledger.post_new(firm["cid"], day, [posting])


def paid(ledger, firm, day: str, amount: int, *, invoice: str = "", pays_vat: bool = False) -> int:
    place = firm["place"]
    data = BankOperationInput(
        doc_date=day,
        direction=OUT,
        account_id=place.account_id,
        subconto=place.subconto,
        kind=SUPPLIER,
        counterparty_id=firm["alfa"],
        lines=(BankLine(firm["acc"]["60.1"], amount, (), invoice, pays_vat),),
        memo="Оплата",
    )
    return ledger.bank.save_bank_operation(firm["cid"], data, post=True, checked=True)


def unpaid(ledger, firm, day: str = "2026-03-25", **options) -> list[tuple[str, int]]:
    found = unpaid_invoices(ledger.conn, firm["cid"], firm["alfa"], True, day, **options)
    return [(i.invoice, i.amount) for i in found]


def test_money_before_the_eqaime_pays_it_oldest_first(ledger, firm):
    paid(ledger, firm, "2026-03-10", 60000)
    bought(ledger, firm, "2026-03-20", "500", A)
    bought(ledger, firm, "2026-03-21", "300", B)
    assert unpaid(ledger, firm) == [(B, 20000)]
    # the number's own balance is what it was: an advance offset reads it (D78)
    raw = open_invoices(ledger.conn, firm["cid"], firm["alfa"], True, "2026-03-25")
    assert [(i.invoice, i.amount) for i in raw] == [(A, 50000), (B, 30000)]


def test_the_order_of_entry_does_not_matter(ledger, firm):
    bought(ledger, firm, "2026-03-20", "500", A)
    bought(ledger, firm, "2026-03-21", "300", B)
    paid(ledger, firm, "2026-03-22", 60000)
    assert unpaid(ledger, firm) == [(B, 20000)]


def test_a_debt_without_a_number_takes_its_money_first(ledger, firm):
    """100.00 owed without a number (an act): of the 600.00 only 500.00 are free — A paid,
    B whole. A debt larger than the money leaves nothing to lay out."""
    bought(ledger, firm, "2026-03-05", "100", None)
    paid(ledger, firm, "2026-03-10", 60000)
    bought(ledger, firm, "2026-03-20", "500", A)
    bought(ledger, firm, "2026-03-21", "300", B)
    assert unpaid(ledger, firm) == [(B, 30000)]
    bought(ledger, firm, "2026-03-22", "700", None)  # 800.00 owed against 600.00 paid
    assert unpaid(ledger, firm) == [(A, 50000), (B, 30000)]


def test_money_after_the_day_is_not_counted(ledger, firm):
    bought(ledger, firm, "2026-03-20", "500", A)
    paid(ledger, firm, "2026-03-26", 20000)
    assert unpaid(ledger, firm) == [(A, 50000)]
    assert unpaid(ledger, firm, "2026-03-26") == [(A, 30000)]


def test_the_edvs_money_pays_the_edv(ledger, firm):
    """E-qaimə A for 100.00 + 18.00: 18.00 to the supplier's deposit without a number —
    118.00 − 18.00 = 100.00 left, no ƏDV; 100.00 of the value instead — 18.00, all ƏDV."""
    cid, acc = firm["cid"], firm["acc"]
    vat = ledger.conn.execute(
        "SELECT id FROM accounts WHERE company_id = ? AND account_type = 'input_vat' "
        "AND is_group = 0 ORDER BY code LIMIT 1",
        (cid,),
    ).fetchone()["id"]
    ledger.post_new(
        cid,
        "2026-03-20",
        [
            PostingInput(acc["26"], acc["60.1"], "100", [firm["cost"]], [firm["alfa"]], invoice=A),
            PostingInput(vat, acc["60.1"], "18", [firm["alfa"]], [firm["alfa"]], invoice=A),
        ],
    )
    operation = paid(ledger, firm, "2026-03-21", 1800, pays_vat=True)
    [left] = unpaid_invoices(ledger.conn, cid, firm["alfa"], True, "2026-03-25")
    assert (left.amount, left.vat) == (10000, 0)
    ledger.bank.delete_bank_operation(cid, operation)
    paid(ledger, firm, "2026-03-21", 10000)
    [left] = unpaid_invoices(ledger.conn, cid, firm["alfa"], True, "2026-03-25")
    assert (left.amount, left.vat) == (1800, 1800)


def test_a_customers_money_the_same_way(ledger, firm):
    """Sold 20.03 for 236.00 (Dt 62.1); 200.00 came on 10.03 without a number: 36.00 owed."""
    cid, acc, place = firm["cid"], firm["acc"], firm["place"]
    data = BankOperationInput(
        doc_date="2026-03-10",
        direction=IN,
        account_id=place.account_id,
        subconto=place.subconto,
        kind="customer",
        counterparty_id=firm["alfa"],
        lines=(BankLine(acc["62.1"], 20000),),
        memo="Поступление",
    )
    ledger.bank.save_bank_operation(cid, data, post=True, checked=True)
    sale = PostingInput(acc["62.1"], acc["80"], "236", [firm["alfa"]], [firm["alfa"]], invoice=A)
    ledger.post_new(cid, "2026-03-20", [sale])
    found = unpaid_invoices(ledger.conn, cid, firm["alfa"], False, "2026-03-25")
    assert [(i.invoice, i.amount) for i in found] == [(A, 3600)]


def test_the_payment_opened_does_not_count_itself(ledger, firm):
    """A payment opened to give it its number sees the e-qaimə it pays."""
    operation = paid(ledger, firm, "2026-03-10", 50000)
    bought(ledger, firm, "2026-03-20", "500", A)
    assert unpaid(ledger, firm) == []
    document = load_bank_operation(ledger.conn, firm["cid"], operation).document_id
    assert unpaid(ledger, firm, without=document) == [(A, 50000)]


def load_lines(ledger, firm, tmp_path, lines) -> dict[str, tuple[str, str, list]]:
    path = kapital_file(tmp_path / "azn.xlsx", AZN_IBAN, "AZN", "4400", lines)
    done = ledger.bank.import_bank_files(
        firm["cid"], [read_bank_file(path)], {AZN_IBAN: firm["place"]}
    )
    return {row.op.reference: (row.state, row.reason, list(row.lines)) for row in done.rows}


def test_the_next_payment_does_not_shift_the_numbers(ledger, firm, tmp_path):
    """After 600.00 without a number the next 200.00 without one goes on B — what is really
    unpaid — not on A, which the first money paid."""
    paid(ledger, firm, "2026-03-10", 60000)
    bought(ledger, firm, "2026-03-20", "500", A)
    bought(ledger, firm, "2026-03-21", "300", B)
    line = ("2026-03-25", "1 / 1", ALFA, "-200", "-200", "muqavileye esasen")
    found = load_lines(ledger, firm, tmp_path, [line])
    assert found["1"][2] == [("60.1", B, 20000)]


def test_all_paid_the_next_payment_is_an_advance(ledger, firm, tmp_path):
    paid(ledger, firm, "2026-03-10", 50000)
    bought(ledger, firm, "2026-03-20", "500", A)
    line = ("2026-03-25", "1 / 1", ALFA, "-200", "-200", "muqavileye esasen")
    found = load_lines(ledger, firm, tmp_path, [line])
    assert found["1"][2] == [("60.1", "", 20000)]


def test_a_number_in_the_purpose_is_a_fact(ledger, firm, tmp_path):
    """The purpose names A: it pays A — the guess gives way, the free 500.00 go on B."""
    paid(ledger, firm, "2026-03-10", 50000)
    bought(ledger, firm, "2026-03-20", "500", A)
    bought(ledger, firm, "2026-03-21", "500", B)
    line = ("2026-03-25", "1 / 1", ALFA, "-500", "-500", f"{A} e-qaimeye esasen")
    found = load_lines(ledger, firm, tmp_path, [line])
    assert found["1"][:2] == ("posted", "")
    assert found["1"][2] == [("60.1", A, 50000)]
    assert unpaid(ledger, firm) == []


def test_the_form_of_the_payment_offers_what_it_pays(qtbot, ledger, firm):
    """The way to give a payment its number: opened, it offers A; a new one offers nothing
    — A is paid."""
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.bank_operation_page import BankOperationPage
    from modern_gl.desktop.session import Session

    cid = firm["cid"]
    operation = paid(ledger, firm, "2026-03-10", 50000)
    bought(ledger, firm, "2026-03-09", "500", A)
    s = Session(ledger.conn, ledger, cid, "ООО", Catalog(ledger.conn, cid), notify=print)
    s.working_date = date(2026, 3, 25)
    opened = BankOperationPage(s, operation)
    qtbot.addWidget(opened)
    assert [(i.invoice, i.amount) for i in opened.open_invoices] == [(A, 50000)]
    new = BankOperationPage(s)
    qtbot.addWidget(new)
    new._set_counterparty(firm["alfa"])
    assert new.open_invoices == []
