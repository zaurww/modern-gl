"""New documents that start filled: a return made from its purchase or sale («Оформить
возврат» — what is left to return of each line, at its price, with its ƏDV, the supplier
in the header), a purchase of what is under its minimum stock (at the last price)."""

from __future__ import annotations

from datetime import date

from modern_gl.application.inventory import line_amount
from modern_gl.desktop.inventory_document_page.columns import InventoryGridRow
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.widgets import to_qdate
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import BelowMinimum, document_shortages

# what each document is returned by
RETURN_OF = {"receipt": "purchase_return", "sale": "sale_return"}


class FillingPart(InventoryDocumentForm):
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

    def fill_missing(self, missing: list[BelowMinimum]) -> None:
        """A purchase of what is under the minimum: up to it, at the last price, to the
        warehouse the item last came to; the supplier is chosen in the header."""
        rows = [
            InventoryGridRow(
                m.item_id,
                m.warehouse_id,
                None,
                m.missing,
                None if m.last_price is None else line_amount(m.last_price, m.missing),
            )
            for m in missing
        ]
        self.memo.setText(tr("Покупка до минимального остатка"))
        self._use_lines(rows, False, self._chosen_vat_rate(), self.model.doc_date)
        self._show_party()
        self._changed()

    def fill_shortage(self, document_id: int) -> bool:
        """A purchase «ждёт e-qaimə» of what the document lacks on its day: dated that day,
        at the last price, from the last supplier; False — nothing lacks."""
        source = self.inventory.load_document(self.s.company_id, document_id)
        shortages = document_shortages(self.s.conn, self.s.company_id, document_id)
        if not shortages:
            return False
        rows = [
            InventoryGridRow(
                s.item_id,
                s.warehouse_id,
                None,
                s.missing,
                None if s.last_price is None else line_amount(s.last_price, s.missing),
                s.supplier_account_id,
                list(s.supplier_subconto),
            )
            for s in shortages
        ]
        self.date.setDate(to_qdate(date.fromisoformat(source.doc_date)))
        self.memo.setText(tr("Товар пришёл раньше документов (для №{n})", n=source.number))
        self._use_lines(rows, False, self._chosen_vat_rate(), source.doc_date)
        self._show_basis("", "", awaits=True)
        self._show_party()
        self._changed()
        return True

    # ---- made by the page ------------------------------------------------------------

    def _use_lines(self, rows, read_only: bool, vat_rate: int | None, doc_date) -> None:
        raise NotImplementedError

    def _show_party(self) -> None:
        raise NotImplementedError

    def _show_basis(self, kind: str, number: str, awaits: bool = False) -> None:
        raise NotImplementedError
