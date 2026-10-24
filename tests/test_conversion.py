"""Currency conversion document (D37). Rates of the Central Bank (hand-calculated examples):
02.03: USD 1.7000, EUR 1.8500; 03.03: USD 1.7100 (not used: the difference is of the debit day).

Sale of 1 000 USD for 1 695.00 AZN on 02.03, the bank takes a fee of 2.00 USD:
  Dt 57         Ct 52 [USD]   1 700.00  (1 000.00 USD × 1.70)
  Dt 91.2 [ExD] Ct 57             5.00  loss: 1 700.00 − 1 695.00
  Dt 91.2 [Fee] Ct 52 [USD]       3.40  (2.00 USD × 1.70)
  Dt 51 [AZN]   Ct 57         1 695.00
Purchase of 1 000 USD for 1 705.00 AZN: Dt 57 / Ct 51 1 705.00, Dt 52 / Ct 57 1 700.00,
  loss 5.00.
500 EUR -> 546 USD: 925.00 (500 × 1.85) against 928.20 (546 × 1.70): gain 3.20 (Dt 57 / Ct 91.1).

Fees are lines, each from any money account in its currency:
  the same exchange with 5.00 AZN taken from 51 and 1.00 USD from the USD account credited:
    Dt 91.2 / Ct 51 5.00;  Dt 91.2 / Ct 52 [USD] 1.70 (1.00 USD × 1.70)
  a purchase credited on 03.03 with 1.00 USD taken there: the fee goes with the credit, at
  the rate of 03.03 — Dt 91.2 / Ct 52 [USD] 1.71; the credit itself stays at 02.03's 1 700.00.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from modern_gl.application.bank import bank_places, statement
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.conversions import (
    ConversionFee,
    ConversionInput,
    ConversionSide,
    bank_rate,
    calculate,
    load_conversion,
)
from modern_gl.application.queries import DocumentOwner, document_owner, load_document
from modern_gl.domain.accounts import BANK_FEE, FX_GAIN, FX_LOSS, FX_TRANSIT
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import trial_balance


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Конвертация")
    banks = ledger.add_subconto_kind(cid, "bank_account", "Банковские счета")
    items = ledger.add_subconto_kind(cid, "other_income", "Прочие доходы и расходы")
    azn_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank AZN")
    usd_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    eur_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank EUR")
    usd, eur = ledger.currency_id(cid, "USD"), ledger.currency_id(cid, "EUR")
    ledger.set_subconto_value_currency(cid, usd_bank, usd)
    ledger.set_subconto_value_currency(cid, eur_bank, eur)
    acc = {
        "51": ledger.add_account(cid, "51", "Расчётный счёт", subconto=[banks]),
        "52": ledger.add_account(cid, "52", "Валютный счёт", subconto=[banks], currency=True),
        "57": ledger.add_account(cid, "57", "Переводы в пути", account_class="asset"),
        "91.1": ledger.add_account(
            cid, "91.1", "Прочие доходы", account_class="revenue", subconto=[items]
        ),
        "91.2": ledger.add_account(
            cid, "91.2", "Прочие расходы", account_class="expense", subconto=[items]
        ),
    }
    for account in ("51", "52"):
        ledger.set_account_class(cid, acc[account], "asset")
    ledger.set_account_role(cid, FX_TRANSIT, acc["57"])
    ledger.set_account_role(cid, FX_GAIN, acc["91.1"])
    ledger.set_account_role(cid, FX_LOSS, acc["91.2"])
    ledger.set_account_role(cid, BANK_FEE, acc["91.2"])
    ledger.set_rate(cid, "USD", "2026-03-02", parse_rate("1.7"))
    ledger.set_rate(cid, "EUR", "2026-03-02", parse_rate("1.85"))
    ledger.set_rate(cid, "USD", "2026-03-03", parse_rate("1.71"))
    return {
        "cid": cid,
        "acc": acc,
        "usd": usd,
        "eur": eur,
        "azn_bank": azn_bank,
        "usd_bank": usd_bank,
        "eur_bank": eur_bank,
    }


def sale(f, **changes) -> ConversionInput:
    data = ConversionInput(
        doc_date="2026-03-02",
        source=ConversionSide(f["acc"]["52"], 100_000, (f["usd_bank"],), f["usd"], "REF-1"),
        target=ConversionSide(f["acc"]["51"], 169_500, (f["azn_bank"],), None, "REF-2"),
        fees=(ConversionFee(f["acc"]["52"], 200, (f["usd_bank"],), f["usd"]),),
        memo="Продажа USD",
    )
    return replace(data, **changes)


def postings(conn, cid, doc_id):
    return [
        (p.debit_account_id, p.credit_account_id, p.amount, p.currency_amount)
        for p in load_document(conn, cid, doc_id).postings
    ]


def balances(conn, cid, day="2026-03-31"):
    return {
        r.code: (r.closing_dt, r.closing_ct)
        for r in trial_balance(conn, cid, "2026-03-01", day).rows
        if not r.is_group
    }


def test_sale_of_currency_posts_through_transit(ledger, conn, firm):
    cid, acc = firm["cid"], firm["acc"]
    conversion_id = ledger.conversion.save_conversion(cid, sale(firm), post=True)

    conversion = load_conversion(conn, cid, conversion_id)
    assert conversion.status == "posted" and conversion.credit_document_id is None
    assert postings(conn, cid, conversion.document_id) == [
        (acc["57"], acc["52"], 170_000, 100_000),
        (acc["91.2"], acc["57"], 500, None),
        (acc["91.2"], acc["52"], 340, 200),
        (acc["51"], acc["57"], 169_500, None),
    ]
    assert balances(conn, cid) == {
        "51": (169_500, 0),
        "52": (0, 170_340),
        "57": (0, 0),
        "91.2": (840, 0),
    }
    # the exchange difference and the fee are items of other expenses, made on first use
    lines = load_document(conn, cid, conversion.document_id).postings
    names = {ledger._subconto_value(cid, p.debit_subconto[0])["name"] for p in lines[1:3]}
    assert names == {"Курсовая разница при конвертации", "Комиссия банка"}
    owner = document_owner(conn, cid, conversion.document_id)
    assert owner == DocumentOwner("conversion", conversion_id, None)


def test_purchase_and_cross_currency(ledger, conn, firm):
    cid, acc = firm["cid"], firm["acc"]
    purchase = ConversionInput(
        doc_date="2026-03-02",
        source=ConversionSide(acc["51"], 170_500, (firm["azn_bank"],)),
        target=ConversionSide(acc["52"], 100_000, (firm["usd_bank"],), firm["usd"]),
    )
    doc = load_conversion(conn, cid, ledger.conversion.save_conversion(cid, purchase, post=True))
    assert postings(conn, cid, doc.document_id) == [
        (acc["57"], acc["51"], 170_500, None),
        (acc["91.2"], acc["57"], 500, None),
        (acc["52"], acc["57"], 170_000, 100_000),
    ]
    assert bank_rate(purchase) is not None and float(bank_rate(purchase)) == 1.705

    cross = ConversionInput(
        doc_date="2026-03-02",
        source=ConversionSide(acc["52"], 50_000, (firm["eur_bank"],), firm["eur"]),
        target=ConversionSide(acc["52"], 54_600, (firm["usd_bank"],), firm["usd"]),
    )
    calc = calculate(conn, cid, cross)
    assert (calc.source_value, calc.target_value, calc.difference) == (92_500, 92_820, -320)
    doc = load_conversion(conn, cid, ledger.conversion.save_conversion(cid, cross, post=True))
    assert postings(conn, cid, doc.document_id) == [
        (acc["57"], acc["52"], 92_500, 50_000),
        (acc["57"], acc["91.1"], 320, None),
        (acc["52"], acc["57"], 92_820, 54_600),
    ]


def test_credit_on_a_later_day_waits_on_transit(ledger, conn, firm):
    cid, acc = firm["cid"], firm["acc"]
    data = sale(firm, target_date="2026-03-03", fees=())
    conversion_id = ledger.conversion.save_conversion(cid, data, post=True)
    conversion = load_conversion(conn, cid, conversion_id)
    assert conversion.credit_document_id is not None
    assert postings(conn, cid, conversion.document_id) == [
        (acc["57"], acc["52"], 170_000, 100_000),
        (acc["91.2"], acc["57"], 500, None),
    ]
    credit = load_document(conn, cid, conversion.credit_document_id)
    assert credit.doc_date == "2026-03-03"
    assert postings(conn, cid, credit.id) == [(acc["51"], acc["57"], 169_500, None)]
    assert balances(conn, cid, "2026-03-02")["57"] == (169_500, 0)
    assert balances(conn, cid, "2026-03-03")["57"] == (0, 0)
    # either GL document opens the conversion (the document_owners view, debt 12)
    owner = DocumentOwner("conversion", conversion_id, None)
    assert document_owner(conn, cid, conversion.document_id) == owner
    assert document_owner(conn, cid, credit.id) == owner
    assert credit.conversion_id == conversion_id and not credit.editable

    # back to one day: the second document goes, the first keeps its number
    ledger.conversion.save_conversion(
        cid, replace(data, target_date=None), conversion_id, post=True
    )
    again = load_conversion(conn, cid, conversion_id)
    assert again.credit_document_id is None and again.number == conversion.number
    assert len(postings(conn, cid, again.document_id)) == 3


def test_draft_may_lack_a_side_and_has_no_postings(ledger, conn, firm):
    cid = firm["cid"]
    draft = sale(firm, target=None)
    conversion_id = ledger.conversion.save_conversion(cid, draft, post=False)
    conversion = load_conversion(conn, cid, conversion_id)
    assert conversion.status == "draft" and conversion.target is None
    assert conversion.source == replace(draft.source, subconto=(firm["usd_bank"], None, None))
    assert load_document(conn, cid, conversion.document_id).postings == []
    with pytest.raises(ValidationError, match="на какой счёт зачислено"):
        ledger.conversion.save_conversion(cid, draft, conversion_id, post=True)

    # the second statement completes it
    ledger.conversion.save_conversion(cid, sale(firm), conversion_id, post=True)
    assert load_conversion(conn, cid, conversion_id).status == "posted"


def test_unpost_and_delete(ledger, conn, firm):
    cid = firm["cid"]
    conversion_id = ledger.conversion.save_conversion(
        cid, sale(firm, target_date="2026-03-03"), post=True
    )
    conversion = load_conversion(conn, cid, conversion_id)
    with pytest.raises(ValidationError, match="Конвертация валюты"):
        ledger.delete_document(cid, conversion.document_id)
    with pytest.raises(ValidationError, match="Конвертация валюты"):
        ledger.reverse(cid, conversion.credit_document_id, "2026-03-04")
    with pytest.raises(ValidationError, match="отмените проведение"):
        ledger.conversion.save_conversion(cid, sale(firm), conversion_id, post=False)

    ledger.conversion.unpost_conversion(cid, conversion_id)
    draft = load_conversion(conn, cid, conversion_id)
    assert draft.status == "draft" and draft.credit_document_id is None
    assert balances(conn, cid) == {}  # a draft has no postings

    ledger.conversion.delete_conversion(cid, conversion_id)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM currency_conversions").fetchone()[0] == 0


def test_errors(ledger, conn, firm):
    cid, acc = firm["cid"], firm["acc"]
    same = sale(firm, target=ConversionSide(acc["52"], 100, (firm["usd_bank"],), firm["usd"]))
    with pytest.raises(ValidationError, match="одинаковая"):
        ledger.conversion.save_conversion(cid, same, post=True)
    with pytest.raises(ValidationError, match="нет курса USD"):
        ledger.conversion.save_conversion(cid, sale(firm, doc_date="2026-02-27"), post=True)
    with pytest.raises(ValidationError, match="раньше даты списания"):
        ledger.conversion.save_conversion(cid, sale(firm, target_date="2026-03-01"), post=True)
    ledger.set_account_role(cid, FX_TRANSIT, None)
    with pytest.raises(ValidationError, match="переводов в пути"):
        ledger.conversion.save_conversion(cid, sale(firm), post=True)
    # nothing half-made is left behind
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_chart_template_sets_conversion_accounts(ledger):
    cid = ledger.create_company("Шаблон 1С")
    apply_chart_template(ledger, cid, "1c77")
    roles = {
        role: ledger._account(cid, ledger.account_role(cid, role) or 0)["code"]
        for role in (FX_TRANSIT, FX_GAIN, FX_LOSS, BANK_FEE)
    }
    assert roles == {FX_TRANSIT: "57", FX_GAIN: "91.1", FX_LOSS: "91.2", BANK_FEE: "91.2"}


def test_classic_chart_posts_conversions_to_57_and_80(ledger):
    cid = ledger.create_company("Шаблон classic")
    apply_chart_template(ledger, cid, "classic")
    roles = {
        role: ledger._account(cid, ledger.account_role(cid, role) or 0)["code"]
        for role in (FX_TRANSIT, FX_GAIN, FX_LOSS, BANK_FEE)
    }
    assert roles == {FX_TRANSIT: "57", FX_GAIN: "80", FX_LOSS: "80", BANK_FEE: "80"}
    assert ledger._account(cid, "57")["account_type"] == "transit"


def test_transit_account_is_found_by_its_type(ledger, conn, firm):
    """Any chart: the only account of the type "money in transit" plays the role."""
    cid, acc = firm["cid"], firm["acc"]
    ledger.set_account_role(cid, FX_TRANSIT, None)
    assert ledger.account_role(cid, FX_TRANSIT) is None
    ledger.set_account_type(cid, acc["57"], "transit")
    assert ledger.account_role(cid, FX_TRANSIT) == acc["57"]
    ledger.conversion.save_conversion(cid, sale(firm), post=True)


def test_fees_from_any_account_in_its_currency(ledger, conn, firm):
    cid, acc = firm["cid"], firm["acc"]
    cross = ConversionInput(
        doc_date="2026-03-02",
        source=ConversionSide(acc["52"], 50_000, (firm["eur_bank"],), firm["eur"]),
        target=ConversionSide(acc["52"], 54_600, (firm["usd_bank"],), firm["usd"]),
        fees=(
            ConversionFee(acc["51"], 500, (firm["azn_bank"],)),
            ConversionFee(acc["52"], 100, (firm["usd_bank"],), firm["usd"]),
        ),
    )
    assert calculate(conn, cid, cross).fee_values == (500, 170)
    conversion_id = ledger.conversion.save_conversion(cid, cross, post=True)
    doc = load_conversion(conn, cid, conversion_id)
    assert doc.fees == tuple(replace(f, subconto=(*f.subconto, None, None)) for f in cross.fees)
    assert postings(conn, cid, doc.document_id) == [
        (acc["57"], acc["52"], 92_500, 50_000),
        (acc["57"], acc["91.1"], 320, None),
        (acc["91.2"], acc["51"], 500, None),
        (acc["52"], acc["57"], 92_820, 54_600),
        (acc["91.2"], acc["52"], 170, 100),
    ]


def test_fee_taken_on_a_later_credit_goes_with_it(ledger, conn, firm):
    cid, acc = firm["cid"], firm["acc"]
    purchase = ConversionInput(
        doc_date="2026-03-02",
        source=ConversionSide(acc["51"], 170_500, (firm["azn_bank"],)),
        target=ConversionSide(acc["52"], 100_000, (firm["usd_bank"],), firm["usd"]),
        target_date="2026-03-03",
        fees=(ConversionFee(acc["52"], 100, (firm["usd_bank"],), firm["usd"]),),
    )
    doc = load_conversion(conn, cid, ledger.conversion.save_conversion(cid, purchase, post=True))
    assert postings(conn, cid, doc.document_id) == [
        (acc["57"], acc["51"], 170_500, None),
        (acc["91.2"], acc["57"], 500, None),
    ]
    assert doc.credit_document_id is not None
    assert postings(conn, cid, doc.credit_document_id) == [
        (acc["52"], acc["57"], 170_000, 100_000),
        (acc["91.2"], acc["52"], 171, 100),
    ]


def test_migration_keeps_the_fee_of_older_files(tmp_path, monkeypatch):
    """A conversion saved before fees became lines keeps its fee as the first line."""
    from modern_gl.application.ledger import Ledger
    from modern_gl.infrastructure import db

    older = tmp_path / "migrations"
    older.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 19:
            (older / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    full = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    file = tmp_path / "old.gl"
    conn = db.connect(file)
    ledger = Ledger(conn)
    cid = ledger.create_company("Старая")
    azn = ledger.add_account(cid, "51", "Расчётный счёт", account_class="asset")
    usd_account = ledger.add_account(cid, "52", "Валютный", account_class="asset", currency=True)
    usd = ledger.currency_id(cid, "USD")
    doc = ledger.create_draft(cid, "2026-03-02", [])
    conn.execute(
        "INSERT INTO currency_conversions (company_id, document_id, from_account_id, "
        "from_currency_id, from_amount, to_account_id, to_amount, fee_amount, fee_side) "
        "VALUES (?, ?, ?, ?, 100000, ?, 169500, 340, 'to')",
        (cid, doc, usd_account, usd, azn),
    )
    conn.close()

    monkeypatch.setattr(db, "MIGRATIONS_DIR", full)
    conn = db.connect(file)
    conversion_id = conn.execute("SELECT id FROM currency_conversions").fetchone()[0]
    loaded = load_conversion(conn, cid, conversion_id)
    assert loaded.fees == (ConversionFee(azn, 340, (None, None, None)),)
    assert loaded.source is not None and loaded.source.amount == 100_000
    conn.close()


def test_the_bank_statement_marks_both_days_of_a_conversion(ledger, conn, firm):
    """The bank statement learns that a conversion made the postings from document_owners,
    not from the conversion's table (debt 12): the debit day on the USD account, the
    credit day on the manat one."""
    cid = firm["cid"]
    ledger.conversion.save_conversion(cid, sale(firm, target_date="2026-03-03"), post=True)
    places = {p.value_id: p for p in bank_places(conn, cid)}
    usd = statement(conn, cid, places[firm["usd_bank"]], "2026-03-01", "2026-03-31")
    azn = statement(conn, cid, places[firm["azn_bank"]], "2026-03-01", "2026-03-31")
    assert [(line.doc_date, line.money_out, line.kind) for line in usd.lines] == [
        ("2026-03-02", 100_200, "conversion")
    ]
    assert [(line.doc_date, line.money_in, line.kind) for line in azn.lines] == [
        ("2026-03-03", 169_500, "conversion")
    ]
