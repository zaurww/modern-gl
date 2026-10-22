"""Measure the reports on a large company (debt 6, D24: «decide by measurements»).

    uv run python scripts/benchmark.py <folder> [--postings 100000]

Makes (once) `<folder>/big-<N>.gl`: the demo company plus N postings over the years
2024–2026 — purchases on e-qaimə from 300 suppliers, their payments, sales to 300
customers, expenses by cost item — and prints how long each report takes, slowest first.
Anything over ~0.3 s is a candidate for a background thread.
"""

from __future__ import annotations

import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import find_documents, list_documents
from modern_gl.demo_data import create_demo_company
from modern_gl.infrastructure.db import connect, transaction

DAYS = (date(2026, 12, 31) - date(2024, 1, 1)).days
PARTNERS = 300


def build(path: Path, postings: int) -> None:
    conn = connect(path)
    led = Ledger(conn)
    cid = create_demo_company(led)
    rnd = random.Random(38)
    acc = {code: led.account_id(cid, code) for code in ("26", "51", "60", "62", "90", "46")}
    kind = {
        r["code"]: r["id"]
        for r in conn.execute("SELECT id, code FROM subconto_kinds WHERE company_id = ?", (cid,))
    }
    bank = conn.execute(
        "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ?",
        (cid, kind["bank_account"]),
    ).fetchone()["id"]
    item = conn.execute(
        "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ? LIMIT 1",
        (cid, kind["cost_item"]),
    ).fetchone()["id"]
    with transaction(conn):
        partners = [
            led.add_subconto_value(cid, kind["counterparty"], f"Firma {i:03}")
            for i in range(PARTNERS)
        ]
        made = 0
        while made < postings:
            day = date(2024, 1, 1) + timedelta(days=rnd.randrange(DAYS))
            who = rnd.choice(partners)
            amount = f"{rnd.randrange(1000, 500000) / 100:.2f}"
            invoice = f"MT{day:%y%m}{rnd.randrange(10**6):06}"
            lines = [
                PostingInput(acc["26"], acc["60"], amount, (item,), (who,), invoice=invoice),
                PostingInput(acc["60"], acc["51"], amount, (who,), (bank,), invoice=invoice),
            ]
            for line in lines:
                led.post_new(cid, day, [line], "Gen")
            made += len(lines)
    conn.close()


def measure(path: Path) -> list[tuple[float, str]]:
    import modern_gl.desktop.main_window  # noqa: F401  modules add their rows of «Bu gün»
    from modern_gl.application.bank import bank_places, bank_statements
    from modern_gl.reporting import invoices, overview, reports

    conn = connect(path)
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    a60 = conn.execute("SELECT id FROM accounts WHERE company_id = ? AND code = '60'", (cid,))
    a60 = a60.fetchone()["id"]
    year = ("2026-01-01", "2026-12-31")
    cases = {
        "ОСВ, год": lambda: reports.trial_balance(conn, cid, *year),
        "Карточка 60, год": lambda: reports.account_card(conn, cid, a60, *year),
        "ОСВ по субконто 60, год": lambda: reports.subconto_balance(conn, cid, a60, *year),
        "Журнал: все документы": lambda: list_documents(conn, cid),
        "Журнал: год": lambda: list_documents(conn, cid, *year),
        "E-qaimə, год": lambda: invoices.invoice_report(conn, cid, *year),
        "E-qaimə неоплаченные": lambda: invoices.invoice_report(conn, cid, *year, open_only=True),
        "Банк: все выписки": lambda: [
            bank_statements(conn, cid, p) for p in bank_places(conn, cid)
        ],
        "«Bu gün»": lambda: overview.attention(conn, cid, year[1]),
        "Ctrl+K: документ не найден": lambda: find_documents(conn, cid, "zzzz"),
    }
    timings = []
    for name, case in cases.items():
        start = time.perf_counter()
        case()
        timings.append((time.perf_counter() - start, name))
    conn.close()
    return sorted(timings, reverse=True)


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    postings = (
        int(sys.argv[sys.argv.index("--postings") + 1]) if "--postings" in sys.argv else 100_000
    )
    path = folder / f"big-{postings}.gl"
    if not path.exists():
        start = time.perf_counter()
        build(path, postings)
        print(f"создано {postings} проводок за {time.perf_counter() - start:.0f} с: {path}")
    for seconds, name in measure(path):
        mark = "  ← в фон?" if seconds > 0.3 else ""
        print(f"{seconds * 1000:9.0f} мс  {name}{mark}")


if __name__ == "__main__":
    main()
