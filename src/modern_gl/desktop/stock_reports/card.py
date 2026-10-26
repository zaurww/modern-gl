"""«Карточка товара»: an item on one warehouse or on all over a period — the balance at
the start, each movement with where it came from or went to, the balance after it
(ERPNext Stock Ledger). A double click opens the warehouse document."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Signal

from modern_gl.desktop.inventory_page.movements import source_text
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.stock_reports.common import quantity_column
from modern_gl.desktop.widgets import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.inventory import ItemCard, item_card


@dataclass(frozen=True)
class CardRow:
    """A line of the card: the balance at the start, a movement, the balance at the end."""

    text: str
    unit_code: str
    precision: int
    quantity_in: int = 0
    quantity_out: int = 0
    quantity_balance: int = 0
    amount_in: int = 0
    amount_out: int = 0
    amount_balance: int = 0
    doc_date: str = ""
    number: int | None = None
    warehouse: str = ""
    document_id: int | None = None
    is_total: bool = False


def card_rows(card: ItemCard) -> list[CardRow]:
    unit = (card.unit_code, card.precision)
    rows = [
        CardRow(
            tr("Остаток на начало"),
            *unit,
            quantity_balance=card.opening_quantity,
            amount_balance=card.opening_amount,
            is_total=True,
        )
    ]
    rows += [
        CardRow(
            source_text(m.source),
            *unit,
            max(m.quantity, 0),
            max(-m.quantity, 0),
            m.quantity_balance,
            max(m.amount, 0),
            max(-m.amount, 0),
            m.amount_balance,
            m.doc_date,
            m.number,
            m.warehouse,
            m.document_id,
        )
        for m in card.lines
    ]
    rows.append(
        CardRow(
            tr("Остаток на конец"),
            *unit,
            quantity_in=sum(r.quantity_in for r in rows),
            quantity_out=sum(r.quantity_out for r in rows),
            quantity_balance=card.closing_quantity,
            amount_in=sum(r.amount_in for r in rows),
            amount_out=sum(r.amount_out for r in rows),
            amount_balance=card.closing_amount,
            is_total=True,
        )
    )
    return rows


class ItemCardPage(ReportPage):
    has_book = False
    open_inventory_document = Signal(int)

    def __init__(
        self,
        session: Session,
        item_id: int,
        warehouse_id: int | None,
        params: ReportParams | None = None,
    ) -> None:
        self.item_id, self.warehouse_id = item_id, warehouse_id
        self.key = ("stock_card", item_id, warehouse_id or 0)
        self.name = ""
        super().__init__(session, tr("Карточка товара"), params)
        self.refresh()

    def title(self) -> str:
        return f"{tr('Карточка товара')} · {self.name}" if self.name else tr("Карточка товара")

    def job(self) -> Callable[[Connection], ItemCard]:
        cid, p, item, place = self.s.company_id, self.params, self.item_id, self.warehouse_id
        return lambda conn: item_card(conn, cid, item, place, p.date_from, p.date_to)

    def fetch(self, conn: Connection) -> ItemCard:
        return self.job()(conn)

    def present(self, data: ItemCard) -> None:
        self.name = data.name
        self.header.title.setText(self.title())
        quantity, value = tr("Количество"), tr("Сумма")
        columns = [
            Column(tr("Дата"), lambda r: ru_date(r.doc_date) if r.doc_date else ""),
            Column("№", lambda r: "" if r.number is None else str(r.number), right=True),
            *([Column(tr("Склад"), lambda r: r.warehouse)] if self.warehouse_id is None else []),
            Column(tr("Операция"), lambda r: r.text),
            quantity_column(tr("Приход"), lambda r: r.quantity_in, quantity),
            quantity_column(tr("Расход"), lambda r: r.quantity_out, quantity),
            quantity_column(tr("Остаток"), lambda r: r.quantity_balance, quantity),
            Column(tr("Приход"), lambda r: r.amount_in, money=True, group=value),
            Column(tr("Расход"), lambda r: r.amount_out, money=True, group=value),
            Column(tr("Остаток"), lambda r: r.amount_balance, money=True, group=value),
        ]
        self.model.set(columns, card_rows(data), emphasis=lambda r: r.is_total)
        self.footer.setText(tr("Движений: {n}. Двойной щелчок — документ", n=len(data.lines)))

    def drill(self, row: CardRow | None) -> None:
        if row is not None and row.document_id is not None:
            self.open_inventory_document.emit(row.document_id)
