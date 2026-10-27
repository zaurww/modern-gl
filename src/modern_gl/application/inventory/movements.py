"""Issues and transfers: their drafts; receipts (drafts in `receipts`), issues and
transfers: their postings."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory.amounts import draft_quantity, money
from modern_gl.application.inventory.model import (
    INCOMING_TYPES,
    IssueLine,
    Movement,
    StoredLine,
    TransferLine,
)
from modern_gl.application.inventory.receipts import ReceiptDraftCommands
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction


def require_complete(doc_type: str, line: Row) -> None:
    """A draft may be unfinished; posting needs every field of the line."""
    line_no = line["line_no"]
    if line["warehouse_id"] is None:
        raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
    if line["quantity"] <= 0:
        raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
    if doc_type == "transfer":
        if line["to_warehouse_id"] is None:
            raise ValidationError(tr("строка {line}: не указан склад-получатель", line=line_no))
        return
    if doc_type in INCOMING_TYPES and line["amount"] <= 0:
        raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
    if line["offset_account_id"] is None:
        raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))


def offset_subconto(line: Row) -> tuple[int | None, int | None, int | None]:
    return (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])


class MovementCommands(ReceiptDraftCommands):
    def create_issue_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[IssueLine],
        memo: str = "",
    ) -> int:
        """Save an editable issue document without affecting stock or GL."""
        with transaction(self.conn):
            document_id = self._insert_document(company_id, doc_date, "issue", memo)
            self._write_issue_draft(company_id, document_id, lines)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "issue"},
            )
        return document_id

    def update_issue_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[IssueLine],
        memo: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "issue":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._release_lines(company_id, document_id, lines)
            self._write_issue_draft(company_id, document_id, lines)
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def create_transfer_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[TransferLine],
        memo: str = "",
    ) -> int:
        """Save an editable transfer document without affecting stock or GL."""
        with transaction(self.conn):
            document_id = self._insert_document(company_id, doc_date, "transfer", memo)
            self._write_transfer_draft(company_id, document_id, lines)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "transfer"},
            )
        return document_id

    def update_transfer_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[TransferLine],
        memo: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "transfer":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._release_lines(company_id, document_id, lines)
            self._write_transfer_draft(company_id, document_id, lines)
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def _write_issue_draft(
        self, company_id: int, document_id: int, lines: Sequence[IssueLine]
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        for line_no, source in enumerate(lines, 1):
            item = self._item(company_id, source.item_id)
            warehouse_id = self._draft_warehouse(company_id, source.warehouse_id)
            quantity = draft_quantity(item, source.quantity, line_no)
            if source.expense_account_id is not None:
                self._account(company_id, source.expense_account_id)
            expense_sc = pad_subconto(source.expense_subconto)
            self._insert_line(
                document_id,
                company_id,
                StoredLine(
                    line_no,
                    item["id"],
                    warehouse_id,
                    quantity,
                    source.memo.strip(),
                    offset_account_id=source.expense_account_id,
                    offset_subconto=expense_sc,
                    line_id=source.line_id,
                ),
            )

    def _write_transfer_draft(
        self, company_id: int, document_id: int, lines: Sequence[TransferLine]
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        for line_no, source in enumerate(lines, 1):
            if (
                source.from_warehouse_id is not None
                and source.from_warehouse_id == source.to_warehouse_id
            ):
                raise ValidationError(tr("склад отправитель и получатель совпадают"))
            item = self._item(company_id, source.item_id)
            from_warehouse_id = self._draft_warehouse(company_id, source.from_warehouse_id)
            to_warehouse_id = self._draft_warehouse(company_id, source.to_warehouse_id)
            quantity = draft_quantity(item, source.quantity, line_no)
            self._insert_line(
                document_id,
                company_id,
                StoredLine(
                    line_no,
                    item["id"],
                    from_warehouse_id,
                    quantity,
                    source.memo.strip(),
                    to_warehouse_id=to_warehouse_id,
                    line_id=source.line_id,
                ),
            )

    def _apply_line(self, company_id: int, doc: Row, line: Row) -> PostingInput:
        if line["item_id"] is None:  # a receipt's service, fixed asset or expense
            return self._expense_posting(doc, line)
        require_complete(doc["doc_type"], line)
        item = self._item(company_id, line["item_id"])
        warehouse = self._warehouse(company_id, line["warehouse_id"])
        if doc["doc_type"] in INCOMING_TYPES:
            return self._receipt_posting(company_id, doc, line, item, warehouse)
        amount = self._cost(company_id, item, warehouse, line["quantity"], doc["id"])
        self.conn.execute(
            "UPDATE inventory_lines SET amount = ?, inventory_amount = ?, "
            "expense_amount = ? WHERE id = ?",
            (
                amount,
                amount if doc["doc_type"] == "transfer" else 0,
                amount if doc["doc_type"] == "issue" else 0,
                line["id"],
            ),
        )
        if doc["doc_type"] == "issue":
            return self._issue_posting(company_id, doc, line, item, warehouse, amount)
        return self._transfer_posting(company_id, doc, line, item, warehouse, amount)

    def _receipt_posting(
        self,
        company_id: int,
        doc: Row,
        line: Row,
        item: Row,
        warehouse: Row,
    ) -> PostingInput:
        """Goods come in at their amount: Dt stock / Kt the line's account."""
        amount = line["amount"]
        self._insert_movement(
            company_id,
            doc["id"],
            line["id"],
            doc["doc_date"],
            Movement(
                item["id"],
                warehouse["id"],
                "receipt" if doc["doc_type"] == "incoming" else doc["doc_type"],
                line["quantity"],
                amount,
            ),
        )
        in_currency = doc["currency_id"] is not None and doc["doc_type"] == "receipt"
        return PostingInput(
            item["inventory_account_id"],
            line["offset_account_id"],
            money(amount),
            self._inventory_subconto(company_id, item, warehouse),
            offset_subconto(line),
            line["memo"],
            doc["currency_id"] if in_currency else None,
            money(line["currency_amount"] or 0) if in_currency else None,
            doc["invoice"] or "",
            doc["invoice_kind"] or "",
        )

    def _issue_posting(
        self,
        company_id: int,
        doc: Row,
        line: Row,
        item: Row,
        warehouse: Row,
        amount: int,
    ) -> PostingInput:
        """Goods go out at their cost: Dt the line's account / Kt stock."""
        self._consume_receipts(company_id, doc["id"], line["id"], item["id"], line["quantity"])
        self._insert_movement(
            company_id,
            doc["id"],
            line["id"],
            doc["doc_date"],
            Movement(item["id"], warehouse["id"], "issue", -line["quantity"], -amount),
        )
        return PostingInput(
            line["offset_account_id"],
            item["inventory_account_id"],
            money(amount),
            offset_subconto(line),
            self._inventory_subconto(company_id, item, warehouse),
            line["memo"],
        )

    def _transfer_posting(
        self,
        company_id: int,
        doc: Row,
        line: Row,
        item: Row,
        warehouse: Row,
        amount: int,
    ) -> PostingInput:
        """Goods move between warehouses at their cost: stock to stock."""
        to_warehouse = self._warehouse(company_id, line["to_warehouse_id"])
        if warehouse["id"] == to_warehouse["id"]:
            raise ValidationError(tr("склад отправитель и получатель совпадают"))
        for target, movement_type, sign in (
            (warehouse, "transfer_out", -1),
            (to_warehouse, "transfer_in", 1),
        ):
            self._insert_movement(
                company_id,
                doc["id"],
                line["id"],
                doc["doc_date"],
                Movement(
                    item["id"], target["id"], movement_type, sign * line["quantity"], sign * amount
                ),
            )
        return PostingInput(
            item["inventory_account_id"],
            item["inventory_account_id"],
            money(amount),
            self._inventory_subconto(company_id, item, to_warehouse),
            self._inventory_subconto(company_id, item, warehouse),
            line["memo"],
        )

    def _expense_posting(self, doc: Row, line: Row) -> PostingInput:
        """A receipt line without an item: Dr its account [subconto] / Cr the supplier."""
        line_no = line["line_no"]
        if not line["memo"]:
            raise ValidationError(
                tr("строка {line}: укажите товар или что куплено (услуга, ОС)", line=line_no)
            )
        if line["amount"] <= 0:
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        if line["cost_account_id"] is None:
            raise ValidationError(tr("строка {line}: не указан счёт затрат", line=line_no))
        self._check_not_stock(doc["company_id"], line["cost_account_id"], line_no)
        if line["offset_account_id"] is None:
            raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
        in_currency = doc["currency_id"] is not None
        return PostingInput(
            line["cost_account_id"],
            line["offset_account_id"],
            money(line["amount"]),
            (line["cost_sc1"], line["cost_sc2"], line["cost_sc3"]),
            (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"]),
            line["memo"],
            doc["currency_id"] if in_currency else None,
            money(line["currency_amount"] or 0) if in_currency else None,
            doc["invoice"] or "",
            doc["invoice_kind"] or "",
        )
