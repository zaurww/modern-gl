"""Развороты ОСВ по месту (D-new-interactive-osv): one account's figures split by a
subconto, by the corresponding accounts or by months — and a row split again.

The demo books (tests/conftest.py build_demo), hand-calculated:
  1  05.01  Dt 221         Ct 301          10 000.00
  2  10.01  Dt 201         Ct 531 [A]       1 200.00
  3  15.01  Dt 531 [A]     Ct 221           1 000.00
  4  03.02  Dt 201         Ct 531 [B]         500.00
  5  04.02  Dt 222         Ct 221           2 000.00
  6  20.02  Dt 721         Ct 201             300.00

531 in February by counterparty:   A  opening Ct 200 (1 200 − 1 000), no turnover, Ct 200
                                   B  opening 0, Ct 500, closing Ct 500
531 in February by corr account:   201 — Ct 500 (turnovers only: a balance «with an
                                   account» means nothing)
531, the row of B, by corr:        201 — Ct 500
201 by months, January–February:   January  0 | 1 200 / 0 | 1 200
                                   February 1 200 | 500 / 300 | 1 400
22 (a group: 221 + 222) by corr in February: with 221 — Dt 2 000 (222 took it from
                                   221), with 222 — Ct 2 000
22 by months, January–February:    January  0 | 10 000 / 1 000 | 9 000
                                   February 9 000 | 2 000 / 2 000 | 9 000
221 and 222 by corr in February, in one query: 221 → {222: Ct 2 000}, 222 → {221: Dt 2 000}.
"""

from __future__ import annotations

import pytest

from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import expand_many, expand_rows

JAN_FEB = ("2026-01-01", "2026-02-28")
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


def test_an_account_by_its_first_subconto(demo, conn):
    rows = expand_rows(conn, demo.company_id, demo.acc["531"], *FEB, by="sc1")
    assert [(r.kind, r.value, r.name, cols(r)) for r in rows] == [
        ("sc1", demo.supplier_a, "Поставщик A", (0, 20000, 0, 0, 0, 20000)),
        ("sc1", demo.supplier_b, "Поставщик B", (0, 0, 0, 50000, 0, 50000)),
    ]


def test_an_account_by_its_corresponding_accounts_shows_turnovers_only(demo, conn):
    rows = expand_rows(conn, demo.company_id, demo.acc["531"], *FEB, by="corr")
    assert [(r.kind, r.value, r.code, r.name, cols(r)) for r in rows] == [
        ("corr", demo.acc["201"], "201", "Материалы", (0, 0, 0, 50000, 0, 0)),
    ]


def test_a_row_of_a_subconto_split_again_by_corr(demo, conn):
    rows = expand_rows(
        conn, demo.company_id, demo.acc["531"], *FEB, steps=[("sc1", demo.supplier_b)], by="corr"
    )
    assert [(r.code, cols(r)) for r in rows] == [("201", (0, 0, 0, 50000, 0, 0))]
    none = expand_rows(
        conn, demo.company_id, demo.acc["531"], *FEB, steps=[("sc1", demo.supplier_a)], by="corr"
    )
    assert none == []  # A did not move in February


def test_an_account_by_months_carries_the_balance(demo, conn):
    rows = expand_rows(conn, demo.company_id, demo.acc["201"], *JAN_FEB, by="month")
    assert [(r.value, r.name, cols(r)) for r in rows] == [
        ("2026-01", "январь 2026", (0, 0, 120000, 0, 120000, 0)),
        ("2026-02", "февраль 2026", (120000, 0, 50000, 30000, 140000, 0)),
    ]


def test_a_month_row_split_by_corr_is_that_month_only(demo, conn):
    rows = expand_rows(
        conn, demo.company_id, demo.acc["201"], *JAN_FEB, steps=[("month", "2026-02")], by="corr"
    )
    assert [(r.code, cols(r)) for r in rows] == [
        ("531", (0, 0, 50000, 0, 0, 0)),
        ("721", (0, 0, 0, 30000, 0, 0)),
    ]


def test_a_group_sums_its_subaccounts(demo, conn):
    by_corr = expand_rows(conn, demo.company_id, demo.acc["22"], *FEB, by="corr")
    assert [(r.code, cols(r)) for r in by_corr] == [
        ("221", (0, 0, 200000, 0, 0, 0)),
        ("222", (0, 0, 0, 200000, 0, 0)),
    ]
    by_month = expand_rows(conn, demo.company_id, demo.acc["22"], *JAN_FEB, by="month")
    assert [(r.value, cols(r)) for r in by_month] == [
        ("2026-01", (0, 0, 1000000, 100000, 900000, 0)),
        ("2026-02", (900000, 0, 200000, 200000, 900000, 0)),
    ]


def test_several_accounts_in_one_query(demo, conn):
    found = expand_many(conn, demo.company_id, [demo.acc["221"], demo.acc["222"]], *FEB, by="corr")
    assert {a: [(r.code, cols(r)) for r in rows] for a, rows in found.items()} == {
        demo.acc["221"]: [("222", (0, 0, 0, 200000, 0, 0))],
        demo.acc["222"]: [("221", (0, 0, 200000, 0, 0, 0))],
    }


def test_a_month_outside_the_period_and_an_unknown_kind_are_refused(demo, conn):
    with pytest.raises(ValidationError, match="вне периода"):
        expand_rows(
            conn, demo.company_id, demo.acc["201"], *FEB, steps=[("month", "2026-01")], by="corr"
        )
    with pytest.raises(ValidationError, match="вид разворота"):
        expand_rows(conn, demo.company_id, demo.acc["201"], *FEB, by="week")
