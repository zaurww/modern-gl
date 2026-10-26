"""Bank operations (D47). Hand-calculated example on the 1C 7.7 chart, March 2026:

01.03  journal: Dt 51 [Kapital AZN] / Ct 80 [Учредитель]  10 000.00
01.03  journal: Dt 52 [Kapital USD] / Ct 80 [Учредитель]   1 700.00 (1 000.00 USD × 1.70)
02.03  journal: Dt 26 [Аренда] / Ct 60.1 [ALFA, Договор 1] 1 180.00, e-qaimə MT001
05.03  out, to ALFA: Dt 60.1 [ALFA, Договор 1] / Ct 51 [Kapital AZN] 1 180.00 MT001
       — the e-qaimə is paid: its balance is 0
06.03  in, from BETA, two e-qaimə: Dt 51 / Ct 62.1 [BETA] 500.00 MT010 and 700.00 MT011
07.03  out, bank fee 2.00 USD at 1.70: Dt 91.2 [Комиссия банка] / Ct 52 [Kapital USD] 3.40
       (2.00 USD)

Kapital AZN: 10 000.00 − 1 180.00 + 1 200.00 = 10 020.00;
from 05.03: opening 10 000.00, in 1 200.00, out 1 180.00, closing 10 020.00.
Kapital USD: 1 000.00 − 2.00 = 998.00 USD (manat: 1 700.00 − 3.40 = 1 696.60).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from modern_gl.application.bank import (
    CUSTOMER,
    FEE,
    IN,
    OTHER,
    OUT,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    bank_places,
    counterparty_balance,
    find_bank_operation,
    kind_of_account,
    last_lines,
    load_bank_operation,
    payment_lines,
    place_balance,
    statement,
)
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.invoices import open_invoices
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import DocumentOwner, document_owner, load_document
from modern_gl.domain.accounts import ADVANCE_PAID
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import PeriodClosedError, ValidationError
from modern_gl.domain.money import to_minor
from modern_gl.reporting.invoices import invoice_report
from modern_gl.reporting.reports import trial_balance


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Банк")
    apply_chart_template(ledger, cid, "1c77", "ru")
    kind = {
        code: ledger.subconto_kind_id(cid, code)
        for code in (
            "bank_account",
            "counterparty",
            "contract",
            "cost_item",
            "other_income",
            "employee",
        )
    }
    acc = {
        code: ledger.account_id(cid, code)
        for code in ("51", "52", "55", "26", "60.1", "62.1", "68.1", "70", "80", "91.2")
    }
    usd = ledger.currency_id(cid, "USD")
    v = {
        "azn": ledger.add_subconto_value(cid, kind["bank_account"], "Kapital AZN"),
        "usd": ledger.add_subconto_value(cid, kind["bank_account"], "Kapital USD"),
        "pasha": ledger.add_subconto_value(cid, kind["bank_account"], "PAŞA AZN"),
        "alfa": ledger.add_subconto_value(cid, kind["counterparty"], "ALFA MMC"),
        "beta": ledger.add_subconto_value(cid, kind["counterparty"], "BETA MMC"),
        "owner": ledger.add_subconto_value(cid, kind["counterparty"], "Учредитель"),
        "rent": ledger.add_subconto_value(cid, kind["cost_item"], "Аренда"),
        "fee": ledger.add_subconto_value(cid, kind["other_income"], "Комиссия банка"),
    }
    v["contract"] = ledger.add_subconto_value(
        cid, kind["contract"], "Договор 1", owner_id=v["alfa"]
    )
    v["contract_b"] = ledger.add_subconto_value(
        cid, kind["contract"], "Договор 2", owner_id=v["beta"]
    )
    ledger.set_subconto_value_currency(cid, v["usd"], usd)
    ledger.set_subconto_value_tax(cid, v["alfa"], "1234567890")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    for doc_date, posting in (
        ("2026-03-01", PostingInput(acc["51"], acc["80"], "10000", [v["azn"]], [v["owner"]])),
        (
            "2026-03-01",
            PostingInput(acc["52"], acc["80"], "1700", [v["usd"]], [v["owner"]], "", usd, "1000"),
        ),
        (
            "2026-03-02",
            PostingInput(
                acc["26"],
                acc["60.1"],
                "1180",
                [v["rent"]],
                [v["alfa"], v["contract"]],
                invoice="MT001",
            ),
        ),
    ):
        ledger.post_new(cid, doc_date, [posting])
    return {"cid": cid, "acc": acc, "v": v, "usd": usd, "kind": kind}


def pay_alfa(f, **changes) -> BankOperationInput:
    acc, v = f["acc"], f["v"]
    data = BankOperationInput(
        doc_date="2026-03-05",
        direction=OUT,
        account_id=acc["51"],
        subconto=(v["azn"],),
        kind=SUPPLIER,
        counterparty_id=v["alfa"],
        lines=(BankLine(acc["60.1"], 118000, (None, v["contract"]), "MT001"),),
        memo="Оплата по счёту MT001",
    )
    return replace(data, **changes)


def from_beta(f) -> BankOperationInput:
    acc, v = f["acc"], f["v"]
    return BankOperationInput(
        doc_date="2026-03-06",
        direction=IN,
        account_id=acc["51"],
        subconto=(v["azn"],),
        kind=CUSTOMER,
        counterparty_id=v["beta"],
        lines=(
            BankLine(acc["62.1"], 50000, (None, v["contract_b"]), "MT010"),
            BankLine(acc["62.1"], 70000, (None, v["contract_b"]), "MT011"),
        ),
        memo="Оплата от BETA",
    )


def usd_fee(f) -> BankOperationInput:
    acc, v = f["acc"], f["v"]
    return BankOperationInput(
        doc_date="2026-03-07",
        direction=OUT,
        account_id=acc["52"],
        subconto=(v["usd"],),
        currency_id=f["usd"],
        kind=FEE,
        lines=(BankLine(acc["91.2"], 200, (v["fee"],)),),
        memo="Комиссия банка",
    )


def postings(ledger, f, operation_id):
    op = load_bank_operation(ledger.conn, f["cid"], operation_id)
    return load_document(ledger.conn, f["cid"], op.document_id).postings


def test_payment_to_supplier_posts_and_closes_the_e_qaime(ledger, firm):
    f = firm
    acc, v = f["acc"], f["v"]
    op_id = ledger.bank.save_bank_operation(f["cid"], pay_alfa(f), post=True)
    [p] = postings(ledger, f, op_id)
    assert (p.debit_account_id, p.credit_account_id, p.amount) == (acc["60.1"], acc["51"], 118000)
    # the counterparty of the operation fills the line's counterparty position
    assert p.debit_subconto == (v["alfa"], v["contract"], None)
    assert p.credit_subconto == (v["azn"], None, None)
    assert (p.memo, p.invoice, p.currency_id) == ("Оплата по счёту MT001", "MT001", None)
    [row] = invoice_report(ledger.conn, f["cid"], "2026-03-01", "2026-03-31")
    assert (row.invoice, row.debit, row.credit, row.balance) == ("MT001", 118000, 118000, 0)
    op = load_bank_operation(ledger.conn, f["cid"], op_id)
    assert op.status == "posted"
    assert op.lines[0].subconto == (v["alfa"], v["contract"], None)
    assert document_owner(ledger.conn, f["cid"], op.document_id) == DocumentOwner(
        "bank", op_id, None
    )


def test_receipt_split_into_two_e_qaime(ledger, firm):
    f = firm
    acc, v = f["acc"], f["v"]
    op_id = ledger.bank.save_bank_operation(f["cid"], from_beta(f), post=True)
    lines = postings(ledger, f, op_id)
    assert [(p.debit_account_id, p.credit_account_id, p.amount, p.invoice) for p in lines] == [
        (acc["51"], acc["62.1"], 50000, "MT010"),
        (acc["51"], acc["62.1"], 70000, "MT011"),
    ]
    assert all(p.credit_subconto == (v["beta"], v["contract_b"], None) for p in lines)
    assert load_bank_operation(ledger.conn, f["cid"], op_id).total == 120000


def test_operation_in_currency_at_the_rate_of_the_day(ledger, firm):
    f = firm
    op_id = ledger.bank.save_bank_operation(f["cid"], usd_fee(f), post=True)
    [p] = postings(ledger, f, op_id)
    assert (p.amount, p.currency_id, p.currency_amount) == (340, f["usd"], 200)
    assert p.credit_subconto == (f["v"]["usd"], None, None)


def test_no_rate_no_posting(ledger, firm):
    f = firm
    with pytest.raises(ValidationError, match=r"нет курса USD на 27\.02\.2026"):
        ledger.bank.save_bank_operation(
            f["cid"], replace(usd_fee(f), doc_date="2026-02-27"), post=True
        )


def test_trial_balance_after_the_month(ledger, firm):
    f = firm
    for data in (pay_alfa(f), from_beta(f), usd_fee(f)):
        ledger.bank.save_bank_operation(f["cid"], data, post=True)
    rows = {
        r.code: r for r in trial_balance(ledger.conn, f["cid"], "2026-03-01", "2026-03-31").rows
    }
    assert rows["51"].closing_dt == 1002000
    assert rows["52"].closing_dt == 169660
    assert rows["60.1"].closing_ct == 0
    assert rows["62.1"].closing_ct == 120000
    assert rows["91.2"].closing_dt == 340


def test_draft_has_no_postings_until_posted_and_keeps_its_number(ledger, firm):
    f = firm
    cid = f["cid"]
    op_id = ledger.bank.save_bank_operation(cid, pay_alfa(f, lines=()), post=False)
    op = load_bank_operation(ledger.conn, cid, op_id)
    assert (op.status, op.lines) == ("draft", ())
    assert load_document(ledger.conn, cid, op.document_id).postings == []
    ledger.bank.save_bank_operation(cid, pay_alfa(f), op_id, post=True)
    posted = load_bank_operation(ledger.conn, cid, op_id)
    assert (posted.status, posted.number) == ("posted", op.number)
    # changed in place (D32): the same document and number, the new amount
    ledger.bank.save_bank_operation(
        cid,
        pay_alfa(f, lines=(BankLine(f["acc"]["60.1"], 100000, (None, f["v"]["contract"])),)),
        op_id,
        post=True,
    )
    again = load_bank_operation(ledger.conn, cid, op_id)
    assert (again.document_id, again.number) == (op.document_id, op.number)
    assert [p.amount for p in postings(ledger, f, op_id)] == [100000]
    with pytest.raises(ValidationError, match="сначала отмените проведение"):
        ledger.bank.save_bank_operation(cid, pay_alfa(f), op_id, post=False)


def test_unpost_and_delete(ledger, firm):
    f = firm
    cid = f["cid"]
    op_id = ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    ledger.bank.unpost_bank_operation(cid, op_id)
    assert load_document(ledger.conn, cid, doc_id).postings == []
    assert load_bank_operation(ledger.conn, cid, op_id).status == "draft"
    ledger.bank.save_bank_operation(cid, pay_alfa(f), op_id, post=True)
    ledger.bank.delete_bank_operation(cid, op_id)
    assert document_owner(ledger.conn, cid, doc_id) is None
    count = ledger.conn.execute("SELECT COUNT(*) FROM documents WHERE id = ?", (doc_id,))
    assert count.fetchone()[0] == 0


def test_marked_operations_are_deleted_all_or_none(ledger, firm):
    """A draft, a payment of 05.03 and one of 10.03 (1 180.00 each) marked; the period is
    closed through 07.03: the payment of 05.03 keeps all three, the draft included.
    Without it the draft and 10.03 go: Kapital AZN 10 000.00 − 1 180.00 = 8 820.00."""
    f = firm
    cid = f["cid"]
    draft = ledger.bank.save_bank_operation(cid, pay_alfa(f, memo="черновик"), post=False)
    early = ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    late = ledger.bank.save_bank_operation(cid, pay_alfa(f, doc_date="2026-03-10"), post=True)
    number = load_bank_operation(ledger.conn, cid, early).number
    ledger.set_closed_through(cid, "2026-03-07")
    with pytest.raises(PeriodClosedError, match=f"№{number} от 05.03"):
        ledger.bank.delete_bank_operations(cid, [draft, late, early])
    left = ledger.conn.execute("SELECT COUNT(*) FROM bank_operations WHERE company_id = ?", (cid,))
    assert left.fetchone()[0] == 3
    ledger.bank.delete_bank_operations(cid, [draft, late])
    assert [load_bank_operation(ledger.conn, cid, early).id] == [early]
    places = {pl.value_id: pl for pl in bank_places(ledger.conn, cid)}
    assert place_balance(ledger.conn, cid, places[f["v"]["azn"]], "2026-03-31") == 882_000
    left = ledger.conn.execute("SELECT COUNT(*) FROM bank_operations WHERE company_id = ?", (cid,))
    assert left.fetchone()[0] == 1


def test_the_journal_does_not_touch_its_postings(ledger, firm):
    f = firm
    cid = f["cid"]
    op_id = ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    assert load_document(ledger.conn, cid, doc_id).bank_operation_id == op_id
    assert not load_document(ledger.conn, cid, doc_id).editable
    for action in (ledger.unpost, ledger.delete_document):
        with pytest.raises(ValidationError, match="банковской операцией"):
            action(cid, doc_id)


def test_the_journal_refuses_by_the_owners_view_alone(ledger, firm, monkeypatch):
    """The core learns who owns a GL document from the document_owners view, never from a
    module's tables; a module's own words are only words: without them the journal still
    refuses, in general terms."""
    f = firm
    cid = f["cid"]
    op_id = ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    owners = ledger.conn.execute(
        "SELECT module, role FROM document_owners WHERE company_id = ? AND document_id = ?",
        (cid, doc_id),
    ).fetchall()
    assert [tuple(r) for r in owners] == [("bank", "made")]
    assert document_owner(ledger.conn, cid, doc_id) == DocumentOwner("bank", op_id, None)
    assert document_owner(ledger.conn, cid, doc_id, "uses") is None
    monkeypatch.setattr("modern_gl.application.ledger.documents.OWNER_TEXTS", {})
    for action in (ledger.unpost, ledger.delete_document):
        with pytest.raises(ValidationError, match="исправьте их там"):
            action(cid, doc_id)


def test_what_cannot_be_posted(ledger, firm):
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    cases = [
        (pay_alfa(f, account_id=None), "не указан банковский счёт"),
        (pay_alfa(f, lines=()), "в операции нет строк"),
        (pay_alfa(f, lines=(BankLine(None, 100),)), "строка 1: не указан счёт"),
        (pay_alfa(f, lines=(BankLine(acc["60.1"], 0),)), "строка 1: нулевая сумма"),
        (
            pay_alfa(
                f, kind=TRANSFER, counterparty_id=None, lines=(BankLine(acc["51"], 5, (v["azn"],)),)
            ),
            "на тот же счёт",
        ),
        (pay_alfa(f, kind="gift"), "неизвестный вид операции"),
        (pay_alfa(f, direction="up"), "неизвестное направление"),
    ]
    for data, message in cases:
        with pytest.raises(ValidationError, match=message):
            ledger.bank.save_bank_operation(cid, data, post=True)


def test_transfer_between_own_accounts(ledger, firm):
    """10 000.00 from Kapital AZN to PAŞA AZN: Dt 51 [PAŞA] / Ct 51 [Kapital]."""
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    data = pay_alfa(
        f,
        kind=TRANSFER,
        counterparty_id=None,
        lines=(BankLine(acc["51"], 300000, (v["pasha"],)),),
        memo="Перевод на PAŞA",
    )
    op_id = ledger.bank.save_bank_operation(cid, data, post=True)
    [p] = postings(ledger, f, op_id)
    assert (p.debit_subconto[0], p.credit_subconto[0], p.amount) == (v["pasha"], v["azn"], 300000)
    places = {pl.value_id: pl for pl in bank_places(ledger.conn, cid)}
    assert place_balance(ledger.conn, cid, places[v["pasha"]], "2026-03-31") == 300000
    assert place_balance(ledger.conn, cid, places[v["azn"]], "2026-03-31") == 700000


def test_vat_deposit_pays_only_vat(ledger, firm):
    f = firm
    cid, acc = f["cid"], f["acc"]
    ledger.set_account_type(cid, acc["55"], "vat_deposit")
    deposit = ledger.add_subconto_value(cid, f["kind"]["bank_account"], "ƏDV depozit")
    base = pay_alfa(f, account_id=acc["55"], subconto=(deposit,))
    with pytest.raises(ValidationError, match="депозитного счёта ƏDV"):
        ledger.bank.save_bank_operation(cid, replace(base, kind=OTHER), post=True)
    # a draft may be anything: the rule is checked when it is posted
    draft = ledger.bank.save_bank_operation(cid, replace(base, kind=OTHER), post=False)
    tax = replace(
        base,
        kind=TAX,
        counterparty_id=None,
        lines=(BankLine(acc["68.1"], 18000),),
    )
    ledger.bank.save_bank_operation(cid, tax, draft, post=True)
    [p] = postings(ledger, f, draft)
    assert (p.debit_account_id, p.credit_account_id, p.amount) == (acc["68.1"], acc["55"], 18000)


def test_a_payment_and_its_vat_from_the_deposit_are_two_operations(ledger, firm):
    """D69: 1 180.00 owed to Alfa — 1 000.00 from Kapital AZN (Dt 60.1 / Kt 51) and the
    ƏDV 180.00 from the deposit (Dt 60.1 / Kt 55) on 06.03, both on MT001; a deposit part
    that may not be posted (kind «other») leaves the bank part unsaved too."""
    f = firm
    cid, acc = f["cid"], f["acc"]
    ledger.set_account_type(cid, acc["55"], "vat_deposit")
    deposit = ledger.add_subconto_value(cid, f["kind"]["bank_account"], "ƏDV depozit")
    bank = pay_alfa(f, lines=(replace(pay_alfa(f).lines[0], amount=100000),))
    vat = pay_alfa(
        f,
        doc_date="2026-03-06",
        account_id=acc["55"],
        subconto=(deposit,),
        lines=(replace(pay_alfa(f).lines[0], amount=18000),),
    )
    with pytest.raises(ValidationError, match="депозитного счёта ƏDV"):
        ledger.bank.save_bank_payment(cid, bank, replace(vat, kind=OTHER), post=True)
    assert ledger.conn.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == 0
    first, second = ledger.bank.save_bank_payment(cid, bank, vat, post=True)
    [p] = postings(ledger, f, first)
    assert (p.debit_account_id, p.credit_account_id, p.amount, p.invoice) == (
        acc["60.1"],
        acc["51"],
        100000,
        "MT001",
    )
    [p] = postings(ledger, f, second)
    assert (p.debit_account_id, p.credit_account_id, p.amount, p.invoice) == (
        acc["60.1"],
        acc["55"],
        18000,
        "MT001",
    )
    assert load_bank_operation(ledger.conn, cid, second).doc_date == "2026-03-06"


def test_last_lines_suggest_the_account_of_the_counterparty(ledger, firm):
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    # nothing paid through the bank yet: nothing to suggest
    assert last_lines(ledger.conn, cid, OUT, v["alfa"]) == []
    ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    assert last_lines(ledger.conn, cid, OUT, v["alfa"]) == [
        BankLine(acc["60.1"], 0, (v["alfa"], v["contract"], None))
    ]
    assert last_lines(ledger.conn, cid, IN, v["alfa"]) == []
    # a payment made in the journal counts too
    ledger.post_new(
        cid,
        "2026-03-09",
        [PostingInput(acc["51"], acc["62.1"], "10", [v["azn"]], [v["beta"], v["contract_b"]])],
    )
    assert last_lines(ledger.conn, cid, IN, v["beta"]) == [
        BankLine(acc["62.1"], 0, (v["beta"], v["contract_b"], None))
    ]


def test_reference_finds_the_operation(ledger, firm):
    f = firm
    op_id = ledger.bank.save_bank_operation(f["cid"], pay_alfa(f, reference=" FT2603 "), post=False)
    assert find_bank_operation(ledger.conn, f["cid"], "FT2603") == op_id
    assert find_bank_operation(ledger.conn, f["cid"], "") is None


def test_bank_places_put_each_account_where_it_belongs(ledger, firm):
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    places = [(p.account_code, p.name, p.currency) for p in bank_places(ledger.conn, cid)]
    # never used: PAŞA AZN is under the first manat account; 55 has no element of its own
    assert places == [
        ("51", "Kapital AZN", ""),
        ("51", "PAŞA AZN", ""),
        ("52", "Kapital USD", "USD"),
    ]
    # used on 55: it is there, and no longer under 51
    ledger.post_new(
        cid, "2026-03-03", [PostingInput(acc["55"], acc["80"], "1", [v["pasha"]], [v["owner"]])]
    )
    places = [(p.account_code, p.name) for p in bank_places(ledger.conn, cid)]
    assert ("55", "PAŞA AZN") in places and ("51", "PAŞA AZN") not in places


def test_statement_with_balances_and_drafts(ledger, firm):
    f = firm
    cid, v = f["cid"], f["v"]
    for data in (pay_alfa(f), from_beta(f), usd_fee(f)):
        ledger.bank.save_bank_operation(cid, data, post=True)
    draft = ledger.bank.save_bank_operation(
        cid,
        pay_alfa(f, doc_date="2026-03-08", lines=(BankLine(f["acc"]["60.1"], 5000),)),
        post=False,
    )
    places = {p.value_id: p for p in bank_places(ledger.conn, cid)}
    st = statement(ledger.conn, cid, places[v["azn"]], "2026-03-05", "2026-03-31")
    assert st.opening == 1000000
    assert [
        (line.doc_date, line.money_in, line.money_out, line.balance, line.status)
        for line in st.lines
    ] == [
        ("2026-03-05", 0, 118000, 882000, "posted"),
        ("2026-03-06", 120000, 0, 1002000, "posted"),
        ("2026-03-08", 0, 5000, None, "draft"),
    ]
    assert (st.total_in, st.total_out, st.closing) == (120000, 118000, 1002000)
    first, second, third = st.lines
    assert (first.counterparty, first.corr, first.kind, first.direction) == (
        "ALFA MMC",
        "60.1",
        SUPPLIER,
        OUT,
    )
    assert second.counterparty == "BETA MMC"
    assert third.document_id == load_bank_operation(ledger.conn, cid, draft).document_id
    # the USD account: in dollars
    usd = statement(ledger.conn, cid, places[v["usd"]], "2026-03-01", "2026-03-31")
    assert usd.currency == "USD"
    assert [(line.money_in, line.money_out) for line in usd.lines] == [(100000, 0), (0, 200)]
    assert usd.closing == 99800


def test_names_of_kinds_and_memos_are_translated():
    from modern_gl.application.bank import KINDS, default_memo
    from modern_gl.i18n import set_language
    from modern_gl.i18n_az import AZ

    assert all(name in AZ for _, name in KINDS)
    set_language("az")
    assert default_memo(OUT, SUPPLIER, "ALFA") == "ALFA malsatanına ödəniş"
    assert default_memo(IN, OTHER) == "Digər mədaxil"
    set_language("ru")
    assert default_memo(OUT, TAX) == "Уплата налогов"


def test_one_payment_over_several_e_qaime_oldest_first():
    """2 000.00 over MT1 1 416.00 and MT2 1 239.00: MT1 in full, MT2 584.00
    (2 000.00 - 1 416.00), nothing left. 3 000.00 pays both (2 655.00) and leaves
    345.00 — an advance. Less than the first pays only part of it."""
    from modern_gl.application.bank import allocate

    assert allocate(200_000, [141_600, 123_900]) == ([141_600, 58_400], 0)
    assert allocate(300_000, [141_600, 123_900]) == ([141_600, 123_900], 34_500)
    assert allocate(100_000, [141_600, 123_900]) == ([100_000, 0], 0)


def test_operations_move_to_another_bank_account(ledger, firm):
    """Paid to ALFA from Kapital AZN by mistake, 1 180.00: moved to PAŞA AZN it keeps its
    number; Kapital AZN is back to 10 000.00, PAŞA AZN −1 180.00. A draft moves too."""
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    paid = ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    draft = ledger.bank.save_bank_operation(cid, pay_alfa(f, memo="черновик"), post=False)
    number = load_bank_operation(ledger.conn, cid, paid).number
    ledger.bank.move_bank_operations(cid, [paid, draft], acc["51"], (v["pasha"],))
    moved = load_bank_operation(ledger.conn, cid, paid)
    assert (moved.number, moved.status, moved.subconto[0]) == (number, "posted", v["pasha"])
    assert load_bank_operation(ledger.conn, cid, draft).subconto[0] == v["pasha"]
    assert load_bank_operation(ledger.conn, cid, draft).status == "draft"
    places = {pl.value_id: pl for pl in bank_places(ledger.conn, cid)}
    assert place_balance(ledger.conn, cid, places[v["azn"]], "2026-03-31") == 1_000_000
    assert place_balance(ledger.conn, cid, places[v["pasha"]], "2026-03-31") == -118_000


def test_an_operation_does_not_move_to_another_currency_or_onto_itself(ledger, firm):
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    paid = ledger.bank.save_bank_operation(cid, pay_alfa(f), post=True)
    with pytest.raises(ValidationError, match="валют"):
        ledger.bank.move_bank_operations(cid, [paid], acc["52"], (v["usd"],))
    transfer = pay_alfa(
        f, kind=TRANSFER, counterparty_id=None, lines=(BankLine(acc["51"], 100, (v["pasha"],)),)
    )
    moved = ledger.bank.save_bank_operation(cid, transfer, post=True)
    with pytest.raises(ValidationError, match="сам на себя"):
        ledger.bank.move_bank_operations(cid, [moved], acc["51"], (v["pasha"],))


def test_the_kind_of_an_operation_by_the_account_of_its_line():
    assert [
        kind_of_account(t)
        for t in ("payable", "receivable", "tax_payable", "payroll", "bank", "vat_deposit", None)
    ] == [SUPPLIER, CUSTOMER, TAX, SALARY, TRANSFER, TRANSFER, OTHER]


def lines_of(ledger, f, amount: str, invoices=(), advance=True, account="60.1"):
    acc, v = f["acc"], f["v"]
    return [
        (
            ledger.conn.execute(
                "SELECT code FROM accounts WHERE id = ?", (x.account_id,)
            ).fetchone()[0],
            x.amount,
            x.invoice,
        )
        for x in payment_lines(
            ledger.conn,
            f["cid"],
            account_id=acc[account],
            account_type="payable",
            subconto=(None, v["contract"]),
            counterparty_id=v["alfa"],
            amount=to_minor(amount),
            direction=OUT,
            day="2026-03-05",
            invoices=invoices,
            advance_account=ledger.account_role(f["cid"], ADVANCE_PAID) if advance else None,
        )
    ]


def test_a_payment_spread_over_e_qaime_debt_and_advance(ledger, firm):
    """ALFA is owed 1 180.00 on 60.1, all of it by MT001 (02.03), hand-calculated:
    1 500.00 for MT001 → 1 180.00 MT001, 320.00 advance on 60.2;
    500.00 with no e-qaimə → 500.00 of the debt on 60.1;
    1 500.00 with no e-qaimə → 1 180.00 debt, 320.00 advance;
    without an advance account 1 500.00 for MT001 → 1 180.00 MT001, 320.00 on 60.1."""
    f = firm
    assert ledger.account_role(f["cid"], ADVANCE_PAID) == ledger.account_id(f["cid"], "60.2")
    mt001 = [("MT001", 118_000)]
    assert lines_of(ledger, f, "1500", mt001) == [("60.1", 118_000, "MT001"), ("60.2", 32_000, "")]
    assert lines_of(ledger, f, "500") == [("60.1", 50_000, "")]
    assert lines_of(ledger, f, "1500") == [("60.1", 118_000, ""), ("60.2", 32_000, "")]
    assert lines_of(ledger, f, "1500", mt001, advance=False) == [
        ("60.1", 118_000, "MT001"),
        ("60.1", 32_000, ""),
    ]
    # an e-qaimə the list does not know takes the whole amount
    assert lines_of(ledger, f, "700", [("MT999", None)]) == [("60.1", 70_000, "MT999")]


def test_an_advance_is_offset_against_a_later_e_qaime(ledger, firm):
    """320.00 paid ahead to ALFA (60.2); MT002 for 400.00 comes: offset 320.00 —
    Dt 60.1 [ALFA, MT002] / Ct 60.2 [ALFA]; MT002 still owes 80.00, 60.2 is zero."""
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    ledger.bank.save_bank_operation(
        cid,
        pay_alfa(
            f,
            lines=(
                BankLine(acc["60.1"], 118_000, (None, v["contract"]), "MT001"),
                BankLine(ledger.account_id(cid, "60.2"), 32_000, (None, v["contract"])),
            ),
        ),
        post=True,
    )
    ledger.post_new(
        cid,
        "2026-03-06",
        [
            PostingInput(
                acc["26"],
                acc["60.1"],
                "400",
                [v["rent"]],
                [v["alfa"], v["contract"]],
                invoice="MT002",
            )
        ],
    )
    a602 = ledger.account_id(cid, "60.2")
    assert counterparty_balance(ledger.conn, cid, a602, v["alfa"], "2026-03-31") == 32_000
    ledger.bank.offset_advances(
        cid,
        "2026-03-07",
        v["alfa"],
        acc["60.1"],
        a602,
        [("MT002", 32_000)],
        contract_id=v["contract"],
    )
    assert counterparty_balance(ledger.conn, cid, a602, v["alfa"], "2026-03-31") == 0
    left = {
        i.invoice: i.amount
        for i in open_invoices(ledger.conn, cid, v["alfa"], payable=True, on_date="2026-03-31")
    }
    assert left == {"MT002": 8_000}
