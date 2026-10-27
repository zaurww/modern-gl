"""«Валовая прибыль по товарам» (Logo «Ayrıntılı maliyet analizi», ERPNext Gross Profit):
sold over a period — revenue without VAT, the cost of the goods, the profit and its
share; by item or by customer with the items under it."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from PySide6.QtCore import Signal

from modern_gl.desktop.preferences import GROSS_PROFIT_VIEW
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.stock_reports.common import INDENT, quantity_column, view_switch
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.inventory import BY_CUSTOMER, BY_ITEM, ProfitRow, gross_profit

VIEW_SETTING = GROSS_PROFIT_VIEW


def margin_text(row: ProfitRow) -> str:
    """The profit's share of the revenue: «42.9 %»; nothing without revenue."""
    if not row.revenue:
        return ""
    return f"{Decimal(row.profit * 100) / row.revenue:.1f} %"


class GrossProfitPage(ReportPage):
    key = ("gross_profit",)
    has_book = False
    open_stock_card = Signal(int, int, object)  # item, warehouse (0 — all), ReportParams

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Валовая прибыль по товарам"), params)
        switch, self.view = view_switch(
            VIEW_SETTING, [(BY_ITEM, "По товарам"), (BY_CUSTOMER, "По покупателям")], self.refresh
        )
        self.add_to_bar(switch)
        self.empty.say(tr("Нет продаж"), tr("За период проведённых продаж не было."))
        self.refresh()

    def title(self) -> str:
        return tr("Валовая прибыль по товарам")

    def job(self) -> Callable[[Connection], list[ProfitRow]]:
        cid, p, by, services = self.s.company_id, self.params, self.view(), tr("Услуги")
        return lambda conn: gross_profit(conn, cid, p.date_from, p.date_to, by, services)

    def fetch(self, conn: Connection) -> list[ProfitRow]:
        return self.job()(conn)

    def present(self, data: list[ProfitRow]) -> None:
        by_customer = self.view() == BY_CUSTOMER
        columns = [
            Column(tr("Покупатель / товар") if by_customer else tr("Товар"), self._name),
            quantity_column(tr("Продано"), lambda r: r.quantity),
            Column(tr("Ед."), lambda r: r.unit_code),
            Column(tr("Выручка без ƏDV"), lambda r: r.revenue, money=True),
            Column(tr("Себестоимость"), lambda r: r.cost, money=True),
            Column(tr("Прибыль"), lambda r: r.profit, money=True),
            Column(tr("Маржа, %"), margin_text, right=True, key="margin"),
        ]
        self.model.set(
            columns,
            data,
            emphasis=lambda r: r.is_total or (by_customer and r.depth == 0),
            muted=lambda r: r.depth > 0,
            total=lambda r: r.is_total,
        )
        self.footer.setText(
            tr(
                "Себестоимость — по средней на день продажи и доп. расходы, пришедшие "
                "позже. Двойной щелчок по товару — его карточка"
            )
        )

    @staticmethod
    def _name(row: ProfitRow) -> str:
        if row.is_total:
            return tr("Итого")
        name = row.name or tr("Без покупателя")
        return INDENT + name if row.depth else name

    def drill(self, row: ProfitRow | None) -> None:
        if row is not None and row.item_id is not None:
            self.open_stock_card.emit(row.item_id, 0, self.params)
