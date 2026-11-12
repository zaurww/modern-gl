"""What every warehouse document's draft shares: its header and its lines."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from modern_gl.application.common import now, pad_subconto
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
    ReturnLine,
    SaleLine,
    StoredLine,
    TransferLine,
)
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import EQAIME, KINDS, basis_note, normalize_invoice
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import insert

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
    "expense_date",
)


class DraftCommands(InventoryBase):
    def load_document(self, company_id: int, document_id: int) -> InventoryDocumentData:
        """Load a warehouse document with its source and calculated line fields."""
        doc = self._inventory_document(company_id, document_id)
        rows = self.conn.execute(
            "SELECT * FROM inventory_lines WHERE company_id = ? AND document_id = ? "
            "ORDER BY line_no",
            (company_id, document_id),
        ).fetchall()
        returned = {
            r["line_id"]: r["returned_line_id"]
            for r in self.conn.execute(
                "SELECT line_id, returned_line_id FROM inventory_returns "
                "WHERE company_id = ? AND document_id = ?",
                (company_id, document_id),
            )
        }
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
                    row["expense_date"],
                    returned.get(row["id"]),
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
                    row["source_line_id"],
                )
                for row in self._charges(document_id)
            ),
            currency_id=doc["currency_id"],
            currency_rate=doc["currency_rate"],
            invoice=doc["invoice"] or "",
            invoice_kind=doc["invoice_kind"] or "",
            basis_note=doc["basis_note"] or "",
            accruals=self._accruals(company_id, document_id),
            incoming_reason=doc["incoming_reason"],
            awaits_invoice=doc["awaits_invoice"] == 1,
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

    def _set_incoming_reason(self, company_id: int, document_id: int, reason: str | None) -> None:
        """A mədaxil's reason (D91): only a mədaxil has one, so it is never cleared here."""
        self.conn.execute(
            "UPDATE inventory_documents SET incoming_reason = ? WHERE company_id = ? AND id = ?",
            (reason, company_id, document_id),
        )

    def _set_vat_rate(self, company_id: int, document_id: int, rate: int | None) -> None:
        if rate is not None and not 0 <= rate <= VAT_RATE_SCALE:
            raise ValidationError(tr("ставка НДС должна быть от 0 до 100%"))
        self.conn.execute(
            "UPDATE inventory_documents SET vat_rate = ? WHERE company_id = ? AND id = ?",
            (rate, company_id, document_id),
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
                "WHERE company_id = ? AND id = ?",
                (
                    company_id,
                    document_id,
                ),
            )
            return
        if self._inventory_document(company_id, document_id)["doc_type"] != "receipt":
            raise ValidationError(tr("в валюте может быть только поступление"))
        self.conn.execute(
            "UPDATE inventory_documents SET currency_id = ?, currency_rate = ? "
            "WHERE company_id = ? AND id = ?",
            (
                self._currency(company_id, currency_id)["id"],
                typed_rate(rate),
                company_id,
                document_id,
            ),
        )

    def _set_invoice(
        self,
        company_id: int,
        document_id: int,
        invoice: str,
        kind: str = EQAIME,
        awaits: bool = False,
        note: str = "",
    ) -> None:
        """The receipt's e-qaimə, or the customs declaration of imported goods. `awaits`:
        a purchase without a number waits for its e-qaimə (D119); a number ends the wait.
        `note`: the basis «Digər» — an act, a receipt… named in free text, kept on the
        document only (D-new-basis-other)."""
        if kind not in KINDS:
            raise ValidationError(tr("неизвестный вид документа: {kind}", kind=kind))
        number = normalize_invoice(invoice)
        basis = basis_note(note)
        if basis is not None and (number is not None or awaits):
            raise ValidationError(tr("у документа одно основание: e-qaimə или «Digər»"))
        self.conn.execute(
            "UPDATE inventory_documents SET invoice = ?, invoice_kind = ?, awaits_invoice = ?, "
            "basis_note = ? WHERE company_id = ? AND id = ?",
            (
                number,
                (kind or None) if number else None,
                1 if awaits and number is None else 0,
                basis,
                company_id,
                document_id,
            ),
        )

    def _check_basis_vat(self, company_id: int, document_id: int) -> None:
        """A purchase on «Digər» has no ƏDV to take: without an e-qaimə it is part of the
        cost (D-new-basis-other)."""
        row = self.conn.execute(
            "SELECT d.basis_note, COALESCE(SUM(ABS(l.vat_amount)), 0) AS vat "
            "FROM inventory_documents d LEFT JOIN inventory_lines l "
            "ON l.company_id = d.company_id AND l.document_id = d.id "
            "WHERE d.company_id = ? AND d.id = ? GROUP BY d.id, d.basis_note",
            (company_id, document_id),
        ).fetchone()
        if row["basis_note"] is not None and row["vat"]:
            raise ValidationError(
                tr("покупка по «Digər» — без ƏDV: зачесть его можно только по e-qaimə")
            )

    def _draft_warehouse(self, company_id: int, warehouse_id: int | None) -> int | None:
        return None if warehouse_id is None else self._warehouse(company_id, warehouse_id)["id"]

    def _insert_line(self, document_id: int, company_id: int, line: StoredLine) -> int:
        values = (
            line.line_no,
            line.item_id,
            line.warehouse_id,
            line.to_warehouse_id,
            line.quantity,
            line.amount,
            line.inventory_amount,
            line.expense_amount,
            line.offset_account_id,
            *pad_subconto(line.offset_subconto),
            line.source_receipt_line_id,
            line.memo,
            line.vat_amount,
            line.currency_amount,
            line.cost_account_id,
            *pad_subconto(line.cost_subconto),
            line.expense_date,
        )
        line_id = line.line_id
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
        | Sequence[ReturnLine]
        | Sequence[LandedCostTarget],
    ) -> None:
        """Before a draft is rewritten: drop the lines that are gone, renumber the rest
        out of the way (line numbers are unique within a document)."""
        keep = {line.line_id for line in lines if line.line_id is not None}
        self._require_lines_unreferenced(company_id, document_id, keep)
        placeholders = ",".join("?" * len(keep))
        self.conn.execute(
            "DELETE FROM inventory_lines "
            f"WHERE company_id = ? AND document_id = ? AND id NOT IN ({placeholders})",
            (company_id, document_id, *keep),
        )
        self.conn.execute(
            "UPDATE inventory_lines SET line_no = -line_no "
            "WHERE company_id = ? AND document_id = ?",
            (
                company_id,
                document_id,
            ),
        )

    def _require_lines_not_returned(
        self, company_id: int, document_id: int, keep: set[int] | tuple[()]
    ) -> None:
        returned = [
            row
            for row in self.conn.execute(
                """
                SELECT own.id, own.line_no, d.number
                FROM inventory_lines own
                JOIN inventory_returns r ON r.company_id = own.company_id
                 AND r.returned_line_id = own.id
                JOIN inventory_documents d ON d.id = r.document_id
                WHERE own.company_id = ? AND own.document_id = ? AND r.document_id <> ?
                ORDER BY own.line_no
                """,
                (company_id, document_id, document_id),
            )
            if row["id"] not in keep
        ]
        if returned:
            raise ValidationError(
                tr(
                    "строка {line}: по ней оформлен возврат №{n} — сначала удалите его",
                    line=abs(returned[0]["line_no"]),
                    n=returned[0]["number"],
                )
            )

    def _require_lines_not_charged(
        self,
        company_id: int,
        document_id: int,
        keep: set[int] | tuple[()],
        posted_only: bool = False,
    ) -> None:
        """A service line a batch took as its expense stays until it is out of the batch;
        `posted_only` — a posted batch: a purchase is not unposted from under it."""
        for row in self.conn.execute(
            """
            SELECT own.id, own.line_no, d.number, d.status
            FROM inventory_lines own
            JOIN landed_cost_charge_lines k
              ON k.company_id = own.company_id AND k.source_line_id = own.id
            JOIN landed_cost_charges c ON c.company_id = k.company_id AND c.id = k.charge_id
            JOIN inventory_documents d ON d.company_id = c.company_id AND d.id = c.document_id
            WHERE own.company_id = ? AND own.document_id = ?
            ORDER BY own.line_no
            """,
            (company_id, document_id),
        ):
            if row["id"] not in keep and (row["status"] == "posted" or not posted_only):
                raise ValidationError(
                    tr(
                        "строка {line}: она взята расходом партии (документ №{n}) — "
                        "сначала уберите её оттуда",
                        line=abs(row["line_no"]),
                        n=row["number"],
                    )
                )

    def _require_lines_unreferenced(
        self, company_id: int, document_id: int, keep: set[int] | tuple[()]
    ) -> None:
        """A receipt line that landed cost was allocated to, a purchase (sale) line a
        return names, cannot disappear."""
        self._require_lines_not_returned(company_id, document_id, keep)
        self._require_lines_not_charged(company_id, document_id, keep)
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
