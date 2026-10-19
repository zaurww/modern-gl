"""Build a demo ledger in memory and print ОСВ, ОСВ по субконто and a card.

uv run python scripts/demo.py
"""

from __future__ import annotations

import sys

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.money import format_minor
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.reports import IFRS, account_card, subconto_balance, trial_balance


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
    apply_chart_template(led, cid, "1c77")

    def value(kind: str, name: str) -> int:
        return led.add_subconto_value(cid, led.subconto_kind_id(cid, kind), name)

    alfa, beta = value("counterparty", "Поставщик Альфа"), value("counterparty", "Поставщик Бета")
    founder = value("counterparty", "Учредитель")
    c1, c2 = value("contract", "Договор №1"), value("contract", "Договор №2")
    bank = value("bank_account", "Основной расчётный счёт")
    paper = value("item", "Бумага офисная")
    store = value("warehouse", "Основной склад")
    materials = value("cost_item", "Материальные расходы")

    def p(dt, ct, amount, dt_sc=(), ct_sc=()):
        return PostingInput(led.account_id(cid, dt), led.account_id(cid, ct), amount, dt_sc, ct_sc)

    led.post_new(cid, "2026-01-05", [p("51", "80", "10000", [bank], [founder])], "Взнос в УК")
    led.post_new(
        cid, "2026-01-10", [p("10.1", "60.1", "1200", [paper, store], [alfa, c1])], "Поступление"
    )
    led.post_new(cid, "2026-01-15", [p("60.1", "51", "1000", [alfa, c1], [bank])], "Оплата")
    led.post_new(
        cid, "2026-02-03", [p("10.1", "60.1", "500", [paper, store], [beta, c2])], "Поступление"
    )
    led.post_new(cid, "2026-02-10", [p("60.1", "51", "600", [beta, c2], [bank])], "Оплата")
    led.post_new(cid, "2026-02-04", [p("50", "51", "2000", [], [bank])], "Снятие в кассу")
    led.post_new(
        cid, "2026-02-20", [p("26", "10.1", "300", [materials], [paper, store])], "Списание"
    )
    led.post_new(
        cid,
        "2026-02-28",
        [p("26", "10.1", "50", [materials], [paper, store])],
        "МСФО корр.",
        layer="ifrs_adj",
    )

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
        "ОСВ по субконто: счёт 60 / Контрагенты",
        subconto_balance(conn, cid, "60.1", *period),
        lambda r: r.name,
    )

    card = account_card(conn, cid, "51", *period)
    print(f"\nКарточка счёта 51, сальдо на начало {format_minor(card.opening)}")
    for ln in card.lines:
        print(
            f"  {ln.doc_date}  №{ln.number:<4} {ln.memo:<18} корр. {ln.corr_code:<5}"
            f"{money(ln.debit):>12}{money(ln.credit):>12}{format_minor(ln.balance):>14}"
        )
    print(f"Сальдо на конец {format_minor(card.closing)}")


if __name__ == "__main__":
    main()
