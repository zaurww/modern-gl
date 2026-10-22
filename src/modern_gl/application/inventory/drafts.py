"""What every warehouse document's draft shares: its header and its lines."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from modern_gl.application.common import insert, now, pad_subconto
from modern_gl.application.inventory.amounts import typed_rate
from modern_gl.application.inventory.base import InventoryBase
from modern_gl.application.inventory.model import (
    VAT_RATE_SCALE,
    InventoryDocumentData,
    InventoryLineData,
    IssueLine,
    LandedCostChargeData,
    LandedCostTarget,
    ReceiptLine,
    SaleLine,
    TransferLine,
)
from modern_gl.domain.dates import iso_date, month_end
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import EQAIME, KINDS, normalize_invoice
from modern_gl.i18n import tr

# the columns of a line a draft writes, in the order _insert_line gives their values
LINE_COLUMNS = (
    "line_no",
    "item_id",
    "warehouse_id",
    "to_warehouse_id",
    "quantity",
    "amount",
    "inventory_amount",
    "expense_amount",
    "offset_account_id",
    "offset_sc1",
    "offset_sc2",
    "offset_sc3",
    "source_receipt_line_id",
    "memo",
    "vat_amount",
    "currency_amount",
    "cost_account_id",
    "cost_sc1",
    "cost_sc2",
    "cost_sc3",
)


class DraftCommands(InventoryBase):
    def load_document(self, company_id: int, document_id: int) -> InventoryDocumentData:
        """Load a warehouse document with its source and calculated line fields."""
        doc = self._document(company_id, document_id)
        rows = self.conn.execute(
            "SELECT * FROM inventory_lines WHERE company_id = ? AND document_id = ? "
            "ORDER BY line_no",
            (company_id, document_id),
        ).fetchall()
        return InventoryDocumentData(
            doc["id"],
            doc["number"],
            doc["doc_date"],
            doc["doc_type"],
            doc["memo"],
            doc["status"],
            doc["landed_cost_type_id"],
            doc["gl_document_id"],
            tuple(
                InventoryLineData(
                    row["id"],
                    row["line_no"],
                    row["item_id"],
                    row["warehouse_id"],
                    row["to_warehouse_id"],
                    row["quantity"],
                    row["amount"],
                    row["inventory_amount"],
                    row["expense_amount"],
                    row["offset_account_id"],
                    (row["offset_sc1"], row["offset_sc2"], row["offset_sc3"]),
                    row["source_receipt_line_id"],
                    row["memo"],
                    row["vat_amount"],
                    row["currency_amount"],
                    row["cost_account_id"],
                    (row["cost_sc1"], row["cost_sc2"], row["cost_sc3"]),
                )
                for row in rows
            ),
            closed=self._closed(doc),
            vat_rate=doc["vat_rate"],
            allocation_method=doc["allocation_method"],
            charges=tuple(
                LandedCostChargeData(
                    row["id"],
                    row["line_no"],
                    row["cost_type_id"],
                    row["account_id"],
                    (row["sc1"], row["sc2"], row["sc3"]),
                    row["amount"],
                    row["vat_amount"],
                    row["source_document_id"],
                    row["source_line_no"],
                    row["memo"],
                    row["currency_id"],
                    row["currency_rate"],
                    row["currency_amount"],
                )
                for row in self._charges(document_id)
            ),
            currency_id=doc["currency_id"],
            currency_rate=doc["currency_rate"],
            invoice=doc["invoice"] or "",
            invoice_kind=doc["invoice_kind"] or "",
            expense_date=doc["expense_date"],
            accrual_document_id=doc["accrual_document_id"],
            incoming_reason=doc["incoming_reason"],
        )

    def _insert_document(
        self,
        company_id: int,
        doc_date: date | str,
        doc_type: str,
        memo: str,
        *,
        cost_type_id: int | None = None,
        incoming_reason: str | None = None,
    ) -> int:
        self._company(company_id)
        value_date = iso_date(doc_date)
        number = self.conn.execute(
            "UPDATE companies SET last_inventory_number = last_inventory_number + 1 "
            "WHERE id = ? RETURNING last_inventory_number",
            (company_id,),
        ).fetchone()[0]
        return insert(
            self.conn,
            "INSERT INTO inventory_documents "
            "(company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id, "
            "incoming_reason, created_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
            (company_id, number, value_date, doc_type, memo, cost_type_id, incoming_reason, now()),
        )

    def _update_draft_header(
        self, company_id: int, document_id: int, doc_date: date | str, memo: str
    ) -> None:
        value_date = iso_date(doc_date)
        self.conn.execute(
            "UPDATE inventory_documents SET doc_date = ?, memo = ? WHERE company_id = ? AND id = ?",
            (value_date, memo.strip(), company_id, document_id),
        )

    def _set_incoming_reason(self, document_id: int, reason: str | None) -> None:
        """A mədaxil's reason (D91): only a mədaxil has one, so it is never cleared here."""
        self.conn.execute(
            "UPDATE inventory_documents SET incoming_reason = ? WHERE id = ?",
            (reason, document_id),
        )

    def _set_vat_rate(self, document_id: int, rate: int | None) -> None:
        if rate is not None and not 0 <= rate <= VAT_RATE_SCALE:
            raise ValidationError(tr("ставка НДС должна быть от 0 до 100%"))
        self.conn.execute(
            "UPDATE inventory_documents SET vat_rate = ? WHERE id = ?", (rate, document_id)
        )

    def _set_currency(
        self,
        company_id: int,
        document_id: int,
        currency_id: int | None,
        rate: str | int | Decimal | None,
    ) -> None:
        if currency_id is None:
            self.conn.execute(
                "UPDATE inventory_documents SET currency_id = NULL, currency_rate = NULL "
                "WHERE id = ?",
                (document_id,),
            )
            return
        if self._document(company_id, document_id)["doc_type"] != "receipt":
            raise ValidationError(tr("в валюте может быть только поступление"))
        self.conn.execute(
            "UPDATE inventory_documents SET currency_id = ?, currency_rate = ? WHERE id = ?",
            (self._currency_id(company_id, currency_id), typed_rate(rate), document_id),
        )

    def _set_invoice(self, document_id: int, invoice: str, kind: str = EQAIME) -> None:
        """The receipt's e-qaimə, or the customs declaration of imported goods."""
        if kind not in KINDS:
            raise ValidationError(tr("неизвестный вид документа: {kind}", kind=kind))
        number = normalize_invoice(invoice)
        self.conn.execute(
            "UPDATE inventory_documents SET invoice = ?, invoice_kind = ? WHERE id = ?",
            (number, (kind or None) if number else None, document_id),
        )

    def _set_expense_date(self, document_id: int, expense_date: date | str | None) -> None:
        """The month a receipt's expense belongs to (D65), kept as its last day."""
        value = None if expense_date is None or expense_date == "" else month_end(expense_date)
        self.conn.execute(
            "UPDATE inventory_documents SET expense_date = ? WHERE id = ?", (value, document_id)
        )

    def _draft_warehouse(self, company_id: int, warehouse_id: int | None) -> int | None:
        return None if warehouse_id is None else self._warehouse(company_id, warehouse_id)["id"]

    def _insert_line(
        self,
        document_id: int,
        company_id: int,
        line_no: int,
        item_id: int | None,
        warehouse_id: int | None,
        to_warehouse_id: int | None,
        quantity: int,
        amount: int,
        inventory_amount: int,
        expense_amount: int,
        offset_account_id: int | None,
        offset_subconto: Sequence[int | None],
        source_receipt_line_id: int | None,
        memo: str,
        *,
        line_id: int | None = None,
        vat_amount: int = 0,
        currency_amount: int | None = None,
        cost_account_id: int | None = None,
        cost_subconto: Sequence[int | None] = (),
    ) -> int:
        values = (
            line_no,
            item_id,
            warehouse_id,
            to_warehouse_id,
            quantity,
            amount,
            inventory_amount,
            expense_amount,
            offset_account_id,
            *pad_subconto(offset_subconto),
            source_receipt_line_id,
            memo,
            vat_amount,
            currency_amount,
            cost_account_id,
            *pad_subconto(cost_subconto),
        )
        if line_id is not None:  # an edited line keeps its id: landed cost refers to it
            updated = self.conn.execute(
                f"UPDATE inventory_lines SET {', '.join(f'{c} = ?' for c in LINE_COLUMNS)} "
                "WHERE company_id = ? AND document_id = ? AND id = ?",
                (*values, company_id, document_id, line_id),
            ).rowcount
            if updated:
                return line_id
        columns = ("company_id", "document_id", *LINE_COLUMNS)
        return insert(
            self.conn,
            f"INSERT INTO inventory_lines ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            (company_id, document_id, *values),
        )

    def _release_lines(
        self,
        company_id: int,
        document_id: int,
        lines: Sequence[ReceiptLine]
        | Sequence[IssueLine]
        | Sequence[TransferLine]
        | Sequence[SaleLine]
        | Sequence[LandedCostTarget],
    ) -> None:
        """Before a draft is rewritten: drop the lines that are gone, renumber the rest
        out of the way (line numbers are unique within a document)."""
        keep = {line.line_id for line in lines if line.line_id is not None}
        self._require_lines_unreferenced(company_id, document_id, keep)
        placeholders = ",".join("?" * len(keep))
        self.conn.execute(
            f"DELETE FROM inventory_lines WHERE document_id = ? AND id NOT IN ({placeholders})",
            (document_id, *keep),
        )
        self.conn.execute(
            "UPDATE inventory_lines SET line_no = -line_no WHERE document_id = ?", (document_id,)
        )

    def _require_lines_unreferenced(
        self, company_id: int, document_id: int, keep: set[int] | tuple[()]
    ) -> None:
        """A receipt line that landed cost was allocated to cannot disappear."""
        used = [
            row
            for row in self.conn.execute(
                """
                SELECT own.id, own.line_no, d.number
                FROM inventory_lines own
                JOIN inventory_lines lc ON lc.source_receipt_line_id = own.id
                JOIN inventory_documents d ON d.id = lc.document_id
                WHERE own.company_id = ? AND own.document_id = ? AND lc.document_id <> ?
                ORDER BY own.line_no
                """,
                (company_id, document_id, document_id),
            )
            if row["id"] not in keep
        ]
        if used:
            raise ValidationError(
                tr(
                    "строка {line}: на неё распределены дополнительные расходы "
                    "(документ №{n}) — сначала удалите их",
                    line=abs(used[0]["line_no"]),
                    n=used[0]["number"],
                )
            )
