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
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    bank_operation_of_document,
    bank_places,
    find_bank_operation,
    last_lines,
    load_bank_operation,
    place_balance,
    statement,
)
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import load_document
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template
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
    op_id = ledger.save_bank_operation(f["cid"], pay_alfa(f), post=True)
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
    assert bank_operation_of_document(ledger.conn, f["cid"], op.document_id) == op_id


def test_receipt_split_into_two_e_qaime(ledger, firm):
    f = firm
    acc, v = f["acc"], f["v"]
    op_id = ledger.save_bank_operation(f["cid"], from_beta(f), post=True)
    lines = postings(ledger, f, op_id)
    assert [(p.debit_account_id, p.credit_account_id, p.amount, p.invoice) for p in lines] == [
        (acc["51"], acc["62.1"], 50000, "MT010"),
        (acc["51"], acc["62.1"], 70000, "MT011"),
    ]
    assert all(p.credit_subconto == (v["beta"], v["contract_b"], None) for p in lines)
    assert load_bank_operation(ledger.conn, f["cid"], op_id).total == 120000


def test_operation_in_currency_at_the_rate_of_the_day(ledger, firm):
    f = firm
    op_id = ledger.save_bank_operation(f["cid"], usd_fee(f), post=True)
    [p] = postings(ledger, f, op_id)
    assert (p.amount, p.currency_id, p.currency_amount) == (340, f["usd"], 200)
    assert p.credit_subconto == (f["v"]["usd"], None, None)


def test_no_rate_no_posting(ledger, firm):
    f = firm
    with pytest.raises(ValidationError, match="нет курса USD на 2026-02-27"):
        ledger.save_bank_operation(f["cid"], replace(usd_fee(f), doc_date="2026-02-27"), post=True)


def test_trial_balance_after_the_month(ledger, firm):
    f = firm
    for data in (pay_alfa(f), from_beta(f), usd_fee(f)):
        ledger.save_bank_operation(f["cid"], data, post=True)
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
    op_id = ledger.save_bank_operation(cid, pay_alfa(f, lines=()), post=False)
    op = load_bank_operation(ledger.conn, cid, op_id)
    assert (op.status, op.lines) == ("draft", ())
    assert load_document(ledger.conn, cid, op.document_id).postings == []
    ledger.save_bank_operation(cid, pay_alfa(f), op_id, post=True)
    posted = load_bank_operation(ledger.conn, cid, op_id)
    assert (posted.status, posted.number) == ("posted", op.number)
    # changed in place (D32): the same document and number, the new amount
    ledger.save_bank_operation(
        cid,
        pay_alfa(f, lines=(BankLine(f["acc"]["60.1"], 100000, (None, f["v"]["contract"])),)),
        op_id,
        post=True,
    )
    again = load_bank_operation(ledger.conn, cid, op_id)
    assert (again.document_id, again.number) == (op.document_id, op.number)
    assert [p.amount for p in postings(ledger, f, op_id)] == [100000]
    with pytest.raises(ValidationError, match="сначала отмените проведение"):
        ledger.save_bank_operation(cid, pay_alfa(f), op_id, post=False)


def test_unpost_and_delete(ledger, firm):
    f = firm
    cid = f["cid"]
    op_id = ledger.save_bank_operation(cid, pay_alfa(f), post=True)
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    ledger.unpost_bank_operation(cid, op_id)
    assert load_document(ledger.conn, cid, doc_id).postings == []
    assert load_bank_operation(ledger.conn, cid, op_id).status == "draft"
    ledger.save_bank_operation(cid, pay_alfa(f), op_id, post=True)
    ledger.delete_bank_operation(cid, op_id)
    assert bank_operation_of_document(ledger.conn, cid, doc_id) is None
    count = ledger.conn.execute("SELECT COUNT(*) FROM documents WHERE id = ?", (doc_id,))
    assert count.fetchone()[0] == 0


def test_the_journal_does_not_touch_its_postings(ledger, firm):
    f = firm
    cid = f["cid"]
    op_id = ledger.save_bank_operation(cid, pay_alfa(f), post=True)
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    assert load_document(ledger.conn, cid, doc_id).bank_operation_id == op_id
    assert not load_document(ledger.conn, cid, doc_id).editable
    for action in (ledger.unpost, ledger.delete_document):
        with pytest.raises(ValidationError, match="банковской операцией"):
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
            ledger.save_bank_operation(cid, data, post=True)


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
    op_id = ledger.save_bank_operation(cid, data, post=True)
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
        ledger.save_bank_operation(cid, replace(base, kind=OTHER), post=True)
    # a draft may be anything: the rule is checked when it is posted
    draft = ledger.save_bank_operation(cid, replace(base, kind=OTHER), post=False)
    tax = replace(
        base,
        kind=TAX,
        counterparty_id=None,
        lines=(BankLine(acc["68.1"], 18000),),
    )
    ledger.save_bank_operation(cid, tax, draft, post=True)
    [p] = postings(ledger, f, draft)
    assert (p.debit_account_id, p.credit_account_id, p.amount) == (acc["68.1"], acc["55"], 18000)


def test_last_lines_suggest_the_account_of_the_counterparty(ledger, firm):
    f = firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    # nothing paid through the bank yet: nothing to suggest
    assert last_lines(ledger.conn, cid, OUT, v["alfa"]) == []
    ledger.save_bank_operation(cid, pay_alfa(f), post=True)
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
    op_id = ledger.save_bank_operation(f["cid"], pay_alfa(f, reference=" FT2603 "), post=False)
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
        ledger.save_bank_operation(cid, data, post=True)
    draft = ledger.save_bank_operation(
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
