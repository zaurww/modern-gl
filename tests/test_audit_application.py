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
