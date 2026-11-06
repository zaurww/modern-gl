from dataclasses import replace

from modern_gl.reporting.reports import (
    IFRS,
    TAX,
    account_analysis,
    account_card,
    subconto_balance,
    subconto_card,
    trial_balance,
)

FEB = ("2026-02-01", "2026-02-28")


def cols(row):
    return (
        row.opening_dt,
        row.opening_ct,
        row.turnover_dt,
        row.turnover_ct,
        row.closing_dt,
        row.closing_ct,
    )


def test_trial_balance_matches_hand_calculation(demo, conn):
    osv = trial_balance(conn, demo.company_id, *FEB)
    assert [(r.code, r.depth, cols(r)) for r in osv.rows] == [
        ("201", 0, (120000, 0, 50000, 30000, 140000, 0)),
        ("22", 0, (900000, 0, 200000, 200000, 900000, 0)),
        ("221", 1, (900000, 0, 0, 200000, 700000, 0)),
        ("222", 1, (0, 0, 200000, 0, 200000, 0)),
        ("301", 0, (0, 1000000, 0, 0, 0, 1000000)),
        ("531", 0, (0, 20000, 0, 50000, 0, 70000)),
        ("721", 0, (0, 0, 30000, 0, 30000, 0)),
    ]
    assert cols(osv.total) == (1020000, 1020000, 280000, 280000, 1070000, 1070000)


def test_trial_balance_totals_always_balance(demo, conn):
    for period in [("2026-01-01", "2026-01-31"), FEB, ("2025-01-01", "2026-12-31")]:
        t = trial_balance(conn, demo.company_id, *period).total
        assert t.opening_dt == t.opening_ct
        assert t.turnover_dt == t.turnover_ct
        assert t.closing_dt == t.closing_ct


def test_ap_account_balance_is_expanded_by_counterparty(demo, conn):
    led, cid = demo.ledger, demo.company_id
    # Pay supplier B 600 against a 500 invoice: B becomes a debit 100 (advance),
    # A stays a credit 200. Netting would wrongly show credit 100.
    led.post_new(cid, "2026-02-10", [demo.p("531", "221", "600", dt_sc=[demo.supplier_b])])
    row = {r.code: r for r in trial_balance(conn, cid, *FEB).rows}["531"]
    assert (row.closing_dt, row.closing_ct) == (10000, 20000)  # not netted into credit 100


def test_subconto_balance(demo, conn):
    rows = subconto_balance(conn, demo.company_id, "531", *FEB)
    assert [(r.name, cols(r)) for r in rows] == [
        ("Поставщик A", (0, 20000, 0, 0, 0, 20000)),
        ("Поставщик B", (0, 0, 0, 50000, 0, 50000)),
    ]


def test_account_card_with_running_balance(demo, conn):
    card = account_card(conn, demo.company_id, "221", *FEB)
    assert card.opening == 900000
    assert [(ln.doc_date, ln.corr_code, ln.debit, ln.credit, ln.balance) for ln in card.lines] == [
        ("2026-02-04", "222", 0, 200000, 700000),
    ]
    assert card.closing == 700000


def test_group_account_card_includes_subaccounts(demo, conn):
    card = account_card(conn, demo.company_id, "22", "2026-01-01", "2026-02-28")
    assert card.opening == 0
    assert card.closing == 900000
    assert [ln.corr_code for ln in card.lines] == ["301", "531", "221", "222"]


def test_account_analysis_by_correspondence(demo, conn):
    rows = account_analysis(conn, demo.company_id, "201", *FEB)
    assert [(r.corr_code, r.debit, r.credit) for r in rows] == [
        ("531", 50000, 0),
        ("721", 0, 30000),
    ]


def test_books_combine_layers_without_copying_common(demo, conn):
    led, cid = demo.ledger, demo.company_id
    led.post_new(cid, "2026-02-28", [demo.p("721", "201", "50")], layer="ifrs_adj")
    led.post_new(cid, "2026-02-28", [demo.p("721", "201", "80")], layer="tax_adj")

    def expense(layers):
        return {r.code: r for r in trial_balance(conn, cid, *FEB, layers).rows}["721"].closing_dt

    assert expense(("common",)) == 30000
    assert expense(IFRS) == 35000
    assert expense(TAX) == 38000
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 8


def test_cards_show_the_posting_memo_and_the_document_memo_without_one(demo, conn):
    """A document of several lines (a batch's expenses): each line says what it is; a line
    without a memo of its own shows the document's."""
    led, cid = demo.ledger, demo.company_id
    duty = replace(demo.p("222", "531", "10", ct_sc=[demo.supplier_b]), memo="Пошлина")
    freight = demo.p("222", "531", "20", ct_sc=[demo.supplier_b])
    led.post_new(cid, "2026-03-05", [duty, freight], "Расходы партии")
    march = ("2026-03-01", "2026-03-31")
    card = account_card(conn, cid, "222", *march)
    assert [(ln.memo, ln.debit) for ln in card.lines] == [
        ("Пошлина", 1000),
        ("Расходы партии", 2000),
    ]
    by_supplier = subconto_card(conn, cid, demo.supplier_b, *march)
    assert [(ln.memo, ln.credit) for ln in by_supplier.lines] == [
        ("Пошлина", 1000),
        ("Расходы партии", 2000),
    ]
