"""Measure the reports on a large company (debt 6, D24: «decide by measurements»).

    uv run python scripts/benchmark.py <folder> [--postings 100000]

Makes (once) `<folder>/big-<N>.gl`: the demo company plus N postings over the years
2024–2026 — purchases on e-qaimə from 300 suppliers, their payments, sales to 300
customers, expenses by cost item — and prints how long each report takes, slowest first.
Anything over ~0.3 s is a candidate for a background thread.

    uv run python scripts/benchmark.py <folder> --stock

Makes (once) `<folder>/stock-year.gl` — the demo year (D76: every module, a year of the
warehouse) — and times the warehouse's recalculation: the year's first document taken out
of the sequence and posted back (every later one recalculated each time), and the stock.
"""

from __future__ import annotations

import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from modern_gl.application.journal import JournalFilter, documents_before
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
    from modern_gl.reporting.cash_flow import cash_flow
    from modern_gl.reporting.columns import MONTHS, column_periods
    from modern_gl.reporting.profit_loss import profit_and_loss
    from modern_gl.reporting.statements import ACCOUNTS, balance_sheet

    conn = connect(path)
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    a60 = conn.execute("SELECT id FROM accounts WHERE company_id = ? AND code = '60'", (cid,))
    a60 = a60.fetchone()["id"]
    partner = conn.execute(  # a supplier of build(); the demo year has none: «не указано»
        "SELECT id FROM subconto_values WHERE company_id = ? AND name = 'Firma 000'", (cid,)
    ).fetchone()
    partner = partner["id"] if partner else None
    year = ("2026-01-01", "2026-12-31")
    months = column_periods(MONTHS, (date(2026, 1, 1), date(2026, 12, 31)))
    ends = [last for _, last in months[:-1]]
    cases = {
        "ОСВ, год": lambda: reports.trial_balance(conn, cid, *year),
        "Баланс по счетам": lambda: balance_sheet(conn, cid, year[1], detail=ACCOUNTS),
        "Баланс по месяцам (D107)": lambda: balance_sheet(
            conn, cid, year[1], detail=ACCOUNTS, days=ends
        ),
        "ОПиУ, год": lambda: profit_and_loss(conn, cid, *year, detail=ACCOUNTS),
        "ОПиУ по месяцам (D107)": lambda: profit_and_loss(
            conn, cid, *year, detail=ACCOUNTS, periods=months
        ),
        "Движение денег по месяцам (D107)": lambda: cash_flow(
            conn, cid, *year, detail=ACCOUNTS, periods=months
        ),
        "Карточка 60, год": lambda: reports.account_card(conn, cid, a60, *year),
        "Карточка 60 по контрагенту, год (долг 5)": lambda: reports.account_card(
            conn, cid, a60, *year, subconto=(partner,)
        ),
        "ОСВ по субконто 60, год": lambda: reports.subconto_balance(conn, cid, a60, *year),
        "Журнал: все документы": lambda: list_documents(conn, cid),
        "Журнал: год": lambda: list_documents(conn, cid, *year),
        "Журнал: порция года (страница, D-new-journal-paging)": lambda: documents_before(
            conn, JournalFilter(cid, *year), None
        ),
        "Журнал: поиск по году, не найдено": lambda: documents_before(
            conn, JournalFilter(cid, *year, "zzzz"), None
        ),
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


def measure_stock(path: Path) -> list[tuple[float, str]]:
    from modern_gl.application.inventory import Inventory
    from modern_gl.reporting.inventory.stock import stock_balances

    if not path.exists():
        from modern_gl.demo_year import create_year_demo

        conn = connect(path)
        create_year_demo(Ledger(conn))
        conn.close()
    conn = connect(path)
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    with transaction(conn):  # the demo year closes its first half: the whole year is open here
        conn.execute("UPDATE companies SET closed_through = NULL WHERE id = ?", (cid,))
    inv = Inventory(conn)
    docs = conn.execute(
        "SELECT id, doc_type FROM inventory_documents WHERE company_id = ? AND status = 'posted' "
        "ORDER BY doc_date, number",
        (cid,),
    ).fetchall()
    first = next(d["id"] for d in docs if d["doc_type"] != "opening")
    print(f"складских документов: {len(docs)}")
    timings = []
    for name, case in (
        (
            "Склад: отмена проведения первого (пересчёт всех)",
            lambda: inv.unpost_document(cid, first),
        ),
        ("Склад: проведение первого (пересчёт всех)", lambda: inv.post_document(cid, first)),
        ("Склад: остатки на конец года", lambda: stock_balances(conn, cid, "2026-12-31")),
    ):
        start = time.perf_counter()
        case()
        timings.append((time.perf_counter() - start, name))
    conn.close()
    return sorted(timings, reverse=True)


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    if "--stock" in sys.argv:
        for seconds, name in measure_stock(folder / "stock-year.gl"):
            mark = "  ← в фон?" if seconds > 0.3 else ""
            print(f"{seconds * 1000:9.0f} мс  {name}{mark}")
        return
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
