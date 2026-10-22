"""Posting in date order: a document goes into its place in the sequence and
every later one is recalculated."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from modern_gl.application.common import now
from modern_gl.application.inventory.accruals import AccrualCommands
from modern_gl.application.inventory.landed_cost import LandedCostCommands
from modern_gl.application.inventory.model import (
    IssueLine,
    LandedCostCharge,
    LandedCostTarget,
    ReceiptLine,
    SaleLine,
    TransferLine,
)
from modern_gl.application.inventory.movements import MovementCommands
from modern_gl.application.inventory.sales import SaleCommands
from modern_gl.application.ledger import PostingInput
from modern_gl.application.ledger.documents import explain_owner
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction

# Within one day, arrivals come before what leaves: the sequence of posting is
# (date, rank, number). There is no time of day.
_SEQUENCE_RANK = {
    "opening": 0,
    "receipt": 1,
    "landed_cost": 2,
    "transfer": 3,
    "issue": 3,
    "sale": 3,
}


def _sequence_key(doc: Row) -> tuple[str, int, int]:
    return doc["doc_date"], _SEQUENCE_RANK[doc["doc_type"]], doc["number"]


explain_owner(
    "inventory",
    lambda _role, _n, m: tr(
        "бухгалтерский документ создан складским документом №{n}; исправьте его через склад",
        n=m,
    ),
)


class PostingCommands(MovementCommands, SaleCommands, LandedCostCommands, AccrualCommands):
    def post_document(self, company_id: int, document_id: int) -> None:
        """Post a saved warehouse draft and calculate all derived amounts atomically.

        A draft dated before already posted documents goes into its place in the sequence:
        the later documents are recalculated (their cost may change)."""
        with transaction(self.conn):
            self._require_inventory_draft(company_id, document_id)
            self._post_in_sequence(company_id, document_id)

    def post_receipt(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[ReceiptLine],
        credit_account_id: int,
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
        """Post a receipt/opening balance and its Dr inventory / Cr offset entries
        (and Dr input VAT / Cr offset for the lines' VAT). With `expense_date` the
        lines without an item are an expense of that earlier month (D65)."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self.create_receipt_draft(
                company_id,
                doc_date,
                lines,
                credit_account_id,
                credit_subconto,
                memo,
                opening=opening,
                vat_rate=vat_rate,
                currency_id=currency_id,
                currency_rate=currency_rate,
                invoice=invoice,
                invoice_kind=invoice_kind,
                expense_date=expense_date,
            )
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    def post_issue(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[IssueLine],
        memo: str = "",
    ) -> int:
        """Issue stock at the moving weighted-average cost."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self.create_issue_draft(company_id, doc_date, lines, memo)
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    def post_transfer(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[TransferLine],
        memo: str = "",
    ) -> int:
        """Move stock between warehouses without changing company-wide quantity/value."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self.create_transfer_draft(company_id, doc_date, lines, memo)
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    def post_sale(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[SaleLine],
        customer_account_id: int,
        customer_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        invoice: str = "",
    ) -> int:
        """Post a sale: Dr customer / Cr revenue for each line, the VAT to pay, and for goods
        Dr cost of sales / Cr inventory at the moving weighted-average cost."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self.create_sale_draft(
                company_id,
                doc_date,
                lines,
                customer_account_id,
                customer_subconto,
                memo,
                vat_rate=vat_rate,
                invoice=invoice,
            )
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    def post_landed_cost(
        self,
        company_id: int,
        doc_date: date | str,
        receipt_line_ids: Sequence[int],
        total_amount: str | int | Decimal,
        credit_account_id: int,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        method: str = "value",
        manual_amounts: Mapping[int, str | int | Decimal] | None = None,
        cost_type_id: int | None = None,
    ) -> int:
        """Post one expense allocated to receipt lines (a «Расходы по партии» document
        with a single charge). If part of a receipt has already been issued, that share
        is posted to the original issue expense account."""
        ids = list(dict.fromkeys(receipt_line_ids))
        if not ids:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        if method == "manual" and (manual_amounts is None or set(manual_amounts) != set(ids)):
            raise ValidationError(tr("ручные суммы заданы не для всех поступлений"))
        manual = manual_amounts or {}
        with transaction(self.conn):
            inv_id = self.create_landed_cost_draft(
                company_id,
                doc_date,
                [LandedCostTarget(i, manual.get(i)) for i in ids],
                [
                    LandedCostCharge(
                        total_amount,
                        credit_account_id,
                        credit_subconto,
                        cost_type_id=cost_type_id,
                    )
                ],
                method,
                memo,
                cost_type_id=cost_type_id,
            )
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    @contextmanager
    def reposting(self, company_id: int, document_id: int) -> Iterator[None]:
        """Edit a posted document in place, as in 1C.

        Inside the block the document is a draft (`update_*_draft` works on it); on exit it
        is posted again, keeping its number and its GL document, and every later warehouse
        document is recalculated. Any error rolls everything back."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            if doc["status"] != "posted":
                raise ValidationError(tr("складской документ не проведён"))
            self._require_open_period(doc)
            snapshot = self._snapshot(doc)
            later = self._withdraw_after(company_id, doc)
            self._withdraw(company_id, doc)
            yield
            edited = self._require_inventory_draft(company_id, document_id)
            self._require_open_period(edited)
            later += self._withdraw_after(company_id, edited)  # it may have moved earlier
            self._apply_in_order(company_id, document_id, later)
            self._audit(company_id, "inventory_document", document_id, "repost", snapshot)

    def unpost_document(self, company_id: int, document_id: int) -> None:
        """Return a posted warehouse document to an editable draft in an open period.
        Later documents are recalculated without it."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            if doc["status"] != "posted":
                raise ValidationError(tr("складской документ уже является черновиком"))
            snapshot = self._snapshot(doc)
            self._unpost(company_id, doc)
            self._audit(company_id, "inventory_document", document_id, "unpost", snapshot)

    def delete_document(self, company_id: int, document_id: int) -> None:
        """Remove an inventory document (a posted one in an open period), with a full
        audit copy. Later documents are recalculated without it."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            snapshot = self._snapshot(doc)
            if doc["status"] == "posted":
                self._unpost(company_id, doc)
            self._require_lines_unreferenced(company_id, document_id, keep=())
            self.conn.execute("DELETE FROM inventory_documents WHERE id = ?", (document_id,))
            self._audit(company_id, "inventory_document", document_id, "delete", snapshot)

    def _post_in_sequence(self, company_id: int, document_id: int) -> None:
        """Post a draft into its place in the date order, recalculating later documents."""
        doc = self._document(company_id, document_id)
        self._apply_in_order(company_id, document_id, self._withdraw_after(company_id, doc))

    def _unpost(self, company_id: int, doc: Row) -> None:
        """Take a posted document out of the sequence: it becomes a draft without GL
        postings, and the documents after it are recalculated without it."""
        self._require_open_period(doc)
        later = self._withdraw_after(company_id, doc)
        self._withdraw(company_id, doc)
        gl_document_id = doc["gl_document_id"]
        self.conn.execute(
            "UPDATE inventory_documents SET gl_document_id = NULL, posted_at = NULL WHERE id = ?",
            (doc["id"],),
        )
        if gl_document_id is not None:
            self.ledger.delete_document(company_id, gl_document_id)
        if doc["accrual_document_id"] is not None:
            self._drop_accrual(company_id, doc)
        self._apply_in_order(company_id, None, later)

    def _withdraw_after(self, company_id: int, doc: Row) -> list[int]:
        """Withdraw every posted document that comes after `doc` (latest first)."""
        key = _sequence_key(doc)
        later = sorted(
            (
                row
                for row in self.conn.execute(
                    "SELECT * FROM inventory_documents "
                    "WHERE company_id = ? AND status = 'posted' AND doc_date >= ? AND id <> ?",
                    (company_id, doc["doc_date"], doc["id"]),
                )
                if _sequence_key(row) > key
            ),
            key=_sequence_key,
            reverse=True,
        )
        for row in later:
            self._withdraw(company_id, row)
        return [row["id"] for row in later]

    def _withdraw(self, company_id: int, doc: Row) -> None:
        """Remove the stock effect of a posted document; it stays a draft that still
        points to its GL document, so posting it again keeps that document's number."""
        document_id = doc["id"]
        self.conn.execute(
            "UPDATE inventory_documents SET status = 'draft' WHERE id = ?", (document_id,)
        )
        for table in (
            "landed_cost_expense_allocations",
            "landed_cost_shares",
            "stock_consumptions",
            "stock_movements",
        ):
            self.conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))
        if doc["doc_type"] in {"issue", "transfer"}:
            self.conn.execute(
                "UPDATE inventory_lines SET amount = 0, inventory_amount = 0, "
                "expense_amount = 0 WHERE document_id = ?",
                (document_id,),
            )
        elif doc["doc_type"] == "sale":  # the revenue is typed; the cost is calculated
            self.conn.execute(
                "UPDATE inventory_lines SET expense_amount = 0, cost_account_id = NULL "
                "WHERE document_id = ?",
                (document_id,),
            )
        elif doc["doc_type"] == "landed_cost":
            self.conn.execute(
                "UPDATE inventory_lines SET inventory_amount = 0, expense_amount = 0 "
                "WHERE document_id = ?",
                (document_id,),
            )

    def _apply_in_order(
        self, company_id: int, document_id: int | None, later: Sequence[int]
    ) -> None:
        """Post `document_id` and the withdrawn `later` documents in date order. A later
        document that no longer fits (not enough stock…) names itself in the error."""
        docs = [self._document(company_id, i) for i in dict.fromkeys(later)]
        if document_id is not None:
            docs.append(self._document(company_id, document_id))
        for doc in sorted(docs, key=_sequence_key):
            if doc["id"] == document_id:
                self._apply(company_id, doc)
                continue
            try:
                self._apply(company_id, doc)
            except LedgerError as exc:
                raise ValidationError(
                    tr(
                        "после изменения не проводится складской документ №{n} от {date}: {error}",
                        n=doc["number"],
                        date=ru_date(doc["doc_date"]),
                        error=exc,
                    )
                ) from exc

    def _apply(self, company_id: int, doc: Row) -> None:
        """Post a draft: movements, derived amounts and its GL document."""
        lines = self.conn.execute(
            "SELECT * FROM inventory_lines WHERE document_id = ? ORDER BY line_no",
            (doc["id"],),
        ).fetchall()
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        accrual: list[PostingInput] = []
        if doc["doc_type"] == "landed_cost":
            postings = self._apply_landed_cost(company_id, doc, lines)
        elif doc["doc_type"] == "sale":
            postings = self._apply_sale(company_id, doc, lines)
        else:
            postings = [self._apply_line(company_id, doc, line) for line in lines]
            if doc["doc_type"] == "receipt" and doc["expense_date"] is not None:
                accrual = self._accrue(company_id, doc, lines, postings)
            if doc["doc_type"] == "receipt":
                postings += self._vat_postings(
                    company_id,
                    (doc["invoice"] or "", doc["invoice_kind"] or ""),
                    [
                        (
                            line["offset_account_id"],
                            (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"]),
                            line["vat_amount"],
                        )
                        for line in lines
                    ],
                )
        if doc["doc_type"] == "receipt":  # while the document is still a draft
            self._finish_accrual(company_id, doc["id"], accrual)
        self._finish(doc["id"], company_id, doc["doc_date"], postings, doc["memo"])

    def _finish(
        self,
        inventory_document_id: int,
        company_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> None:
        """Mark the document posted with its GL document. A recalculated document rewrites
        its existing GL document, which keeps its number."""
        if not postings:
            raise ValidationError(tr("складской документ не создал проводок"))
        doc = self._document(company_id, inventory_document_id)
        gl_document_id = doc["gl_document_id"]
        if gl_document_id is None:
            gl_document_id = self.ledger.post_new(company_id, doc_date, postings, memo)
        else:
            self.ledger.rewrite_linked(company_id, gl_document_id, doc_date, postings, memo)
        self.conn.execute(
            "UPDATE inventory_documents SET status = 'posted', gl_document_id = ?, "
            "posted_at = COALESCE(posted_at, ?) WHERE id = ?",
            (gl_document_id, now(), inventory_document_id),
        )
        if doc["posted_at"] is None:  # recalculation after an edit is not a new posting
            self._audit(
                company_id,
                "inventory_document",
                inventory_document_id,
                "post",
                {
                    "number": doc["number"],
                    "type": doc["doc_type"],
                    "gl_document_id": gl_document_id,
                },
            )
