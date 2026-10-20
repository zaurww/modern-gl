"""A small demo company on the classic chart — for screenshots, demos and trying the UI."""

from __future__ import annotations

from modern_gl.application.inventory import Inventory, IssueLine, ReceiptLine
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.i18n import tr
from modern_gl.infrastructure.chart_csv import apply_chart_template


def create_demo_company(ledger: Ledger, name: str | None = None) -> int:
    cid = ledger.create_company(name or tr("ДЕМО ООО"))
    apply_chart_template(ledger, cid, "classic")

    def value(kind: str, title: str, owner: int | None = None) -> int:
        kind_id = ledger.subconto_kind_id(cid, kind)
        return ledger.add_subconto_value(cid, kind_id, title, owner_id=owner)

    alfa = value("counterparty", tr("Альфа Трейд"))
    beta = value("counterparty", tr("Бета Сервис"))
    founder = value("counterparty", tr("Учредитель"))
    c1 = value("contract", tr("Договор поставки №1"), alfa)
    c2 = value("contract", tr("Договор №7-У"), beta)
    bank = value("bank_account", tr("Основной расчётный счёт"))
    paper = value("item", tr("Бумага офисная А4"))
    store = value("warehouse", tr("Основной склад"))
    materials = value("cost_item", tr("Материальные расходы"))
    rent = value("cost_item", tr("Аренда офиса"))
    employee = value("employee", tr("Мамедов Р."))

    inventory = Inventory(ledger.conn, actor=ledger.actor)
    package = inventory.add_unit(cid, "уп.", tr("Упаковка"), precision=0)
    paper_item = inventory.add_item(
        cid,
        tr("Бумага офисная А4"),
        package,
        ledger.account_id(cid, "10"),
        subconto_value_id=paper,
    )
    main_warehouse = inventory.add_warehouse(cid, tr("Основной склад"), subconto_value_id=store)

    def p(dt, ct, amount, dt_sc=(), ct_sc=(), memo=""):
        return PostingInput(
            ledger.account_id(cid, dt), ledger.account_id(cid, ct), amount, dt_sc, ct_sc, memo
        )

    post = ledger.post_new
    post(
        cid,
        "2026-01-05",
        [p("51", "85", "10000", [bank], [founder])],
        tr("Взнос в уставный капитал"),
    )
    inventory.post_receipt(
        cid,
        "2026-01-10",
        [ReceiptLine(paper_item, main_warehouse, "120", "1200")],
        ledger.account_id(cid, "60"),
        [alfa, c1],
        tr("Поступление материалов"),
    )
    post(cid, "2026-01-15", [p("60", "51", "1000", [alfa, c1], [bank])], tr("Оплата поставщику"))
    inventory.post_receipt(
        cid,
        "2026-02-03",
        [ReceiptLine(paper_item, main_warehouse, "50", "500")],
        ledger.account_id(cid, "60"),
        [beta, c2],
        tr("Поступление материалов"),
    )
    post(cid, "2026-02-04", [p("50", "51", "2000", [], [bank])], tr("Снятие наличных в кассу"))
    post(cid, "2026-02-10", [p("60", "51", "600", [beta, c2], [bank])], tr("Оплата поставщику"))
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
    inventory.post_issue(
        cid,
        "2026-02-20",
        [
            IssueLine(
                paper_item,
                main_warehouse,
                "30",
                ledger.account_id(cid, "26"),
                [materials],
            )
        ],
        tr("Списание материалов"),
    )
    post(
        cid,
        "2026-02-25",
        [
            p("62", "46", "1180", [beta, c2], [], tr("Услуги оказаны")),
            p("46", "68.2", "180", [], [], tr("НДС 18%")),
        ],
        tr("Реализация услуг"),
    )
    post(cid, "2026-02-27", [p("51", "62", "1180", [bank], [beta, c2])], tr("Оплата от покупателя"))
    post(
        cid,
        "2026-02-28",
        [p("26", "10", "50", [materials], [paper, store])],
        tr("Корректировка оценки запасов"),
        layer="ifrs_adj",
    )
    ledger.create_draft(
        cid, "2026-02-28", [p("26", "60", "400", [rent], [alfa, c1])], tr("Аренда за март")
    )
    return cid
