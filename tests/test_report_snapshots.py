"""Snapshots of the reports on the golden example (syrupy): the ОСВ, the card and the
analysis of an account, the balance sheet, the profit and loss and the hledger journal
as stable JSON / text in `tests/__snapshots__/`. A change of a report's figures or
shape is seen in the diff of the snapshot; `pytest --snapshot-update` accepts it.

The ОСВ of February 2026 is hand-calculated in the docstring of `tests/conftest.py`:
`test_osv_matches_the_hand_calculation` ties the snapshot to those figures.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension

from modern_gl.reporting.plaintext import hledger_journal
from modern_gl.reporting.profit_loss import profit_and_loss
from modern_gl.reporting.reports.card import account_analysis, account_card
from modern_gl.reporting.reports.osv import trial_balance
from modern_gl.reporting.statements import ACCOUNTS, balance_sheet
from tests.conftest import Demo

FEBRUARY = ("2026-02-01", "2026-02-28")


def plain(value: Any) -> Any:
    """Dataclasses, tuples and int keys as JSON holds them."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


@pytest.fixture
def json_snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


def test_osv(demo: Demo, json_snapshot: SnapshotAssertion) -> None:
    osv = trial_balance(demo.ledger.conn, demo.company_id, *FEBRUARY)
    assert plain(osv) == json_snapshot


def test_osv_matches_the_hand_calculation(demo: Demo) -> None:
    """The figures of the conftest docstring (minor units): opening, turnover, closing."""
    osv = trial_balance(demo.ledger.conn, demo.company_id, *FEBRUARY)
    by_code = {r.code: r for r in osv.rows if not r.subconto}
    expected = {
        "201": (120_000, 0, 50_000, 30_000, 140_000, 0),
        "22": (900_000, 0, 200_000, 200_000, 900_000, 0),
        "221": (900_000, 0, 0, 200_000, 700_000, 0),
        "222": (0, 0, 200_000, 0, 200_000, 0),
        "301": (0, 1_000_000, 0, 0, 0, 1_000_000),
        "531": (0, 20_000, 0, 50_000, 0, 70_000),
        "721": (0, 0, 30_000, 0, 30_000, 0),
    }
    for code, figures in expected.items():
        r = by_code[code]
        assert (
            r.opening_dt,
            r.opening_ct,
            r.turnover_dt,
            r.turnover_ct,
            r.closing_dt,
            r.closing_ct,
        ) == figures, code
    t = osv.total
    assert (t.opening_dt, t.opening_ct) == (1_020_000, 1_020_000)
    assert (t.turnover_dt, t.turnover_ct) == (280_000, 280_000)
    assert (t.closing_dt, t.closing_ct) == (1_070_000, 1_070_000)


def test_account_card(demo: Demo, json_snapshot: SnapshotAssertion) -> None:
    conn, cid = demo.ledger.conn, demo.company_id
    assert plain(account_card(conn, cid, "221", *FEBRUARY)) == json_snapshot
    assert plain(account_card(conn, cid, "531", *FEBRUARY)) == json_snapshot


def test_account_analysis(demo: Demo, json_snapshot: SnapshotAssertion) -> None:
    conn, cid = demo.ledger.conn, demo.company_id
    assert plain(account_analysis(conn, cid, "201", *FEBRUARY)) == json_snapshot
    assert plain(account_analysis(conn, cid, "22", *FEBRUARY)) == json_snapshot


def test_balance_sheet(demo: Demo, json_snapshot: SnapshotAssertion) -> None:
    conn, cid = demo.ledger.conn, demo.company_id
    assert plain(balance_sheet(conn, cid, FEBRUARY[1])) == json_snapshot
    assert plain(balance_sheet(conn, cid, FEBRUARY[1], detail=ACCOUNTS)) == json_snapshot


def test_profit_and_loss(demo: Demo, json_snapshot: SnapshotAssertion) -> None:
    conn, cid = demo.ledger.conn, demo.company_id
    assert plain(profit_and_loss(conn, cid, *FEBRUARY)) == json_snapshot
    assert plain(profit_and_loss(conn, cid, *FEBRUARY, detail=ACCOUNTS)) == json_snapshot


def test_hledger_journal(demo: Demo, snapshot: SnapshotAssertion) -> None:
    conn, cid = demo.ledger.conn, demo.company_id
    assert hledger_journal(conn, cid, FEBRUARY[1], generated="2026-03-01") == snapshot
