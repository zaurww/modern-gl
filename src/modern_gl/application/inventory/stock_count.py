"""«Инвентаризация»: what was counted on a warehouse against what the books say on that
day. Nothing new is stored: a surplus comes in as a mədaxil «Излишки» (D91), a shortage
goes out as a write-off — ordinary documents, posted together or not at all (1C
«Инвентаризация товаров», Katana stocktake by warehouse)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from modern_gl.application.inventory.amounts import (
    format_quantity,
    money,
    positive_amount,
    to_quantity,
)
from modern_gl.application.inventory.catalog import CatalogCommands
from modern_gl.application.inventory.model import QUANTITY_SCALE, IssueLine, ReceiptLine
from modern_gl.application.inventory.posting import PostingCommands
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


@dataclass(frozen=True)
class CountedLine:
    """An item as counted. `amount`: what a surplus is worth, when the warehouse has none
    of the item to take an average from (or to take another value); in manat."""

    item_id: int
    quantity: str | int | Decimal
    amount: str | int | Decimal | None = None


@dataclass(frozen=True)
class StockCountResult:
    surplus_document_id: int | None
    shortage_document_id: int | None


def user_quantity(quantity: int) -> Decimal:
    """An internal quantity as a line takes it (millionths → units)."""
    return Decimal(quantity).scaleb(-QUANTITY_SCALE)


class StockCountCommands(CatalogCommands, PostingCommands):
    def post_stock_count(
        self,
        company_id: int,
        doc_date: date | str,
        warehouse_id: int,
        counted: Sequence[CountedLine],
        shortage_account_id: int | None,
        shortage_subconto: Sequence[int | None] = (),
        memo: str = "",
    ) -> StockCountResult:
        """Post the differences of a count: a surplus at the average cost of what the
        warehouse holds that day (or at the amount given), a shortage written off to
        `shortage_account_id` at the average cost. Items that agree make nothing."""
        day = iso_date(doc_date)
        warehouse = self._warehouse(company_id, warehouse_id)
        memo = memo or tr("Инвентаризация · {w}", w=warehouse["name"])
        surplus: list[ReceiptLine] = []
        shortage: list[IssueLine] = []
        with transaction(self.conn):
            for line in counted:
                item = self._item(company_id, line.item_id)
                actual = to_quantity(line.quantity)
                if actual < 0:
                    raise ValidationError(tr("фактическое количество не может быть меньше нуля"))
                book, value = self._book_balance(company_id, line.item_id, warehouse_id, day)
                if actual > book:
                    amount = self._surplus_amount(item, actual - book, book, value, line.amount)
                    surplus.append(
                        ReceiptLine(
                            line.item_id,
                            warehouse_id,
                            user_quantity(actual - book),
                            money(amount),
                            item["name"],
                        )
                    )
                elif actual < book:
                    if shortage_account_id is None:
                        raise ValidationError(tr("укажите счёт, на который списать недостачу"))
                    shortage.append(
                        IssueLine(
                            line.item_id,
                            warehouse_id,
                            user_quantity(book - actual),
                            shortage_account_id,
                            shortage_subconto,
                            item["name"],  # the posting names the item, as a receipt's does
                        )
                    )
            if not surplus and not shortage:
                raise ValidationError(tr("факт совпадает с учётом — проводить нечего"))
            return StockCountResult(
                self._post_surplus(company_id, day, surplus, memo),
                self._post_shortage(company_id, day, shortage, memo),
            )

    def _book_balance(
        self, company_id: int, item_id: int, warehouse_id: int, day: str
    ) -> tuple[int, int]:
        """Quantity and value of the item on the warehouse at the end of the day."""
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(m.quantity), 0) AS quantity, COALESCE(SUM(m.amount), 0) AS amount
            FROM stock_movements m
            JOIN inventory_documents d ON d.id = m.document_id AND d.status = 'posted'
            WHERE m.company_id = ? AND m.item_id = ? AND m.warehouse_id = ? AND m.doc_date <= ?
            """,
            (company_id, item_id, warehouse_id, day),
        ).fetchone()
        return row["quantity"], row["amount"]

    @staticmethod
    def _surplus_amount(
        item, extra: int, book: int, value: int, given: str | int | Decimal | None
    ) -> int:
        """What the extra goods are worth: given, or the average of what is on hand."""
        if given is not None and str(given).strip():
            return positive_amount(given, 0)
        if book > 0 and value > 0:
            return round_ratio(value * extra, book)
        raise ValidationError(
            tr(
                "«{item}»: на складе нет остатка, чтобы взять среднюю цену — укажите сумму "
                "излишков ({q})",
                item=item["name"],
                q=format_quantity(extra, item["unit_precision"]),
            )
        )

    def _post_surplus(
        self, company_id: int, day: str, lines: list[ReceiptLine], memo: str
    ) -> int | None:
        if not lines:
            return None
        account = self.incoming_account(company_id, "surplus")
        if account is None:
            raise ValidationError(
                tr("не выбран счёт излишков — укажите его в настройках склада (Оприходование)")
            )
        document_id = self.create_receipt_draft(
            company_id, day, lines, account, (), memo, incoming_reason="surplus"
        )
        self._post_in_sequence(company_id, document_id)
        return document_id

    def _post_shortage(
        self, company_id: int, day: str, lines: list[IssueLine], memo: str
    ) -> int | None:
        if not lines:
            return None
        document_id = self.create_issue_draft(company_id, day, lines, memo)
        self._post_in_sequence(company_id, document_id)
        return document_id
