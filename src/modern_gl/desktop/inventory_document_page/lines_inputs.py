"""The lines as the inputs of `Inventory`: checked to be complete before posting."""

from __future__ import annotations

from decimal import Decimal

from modern_gl.application.inventory import (
    INCOMING_TYPES,
    RETURN_TYPES,
    IssueLine,
    ReceiptLine,
    ReturnLine,
    SaleLine,
    TransferLine,
)
from modern_gl.desktop.inventory_document_page.columns import (
    SALE1,
    SALE2,
    SALE3,
    InventoryGridRow,
)
from modern_gl.desktop.inventory_document_page.lines_base import InventoryLinesBase
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr


def manats(minor: int | None) -> Decimal | None:
    """An amount in kopecks as the Decimal the inputs take."""
    return None if minor is None else from_minor(minor)


class LineInputs(InventoryLinesBase):
    def to_inputs(
        self, complete: bool = True
    ) -> (
        list[ReceiptLine] | list[IssueLine] | list[TransferLine] | list[SaleLine] | list[ReturnLine]
    ):
        """Lines for saving. A draft (complete=False) needs only the item of each line."""
        rows = [row for row in self.rows if not row.is_empty()]
        if not rows:
            raise ValidationError(tr("складской документ без строк"))
        result = []
        for line_no, row in enumerate(rows, 1):
            item_id = row.item_id
            services = self.doc_type in {"sale", "receipt"} and not self.stock_only  # D90
            if item_id is None and not services:
                raise ValidationError(tr("строка {line}: не указан товар", line=line_no))
            if complete:
                self._validate_complete(row, line_no)
            quantity = None if row.quantity is None else Decimal(row.quantity).scaleb(-6)
            if self.doc_type == "sale":
                result.append(self._sale_line(row, quantity))
                continue
            if self.doc_type in RETURN_TYPES:
                result.append(
                    ReturnLine(
                        item_id,
                        row.warehouse_id,
                        quantity,
                        manats(row.amount),
                        manats(row.vat_amount),
                        row.memo.strip(),
                        row.offset_account_id,
                        tuple(row.offset_subconto),
                        row.line_id,
                        row.returned_line_id,
                    )
                )
                continue
            if self.doc_type in INCOMING_TYPES:
                result.append(self._receipt_line(row, quantity))
                continue
            assert item_id is not None  # only a sale's or receipt's line may have none
            if self.doc_type == "issue":
                result.append(
                    IssueLine(
                        item_id,
                        row.warehouse_id,
                        quantity,
                        row.offset_account_id,
                        tuple(row.offset_subconto),
                        row.memo.strip(),
                        row.line_id,
                    )
                )
            elif self.doc_type == "transfer":
                result.append(
                    TransferLine(
                        item_id,
                        row.warehouse_id,
                        row.to_warehouse_id,
                        quantity,
                        row.memo.strip(),
                        row.line_id,
                    )
                )
        return result

    def _sale_line(self, row: InventoryGridRow, quantity: Decimal | None) -> SaleLine:
        return SaleLine(
            row.item_id,
            row.warehouse_id,
            quantity,
            manats(row.amount),
            manats(row.vat_amount),
            row.memo.strip(),
            row.offset_account_id,
            tuple(row.offset_subconto),
            row.line_id,
            tuple(
                row.sale_subconto[position]
                for position, key in enumerate((SALE1, SALE2, SALE3))
                if self._takes_sale(row, key)
            ),
            expense_date=row.expense_date if row.item_id is None else None,
        )

    @staticmethod
    def _receipt_line(row: InventoryGridRow, quantity: Decimal | None) -> ReceiptLine:
        item_id = row.item_id
        return ReceiptLine(
            item_id,
            row.warehouse_id,
            quantity,
            manats(row.amount),
            row.memo.strip(),
            row.offset_account_id,
            tuple(row.offset_subconto),
            row.line_id,
            manats(row.vat_amount),
            manats(row.currency_amount),
            row.expense_account_id if item_id is None else None,
            tuple(row.expense_subconto) if item_id is None else (),
            expense_date=row.expense_date if item_id is None else None,
        )

    def _validate_complete(self, row: InventoryGridRow, line_no: int) -> None:
        self._validate_what(row, line_no)
        if self.doc_type == "transfer":
            if row.to_warehouse_id is None:
                raise ValidationError(tr("строка {line}: не указан склад-получатель", line=line_no))
            return
        priced = {*INCOMING_TYPES, "sale", *RETURN_TYPES}
        if self.doc_type in priced and (row.amount is None or row.amount <= 0):
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        if self.rate is not None and not row.currency_amount:
            raise ValidationError(tr("строка {line}: не указана сумма в валюте", line=line_no))
        if row.offset_account_id is None:
            raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
        self._require_subconto(row.offset_account_id, row.offset_subconto, line_no)
        for key in (SALE1, SALE2, SALE3):  # a sales group: what the sale accounts ask for
            kind_id = self.sale_kind(key)
            if kind_id is None or not self._takes_sale(row, key):
                continue
            if (
                kind_id not in self.s.catalog.owner_kinds
                and row.sale_subconto[int(key[-1]) - 1] is None
            ):
                raise ValidationError(
                    tr(
                        "строка {line}: заполните субконто «{kind}»",
                        line=line_no,
                        kind=self.s.catalog.kinds[kind_id],
                    )
                )

    def _validate_what(self, row: InventoryGridRow, line_no: int) -> None:
        """What the line is: an item from a warehouse, or a sale's service, or a receipt's
        service or fixed asset with the account it goes to."""
        if self.doc_type == "sale" and row.item_id is None:  # a service: no stock
            if not row.memo.strip():
                raise ValidationError(
                    tr("строка {line}: укажите товар или что за услуга", line=line_no)
                )
        elif self.doc_type == "receipt" and row.item_id is None:  # a service, a fixed asset
            if not row.memo.strip():
                raise ValidationError(
                    tr("строка {line}: укажите товар или что куплено (услуга, ОС)", line=line_no)
                )
            if row.expense_account_id is None:
                raise ValidationError(tr("строка {line}: не указан счёт затрат", line=line_no))
            if self.s.catalog.is_stock_account(row.expense_account_id):
                account = self.s.catalog.accounts[row.expense_account_id]
                raise ValidationError(
                    tr(
                        "строка {line}: счёт {account} складской — выберите товар в колонке "
                        "«Товар», тогда он придёт на склад",
                        line=line_no,
                        account=account.short,
                    )
                )
            self._require_subconto(row.expense_account_id, row.expense_subconto, line_no)
        else:
            if row.warehouse_id is None:
                raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
            if row.quantity is None or row.quantity <= 0:
                raise ValidationError(tr("строка {line}: не указано количество", line=line_no))

    def _require_subconto(self, account_id: int, subconto: list[int | None], line_no: int) -> None:
        """Every subconto of the account but a contract: many suppliers have none, only the
        e-qaimə; reports show such amounts as «not given»."""
        catalog = self.s.catalog
        account = catalog.accounts[account_id]
        for position, kind_id in enumerate(account.sc_kinds):
            # a contract belongs to a counterparty; a kind added to an account with postings
            optional = kind_id in catalog.owner_kinds or position in account.sc_optional
            if kind_id is not None and subconto[position] is None and not optional:
                raise ValidationError(
                    tr(
                        "строка {line}: заполните субконто «{kind}»",
                        line=line_no,
                        kind=self.s.catalog.kinds[kind_id],
                    )
                )
