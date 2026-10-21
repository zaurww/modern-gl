"""Parallel books (IFRS, tax) are turned on per company (D63)."""

from __future__ import annotations

import pytest

from modern_gl.application.queries import parallel_books
from modern_gl.domain.errors import ValidationError


def test_a_new_company_keeps_one_book(ledger):
    cid = ledger.create_company("Firma")
    assert not parallel_books(ledger.conn, cid)
    ledger.set_parallel_books(cid, True)
    assert parallel_books(ledger.conn, cid)
    ledger.set_parallel_books(cid, False)
    assert not parallel_books(ledger.conn, cid)


def test_a_document_in_an_adjustment_layer_turns_the_books_on(demo):
    led, cid = demo.ledger, demo.company_id
    assert not parallel_books(led.conn, cid)  # the demo posts in the common layer only
    led.create_draft(cid, "2026-02-28", [demo.p("721", "201", "50")], layer="tax_adj")
    assert parallel_books(led.conn, cid)
    with pytest.raises(ValidationError, match="есть документы"):
        led.set_parallel_books(cid, False)
    assert parallel_books(led.conn, cid)
