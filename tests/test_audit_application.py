"""The audit of the `application` layer (session 2026-10-27): a getter has no side
effect, one function fills subconto by kind, the reference map is read once, errors keep
their taxonomy, a posting is one record."""

from __future__ import annotations

from modern_gl.application.queries import parallel_books


def test_a_document_in_an_adjustment_layer_shows_the_books_but_reading_a_layer_does_not(demo):
    led, cid = demo.ledger, demo.company_id
    assert not parallel_books(led.conn, cid)
    assert led._layer_id(cid, "ifrs_adj") > 0  # a lookup writes nothing
    assert not parallel_books(led.conn, cid)
    led.create_draft(cid, "2026-02-28", [demo.p("721", "201", "50")], layer="ifrs_adj")
    assert parallel_books(led.conn, cid)


def test_a_posted_document_in_an_adjustment_layer_shows_the_books(demo):
    led, cid = demo.ledger, demo.company_id
    led.post_new(cid, "2026-02-28", [demo.p("721", "201", "50")], layer="tax_adj")
    assert parallel_books(led.conn, cid)


def test_a_draft_moved_into_an_adjustment_layer_shows_the_books(demo):
    led, cid = demo.ledger, demo.company_id
    doc = led.create_draft(cid, "2026-02-28", [demo.p("721", "201", "50")])
    assert not parallel_books(led.conn, cid)
    led.update_draft(cid, doc, "2026-02-28", [demo.p("721", "201", "50")], layer="tax_adj")
    assert parallel_books(led.conn, cid)


# ---- one rule: the account's subconto filled by kind ---------------------------------


def _account(*kinds: int | None) -> dict:
    return {"sc1_kind_id": kinds[0], "sc2_kind_id": kinds[1], "sc3_kind_id": kinds[2]}


def test_fill_subconto_puts_each_element_at_the_position_of_its_kind():
    from modern_gl.application.common import fill_subconto

    counterparty, contract = 7, 9  # kinds
    account = _account(counterparty, contract, None)  # 60.1: counterparty, contract
    assert fill_subconto(account, {counterparty: 41, contract: 52}) == (41, 52, None)
    assert fill_subconto(account, {counterparty: 41}) == (41, None, None)
    assert fill_subconto(account, {contract: 52, 99: 3}) == (None, 52, None)  # unknown kind
    assert fill_subconto(_account(None, None, None), {counterparty: 41}) == (None, None, None)


def test_fill_subconto_keeps_what_was_typed_and_fills_only_the_empty_positions():
    from modern_gl.application.common import fill_subconto

    counterparty, contract = 7, 9
    account = _account(contract, counterparty, None)
    typed = (52,)  # the contract typed, the counterparty from the operation
    assert fill_subconto(account, {counterparty: 41}, keep=typed) == (52, 41, None)
    typed = (52, 43)  # a counterparty typed by hand wins over the operation's
    assert fill_subconto(account, {counterparty: 41}, keep=typed) == (52, 43, None)
    assert fill_subconto(account, {}, keep=(None, None, 5)) == (None, None, 5)


def test_fill_subconto_refuses_more_than_three_typed_values():
    import pytest

    from modern_gl.application.common import fill_subconto
    from modern_gl.domain.errors import ValidationError

    with pytest.raises(ValidationError, match="больше 3 субконто"):
        fill_subconto(_account(1, 2, 3), {}, keep=(1, 2, 3, 4))


# ---- the map of references is read once ----------------------------------------------


def test_where_used_reads_the_schema_once_per_process(demo, monkeypatch):
    from modern_gl.application import common
    from modern_gl.infrastructure import db

    calls = []
    read = db.foreign_key_columns
    monkeypatch.setattr(
        common.db, "foreign_key_columns", lambda c, t: calls.append(t) or read(c, t)
    )
    common._REFERENCES.clear()
    led, cid = demo.ledger, demo.company_id
    assert common.where_used(led.conn, cid, "subconto_values", demo.supplier_a) is not None
    scanned = len(calls)
    assert scanned > 0
    assert common.where_used(led.conn, cid, "subconto_values", demo.supplier_b) is not None
    assert common.where_used(led.conn, cid, "accounts", demo.acc["301"]) is not None
    assert len(calls) == scanned, "the foreign keys were read again"


# ---- one taxonomy of errors ------------------------------------------------------------


def test_a_missing_bank_operation_or_conversion_is_not_found(demo):
    import pytest

    from modern_gl.domain.errors import NotFoundError

    led, cid = demo.ledger, demo.company_id
    with pytest.raises(NotFoundError, match="документ 999 не найден"):
        led.bank.delete_bank_operation(cid, 999)
    with pytest.raises(NotFoundError, match="документ 999 не найден"):
        led.conversion.delete_conversion(cid, 999)


def test_a_line_of_a_wrong_shape_is_a_format_error(demo):
    import pytest

    from modern_gl.application.catalog import Catalog
    from modern_gl.application.exchange import FormatError
    from modern_gl.application.exchange.lines import posting_lines

    cat = Catalog(demo.ledger.conn, demo.company_id)
    with pytest.raises(FormatError, match="нет проводок"):
        posting_lines(cat, [])
    with pytest.raises(FormatError, match="строка 1: ожидается объект"):
        posting_lines(cat, ["221"])
    with pytest.raises(FormatError, match="строка 1: лишние поля"):
        posting_lines(cat, [{"debit": "221", "credit": "301", "amount": "1", "x": 1}])
    with pytest.raises(FormatError, match="сумма — строкой"):
        posting_lines(cat, [{"debit": "221", "credit": "301", "amount": 1.5}])
    with pytest.raises(FormatError, match="pays_vat"):
        posting_lines(cat, [{"debit": "221", "credit": "301", "amount": "1", "pays_vat": 1}])
    with pytest.raises(FormatError, match="субконто — списком"):
        posting_lines(
            cat, [{"debit": "221", "credit": "301", "amount": "1", "debit_subconto": "x"}]
        )
    with pytest.raises(FormatError, match="у счёта 221 субконто"):
        posting_lines(
            cat, [{"debit": "221", "credit": "301", "amount": "1", "debit_subconto": ["x"]}]
        )
    assert issubclass(FormatError, ValueError)  # whoever caught ValueError still does


def test_a_payment_without_a_counterparty_is_one_line(demo):
    from modern_gl.application.bank.advances import payment_lines
    from modern_gl.application.bank.operations import OUT

    lines = payment_lines(
        demo.ledger.conn,
        demo.company_id,
        account_id=demo.acc["531"],
        account_type="payable",
        subconto=(),
        counterparty_id=None,
        amount=12_000,
        direction=OUT,
        day="2026-03-01",
        invoices=(("A-1", 5_000), ("A-2", 5_000)),
    )
    assert [(x.account_id, x.amount, x.invoice) for x in lines] == [(demo.acc["531"], 12_000, "")]


# ---- a posting is one record -------------------------------------------------------------


def test_a_column_of_a_posting_is_added_in_one_place(conn):
    """`PostingRecord.COLUMNS` is the table's content, in its order, and the fields of the
    record: the insert, the storno, the comparison and the snapshot all follow it."""
    from dataclasses import fields

    from modern_gl.application.ledger.posting_record import (
        INSERT_POSTING,
        KEY_COLUMNS,
        PostingRecord,
    )

    table = [r["name"] for r in conn.execute("PRAGMA table_info(postings)")]
    assert tuple(c for c in table if c not in KEY_COLUMNS) == PostingRecord.COLUMNS
    assert tuple(f.name for f in fields(PostingRecord)) == PostingRecord.COLUMNS
    assert all(column in INSERT_POSTING for column in PostingRecord.COLUMNS)


def test_a_storno_negates_the_record_and_keeps_the_rest(demo):
    from modern_gl.application.ledger.inputs import PostingInput
    from modern_gl.application.ledger.posting_record import PostingRecord

    led, cid = demo.ledger, demo.company_id
    usd = led._currency(cid, "USD")["id"]
    led.set_rate(cid, usd, "2026-03-01", 1_700_000)
    bank = led.add_account(cid, "223", "Валютный счёт", parent="22", currency=True)
    line = PostingInput(demo.acc["201"], bank, "170.00", (), (), "по счёту", usd, "100")
    record = PostingRecord.from_input(line, 1)
    assert record.params() == (
        demo.acc["201"], bank, 17_000, None, None, None,
        None, None, None, "по счёту", usd, 10_000, None, None, 0,
    )  # fmt: skip
    assert record.negated().params()[2] == -17_000
    assert record.negated().params()[11] == -10_000
    assert record.negated().memo == "по счёту"
    doc = led.post_new(cid, "2026-03-01", [line])
    storno = led.reverse(cid, doc, "2026-03-02")
    stored = [
        PostingRecord.from_row(r)
        for r in led.conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (storno,)
        )
    ]
    assert stored == [record.negated()]


# ---- no query a document in a loop ---------------------------------------------------------


def test_bank_operations_are_read_in_parts_as_one_by_one(monkeypatch):
    from modern_gl.application import common
    from modern_gl.application.bank import operations
    from modern_gl.application.ledger import Ledger
    from modern_gl.demo_year import create_year_demo
    from modern_gl.infrastructure.db import connect

    conn = connect(":memory:")
    cid = create_year_demo(Ledger(conn))
    ids = [r[0] for r in conn.execute("SELECT id FROM bank_operations ORDER BY id DESC")]
    monkeypatch.setattr(common, "BATCH", 7)  # parts of 7: the seams are read too
    monkeypatch.setattr(operations, "batches", lambda items: common.batches(items, common.BATCH))
    together = operations.load_bank_operations(conn, cid, [*ids, -1])
    assert -1 not in together and len(together) == len(ids)
    assert all(together[i] == operations.load_bank_operation(conn, cid, i) for i in ids[:40])
    conn.close()


def test_an_operation_on_an_unknown_account_or_moved_unknown_is_not_found(demo):
    import pytest

    from modern_gl.application.bank.operations import OUT, BankLine, BankOperationInput
    from modern_gl.domain.errors import NotFoundError

    led, cid = demo.ledger, demo.company_id
    data = BankOperationInput(
        doc_date="2026-03-01",
        direction=OUT,
        account_id=demo.acc["221"],
        kind="other",
        lines=(BankLine(demo.acc["721"], 1_000), BankLine(99_999, 500)),
    )
    with pytest.raises(NotFoundError, match="счёт не найден"):
        led.bank.save_bank_operation(cid, data, post=False)
    with pytest.raises(NotFoundError, match="документ 999 не найден"):
        led.bank.move_bank_operations(cid, [999], demo.acc["222"], ())


# ---- a receipt's header is one value ----------------------------------------------------------


def test_a_receipt_posted_from_its_header_posts_as_with_the_arguments(ledger, conn):
    """10 pcs for 120.00 with 18% VAT 21.60: Dr 41 120.00 and Dr 18 21.60 / Cr 60 —
    the same whether the header is one value or a dozen arguments."""
    from modern_gl.application.inventory import Inventory, ReceiptHeader, ReceiptLine

    cid = ledger.create_company("Склад")
    item_kind = ledger.add_subconto_kind(cid, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    stock = ledger.add_account(cid, "41", "Товары", subconto=[item_kind, warehouse_kind])
    payable = ledger.add_account(cid, "60", "Поставщики", account_class="liability")
    vat = ledger.add_account(cid, "18", "НДС к возмещению", account_class="asset")
    from modern_gl.domain.accounts import INPUT_VAT

    ledger.set_account_role(cid, INPUT_VAT, vat)
    inventory = Inventory(conn, actor="test", ledger=ledger)
    unit = inventory.add_unit(cid, "шт", "Штука", precision=0)
    item = inventory.add_item(cid, "Бумага", unit, stock)
    main = inventory.add_warehouse(cid, "Основной")
    line = ReceiptLine(item, main, "10", "120.00", vat_amount="21.60")
    header = ReceiptHeader("2026-01-10", payable, (), "Покупка", vat_rate=1800, invoice="MT1")
    assert header.doc_type == "receipt"
    by_header = inventory.post_new_receipt(cid, header, [line])
    by_arguments = inventory.post_receipt(
        cid, "2026-01-10", [line], payable, (), "Покупка", vat_rate=1800, invoice="MT1"
    )

    def postings(inventory_id: int) -> list[tuple]:
        gl = conn.execute(
            "SELECT gl_document_id FROM inventory_documents WHERE id = ?", (inventory_id,)
        ).fetchone()[0]
        return [
            (r["debit_account_id"], r["credit_account_id"], r["amount"], r["invoice"])
            for r in conn.execute(
                "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl,)
            )
        ]

    assert postings(by_header) == [(stock, payable, 12_000, "MT1"), (vat, payable, 2_160, "MT1")]
    assert postings(by_arguments) == postings(by_header)
    assert ReceiptHeader("2026-01-10", payable, opening=True).doc_type == "opening"
    assert ReceiptHeader("2026-01-10", None, incoming_reason="gift").doc_type == "incoming"
