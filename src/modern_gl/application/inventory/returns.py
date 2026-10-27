"""Returns (D153): goods back to the supplier and goods back from a customer — posted the
other way round from their purchase or sale, with the number of the return e-qaimə
(«malların geri qaytarılması»), so the ƏDV reports and the portal see the same.

Back to the supplier: the goods leave at the average cost (as a write-off), the supplier
owes the price of the return (Dt 60 / Ct 41); a price above or below the cost is other
income or expense; the input ƏDV goes back (Dt 60 / Ct 19). Back from a customer: the
revenue and its ƏDV go back (Dt 46 / Ct 62, Dt 68.2 / Ct 46 or 62), the goods come in at
the cost they were sold at (Dt 41 / Ct the cost of sales) — that sale's when the line
names it, else the average on the warehouse."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory.amounts import (
    blank,
    draft_quantity,
    format_quantity,
    money,
    nonnegative_amount,
    positive_amount,
)
from modern_gl.application.inventory.model import (
    PURCHASE_RETURN,
    RETURN_TYPES,
    SALE_RETURN,
    ReturnLine,
)
from modern_gl.application.inventory.sales import SaleCommands
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import (
    COST_OF_SALES,
    FX_GAIN,
    FX_LOSS,
    OUTPUT_VAT,
    SALES_REVENUE,
    SALES_VAT,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction


class ReturnCommands(SaleCommands):
    def create_return_draft(
        self,
        company_id: int,
        doc_date: date | str,
        doc_type: str,
        lines: Sequence[ReturnLine],
        party_account_id: int | None,
        party_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        invoice: str = "",
    ) -> int:
        """Save a return to the supplier (`purchase_return`) or from a customer
        (`sale_return`) without affecting stock or GL; a draft may be unfinished."""
        if doc_type not in RETURN_TYPES:
            raise ValidationError(tr("неизвестный вид возврата"))
        with transaction(self.conn):
            document_id = self._insert_document(company_id, doc_date, doc_type, memo)
            self._set_vat_rate(document_id, vat_rate)
            self._set_invoice(document_id, invoice)
            self._write_return_draft(
                company_id, document_id, doc_type, lines, party_account_id, party_subconto
            )
            self._audit(
                company_id, "inventory_document", document_id, "create_draft", {"type": doc_type}
            )
        return document_id

    def update_return_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[ReturnLine],
        party_account_id: int | None,
        party_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        invoice: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] not in RETURN_TYPES:
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._set_vat_rate(document_id, vat_rate)
            self._set_invoice(document_id, invoice)
            self._write_return_draft(
                company_id,
                document_id,
                doc["doc_type"],
                lines,
                party_account_id,
                party_subconto,
            )

    def post_return(
        self,
        company_id: int,
        doc_date: date | str,
        doc_type: str,
        lines: Sequence[ReturnLine],
        party_account_id: int,
        party_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        invoice: str = "",
    ) -> int:
        with transaction(self.conn):
            document_id = self.create_return_draft(
                company_id,
                doc_date,
                doc_type,
                lines,
                party_account_id,
                party_subconto,
                memo,
                vat_rate=vat_rate,
                invoice=invoice,
            )
            self._post_in_sequence(company_id, document_id)
        return document_id

    def returnable(self, company_id: int, line_id: int) -> int:
        """How much of a posted purchase's (sale's) line is still not returned."""
        line = self.conn.execute(
            "SELECT quantity FROM inventory_lines WHERE company_id = ? AND id = ?",
            (company_id, line_id),
        ).fetchone()
        returned = self.conn.execute(
            """
            SELECT COALESCE(SUM(l.quantity), 0) FROM inventory_returns r
            JOIN inventory_lines l ON l.company_id = r.company_id AND l.id = r.line_id
            JOIN inventory_documents d ON d.id = r.document_id AND d.status = 'posted'
            WHERE r.company_id = ? AND r.returned_line_id = ?
            """,
            (company_id, line_id),
        ).fetchone()[0]
        return (line["quantity"] if line else 0) - returned

    # ---- the draft -------------------------------------------------------------------

    def _write_return_draft(
        self,
        company_id: int,
        document_id: int,
        doc_type: str,
        lines: Sequence[ReturnLine],
        party_account_id: int | None,
        party_subconto: Sequence[int | None],
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        self._release_lines(company_id, document_id, lines)
        self.conn.execute("DELETE FROM inventory_returns WHERE document_id = ?", (document_id,))
        for line_no, source in enumerate(lines, 1):
            if source.item_id is None:
                raise ValidationError(tr("строка {line}: укажите товар", line=line_no))
            item = self._item(company_id, source.item_id)
            sale_sc: tuple[int | None, ...] = ()
            if source.returned_line_id is not None:
                returned = self._returned_line(company_id, doc_type, source, line_no)
                if doc_type == SALE_RETURN:  # the sale's own subconto (a sales group, D61)
                    sale_sc = (returned["cost_sc1"], returned["cost_sc2"], returned["cost_sc3"])
            account_id = source.party_account_id or party_account_id
            if account_id is not None:
                self._account(company_id, account_id)
            line_id = self._insert_line(
                document_id,
                company_id,
                line_no,
                source.item_id,
                self._draft_warehouse(company_id, source.warehouse_id),
                None,
                draft_quantity(item, source.quantity, line_no),
                0 if blank(source.amount) else positive_amount(source.amount, line_no),
                0,
                0,
                account_id,
                pad_subconto(source.party_subconto or party_subconto),
                None,
                source.memo.strip(),
                line_id=source.line_id,
                vat_amount=(
                    0
                    if source.vat_amount is None or blank(source.vat_amount)
                    else nonnegative_amount(source.vat_amount)
                ),
                cost_subconto=sale_sc,
            )
            if source.returned_line_id is not None:
                self.conn.execute(
                    "INSERT INTO inventory_returns "
                    "(company_id, document_id, line_id, returned_line_id) VALUES (?, ?, ?, ?)",
                    (company_id, document_id, line_id, source.returned_line_id),
                )

    def _returned_line(self, company_id: int, doc_type: str, source: ReturnLine, line_no: int):
        """The line a return names: a posted purchase (sale) line of the same item."""
        row = self.conn.execute(
            """
            SELECT l.*, d.number FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE l.company_id = ? AND l.id = ? AND d.status = 'posted' AND d.doc_type = ?
            """,
            (company_id, source.returned_line_id, RETURN_TYPES[doc_type]),
        ).fetchone()
        if row is None or row["item_id"] != source.item_id:
            raise ValidationError(
                tr("строка {line}: возвращаемая строка документа не найдена", line=line_no)
            )
        return row

    def _return_link(self, company_id: int, line_id: int) -> Row | None:
        """The purchase's (sale's) line a return line returns, if it names one."""
        return self.conn.execute(
            """
            SELECT o.*, d.number FROM inventory_returns r
            JOIN inventory_lines o ON o.company_id = r.company_id AND o.id = r.returned_line_id
            JOIN inventory_documents d ON d.id = o.document_id
            WHERE r.company_id = ? AND r.line_id = ?
            """,
            (company_id, line_id),
        ).fetchone()

    # ---- posting -----------------------------------------------------------------------

    def _apply_return(self, company_id: int, doc: Row, lines: Sequence[Row]) -> list[PostingInput]:
        invoice = doc["invoice"] or ""
        postings: list[PostingInput] = []
        vat_items: list[tuple[int, tuple[int | None, ...], int]] = []
        for line in lines:
            self._require_return_line(company_id, line)
            if doc["doc_type"] == PURCHASE_RETURN:
                postings += self._purchase_return_line(company_id, doc, line, invoice)
            else:
                postings += self._sale_return_line(company_id, doc, line, invoice)
            party_sc = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
            vat_items.append((line["offset_account_id"], party_sc, line["vat_amount"]))
        if doc["doc_type"] == PURCHASE_RETURN:
            # the input ƏDV goes back: Dt the supplier / Ct input ƏDV
            postings += [
                PostingInput(p.credit_account_id, p.debit_account_id, p.amount,
                             p.credit_subconto, p.debit_subconto, p.memo, invoice=invoice)
                for p in self._vat_postings(company_id, (invoice, ""), vat_items)
            ]  # fmt: skip
        else:
            postings += self._sale_return_vat(company_id, invoice, lines)
        return postings

    def _require_return_line(self, company_id: int, line: Row) -> None:
        line_no = line["line_no"]
        if line["item_id"] is None or line["warehouse_id"] is None:
            raise ValidationError(tr("строка {line}: укажите товар и склад", line=line_no))
        if line["quantity"] <= 0:
            raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
        if line["amount"] <= 0:
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        if line["offset_account_id"] is None:
            raise ValidationError(tr("строка {line}: не указан контрагент", line=line_no))
        link = self._return_link(company_id, line["id"])
        if link is not None and line["quantity"] > self.returnable(company_id, link["id"]):
            item = self._item(company_id, line["item_id"])
            raise ValidationError(
                tr(
                    "строка {line}: по документу №{n} можно вернуть не больше {q}",
                    line=line_no,
                    n=link["number"],
                    q=self._quantity_text(item, self.returnable(company_id, link["id"])),
                )
            )

    @staticmethod
    def _quantity_text(item: Row, quantity: int) -> str:
        return format_quantity(quantity, item["unit_precision"])

    def _purchase_return_line(
        self, company_id: int, doc: Row, line: Row, invoice: str
    ) -> list[PostingInput]:
        """The goods leave at the average cost; the supplier owes the return's price; the
        difference is other income (a higher price) or expense (a lower one)."""
        item = self._item(company_id, line["item_id"])
        warehouse = self._warehouse(company_id, line["warehouse_id"])
        cost = self._cost(company_id, item, warehouse, line["quantity"], doc["id"])
        self._consume_receipts(company_id, doc["id"], line["id"], item["id"], line["quantity"])
        self._insert_movement(
            company_id, doc["id"], line["id"], doc["doc_date"], item["id"], warehouse["id"],
            "issue", -line["quantity"], -cost,
        )  # fmt: skip
        self.conn.execute(
            "UPDATE inventory_lines SET inventory_amount = ? WHERE id = ?", (cost, line["id"])
        )
        party = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
        stock = self._inventory_subconto(company_id, item, warehouse)
        memo = line["memo"] or item["name"]
        amount = line["amount"]
        postings = [
            PostingInput(
                line["offset_account_id"], item["inventory_account_id"], money(min(amount, cost)),
                party, stock, memo, invoice=invoice,
            )
        ]  # fmt: skip
        if amount > cost:
            postings.append(
                PostingInput(
                    line["offset_account_id"], self._difference_account(company_id, FX_GAIN),
                    money(amount - cost), party, (), tr("Разница цены возврата"), invoice=invoice,
                )
            )  # fmt: skip
        elif amount < cost:
            postings.append(
                PostingInput(
                    self._difference_account(company_id, FX_LOSS), item["inventory_account_id"],
                    money(cost - amount), (), stock, tr("Разница цены возврата"),
                )
            )  # fmt: skip
        return postings

    def _difference_account(self, company_id: int, role: str) -> int:
        account_id = self.ledger.account_role(company_id, role)
        if account_id is None:
            raise ValidationError(
                tr("цена возврата не равна себестоимости, а счёта прочих доходов/расходов нет")
            )
        return account_id

    def _sale_return_line(
        self, company_id: int, doc: Row, line: Row, invoice: str
    ) -> list[PostingInput]:
        """The revenue goes back (Dt revenue / Ct the customer, with the ƏDV when it is
        charged from another account); the goods come back at the cost they left at."""
        item = self._item(company_id, line["item_id"])
        warehouse = self._warehouse(company_id, line["warehouse_id"])
        cost = self._returned_cost(company_id, doc, line, item, warehouse)
        revenue_id = self._sale_account(company_id, SALES_REVENUE)
        cost_id = self._sale_account(company_id, COST_OF_SALES)
        sales_vat_id = self.ledger.account_role(company_id, SALES_VAT)
        self.conn.execute(
            "UPDATE inventory_lines SET inventory_amount = ?, cost_account_id = ? WHERE id = ?",
            (cost, cost_id, line["id"]),
        )
        self._insert_movement(
            company_id, doc["id"], line["id"], doc["doc_date"], item["id"], warehouse["id"],
            "receipt", line["quantity"], cost,
        )  # fmt: skip
        values = self._sale_values(company_id, line)
        customer = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
        memo = line["memo"] or item["name"]
        return [
            PostingInput(
                revenue_id, line["offset_account_id"],
                money(line["amount"] + (line["vat_amount"] if sales_vat_id else 0)),
                self._sale_side(company_id, revenue_id, values, line["line_no"]), customer, memo,
                invoice=invoice,
            ),
            PostingInput(
                item["inventory_account_id"], cost_id, money(cost),
                self._inventory_subconto(company_id, item, warehouse),
                self._sale_side(company_id, cost_id, values, line["line_no"]), memo,
            ),
        ]  # fmt: skip

    def _returned_cost(self, company_id: int, doc: Row, line: Row, item: Row, warehouse: Row):
        """The cost the goods left at: the named sale's (with the expenses of its batch
        that came later), else the average on the warehouse that day."""
        link = self._return_link(company_id, line["id"])
        if link is not None:
            late = self.conn.execute(
                "SELECT COALESCE(SUM(a.amount), 0) FROM landed_cost_expense_allocations a "
                "JOIN inventory_documents d ON d.id = a.document_id AND d.status = 'posted' "
                "WHERE a.company_id = ? AND a.issue_line_id = ?",
                (company_id, link["id"]),
            ).fetchone()[0]
            return round_ratio((link["expense_amount"] + late) * line["quantity"], link["quantity"])
        quantity, value = self._balance(company_id, item["id"], warehouse["id"], doc["id"])
        if quantity <= 0 or value <= 0:
            raise ValidationError(
                tr(
                    "строка {line}: «{item}» нет на складе, себестоимость не из чего взять — "
                    "укажите продажу, по которой возврат",
                    line=line["line_no"],
                    item=item["name"],
                )
            )
        return round_ratio(value * line["quantity"], quantity)

    def _sale_return_vat(self, company_id: int, invoice: str, lines: Sequence[Row]):
        """The ƏDV back: Dt output ƏDV / Ct the account it was charged from (the customer's
        own when none is chosen), one posting per account and customer."""
        sales_vat_id = self.ledger.account_role(company_id, SALES_VAT)
        totals: dict[tuple[int, tuple[int | None, ...], tuple[int | None, ...]], int] = {}
        for line in lines:
            if not line["vat_amount"]:
                continue
            customer = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
            credit_sc = (
                customer
                if sales_vat_id is None
                else self._sale_side(
                    company_id, sales_vat_id, self._sale_values(company_id, line), line["line_no"]
                )
            )
            key = (sales_vat_id or line["offset_account_id"], tuple(credit_sc), customer)
            totals[key] = totals.get(key, 0) + line["vat_amount"]
        if not totals:
            return []
        vat_id = self._sale_account(company_id, OUTPUT_VAT)
        return [
            PostingInput(
                vat_id, credit_id, money(amount), self._by_kind(company_id, vat_id, customer),
                credit_sc, tr("НДС"), invoice=invoice,
            )
            for (credit_id, credit_sc, customer), amount in totals.items()
        ]  # fmt: skip

    # ---- made by the posting group -----------------------------------------------------

    def _post_in_sequence(self, company_id: int, document_id: int) -> None:
        raise NotImplementedError
