"""New documents that start filled: a return made from its purchase or sale («Оформить
возврат» — what is left to return of each line, at its price, with its ƏDV, the supplier
in the header), a purchase of what is under its minimum stock (at the last price)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from modern_gl.application.inventory import InventoryDocumentData, line_amount, vat_of
from modern_gl.desktop.inventory_document_page.columns import InventoryGridRow
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.inventory_document_page.lines_model import by_sale_kinds, sale_kinds
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

    def fill_copy_of(self, document_id: int) -> None:
        """A new document like this one (a monthly rent, a regular supply): its lines, ƏDV,
        party and memo; the date is today's work, the e-qaimə and returns belong to it."""
        source = self.inventory.load_document(self.s.company_id, document_id)
        self._show_vat_rate(source.vat_rate)
        vat_rate = self._chosen_vat_rate()
        rows = [
            replace(row, line_id=None, returned_line_id=None)
            for row in self._rows_of(source, vat_rate)
        ]
        self.memo.setText(source.memo)
        self._use_lines(rows, False, vat_rate, self.model.doc_date)
        self._show_currency(source.currency_id, None)
        self._show_party()
        self._changed()

    def _rows_of(self, doc: InventoryDocumentData, vat_rate: int | None) -> list[InventoryGridRow]:
        """The document's lines as the table shows them."""
        kinds = sale_kinds(self.s) if self.doc_type == "sale" else []
        return [
            InventoryGridRow(
                line.item_id,
                line.warehouse_id,
                line.to_warehouse_id,
                line.quantity or None,
                line.amount or None,
                line.offset_account_id,
                list(line.offset_subconto),
                line.memo,
                line.id,
                vat_amount=line.vat_amount if vat_rate is not None or line.vat_amount else None,
                vat_typed=line.vat_amount != vat_of(line.amount, vat_rate),
                currency_amount=line.currency_amount,
                expense_account_id=line.cost_account_id if self.doc_type == "receipt" else None,
                expense_subconto=(
                    list(line.cost_subconto) if self.doc_type == "receipt" else [None, None, None]
                ),
                sale_subconto=by_sale_kinds(self.s.catalog, kinds, line.cost_subconto),
                expense_date=line.expense_date if self.doc_type == "receipt" else None,
                returned_line_id=line.returned_line_id,
            )
            for line in doc.lines
        ] or [InventoryGridRow()]

    # ---- made by the page ------------------------------------------------------------

    def _use_lines(self, rows, read_only: bool, vat_rate: int | None, doc_date) -> None:
        raise NotImplementedError

    def _show_party(self) -> None:
        raise NotImplementedError

    def _show_currency(self, currency_id: int | None, rate: int | None) -> None:
        raise NotImplementedError

    def _show_basis(self, kind: str, number: str, awaits: bool = False, note: str = "") -> None:
        raise NotImplementedError
