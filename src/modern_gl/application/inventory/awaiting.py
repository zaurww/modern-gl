"""A purchase whose goods came before their e-qaimə (D119): posted at once without a
number, the e-qaimə written into it when it comes — with its VAT when the amounts agree."""

from __future__ import annotations

from modern_gl.application.inventory.amounts import allocate_minor
from modern_gl.application.inventory.model import STANDARD_VAT_RATE
from modern_gl.application.inventory.posting import PostingCommands
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction


class AwaitingCommands(PostingCommands):
    def attach_invoice(
        self, company_id: int, document_id: int, invoice: str, vat: int | None = None
    ) -> None:
        """Give a waiting purchase its e-qaimə. `vat` (minor units), when the e-qaimə's
        amount without VAT is the purchase's: it replaces the lines' VAT, split by their
        amounts; None leaves the lines as they are. A posted purchase is posted again in
        place (D32): its postings carry the number and the VAT."""
        with transaction(self.conn):
            doc = self._inventory_document(company_id, document_id)
            if doc["doc_type"] != "receipt" or doc["awaits_invoice"] != 1:
                raise ValidationError(tr("покупка №{n} не ждёт e-qaimə", n=doc["number"]))
            if doc["status"] == "posted":
                with self.reposting(company_id, document_id):
                    self._write_invoice(company_id, doc, invoice, vat)
            else:
                self._write_invoice(company_id, doc, invoice, vat)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "attach_invoice",
                {"invoice": invoice, "vat": vat},
            )

    def _write_invoice(self, company_id: int, doc: Row, invoice: str, vat: int | None) -> None:
        if not invoice.strip():
            raise ValidationError(tr("не указан номер e-qaimə"))
        if vat is not None:
            self._split_vat(company_id, doc, vat)
        self._set_invoice(doc["id"], invoice)

    def _split_vat(self, company_id: int, doc: Row, vat: int) -> None:
        if vat and doc["currency_id"] is not None:
            raise ValidationError(
                tr("в поступлении в валюте НДС не указывается: импортный НДС — в расходах")
            )
        lines = self.conn.execute(
            "SELECT id, amount FROM inventory_lines WHERE company_id = ? AND document_id = ? "
            "ORDER BY line_no",
            (company_id, doc["id"]),
        ).fetchall()
        shares = (
            allocate_minor(vat, [(row["id"], row["amount"]) for row in lines])
            if vat
            else {row["id"]: 0 for row in lines}
        )
        for line_id, share in shares.items():
            self.conn.execute(
                "UPDATE inventory_lines SET vat_amount = ? WHERE company_id = ? AND id = ?",
                (share, company_id, line_id),
            )
        if vat and doc["vat_rate"] is None:
            self._set_vat_rate(doc["id"], STANDARD_VAT_RATE)
