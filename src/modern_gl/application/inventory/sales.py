"""Sales of goods and services: revenue, VAT and the cost of what is sold (D61)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from modern_gl.application.common import account_kinds, pad_subconto
from modern_gl.application.inventory.amounts import (
    blank,
    draft_quantity,
    money,
    nonnegative_amount,
    positive_amount,
    service_quantity,
)
from modern_gl.application.inventory.model import SALE_ROLE_NAMES, Movement, SaleLine, StoredLine
from modern_gl.application.inventory.stock import StockCommands
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import COST_OF_SALES, OUTPUT_VAT, SALES_REVENUE, SALES_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import Row, transaction


def require_sale_line(line: Row) -> None:
    line_no = line["line_no"]
    if line["item_id"] is not None:
        if line["warehouse_id"] is None:
            raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
        if line["quantity"] <= 0:
            raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
    elif not line["memo"]:
        raise ValidationError(tr("строка {line}: укажите товар или что за услуга", line=line_no))
    if line["amount"] <= 0:
        raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
    if line["offset_account_id"] is None:
        raise ValidationError(tr("строка {line}: не указан счёт покупателя", line=line_no))


class SaleCommands(StockCommands):
    def create_sale_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[SaleLine],
        customer_account_id: int | None,
        customer_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        invoice: str = "",
    ) -> int:
        """Save an editable sale without affecting stock or GL. A draft may be unfinished:
        a line needs only an item or, for a service, an amount or a memo."""
        with transaction(self.conn):
            document_id = self._insert_document(company_id, doc_date, "sale", memo)
            self._set_vat_rate(document_id, vat_rate)
            self._set_invoice(document_id, invoice)
            self._write_sale_draft(
                company_id, document_id, lines, customer_account_id, customer_subconto
            )
            self._audit(
                company_id, "inventory_document", document_id, "create_draft", {"type": "sale"}
            )
        return document_id

    def update_sale_draft(  # noqa: PLR0913 the sale form's header fields, by keyword
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[SaleLine],
        customer_account_id: int | None,
        customer_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        invoice: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "sale":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._set_vat_rate(document_id, vat_rate)
            self._set_invoice(document_id, invoice)
            self._release_lines(company_id, document_id, lines)
            self._write_sale_draft(
                company_id, document_id, lines, customer_account_id, customer_subconto
            )
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def _write_sale_draft(
        self,
        company_id: int,
        document_id: int,
        lines: Sequence[SaleLine],
        customer_account_id: int | None,
        customer_subconto: Sequence[int | None],
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        for line_no, source in enumerate(lines, 1):
            if source.item_id is None:  # a service: no stock
                if source.warehouse_id is not None:
                    raise ValidationError(tr("строка {line}: у услуги нет склада", line=line_no))
                warehouse_id = None
                quantity = service_quantity(source.quantity, line_no)
            else:
                item = self._item(company_id, source.item_id)
                warehouse_id = self._draft_warehouse(company_id, source.warehouse_id)
                quantity = draft_quantity(item, source.quantity, line_no)
            amount = 0 if blank(source.amount) else positive_amount(source.amount, line_no)
            vat = (
                0
                if source.vat_amount is None or blank(source.vat_amount)
                else nonnegative_amount(source.vat_amount)
            )
            account_id = source.customer_account_id or customer_account_id
            if account_id is not None:
                self._account(company_id, account_id)
            sale_sc = [value for value in source.sale_subconto if value is not None]
            kinds = [self._subconto_value(company_id, value)["kind_id"] for value in sale_sc]
            if len(set(kinds)) != len(kinds) or len(kinds) > 3:
                raise ValidationError(
                    tr("строка {line}: лишние значения субконто продажи", line=line_no)
                )
            self._insert_line(
                document_id,
                company_id,
                StoredLine(
                    line_no,
                    source.item_id,
                    warehouse_id,
                    quantity,
                    source.memo.strip(),
                    amount=amount,
                    offset_account_id=account_id,
                    offset_subconto=pad_subconto(source.customer_subconto or customer_subconto),
                    line_id=source.line_id,
                    vat_amount=vat,
                    cost_subconto=sale_sc,
                ),
            )

    def fill_sale_subconto(
        self, company_id: int, document_id: int, line_id: int, subconto: Sequence[int | None]
    ) -> None:
        """Give a sale draft's line without its own subconto the sale subconto (a sales
        group, D61) — drafts posted in bulk (D87). A line that has one is left as it is."""
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "sale":
                raise ValidationError(tr("аналитика продажи указывается только в продаже"))
            for value_id in subconto:
                if value_id is not None:
                    self._subconto_value(company_id, value_id)
            self.conn.execute(
                "UPDATE inventory_lines SET cost_sc1 = ?, cost_sc2 = ?, cost_sc3 = ? "
                "WHERE company_id = ? AND document_id = ? AND id = ? "
                "AND cost_sc1 IS NULL AND cost_sc2 IS NULL AND cost_sc3 IS NULL",
                (*pad_subconto(subconto), company_id, document_id, line_id),
            )
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "fill_sale_subconto",
                {"line_id": line_id, "subconto": list(subconto)},
            )

    def sale_kinds(self, company_id: int) -> list[int]:
        """The subconto kinds a sale line is asked for (D61): those of the sale accounts
        (revenue, cost of sales, the VAT charge) but the item and the warehouse, which the
        line gives itself. A kind the customer's account has comes from the customer."""
        result: list[int] = []
        for role in (SALES_REVENUE, COST_OF_SALES, SALES_VAT):
            account_id = self.ledger.account_role(company_id, role)
            if account_id is None:
                continue
            account = self._account(company_id, account_id)
            codes = self._account_kind_codes(company_id, account)
            for kind_id, code in zip(account_kinds(account), codes, strict=True):
                if kind_id not in (None, *result) and code not in {"item", "warehouse"}:
                    result.append(kind_id)
        return result

    def _apply_sale(self, company_id: int, doc: Row, lines: Sequence[Row]) -> list[PostingInput]:
        """A sale's postings: Dr customer / Cr revenue for each line (with its VAT when the
        VAT is charged from another account), the VAT to pay once per customer (and per
        subconto of the VAT charge account), and for goods Dr cost of sales / Cr inventory
        at the average cost. The sale accounts take their subconto by kind from the
        customer's, the item's, the warehouse's and the line's own values (D61)."""
        revenue_id = self._sale_account(company_id, SALES_REVENUE)
        sales_vat_id = self.ledger.account_role(company_id, SALES_VAT)
        invoice = doc["invoice"] or ""
        revenue: list[PostingInput] = []
        costs: list[PostingInput] = []
        vat: dict[tuple[int, tuple[int | None, ...], tuple[int | None, ...]], int] = {}
        for line in lines:
            require_sale_line(line)
            customer_sc = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
            values = self._sale_values(company_id, line)
            memo = line["memo"]
            if line["item_id"] is not None:
                item = self._item(company_id, line["item_id"])
                memo = memo or item["name"]
                costs.append(self._sale_cost(company_id, doc, line, item, memo, values))
            revenue.append(
                PostingInput(
                    line["offset_account_id"],
                    revenue_id,
                    money(line["amount"] + (line["vat_amount"] if sales_vat_id else 0)),
                    customer_sc,
                    self._sale_side(company_id, revenue_id, values, line["line_no"]),
                    memo,
                    invoice=invoice,
                )
            )
            if line["vat_amount"]:
                debit_sc = (
                    customer_sc
                    if sales_vat_id is None
                    else self._sale_side(company_id, sales_vat_id, values, line["line_no"])
                )
                key = (sales_vat_id or line["offset_account_id"], debit_sc, customer_sc)
                vat[key] = vat.get(key, 0) + line["vat_amount"]
        return revenue + self._sale_vat(company_id, invoice, vat) + costs

    def _sale_side(
        self, company_id: int, account_id: int, values: Sequence[int | None], line_no: int
    ) -> tuple[int | None, ...]:
        """The account's subconto filled by kind from `values`; a kind none of them gives
        is asked for by name, unless it may stay empty (a contract; a kind added when the
        account had postings already)."""
        account = self._account(company_id, account_id)
        result = self._by_kind(company_id, account_id, values)
        for position, (kind_id, value_id) in enumerate(
            zip(account_kinds(account), result, strict=True)
        ):
            if kind_id is None or value_id is not None:
                continue
            kind = self.conn.execute(
                "SELECT name, owner_kind_id FROM subconto_kinds WHERE id = ?", (kind_id,)
            ).fetchone()
            if kind["owner_kind_id"] is None and not account["sc_optional"] & (1 << position):
                raise ValidationError(
                    tr(
                        "строка {line}: укажите «{kind}» — его требует счёт {account}",
                        line=line_no,
                        kind=kind["name"],
                        account=account["code"] or account["name"],
                    )
                )
        return result

    def _sale_cost(
        self,
        company_id: int,
        doc: Row,
        line: Row,
        item: Row,
        memo: str,
        values: Sequence[int | None],
    ) -> PostingInput:
        """Take a goods line from stock: its movement, and Dr cost of sales / Cr inventory."""
        warehouse = self._warehouse(company_id, line["warehouse_id"])
        cost_id = self._sale_account(company_id, COST_OF_SALES)
        amount = self._cost(company_id, item, warehouse, line["quantity"], doc["id"])
        self.conn.execute(
            "UPDATE inventory_lines SET expense_amount = ?, cost_account_id = ? WHERE id = ?",
            (amount, cost_id, line["id"]),
        )
        self._consume_receipts(company_id, doc["id"], line["id"], item["id"], line["quantity"])
        self._insert_movement(
            company_id,
            doc["id"],
            line["id"],
            doc["doc_date"],
            Movement(item["id"], warehouse["id"], "issue", -line["quantity"], -amount),
        )
        return PostingInput(
            cost_id,
            item["inventory_account_id"],
            money(amount),
            self._sale_side(company_id, cost_id, values, line["line_no"]),
            self._inventory_subconto(company_id, item, warehouse),
            memo,
        )

    def _sale_vat(
        self,
        company_id: int,
        invoice: str,
        totals: Mapping[tuple[int, tuple[int | None, ...], tuple[int | None, ...]], int],
    ) -> list[PostingInput]:
        """The VAT to pay: Dr the account it is charged from (the customer's own when none
        is chosen) / Cr output VAT, one posting per debit account with its subconto and
        customer. The output VAT account takes the customer's subconto by kind."""
        if not totals:
            return []
        vat_id = self._sale_account(company_id, OUTPUT_VAT)
        return [
            PostingInput(
                debit_id,
                vat_id,
                money(amount),
                debit_sc,
                self._by_kind(company_id, vat_id, customer_sc),
                trd("НДС"),
                invoice=invoice,
            )
            for (debit_id, debit_sc, customer_sc), amount in totals.items()
        ]

    def _sale_account(self, company_id: int, role: str) -> int:
        account_id = self.ledger.account_role(company_id, role)
        if account_id is None:
            raise ValidationError(
                tr(
                    "не указан счёт «{role}» — выберите его в настройках склада",
                    role=tr(SALE_ROLE_NAMES[role]),
                )
            )
        return account_id
