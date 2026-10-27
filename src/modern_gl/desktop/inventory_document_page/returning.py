"""A return made from its purchase or sale: «Оформить возврат» on the posted document opens
a return filled with what is left to return of each line — at its price, with its ƏDV,
the supplier (customer) in the header; the user keeps what comes back."""

from __future__ import annotations

from modern_gl.desktop.inventory_document_page.columns import InventoryGridRow
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr

# what each document is returned by
RETURN_OF = {"receipt": "purchase_return", "sale": "sale_return"}


class ReturningPart(InventoryDocumentForm):
    def fill_return_of(self, document_id: int) -> bool:
        """The lines of the document still to return; False — nothing is left."""
        source = self.inventory.load_document(self.s.company_id, document_id)
        rows = []
        for line in source.lines:
            if line.item_id is None or not line.quantity:  # a service is not returned
                continue
            left = self.inventory.returnable(self.s.company_id, line.id)
            if left <= 0:
                continue
            rows.append(
                InventoryGridRow(
                    line.item_id,
                    line.warehouse_id,
                    None,
                    left,
                    round_ratio(line.amount * left, line.quantity),
                    line.offset_account_id,
                    list(line.offset_subconto),
                    vat_amount=round_ratio(line.vat_amount * left, line.quantity),
                    returned_line_id=line.id,
                )
            )
        if not rows:
            self.show_error(tr("По документу №{n} возвращать нечего", n=source.number))
            return False
        self._show_vat_rate(source.vat_rate)
        self.memo.setText(tr("Возврат по документу №{n}", n=source.number))
        self._use_lines(rows, False, source.vat_rate, self.model.doc_date)
        self._show_party()
        self._changed()
        return True

    # ---- made by the page ------------------------------------------------------------

    def _use_lines(self, rows, read_only: bool, vat_rate: int | None, doc_date) -> None:
        raise NotImplementedError

    def _show_party(self) -> None:
        raise NotImplementedError
