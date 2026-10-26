"""A company file of this program's schema, kept for the upgrade test (D-new1).

    uv run python scripts/upgrade_fixture.py tests/fixtures/upgrade

Writes `schema_NNNN.gl.xz` — the year demo (every module, the whole year 2026) — and
`schema_NNNN.json` — what this program reports from it: the trial balance of every
account (by first subconto and currency too) and the raw sums of the postings.
`tests/test_upgrade_fixtures.py` opens each file with the current program and expects the
same numbers. Run it on the commit of each release whose schema users may hold; the
script uses only what every version since schema 0049 has, so it runs on older
commits too (`git worktree add <dir> <commit>`, then this script from there).
"""

from __future__ import annotations

import json
import lzma
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from modern_gl.application.ledger import Ledger
from modern_gl.demo_year import create_year_demo
from modern_gl.i18n import DEFAULT, set_language
from modern_gl.infrastructure.db import close, connect, schema_version
from modern_gl.reporting.reports import trial_balance

PERIOD = ("2026-01-01", "2026-12-31")
MONEY = ("opening_dt", "opening_ct", "turnover_dt", "turnover_ct", "closing_dt", "closing_ct")


def money(row: object) -> list[int]:
    values = asdict(row)  # type: ignore[call-overload]
    return [values[k] for k in MONEY]


def expected(conn: sqlite3.Connection, company_id: int) -> dict[str, object]:
    """What a program reports from the file: equal before and after an update."""
    osv = trial_balance(conn, company_id, *PERIOD)
    return {
        "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "postings": conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0],
        "posting_sums": [
            list(r)
            for r in conn.execute(
                "SELECT debit_account_id, credit_account_id, COUNT(*), SUM(amount), "
                "SUM(COALESCE(currency_amount, 0)) FROM postings "
                "GROUP BY debit_account_id, credit_account_id "
                "ORDER BY debit_account_id, credit_account_id"
            )
        ],
        "osv": [[r.account_id, list(r.subconto), *money(r)] for r in osv.rows],
        "osv_total": money(osv.total),
        "osv_subconto": {
            str(account): [[r.value_id, *money(r)] for r in rows]
            for account, rows in sorted(osv.subconto.items())
        },
        "osv_currency": {
            str(account): [[asdict(r).get("code", ""), *money(r)] for r in rows]
            for account, rows in sorted(osv.currency.items())
        },
    }


def main(folder: Path) -> Path:
    set_language(DEFAULT)  # the texts of the postings: a rebuild in another one rewrites them
    folder.mkdir(parents=True, exist_ok=True)
    work = folder / "building.gl"
    work.unlink(missing_ok=True)
    conn = connect(work)
    company_id = create_year_demo(Ledger(conn))
    version = schema_version(conn)
    data = {"schema": version, "company_id": company_id, **expected(conn, company_id)}
    close(conn)
    plain = sqlite3.connect(work, isolation_level=None)
    plain.execute("PRAGMA journal_mode = DELETE")  # one file, as it is handed over
    plain.execute("VACUUM")
    plain.close()
    target = folder / f"schema_{version:04d}.gl.xz"
    target.write_bytes(lzma.compress(work.read_bytes(), preset=9))
    work.unlink()
    text = json.dumps(data, ensure_ascii=False, indent=0)
    (folder / f"schema_{version:04d}.json").write_text(text + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/upgrade")))
