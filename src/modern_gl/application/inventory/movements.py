"""Opening balances, receipts, issues and transfers: their drafts and
postings."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory.amounts import (
    blank,
    draft_quantity,
    money,
    nonnegative_amount,
    positive_amount,
    service_quantity,
)
from modern_gl.application.inventory.model import IssueLine, ReceiptLine, TransferLine
from modern_gl.application.inventory.stock import StockCommands
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.currency import to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


def require_complete(doc_type: str, line: sqlite3.Row) -> None:
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
    if doc_type in {"opening", "receipt"} and line["amount"] <= 0:
        raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
    if line["offset_account_id"] is None:
        raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))


class MovementCommands(StockCommands):
    def create_receipt_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[ReceiptLine],
        credit_account_id: int | None,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        opening: bool = False,
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
        expense_date: date | str | None = None,
    ) -> int:
        """Save an editable receipt/opening document without affecting stock or GL.

        A draft may be unfinished: only the item of each line is required. Line amounts
        are without VAT; each line's VAT is given (`vat_rate` only remembers the rate)."""
        with transaction(self.conn):
            document_id = self._insert_document(
                company_id,
                doc_date,
                "opening" if opening else "receipt",
                memo,
            )
            self._set_vat_rate(document_id, None if opening else vat_rate)
            self._set_currency(company_id, document_id, currency_id, currency_rate)
            self._set_invoice(document_id, "" if opening else invoice, invoice_kind)
            self._set_expense_date(document_id, None if opening else expense_date)
            self._write_receipt_draft(
                company_id, document_id, lines, credit_account_id, credit_subconto
            )
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "opening" if opening else "receipt"},
            )
        return document_id

    def update_receipt_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[ReceiptLine],
        credit_account_id: int | None,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
        expense_date: date | str | None = None,
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] not in {"opening", "receipt"}:
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._set_vat_rate(document_id, vat_rate if doc["doc_type"] == "receipt" else None)
            self._set_currency(company_id, document_id, currency_id, currency_rate)
            receipt = doc["doc_type"] == "receipt"
            self._set_invoice(document_id, invoice if receipt else "", invoice_kind)
            self._set_expense_date(document_id, expense_date if receipt else None)
            self._release_lines(company_id, document_id, lines)
            self._write_receipt_draft(
                company_id, document_id, lines, credit_account_id, credit_subconto
            )
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

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

    def _write_receipt_draft(
        self,
        company_id: int,
        document_id: int,
        lines: Sequence[ReceiptLine],
        credit_account_id: int | None,
        credit_subconto: Sequence[int | None],
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        doc = self._document(company_id, document_id)
        doc_type = doc["doc_type"]
        for line_no, source in enumerate(lines, 1):
            expense = self._expense_of(company_id, doc_type, source, line_no)
            if source.item_id is None:  # a service, fixed asset or expense: no stock
                warehouse_id = None
                quantity = service_quantity(source.quantity, line_no)
            else:
                item = self._item(company_id, source.item_id)
                warehouse_id = self._draft_warehouse(company_id, source.warehouse_id)
                quantity = draft_quantity(item, source.quantity, line_no)
            currency_amount, amount = self._line_amounts(doc, source, line_no)
            vat = (
                0
                if source.vat_amount is None or blank(source.vat_amount)
                else nonnegative_amount(source.vat_amount)
            )
            if vat and doc_type != "receipt":
                raise ValidationError(tr("НДС указывается только в поступлении"))
            if vat and doc["currency_id"] is not None:
                raise ValidationError(
                    tr("в поступлении в валюте НДС не указывается: импортный НДС — в расходах")
                )
            line_credit_account = source.credit_account_id or credit_account_id
            if line_credit_account is not None:
                self._account(company_id, line_credit_account)
            line_credit_sc = pad_subconto(source.credit_subconto or credit_subconto)
            stock = source.item_id is not None
            self._insert_line(
                document_id,
                company_id,
                line_no,
                source.item_id,
                warehouse_id,
                None,
                quantity,
                amount,
                amount if stock else 0,
                0 if stock else amount,
                line_credit_account,
                line_credit_sc,
                None,
                source.memo.strip(),
                line_id=source.line_id,
                vat_amount=vat,
                currency_amount=currency_amount,
                cost_account_id=expense[0],
                cost_subconto=expense[1],
            )

    def _expense_of(
        self, company_id: int, doc_type: str, source: ReceiptLine, line_no: int
    ) -> tuple[int | None, tuple[int | None, ...]]:
        """The account and subconto a receipt line without an item goes to (an item's line
        has none: its account is the item's)."""
        if source.item_id is not None:
            return None, (None, None, None)
        if doc_type != "receipt":
            raise ValidationError(tr("строка {line}: не указан товар", line=line_no))
        if source.warehouse_id is not None:
            raise ValidationError(tr("строка {line}: у услуги нет склада", line=line_no))
        if source.expense_account_id is not None:
            self._account(company_id, source.expense_account_id)
        for value_id in source.expense_subconto:
            if value_id is not None:
                self._subconto_value(company_id, value_id)
        return source.expense_account_id, pad_subconto(source.expense_subconto)

    def _line_amounts(
        self, doc: sqlite3.Row, source: ReceiptLine, line_no: int
    ) -> tuple[int | None, int]:
        """(amount in the currency, amount in manat) of a receipt line. In a currency the
        manat amount follows from the document's rate."""
        if doc["currency_id"] is None:
            if blank(source.amount):
                return None, 0
            return None, positive_amount(source.amount, line_no)
        value = source.currency_amount
        if value is None or blank(value):
            return 0, 0
        currency_amount = positive_amount(value, line_no)
        return currency_amount, to_base(currency_amount, unit_rate(doc["currency_rate"]))

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
                line_no,
                item["id"],
                warehouse_id,
                None,
                quantity,
                0,
                0,
                0,
                source.expense_account_id,
                expense_sc,
                None,
                source.memo.strip(),
                line_id=source.line_id,
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
                line_no,
                item["id"],
                from_warehouse_id,
                to_warehouse_id,
                quantity,
                0,
                0,
                0,
                None,
                (),
                None,
                source.memo.strip(),
                line_id=source.line_id,
            )

    def _apply_line(self, company_id: int, doc: sqlite3.Row, line: sqlite3.Row) -> PostingInput:
        document_id = doc["id"]
        if line["item_id"] is None:  # a receipt's service, fixed asset or expense
            return self._expense_posting(doc, line)
        require_complete(doc["doc_type"], line)
        item = self._item(company_id, line["item_id"])
        warehouse = self._warehouse(company_id, line["warehouse_id"])
        offset_sc = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
        if doc["doc_type"] in {"opening", "receipt"}:
            amount = line["amount"]
            self._insert_movement(
                company_id,
                document_id,
                line["id"],
                doc["doc_date"],
                item["id"],
                warehouse["id"],
                doc["doc_type"],
                line["quantity"],
                amount,
            )
            in_currency = doc["currency_id"] is not None and doc["doc_type"] == "receipt"
            return PostingInput(
                item["inventory_account_id"],
                line["offset_account_id"],
                money(amount),
                self._inventory_subconto(company_id, item, warehouse),
                offset_sc,
                line["memo"],
                doc["currency_id"] if in_currency else None,
                money(line["currency_amount"] or 0) if in_currency else None,
                doc["invoice"] or "",
                doc["invoice_kind"] or "",
            )

        amount = self._cost(company_id, item, warehouse, line["quantity"], document_id)
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
            self._consume_receipts(
                company_id, document_id, line["id"], item["id"], line["quantity"]
            )
            self._insert_movement(
                company_id,
                document_id,
                line["id"],
                doc["doc_date"],
                item["id"],
                warehouse["id"],
                "issue",
                -line["quantity"],
                -amount,
            )
            return PostingInput(
                line["offset_account_id"],
                item["inventory_account_id"],
                money(amount),
                offset_sc,
                self._inventory_subconto(company_id, item, warehouse),
                line["memo"],
            )

        to_warehouse = self._warehouse(company_id, line["to_warehouse_id"])
        if warehouse["id"] == to_warehouse["id"]:
            raise ValidationError(tr("склад отправитель и получатель совпадают"))
        for target, movement_type, sign in (
            (warehouse, "transfer_out", -1),
            (to_warehouse, "transfer_in", 1),
        ):
            self._insert_movement(
                company_id,
                document_id,
                line["id"],
                doc["doc_date"],
                item["id"],
                target["id"],
                movement_type,
                sign * line["quantity"],
                sign * amount,
            )
        return PostingInput(
            item["inventory_account_id"],
            item["inventory_account_id"],
            money(amount),
            self._inventory_subconto(company_id, item, to_warehouse),
            self._inventory_subconto(company_id, item, warehouse),
            line["memo"],
        )

    def _expense_posting(self, doc: sqlite3.Row, line: sqlite3.Row) -> PostingInput:
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
