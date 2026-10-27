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
