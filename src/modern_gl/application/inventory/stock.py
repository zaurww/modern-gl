"""The stock register: movements, balances, the average cost and what
issues consumed of receipts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from modern_gl.application.inventory.amounts import format_quantity, money
from modern_gl.application.inventory.drafts import DraftCommands
from modern_gl.application.inventory.model import QUEUE_SQL
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row


class StockShortage(ValidationError):
    """Not enough of an item on a warehouse for what a document takes — the goods came,
    their papers did not (D-new): the page offers to bring them in («ждёт e-qaimə»)."""

    def __init__(self, message: str, item_id: int, warehouse_id: int) -> None:
        super().__init__(message)
        self.item_id, self.warehouse_id = item_id, warehouse_id


def require_stock(item: Row, warehouse: Row, requested: int, available: int) -> None:
    if requested > available:
        raise StockShortage(
            tr(
                "недостаточно товара «{item}» на складе «{warehouse}»: "
                "доступно {available}, требуется {requested}",
                item=item["name"],
                warehouse=warehouse["name"],
                available=format_quantity(available, item["unit_precision"]),
                requested=format_quantity(requested, item["unit_precision"]),
            ),
            item["id"],
            warehouse["id"],
        )


class StockCommands(DraftCommands):
    def _insert_movement(
        self,
        company_id: int,
        document_id: int,
        line_id: int,
        doc_date: date | str,
        item_id: int,
        warehouse_id: int,
        movement_type: str,
        quantity: int,
        amount: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO stock_movements (company_id, document_id, line_id, doc_date, item_id, "
            "warehouse_id, movement_type, quantity, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                document_id,
                line_id,
                iso_date(doc_date),
                item_id,
                warehouse_id,
                movement_type,
                quantity,
                amount,
            ),
        )
        kept = self._kept_now(("balance", company_id, item_id, warehouse_id))
        if kept is not None:
            kept[0] += quantity
            kept[1] += amount

    def _kept_now(self, key: tuple) -> list | None:
        """What is kept for the recalculation under `key`, if it was read already."""
        return None if self._kept is None else self._kept.get(key)  # type: ignore[return-value]

    def _balance(
        self, company_id: int, item_id: int, warehouse_id: int, current_document_id: int | None
    ) -> tuple[int, int]:
        """Quantity and value on the warehouse: posted movements and the current
        document's. While documents are recalculated it is read once and then kept in step
        with every movement written (debt 6)."""
        quantity, amount = self._kept_row(
            ("balance", company_id, item_id, warehouse_id),
            lambda: self._read_balance(company_id, item_id, warehouse_id, current_document_id),
        )
        return quantity, amount

    def _read_balance(
        self, company_id: int, item_id: int, warehouse_id: int, current_document_id: int | None
    ) -> list[int]:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(m.quantity), 0) AS quantity,
                   COALESCE(SUM(m.amount), 0) AS amount
            FROM stock_movements m
            JOIN inventory_documents d ON d.id = m.document_id
            WHERE m.company_id = ? AND m.item_id = ? AND m.warehouse_id = ?
              AND (d.status = 'posted' OR d.id = ?)
            """,
            (company_id, item_id, warehouse_id, current_document_id),
        ).fetchone()
        return [row["quantity"], row["amount"]]

    def _cost(
        self,
        company_id: int,
        item: Row,
        warehouse: Row,
        quantity: int,
        document_id: int,
    ) -> int:
        """What `quantity` taken from a warehouse costs: its share of the balance's value
        (moving weighted average); all of it when the whole balance goes."""
        balance_qty, balance_amount = self._balance(
            company_id, item["id"], warehouse["id"], document_id
        )
        require_stock(item, warehouse, quantity, balance_qty)
        if quantity == balance_qty:
            return balance_amount
        return round_ratio(balance_amount * quantity, balance_qty)

    def _consume_receipts(
        self,
        company_id: int,
        document_id: int,
        issue_line_id: int,
        item_id: int,
        quantity: int,
    ) -> None:
        """Take `quantity` from the oldest receipts of the item that still have some."""
        receipts = self._kept_row(
            ("receipts", company_id, item_id), lambda: self._read_receipts(company_id, item_id)
        )
        remaining = quantity
        for receipt in receipts:
            used = min(remaining, receipt[1])
            if used:
                self.conn.execute(
                    "INSERT INTO stock_consumptions "
                    "(company_id, document_id, issue_line_id, receipt_line_id, quantity) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (company_id, document_id, issue_line_id, receipt[0], used),
                )
                receipt[1] -= used
                remaining -= used
            if remaining == 0:
                break
        receipts[:] = [receipt for receipt in receipts if receipt[1] > 0]
        if remaining:
            raise ValidationError(tr("не удалось определить поступления для списания"))

    def _forget_receipts(self, company_id: int, lines: Sequence[Row]) -> None:
        """A receipt posted during a recalculation: its items' queues are read again."""
        if self._kept is not None:
            for line in lines:
                self._kept.pop(("receipts", company_id, line["item_id"]), None)

    def _read_receipts(self, company_id: int, item_id: int) -> list[list[int]]:
        """[receipt line, what is left of it], oldest first; while documents are
        recalculated it is read once and then kept in step (debt 6)."""
        rows = self.conn.execute(
            f"""
            SELECT l.id, l.quantity - COALESCE(SUM(c.quantity), 0) AS available
            FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id AND d.company_id = l.company_id
            LEFT JOIN stock_consumptions c ON c.receipt_line_id = l.id
            WHERE l.company_id = ? AND l.item_id = ? AND d.status = 'posted'
              AND d.doc_type IN {QUEUE_SQL}
            GROUP BY l.id, l.quantity, d.doc_date, d.id, l.line_no
            HAVING available > 0
            ORDER BY d.doc_date, d.id, l.line_no
            """,
            (company_id, item_id),
        ).fetchall()
        return [[row["id"], row["available"]] for row in rows]

    def _item_warehouse_quantities(self, company_id: int, item_id: int) -> list[tuple[int, int]]:
        return [
            (row["warehouse_id"], row["quantity"])
            for row in self.conn.execute(
                """
                SELECT m.warehouse_id, SUM(m.quantity) AS quantity
                FROM stock_movements m
                JOIN inventory_documents d ON d.id = m.document_id
                WHERE m.company_id = ? AND m.item_id = ? AND d.status = 'posted'
                GROUP BY m.warehouse_id HAVING quantity > 0
                ORDER BY m.warehouse_id
                """,
                (company_id, item_id),
            )
        ]

    def _receipt_consumptions(self, company_id: int, receipt_line_id: int) -> list[Row]:
        return self.conn.execute(
            """
            SELECT c.issue_line_id, c.quantity, d.doc_type,
                   CASE WHEN d.doc_type = 'sale' THEN l.cost_account_id
                        ELSE l.offset_account_id END AS offset_account_id,
                   CASE WHEN d.doc_type = 'sale' THEN NULL ELSE l.offset_sc1 END AS offset_sc1,
                   CASE WHEN d.doc_type = 'sale' THEN NULL ELSE l.offset_sc2 END AS offset_sc2,
                   CASE WHEN d.doc_type = 'sale' THEN NULL ELSE l.offset_sc3 END AS offset_sc3
            FROM stock_consumptions c
            JOIN inventory_lines l ON l.id = c.issue_line_id
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE c.company_id = ? AND c.receipt_line_id = ? AND d.status = 'posted'
            ORDER BY c.issue_line_id
            """,
            (company_id, receipt_line_id),
        ).fetchall()

    def _sale_values(self, company_id: int, line: Row) -> tuple[int | None, ...]:
        """What a sale line's accounts take their subconto from: the customer, the line's
        own values (a sales group), the item and the warehouse."""
        values = [line["offset_sc1"], line["offset_sc2"], line["offset_sc3"]]
        values += [line["cost_sc1"], line["cost_sc2"], line["cost_sc3"]]
        if line["item_id"] is not None:
            values.append(self._item(company_id, line["item_id"])["subconto_value_id"])
        if line["warehouse_id"] is not None:
            values.append(self._warehouse(company_id, line["warehouse_id"])["subconto_value_id"])
        return tuple(values)

    def _vat_postings(
        self,
        company_id: int,
        invoice: tuple[str, str],  # (number, kind) of the receipt's e-qaimə / declaration
        items: Sequence[tuple[int, tuple[int | None, ...], int]],
    ) -> list[PostingInput]:
        """Dr input VAT / Cr the settlement account for (account, subconto, VAT) items: one
        posting per supplier (the same account and subconto). The VAT account takes the
        supplier's subconto by kind."""
        totals: dict[tuple[int, tuple[int | None, ...]], int] = {}
        for account_id, subconto, vat in items:
            if vat:
                key = (account_id, tuple(subconto))
                totals[key] = totals.get(key, 0) + vat
        if not totals:
            return []
        vat_account_id = self.ledger.account_role(company_id, INPUT_VAT)
        if vat_account_id is None:
            raise ValidationError(
                tr("не указан счёт НДС к возмещению — выберите его в настройках склада")
            )
        vat_kinds = self._account_kind_ids(self._account(company_id, vat_account_id))
        result = []
        for (account_id, offset_sc), amount in totals.items():
            by_kind = {
                self._subconto_value(company_id, value_id)["kind_id"]: value_id
                for value_id in offset_sc
                if value_id is not None
            }
            result.append(
                PostingInput(
                    vat_account_id,
                    account_id,
                    money(amount),
                    tuple(None if kind is None else by_kind.get(kind) for kind in vat_kinds),
                    offset_sc,
                    tr("НДС"),
                    invoice=invoice[0],
                    invoice_kind=invoice[1],
                )
            )
        return result
