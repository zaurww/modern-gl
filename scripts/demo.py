"""Build a demo ledger in memory and print ОСВ, ОСВ по субконто and a card.

uv run python scripts/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.money import format_minor
from modern_gl.infrastructure.chart_csv import import_chart_csv
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.reports import IFRS, account_card, subconto_balance, trial_balance

CHART = Path(__file__).parent.parent / "examples" / "demo_chart.csv"


def money(v: int) -> str:
    return format_minor(v) if v else ""


def print_turnovers(title: str, rows, label) -> None:
    print(f"\n{title}")
    header = (
        "Сальдо нач. Дт",
        "Сальдо нач. Кт",
        "Оборот Дт",
        "Оборот Кт",
        "Сальдо кон. Дт",
        "Сальдо кон. Кт",
    )
    print(f"{'':34}" + "".join(f"{h:>16}" for h in header))
    for r in rows:
        values = (
            r.opening_dt,
            r.opening_ct,
            r.turnover_dt,
            r.turnover_ct,
            r.closing_dt,
            r.closing_ct,
        )
        print(f"{label(r):34.34}" + "".join(f"{money(v):>16}" for v in values))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    conn = connect(":memory:")
    led = Ledger(conn)
    cid = led.create_company("ДЕМО ООО")
    cp = led.add_subconto_kind(cid, "counterparty", "Контрагенты")
    ct = led.add_subconto_kind(cid, "contract", "Договоры")
    import_chart_csv(led, cid, CHART)
    alfa = led.add_subconto_value(cid, cp, "ДЕМО Поставщик Альфа")
    beta = led.add_subconto_value(cid, cp, "ДЕМО Поставщик Бета")
    c1 = led.add_subconto_value(cid, ct, "Договор №1")
    c2 = led.add_subconto_value(cid, ct, "Договор №2")
    a = {code: led.account_id(cid, code) for code in ("201", "221", "222", "301", "531", "721")}

    def p(dt, ct_, amount, dt_sc=(), ct_sc=()):
        return PostingInput(a[dt], a[ct_], amount, dt_sc, ct_sc)

    led.post_new(cid, "2026-01-05", [p("221", "301", "10000")], "Взнос в капитал")
    led.post_new(cid, "2026-01-10", [p("201", "531", "1200", ct_sc=[alfa, c1])], "Поступление")
    led.post_new(cid, "2026-01-15", [p("531", "221", "1000", dt_sc=[alfa, c1])], "Оплата")
    led.post_new(cid, "2026-02-03", [p("201", "531", "500", ct_sc=[beta, c2])], "Поступление")
    led.post_new(cid, "2026-02-10", [p("531", "221", "600", dt_sc=[beta, c2])], "Оплата")
    led.post_new(cid, "2026-02-04", [p("222", "221", "2000")], "Перевод")
    led.post_new(cid, "2026-02-20", [p("721", "201", "300")], "Списание")
    led.post_new(cid, "2026-02-28", [p("721", "201", "50")], "МСФО корр.", layer="ifrs_adj")

    period = ("2026-02-01", "2026-02-28")
    osv = trial_balance(conn, cid, *period)
    print_turnovers(
        "ОСВ за февраль 2026, книга COMMON",
        [*osv.rows, osv.total],
        lambda r: f"{'  ' * r.depth}{r.code} {r.name}" if hasattr(r, "code") else "Итого",
    )
    osv = trial_balance(conn, cid, *period, IFRS)
    print_turnovers(
        "ОСВ за февраль 2026, книга IFRS = common + ifrs_adj",
        [*osv.rows, osv.total],
        lambda r: f"{'  ' * r.depth}{r.code} {r.name}" if hasattr(r, "code") else "Итого",
    )
    print_turnovers(
        "ОСВ по субконто: счёт 531 / Контрагенты",
        subconto_balance(conn, cid, "531", *period),
        lambda r: r.name,
    )

    card = account_card(conn, cid, "221", *period)
    print(f"\nКарточка счёта 221, сальдо на начало {format_minor(card.opening)}")
    for ln in card.lines:
        print(
            f"  {ln.doc_date}  №{ln.number:<4} {ln.memo:<18} корр. {ln.corr_code:<5}"
            f"{money(ln.debit):>12}{money(ln.credit):>12}{format_minor(ln.balance):>14}"
        )
    print(f"Сальдо на конец {format_minor(card.closing)}")


if __name__ == "__main__":
    main()
