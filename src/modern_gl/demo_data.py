"""A small demo company on the 1C 7.7 chart — for screenshots, demos and trying the UI."""

from __future__ import annotations

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.i18n import tr
from modern_gl.infrastructure.chart_csv import apply_chart_template


def create_demo_company(ledger: Ledger, name: str | None = None) -> int:
    cid = ledger.create_company(name or tr("ДЕМО ООО"))
    apply_chart_template(ledger, cid, "1c77")

    def value(kind: str, title: str) -> int:
        return ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), title)

    alfa = value("counterparty", tr("Альфа Трейд"))
    beta = value("counterparty", tr("Бета Сервис"))
    founder = value("counterparty", tr("Учредитель"))
    c1, c2 = value("contract", tr("Договор поставки №1")), value("contract", tr("Договор №7-У"))
    bank = value("bank_account", tr("Основной расчётный счёт"))
    paper = value("item", tr("Бумага офисная А4"))
    store = value("warehouse", tr("Основной склад"))
    materials = value("cost_item", tr("Материальные расходы"))
    rent = value("cost_item", tr("Аренда офиса"))
    employee = value("employee", tr("Мамедов Р."))

    def p(dt, ct, amount, dt_sc=(), ct_sc=(), memo=""):
        return PostingInput(
            ledger.account_id(cid, dt), ledger.account_id(cid, ct), amount, dt_sc, ct_sc, memo
        )

    post = ledger.post_new
    post(
        cid,
        "2026-01-05",
        [p("51", "80", "10000", [bank], [founder])],
        tr("Взнос в уставный капитал"),
    )
    post(
        cid,
        "2026-01-10",
        [p("10.1", "60.1", "1200", [paper, store], [alfa, c1])],
        tr("Поступление материалов"),
    )
    post(cid, "2026-01-15", [p("60.1", "51", "1000", [alfa, c1], [bank])], tr("Оплата поставщику"))
    post(
        cid,
        "2026-02-03",
        [p("10.1", "60.1", "500", [paper, store], [beta, c2])],
        tr("Поступление материалов"),
    )
    post(cid, "2026-02-04", [p("50", "51", "2000", [], [bank])], tr("Снятие наличных в кассу"))
    post(cid, "2026-02-10", [p("60.1", "51", "600", [beta, c2], [bank])], tr("Оплата поставщику"))
    post(cid, "2026-02-12", [p("71", "50", "300", [employee], [])], tr("Выдано под отчёт"))
    post(
        cid,
        "2026-02-14",
        [
            p("26", "71", "250", [rent], [employee], tr("Аренда за февраль")),
            p("50", "71", "50", [], [employee], tr("Возврат остатка")),
        ],
        tr("Авансовый отчёт"),
    )
    post(
        cid,
        "2026-02-20",
        [p("26", "10.1", "300", [materials], [paper, store])],
        tr("Списание материалов"),
    )
    post(
        cid,
        "2026-02-28",
        [p("26", "10.1", "50", [materials], [paper, store])],
        tr("Корректировка оценки запасов"),
        layer="ifrs_adj",
    )
    ledger.create_draft(
        cid, "2026-02-28", [p("26", "60.1", "400", [rent], [alfa, c1])], tr("Аренда за март")
    )
    return cid
