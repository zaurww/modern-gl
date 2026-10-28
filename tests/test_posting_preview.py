"""The postings of a module's document before it is posted: its own saving and posting,
rolled back (`application/posting_preview.py`). Hand-calculated on the bank example of
test_bank.py (1C 7.7 chart, March 2026):

05.03  out, to ALFA 1 180.00, e-qaimə MT001:
       Dt 60.1 [ALFA MMC, Договор 1] / Ct 51 [Kapital AZN] 1 180.00 MT001
07.03  out, bank fee 2.00 USD at 1.70:
       Dt 91.2 [Комиссия банка] / Ct 52 [Kapital USD] 3.40 (USD 2.00)
A conversion (test_conversion.py): 1 000 USD sold for 1 695.00 AZN, fee 2.00 USD —
  Dt 57 / Ct 52 1 700.00, Dt 91.2 / Ct 57 5.00 (loss), Dt 91.2 / Ct 52 3.40, Dt 51 / Ct 57
  1 695.00; total 3 403.40.
The warehouse (tests/helpers/inventory.py): 2 pcs of Товар A bought for 20.00 —
  Dt 41 [Товар A, Основной] / Ct 60 [Поставщик] 20.00; then 1 pc issued at the average
  10.00 — Dt 46 / Ct 41 [Товар A, Основной] 10.00.
"""

from __future__ import annotations

import pytest

from modern_gl.application.bank import (
    OUT,
    SUPPLIER,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.inventory import IssueLine, ReceiptLine
from modern_gl.application.posting_preview import owned_postings, preview_postings
from tests.helpers.bank import usd_fee
from tests.helpers.conversion import sale


@pytest.fixture
def firm(bank_firm):
    return bank_firm


def counts(conn):
    return tuple(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("documents", "postings", "bank_operations", "audit_events")
    )


def pay_alfa(f) -> BankOperationInput:
    acc, v = f["acc"], f["v"]
    return BankOperationInput(
        doc_date="2026-03-05",
        direction=OUT,
        account_id=acc["51"],
        subconto=(v["azn"],),
        kind=SUPPLIER,
        counterparty_id=v["alfa"],
        lines=(BankLine(acc["60.1"], 118000, (None, v["contract"]), "MT001"),),
        memo="Оплата по счёту MT001",
    )


def test_a_new_payment_shows_its_postings_and_writes_nothing(ledger, firm):
    cid, before = firm["cid"], counts(ledger.conn)
    preview = preview_postings(
        ledger.conn,
        cid,
        "bank",
        lambda: [ledger.bank.save_bank_operation(cid, pay_alfa(firm), post=True)],
    )
    assert preview.error == ""
    [posting] = preview.postings
    assert posting.debit == "60.1" and posting.credit == "51"
    assert posting.debit_subconto == ("ALFA MMC", "Договор 1")
    assert posting.credit_subconto == ("Kapital AZN",)
    assert (posting.amount, posting.invoice) == (118000, "MT001")
    assert preview.total == 118000
    assert counts(ledger.conn) == before


def test_a_draft_shows_what_posting_would_make_and_stays_a_draft(ledger, firm):
    cid = firm["cid"]
    draft = ledger.bank.save_bank_operation(cid, pay_alfa(firm), post=False)
    assert owned_postings(ledger.conn, cid, "bank", [draft]) == []  # a draft has none
    before = counts(ledger.conn)
    preview = preview_postings(
        ledger.conn,
        cid,
        "bank",
        lambda: [ledger.bank.save_bank_operation(cid, pay_alfa(firm), draft, post=True)],
    )
    assert [(p.debit, p.credit, p.amount) for p in preview.postings] == [("60.1", "51", 118000)]
    assert counts(ledger.conn) == before
    assert load_bank_operation(ledger.conn, cid, draft).status == "draft"


def test_the_preview_is_what_is_posted(ledger, firm):
    cid = firm["cid"]
    preview = preview_postings(
        ledger.conn,
        cid,
        "bank",
        lambda: [ledger.bank.save_bank_operation(cid, usd_fee(firm), post=True)],
    )
    posted = ledger.bank.save_bank_operation(cid, usd_fee(firm), post=True)
    [fee] = owned_postings(ledger.conn, cid, "bank", [posted])
    assert preview.postings == [fee]
    assert (fee.debit, fee.credit, fee.amount) == ("91.2", "52", 340)  # 2.00 USD × 1.70
    assert (fee.currency, fee.currency_amount) == ("USD", 200)
    assert fee.debit_subconto == ("Комиссия банка",)


def test_what_would_not_post_says_why(ledger, firm):
    cid = firm["cid"]
    ledger.set_closed_through(cid, "2026-03-31")
    before = counts(ledger.conn)
    preview = preview_postings(
        ledger.conn,
        cid,
        "bank",
        lambda: [ledger.bank.save_bank_operation(cid, pay_alfa(firm), post=True)],
    )
    assert preview.postings == [] and "закрыт" in preview.error
    assert counts(ledger.conn) == before


def test_postings_of_another_company_are_not_read(ledger, firm):
    cid = firm["cid"]
    posted = ledger.bank.save_bank_operation(cid, pay_alfa(firm), post=True)
    other = ledger.create_company("ООО Другая")
    assert owned_postings(ledger.conn, other, "bank", [posted]) == []
    assert owned_postings(ledger.conn, cid, "conversion", [posted]) == []


def test_a_conversion_shows_its_postings_and_makes_no_items(ledger, conversion_firm):
    f = conversion_firm
    cid, before = f["cid"], counts(ledger.conn)
    values = ledger.conn.execute("SELECT COUNT(*) FROM subconto_values").fetchone()[0]
    preview = preview_postings(
        ledger.conn,
        cid,
        "conversion",
        lambda: [ledger.conversion.save_conversion(cid, sale(f), post=True)],
    )
    assert preview.error == ""
    assert sorted((p.debit, p.credit, p.amount) for p in preview.postings) == [
        ("51", "57", 169500),
        ("57", "52", 170000),
        ("91.2", "52", 340),
        ("91.2", "57", 500),
    ]
    assert preview.total == 340340
    assert counts(ledger.conn) == before
    # the items of the loss and the fee, made on first use, are undone with the rest
    assert ledger.conn.execute("SELECT COUNT(*) FROM subconto_values").fetchone()[0] == values


def stock(conn):
    return conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]


def test_a_purchase_and_an_issue_show_their_postings(inventory_demo, conn):
    demo = inventory_demo
    inv, cid = demo.inventory, demo.company_id

    def buy() -> list[int]:
        line = ReceiptLine(demo.item, demo.main, "2", "20")
        doc = inv.create_receipt_draft(
            cid, "2026-01-10", [line], demo.payable_account, [demo.supplier]
        )
        inv.post_document(cid, doc)
        return [doc]

    before = (counts(conn), stock(conn))
    [bought] = preview_postings(conn, cid, "inventory", buy).postings
    assert (bought.debit, bought.debit_subconto) == ("41", ("Товар A", "Основной"))
    assert (bought.credit, bought.credit_subconto, bought.amount) == ("60", ("Поставщик",), 2000)
    assert (counts(conn), stock(conn)) == before

    def issue() -> list[int]:
        line = IssueLine(demo.item, demo.main, "1", demo.expense_account)
        doc = inv.create_issue_draft(cid, "2026-01-12", [line])
        inv.post_document(cid, doc)
        return [doc]

    assert "недостаточно товара" in preview_postings(conn, cid, "inventory", issue).error
    buy()
    [issued] = preview_postings(conn, cid, "inventory", issue).postings
    assert (issued.debit, issued.credit, issued.amount) == ("46", "41", 1000)
    assert issued.credit_subconto == ("Товар A", "Основной")
