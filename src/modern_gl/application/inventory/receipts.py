"""Receipts, opening balances and mədaxil without a purchase (D91): their drafts.

Posting them is in `movements` with the other stock documents."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory.amounts import (
    blank,
    draft_quantity,
    nonnegative_amount,
    positive_amount,
    service_quantity,
)
from modern_gl.application.inventory.model import INCOMING_REASONS, INCOMING_TYPES, ReceiptLine
from modern_gl.application.inventory.stock import StockCommands
from modern_gl.domain.currency import to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction


def check_reason(reason: str | None) -> None:
    if reason is not None and reason not in INCOMING_REASONS:
        raise ValidationError(tr("неизвестная причина поступления: {r}", r=reason))


class ReceiptDraftCommands(StockCommands):
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
        incoming_reason: str | None = None,
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
        expense_date: date | str | None = None,
        awaits_invoice: bool = False,
    ) -> int:
        """Save an editable receipt/opening document — or, with `incoming_reason`, a mədaxil
        without a purchase (D91) — without affecting stock or GL.

        A draft may be unfinished: only the item of each line is required. Line amounts
        are without VAT; each line's VAT is given (`vat_rate` only remembers the rate).
        `awaits_invoice`: a purchase whose goods came before their e-qaimə (D119)."""
        check_reason(incoming_reason)
        doc_type = "incoming" if incoming_reason else "opening" if opening else "receipt"
        purchase = doc_type == "receipt"
        with transaction(self.conn):
            document_id = self._insert_document(
                company_id, doc_date, doc_type, memo, incoming_reason=incoming_reason
            )
            self._set_vat_rate(document_id, vat_rate if purchase else None)
            self._set_currency(company_id, document_id, currency_id, currency_rate)
            self._set_invoice(
                document_id,
                invoice if purchase else "",
                invoice_kind,
                awaits=purchase and awaits_invoice,
            )
            self._set_expense_date(document_id, expense_date if purchase else None)
            self._write_receipt_draft(
                company_id, document_id, lines, credit_account_id, credit_subconto
            )
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": doc_type},
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
        incoming_reason: str | None = None,
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
        expense_date: date | str | None = None,
        awaits_invoice: bool = False,
    ) -> None:
        check_reason(incoming_reason)
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            incoming = doc["doc_type"] == "incoming"
            if doc["doc_type"] not in INCOMING_TYPES or incoming != (incoming_reason is not None):
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            if incoming:
                self._set_incoming_reason(document_id, incoming_reason)
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._set_vat_rate(document_id, vat_rate if doc["doc_type"] == "receipt" else None)
            self._set_currency(company_id, document_id, currency_id, currency_rate)
            receipt = doc["doc_type"] == "receipt"
            self._set_invoice(
                document_id,
                invoice if receipt else "",
                invoice_kind,
                awaits=receipt and awaits_invoice,
            )
            self._set_expense_date(document_id, expense_date if receipt else None)
            self._release_lines(company_id, document_id, lines)
            self._write_receipt_draft(
                company_id, document_id, lines, credit_account_id, credit_subconto
            )
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def fill_expense_account(
        self,
        company_id: int,
        document_id: int,
        line_id: int,
        account_id: int,
        subconto: Sequence[int | None] = (),
        offset_account_id: int | None = None,
    ) -> None:
        """Give a purchase draft's line without an item and without an account the account
        its value goes to (D73: drafts posted in bulk, like the supplier's last purchase).
        A line that has an item or an account already is left as it is. `offset_account_id`:
        the line is owed on it instead (76, not the 60 of the import; D110) — its supplier
        and contract go with it where the account has their directories."""
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "receipt":
                raise ValidationError(tr("счёт затрат указывается только в покупке"))
            self._account(company_id, account_id)
            for value_id in subconto:
                if value_id is not None:
                    self._subconto_value(company_id, value_id)
            sc = pad_subconto(subconto)
            self.conn.execute(
                "UPDATE inventory_lines SET cost_account_id = ?, cost_sc1 = ?, cost_sc2 = ?, "
                "cost_sc3 = ? WHERE company_id = ? AND document_id = ? AND id = ? "
                "AND item_id IS NULL AND cost_account_id IS NULL",
                (account_id, *sc, company_id, document_id, line_id),
            )
            if offset_account_id is not None:
                self._move_offset(company_id, document_id, line_id, offset_account_id)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "fill_expense_account",
                {
                    "line_id": line_id,
                    "account_id": account_id,
                    "offset_account_id": offset_account_id,
                },
            )

    def _move_offset(
        self, company_id: int, document_id: int, line_id: int, account_id: int
    ) -> None:
        """The line owed on `account_id`: each of its subconto takes the value of the same
        directory the line had (the supplier, its contract), else none."""
        account = self._account(company_id, account_id)
        line = self.conn.execute(
            "SELECT offset_sc1, offset_sc2, offset_sc3 FROM inventory_lines "
            "WHERE company_id = ? AND document_id = ? AND id = ?",
            (company_id, document_id, line_id),
        ).fetchone()
        had = {}
        for value_id in (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"]):
            if value_id is not None:
                had[self._subconto_value(company_id, value_id)["kind_id"]] = value_id
        sc = [had.get(account[f"sc{i}_kind_id"]) for i in (1, 2, 3)]
        self.conn.execute(
            "UPDATE inventory_lines SET offset_account_id = ?, offset_sc1 = ?, offset_sc2 = ?, "
            "offset_sc3 = ? WHERE company_id = ? AND document_id = ? AND id = ?",
            (account_id, *sc, company_id, document_id, line_id),
        )

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

    def _line_amounts(self, doc: Row, source: ReceiptLine, line_no: int) -> tuple[int | None, int]:
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
