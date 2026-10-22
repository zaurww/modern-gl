"""A small demo company on the classic chart — for screenshots, demos and trying the UI."""

from __future__ import annotations

from modern_gl.application.inventory import (
    STANDARD_VAT_RATE,
    Inventory,
    IssueLine,
    ReceiptLine,
    SaleLine,
)
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.i18n import tr
from modern_gl.infrastructure.chart_csv import apply_chart_template


def create_demo_company(ledger: Ledger, name: str | None = None) -> int:
    cid = ledger.create_company(name or tr("ДЕМО ООО"))
    apply_chart_template(ledger, cid, "classic")
    demo = _Demo(ledger, cid)
    demo.january()
    demo.february()
    return cid


class _Demo:
    """The demo's directories, its stock catalogue and its documents, in date order (the
    order gives the numbers)."""

    def __init__(self, ledger: Ledger, cid: int) -> None:
        self.ledger, self.cid = ledger, cid
        self.alfa = self._value("counterparty", tr("Альфа Трейд"))
        self.beta = self._value("counterparty", tr("Бета Сервис"))
        self.founder = self._value("counterparty", tr("Учредитель"))
        self.c1 = self._value("contract", tr("Договор поставки №1"), self.alfa)
        self.c2 = self._value("contract", tr("Договор №7-У"), self.beta)
        self.bank = self._value("bank_account", tr("Основной расчётный счёт"))
        self.paper = self._value("item", tr("Бумага офисная А4"))
        self.store = self._value("warehouse", tr("Основной склад"))
        self.materials = self._value("cost_item", tr("Материальные расходы"))
        self.rent = self._value("cost_item", tr("Аренда офиса"))
        self.employee = self._value("employee", tr("Мамедов Р."))
        self.inventory = Inventory(ledger.conn, actor=ledger.actor)
        package = self.inventory.add_unit(cid, "уп.", tr("Упаковка"), precision=0)
        self.paper_item = self.inventory.add_item(
            cid,
            tr("Бумага офисная А4"),
            package,
            ledger.account_id(cid, "10"),
            subconto_value_id=self.paper,
        )
        self.main_warehouse = self.inventory.add_warehouse(
            cid, tr("Основной склад"), subconto_value_id=self.store
        )

    def _value(self, kind: str, title: str, owner: int | None = None) -> int:
        kind_id = self.ledger.subconto_kind_id(self.cid, kind)
        return self.ledger.add_subconto_value(self.cid, kind_id, title, owner_id=owner)

    def p(self, dt, ct, amount, dt_sc=(), ct_sc=(), memo="", invoice=""):
        return PostingInput(
            self.ledger.account_id(self.cid, dt),
            self.ledger.account_id(self.cid, ct),
            amount,
            dt_sc,
            ct_sc,
            memo,
            invoice=invoice,
        )

    def january(self) -> None:
        self.ledger.post_new(
            self.cid,
            "2026-01-05",
            [self.p("51", "85", "10000", [self.bank], [self.founder])],
            tr("Взнос в уставный капитал"),
        )
        self.inventory.post_receipt(
            self.cid,
            "2026-01-10",
            [ReceiptLine(self.paper_item, self.main_warehouse, "120", "1200", vat_amount="216")],
            self.ledger.account_id(self.cid, "60"),
            [self.alfa, self.c1],
            tr("Поступление материалов"),
            vat_rate=STANDARD_VAT_RATE,
            invoice="MT2601001842",
        )
        self.ledger.post_new(
            self.cid,
            "2026-01-15",
            [self.p("60", "51", "1000", [self.alfa, self.c1], [self.bank])],
            tr("Оплата поставщику"),
        )

    def february(self) -> None:
        self.inventory.post_receipt(
            self.cid,
            "2026-02-03",
            [ReceiptLine(self.paper_item, self.main_warehouse, "50", "500")],
            self.ledger.account_id(self.cid, "60"),
            [self.beta, self.c2],
            tr("Поступление материалов"),
        )
        self.ledger.post_new(
            self.cid,
            "2026-02-04",
            [self.p("50", "51", "2000", [], [self.bank])],
            tr("Снятие наличных в кассу"),
        )
        self.ledger.post_new(
            self.cid,
            "2026-02-10",
            [self.p("60", "51", "600", [self.beta, self.c2], [self.bank])],
            tr("Оплата поставщику"),
        )
        self.ledger.post_new(
            self.cid,
            "2026-02-12",
            [self.p("71", "50", "300", [self.employee], [])],
            tr("Выдано под отчёт"),
        )
        self.ledger.post_new(
            self.cid,
            "2026-02-14",
            [
                self.p("26", "71", "250", [self.rent], [self.employee], tr("Аренда за февраль")),
                self.p("50", "71", "50", [], [self.employee], tr("Возврат остатка")),
            ],
            tr("Авансовый отчёт"),
        )
        self.inventory.post_issue(
            self.cid,
            "2026-02-20",
            [
                IssueLine(
                    self.paper_item,
                    self.main_warehouse,
                    "30",
                    self.ledger.account_id(self.cid, "26"),
                    [self.materials],
                )
            ],
            tr("Списание материалов"),
        )
        self.inventory.post_sale(  # a service: Dt 62 / Kt 46 1 180.00, Dt 46 / Kt 68.2 180.00
            self.cid,
            "2026-02-25",
            [SaleLine(None, None, "1", "1000", "180", tr("Услуги оказаны"))],
            self.ledger.account_id(self.cid, "62"),
            [self.beta, self.c2],
            tr("Реализация услуг"),
            vat_rate=STANDARD_VAT_RATE,
            invoice="MT2602004571",
        )
        self.ledger.post_new(
            self.cid,
            "2026-02-27",
            [self.p("51", "62", "1180", [self.bank], [self.beta, self.c2], invoice="MT2602004571")],
            tr("Оплата от покупателя"),
        )
        self.ledger.post_new(
            self.cid,
            "2026-02-28",
            [self.p("26", "10", "50", [self.materials], [self.paper, self.store])],
            tr("Корректировка оценки запасов"),
            layer="ifrs_adj",
        )
        self.ledger.create_draft(
            self.cid,
            "2026-02-28",
            [self.p("26", "60", "400", [self.rent], [self.alfa, self.c1], invoice="MT2602009310")],
            tr("Аренда за март"),
        )
