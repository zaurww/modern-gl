"""The page of a warehouse document: header, lines, totals; save, post, unpost."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from PySide6.QtWidgets import (
    QMenu,
    QMessageBox,
)

from modern_gl.application.document_kinds import kind_name
from modern_gl.application.inventory import (
    INCOMING_TYPES,
    RETURN_TYPES,
    StockShortageError,
    vat_of,
)
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.desktop.inventory_document_page.clipboard import ClipboardPart
from modern_gl.desktop.inventory_document_page.columns import (
    VAT_DOCUMENTS,
    InventoryGridRow,
)
from modern_gl.desktop.inventory_document_page.filling import RETURN_OF, FillingPart
from modern_gl.desktop.inventory_document_page.goods_lines import GoodsLinesPart
from modern_gl.desktop.inventory_document_page.header import HeaderPart
from modern_gl.desktop.inventory_document_page.line_objects import LineObjectsPart
from modern_gl.desktop.inventory_document_page.lines_model import (
    InventoryLinesModel,
    by_sale_kinds,
    sale_kinds,
)
from modern_gl.desktop.inventory_document_page.lines_table import (
    InventoryLinesDelegate,
)
from modern_gl.desktop.inventory_document_page.new_values import NewValuesPart
from modern_gl.desktop.inventory_document_page.party import PartyPart
from modern_gl.desktop.inventory_document_page.splits import SplitPart
from modern_gl.desktop.posting_preview import document_postings
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.widgets import (
    edited_date,
    enter_goes_on,
    money,
    to_qdate,
)
from modern_gl.domain.dates import month_title
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.invoice import EQAIME
from modern_gl.i18n import N_, tr

PARTY_MISSING = {
    "receipt": N_("Укажите поставщика"),
    "sale": N_("Укажите покупателя"),
    "purchase_return": N_("Укажите поставщика"),
    "sale_return": N_("Укажите покупателя"),
}


class InventoryDocumentPage(
    HeaderPart,
    PartyPart,
    ClipboardPart,
    NewValuesPart,
    GoodsLinesPart,
    LineObjectsPart,
    SplitPart,
    FillingPart,
):
    def __init__(
        self,
        session: Session,
        document_id: int | None = None,
        doc_type: str = "receipt",
    ) -> None:
        super().__init__(session, doc_type)
        self._connect()
        if document_id is None:
            self._set_new()
        else:
            self.load(document_id)

    def _connect(self) -> None:
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        self.btn_accrual.clicked.connect(self._open_accrual)
        self.btn_return.clicked.connect(self._make_return)
        self.btn_shortage.clicked.connect(
            lambda: self.doc is not None and self.buy_shortage.emit(self.doc.id)
        )
        self._connect_delegate()
        self.model.changed.connect(self._changed)
        self._connect_goods()
        self._connect_objects()
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.vat_rate.activated.connect(self._vat_rate_changed)
        self.basis.activated.connect(self._basis_changed)
        self.reason.activated.connect(self._reason_changed)
        self.invoice.textEdited.connect(self._changed)
        self.currency.activated.connect(self._currency_changed)
        self.rate.textEdited.connect(self._rate_edited)
        self.date.dateChanged.connect(self._date_changed)
        bind(self, "save", lambda: self.save(post=False))
        bind(self, "post", lambda: self.save(post=True))
        bind(self.table, "insert", self._insert_row)
        bind(self.table, "duplicate_row", self._duplicate_row)
        bind(self.table, "split_row", self._split_row)
        bind(self.table, "delete", self._remove_row)
        bind(self.table, "paste_rows", self.paste)  # inside a cell editor: its own paste
        bind(self.table, "copy_rows", self.copy)
        self.postings.bind_key(self)

    @property
    def document_id(self) -> int | None:
        return self.doc.id if self.doc else None

    @property
    def key(self):
        return ("inventory_doc", self.document_id) if self.doc else ("new_inventory", id(self))

    def title(self) -> str:
        operation = kind_name(self.doc_type)
        title = (
            f"{operation} №{self.doc.number}" if self.doc else tr("Новое: {type}", type=operation)
        )
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.table.setFocus()

    def keyPressEvent(self, event) -> None:
        """Enter in the comment, date, VAT, basis, currency or rate goes on as Tab does."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _set_new(self) -> None:
        self.number.setText(tr("Новый"))
        self.status.set(tr("Новый"), "blue")
        self._apply_mode(False)
        self._show_currency(None, None)
        self._show_basis(EQAIME, "")
        self._show_reason(None)
        if self.doc_type == "incoming":  # the first reason's account on the first line
            self._reason_changed()
        self._show_party()
        self.dirty = False  # showing the defaults is not an edit
        self._show_totals()

    def load(self, document_id: int) -> None:
        self.doc = self.inventory.load_document(self.s.company_id, document_id)
        self.doc_type = self.doc.doc_type
        self.number.setText(f"№{self.doc.number}")
        self.memo.setText(self.doc.memo)
        self.date.setDate(to_qdate(date.fromisoformat(self.doc.doc_date)))
        self.type_label.setText(kind_name(self.doc_type))
        self._show_vat_rate(self.doc.vat_rate)
        self._show_reason(self.doc.incoming_reason)
        vat_rate = self._chosen_vat_rate()
        kinds = sale_kinds(self.s) if self.doc_type == "sale" else []
        rows = [
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
            for line in self.doc.lines
        ] or [InventoryGridRow()]
        # a posted document is edited in place, as in 1C; not while viewing (D80)
        read_only = not self.doc.editable or self.s.read_only
        self._use_lines(rows, read_only, vat_rate, self.doc.doc_date)
        if self.doc.status == "posted":
            self.status.set(tr("Проведён"), "green")
        else:
            self.status.set(tr("Черновик"), "amber")
        self._apply_mode(read_only)
        self._show_currency(self.doc.currency_id, self.doc.currency_rate)
        self._show_basis(self.doc.invoice_kind, self.doc.invoice, self.doc.awaits_invoice)
        self._show_party()
        self.dirty = False
        self._show_totals()
        self.title_changed.emit()

    def _use_lines(
        self, rows: list[InventoryGridRow], read_only: bool, vat_rate: int | None, doc_date
    ) -> None:
        """A new model of the lines (a document loaded, a return filled), wired as the
        first one."""
        self.model = InventoryLinesModel(
            self.s,
            self.doc_type,
            rows,
            read_only=read_only,
            vat_rate=vat_rate,
            incoming_account=self._incoming_account(),
            doc_date=doc_date,
        )
        self.table.setModel(self.model)
        self.table.configure_columns()
        self.expense_columns = self._expense_columns()
        self.delegate = InventoryLinesDelegate(self)
        self._connect_delegate()
        self.table.setItemDelegate(self.delegate)
        self.model.changed.connect(self._changed)
        self._connect_goods()

    def _apply_mode(self, read_only: bool) -> None:
        self.memo.setReadOnly(read_only)
        self.memo.setEnabled(not read_only)
        self.date.setEnabled(not read_only)
        self.vat_rate.setEnabled(not read_only)
        self.currency.setEnabled(not read_only)
        self.rate.setReadOnly(read_only)
        self.basis.setEnabled(not read_only)
        self.invoice.setReadOnly(read_only)
        self.reason.setEnabled(not read_only)
        self.model.read_only = read_only
        posted = self.doc is not None and self.doc.status == "posted"
        editable = not read_only and self.doc_type != "landed_cost"
        self.btn_save.setVisible(editable and not posted)  # Ctrl+S reposts a posted one
        self.btn_post.setVisible(editable)
        viewing = self.s.read_only
        self.btn_delete.setVisible(self.doc is not None and not viewing)
        self.btn_unpost.setVisible(posted and self.doc_type != "landed_cost" and not viewing)
        books = not self.s.stock_only  # the postings are not shown in a warehouse only (D90)
        self.btn_gl.setVisible(
            books and self.doc is not None and self.doc.gl_document_id is not None
        )
        self.btn_accrual.setVisible(books and self.doc is not None and bool(self.doc.accruals))
        self.hint.setVisible(not read_only and self.doc_type != "landed_cost")
        self.btn_shortage.hide()
        self.btn_return.setVisible(posted and not viewing and self.doc_type in RETURN_OF)
        self._show_objects_button()

    def _show_totals(self) -> None:
        in_currency = self.model.rate is not None
        self.currency_total.setVisible(in_currency)
        self.currency_total.setText(
            f"{money(self.model.currency_total(), blank_zero=False)} {self.model.currency_code}"
        )
        vat = self.model.vat_total()
        shown = self.doc_type in VAT_DOCUMENTS and self.model.has_vat()
        self.vat_total_caption.setVisible(shown)
        self.vat_total.setVisible(shown)
        self.vat_total.setText(money(vat, blank_zero=False))
        self.total.setText(money(self.model.total() + vat, blank_zero=False))
        self.postings.changed()

    def _changed(self, *_args) -> None:
        self._show_totals()
        self._show_objects_button()
        if self._expense_columns() != self.expense_columns:  # a service line came or went
            self.table.configure_columns()
            self.expense_columns = self._expense_columns()
        if not self.model.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    # ---- saving --------------------------------------------------------------------

    def save(self, post: bool) -> bool:
        if self.model.read_only or self.doc_type == "landed_cost":
            return False
        self._finish_editing()
        self.table.setFocus()
        self.error.hide()
        if post and self._party_missing():
            return False
        try:
            posted = self.doc is not None and self.doc.status == "posted"
            post = post or posted  # edited in place: posted again at once
            document_id = self._write(post)
            self.model.new_items_saved()
            self.s.catalog.reload()
            if post and not posted:
                self._post_saved(document_id)
        except (LedgerError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            # goods short: brought in as a purchase that waits for its e-qaimə (D154)
            self.btn_shortage.setVisible(
                isinstance(exc, StockShortageError) and self.doc is not None
            )
            return False
        self.s.working_date = edited_date(self.date)
        self.load(document_id)
        assert self.doc is not None  # load() has just read it
        self.s.notify(
            tr(
                "Складской документ №{n} проведён" if post else "Складской документ №{n} сохранён",
                n=self.doc.number,
            )
        )
        self.saved.emit(document_id)
        return True

    def _write(self, post: bool) -> int:
        """Save the document as typed; a posted one is edited in place — posted again,
        later documents recalculated. A draft is posted after (`post_document`). The new
        names of its lines become items with it, in the same transaction (D209)."""
        posted = self.doc is not None and self.doc.status == "posted"
        inputs = self.model.to_inputs(complete=post or posted)
        with self.inventory.adding_items(
            self.s.company_id, self.model.new_items_on_lines()
        ) as made:
            lines = [
                replace(line, item_id=made[line.item_id]) if line.item_id in made else line
                for line in inputs
            ]
            if self.doc is not None and posted:
                with self.inventory.reposting(self.s.company_id, self.doc.id):
                    return self._save_draft(lines)
            return self._save_draft(lines)

    def postings_preview(self) -> PostingPreview:
        """Posted and not edited — its postings; else what «Провести» would post."""
        saved = [self.doc.id] if self.doc is not None else []
        stored = self.doc is not None and self.doc.status == "posted" and not self.dirty
        if stored or self.doc_type == "landed_cost":  # costs are posted on their own page
            return document_postings(self.s, "inventory", saved, None)
        return document_postings(self.s, "inventory", saved, self._write_posted)

    def _write_posted(self) -> list[int]:
        if (missing := self._missing_party()) is not None:
            raise ValidationError(missing)
        document_id = self._write(post=True)
        if self.doc is None or self.doc.status != "posted":
            self.inventory.post_document(self.s.company_id, document_id)
        return [document_id]

    def _missing_party(self) -> str | None:
        """Why it cannot post without the header's supplier (customer)."""
        party, _contract = self._positions()
        if not self.model.party_in_header() or party is None:
            return None
        if self.model.party_subconto[party] is not None:
            return None
        return tr(PARTY_MISSING[self.doc_type])

    def _party_missing(self) -> bool:
        """Posting without the header's supplier (customer): say so at its field."""
        if (missing := self._missing_party()) is None:
            return False
        self.show_error(missing)
        self.party.setFocus()
        return True

    def _save_draft(self, inputs) -> int:
        company_id = self.s.company_id
        document_date = edited_date(self.date)
        memo = self.memo.text().strip()
        if self.doc_type in INCOMING_TYPES:
            first = inputs[0]
            if self.doc is None:
                return self.inventory.create_receipt_draft(
                    company_id,
                    document_date,
                    inputs,
                    first.credit_account_id,
                    first.credit_subconto,
                    memo,
                    opening=self.doc_type == "opening",
                    incoming_reason=self._chosen_reason(),
                    vat_rate=self._chosen_vat_rate(),
                    currency_id=self._chosen_currency(),
                    currency_rate=self._rate_text(),
                    awaits_invoice=self._awaits(),
                    **self._invoice(),
                )
            self.inventory.update_receipt_draft(
                company_id,
                self.doc.id,
                document_date,
                inputs,
                first.credit_account_id,
                first.credit_subconto,
                memo,
                incoming_reason=self._chosen_reason(),
                vat_rate=self._chosen_vat_rate(),
                currency_id=self._chosen_currency(),
                currency_rate=self._rate_text(),
                awaits_invoice=self._awaits(),
                **self._invoice(),
            )
            return self.doc.id
        if self.doc_type in RETURN_TYPES:
            return self._save_return(inputs, document_date, memo)
        if self.doc_type == "sale":
            first = inputs[0]
            header = (first.customer_account_id, first.customer_subconto, memo)
            extra = {"vat_rate": self._chosen_vat_rate(), **self._invoice()}
            if self.doc is None:
                return self.inventory.create_sale_draft(
                    company_id, document_date, inputs, *header, **extra
                )
            self.inventory.update_sale_draft(
                company_id, self.doc.id, document_date, inputs, *header, **extra
            )
            return self.doc.id
        if self.doc_type == "issue":
            if self.doc is None:
                return self.inventory.create_issue_draft(company_id, document_date, inputs, memo)
            self.inventory.update_issue_draft(company_id, self.doc.id, document_date, inputs, memo)
            return self.doc.id
        if self.doc is None:
            return self.inventory.create_transfer_draft(company_id, document_date, inputs, memo)
        self.inventory.update_transfer_draft(company_id, self.doc.id, document_date, inputs, memo)
        return self.doc.id

    def _post_saved(self, document_id: int) -> None:
        """Post the draft just saved; when it does not post, the page holds that draft
        (a second «Провести» must not save another one) and says why."""
        try:
            self.inventory.post_document(self.s.company_id, document_id)
        except LedgerError:
            fresh = self.doc is None
            self.load(document_id)
            if fresh:
                self.saved.emit(document_id)  # a new draft: the lists show it
            raise

    def _save_return(self, inputs, document_date, memo: str) -> int:
        first = inputs[0]
        header = (first.party_account_id, first.party_subconto, memo)
        extra = {"vat_rate": self._chosen_vat_rate(), **self._invoice()}
        if self.doc is None:
            return self.inventory.create_return_draft(
                self.s.company_id, document_date, self.doc_type, inputs, *header, **extra
            )
        self.inventory.update_return_draft(
            self.s.company_id, self.doc.id, document_date, inputs, *header, **extra
        )
        return self.doc.id

    def delete(self) -> None:
        if self.doc is None:
            return
        if (
            QMessageBox.question(
                self,
                tr("Удалить складской документ"),
                tr("Удалить складской документ №{n}?", n=self.doc.number),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        number = self.doc.number
        try:
            self.inventory.delete_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.dirty = False
        self.s.notify(tr("Складской документ №{n} удалён", n=number))
        self.saved.emit(self.doc.id)
        self.close_requested.emit()

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.inventory.unpost_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.load(self.doc.id)
        self.s.notify(
            tr(
                "Проведение складского документа №{n} отменено — можно исправлять",
                n=self.doc.number,
            )
        )
        self.saved.emit(self.doc.id)

    def _make_return(self) -> None:
        if self.doc is not None and self.doc_type in RETURN_OF:
            self.make_return.emit(RETURN_OF[self.doc_type], self.doc.id)

    def _open_gl(self) -> None:
        if self.doc is not None and self.doc.gl_document_id is not None:
            self.open_gl_document.emit(self.doc.gl_document_id)

    def _open_accrual(self) -> None:
        """The accrual document; a receipt with several months offers them in a menu."""
        accruals = self.doc.accruals if self.doc is not None else ()
        if len(accruals) == 1:
            self.open_gl_document.emit(accruals[0].gl_document_id)
            return
        menu = QMenu(self.btn_accrual)
        for accrual in accruals:
            action = menu.addAction(month_title(accrual.expense_date[:7]))
            action.triggered.connect(
                lambda _=False, gl_id=accrual.gl_document_id: self.open_gl_document.emit(gl_id)
            )
        if accruals:
            menu.exec(self.btn_accrual.mapToGlobal(self.btn_accrual.rect().bottomLeft()))
