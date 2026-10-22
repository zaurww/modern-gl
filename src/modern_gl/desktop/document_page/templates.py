"""Entry templates in a document: a document from a template asks for the operation amount,
«#template» in a Dt cell puts its lines in, the document is saved as a template."""

from __future__ import annotations

import re

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QInputDialog,
)

from modern_gl.application.ledger import TemplateLine
from modern_gl.application.queries import (
    TemplateData,
    load_template,
)
from modern_gl.desktop.document_page.form import DocumentForm
from modern_gl.desktop.postings import (
    PostingRow,
)
from modern_gl.domain import formula
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr


class TemplatesPart(DocumentForm):
    def _set_entry(self, entry: TemplateData) -> None:
        """Prefill from an entry template; amounts come from the operation amount."""
        self.memo.setText(entry.memo or entry.name)
        rows = [
            PostingRow(
                ln.debit_account_id,
                list(ln.debit_subconto),
                ln.credit_account_id,
                list(ln.credit_subconto),
                None,
                ln.memo,
                ln.formula,
            )
            for ln in entry.lines
        ]
        self.model.beginResetModel()
        self.model.rows = rows or [PostingRow()]
        self.model.endResetModel()
        self.dirty = True
        asks = formula.uses_amount([ln.formula for ln in entry.lines])
        self.amount_caption.setVisible(asks)
        self.amount.setVisible(asks)
        self._update_total()
        QTimer.singleShot(0, (self.amount if asks else self.table).setFocus)
        if not asks:
            QTimer.singleShot(0, self._focus_grid)

    def _amount_edited(self, text: str) -> None:
        self.error.hide()
        try:
            total = to_minor(text) if text.strip() else None
        except ValueError as e:
            self.show_error(str(e))
            return
        problem = self.model.recalculate(total)
        if problem:
            self.show_error(problem)

    def save_as_template(self) -> None:
        """Make an entry template of these lines: an amount equal to the first line's
        becomes S, others stay as numbers — formulas can be refined in the template."""
        self.table.setFocus()  # commits an open cell editor
        name, ok = QInputDialog.getText(
            self, tr("Новый шаблон"), tr("Название шаблона:"), text=self.memo.text().strip()
        )
        if not ok or not name.strip():
            return
        rows = [r for r in self.model.rows if not r.is_empty()]
        first = next((r.amount for r in rows if r.amount), None)
        lines = [
            TemplateLine(
                r.debit,
                r.credit,
                r.formula
                or (
                    "S"
                    if r.amount and r.amount == first
                    else (format_minor(r.amount).replace(" ", "") if r.amount else "")
                ),
                r.debit_sc,
                r.credit_sc,
                r.memo,
            )
            for r in rows
        ]
        try:
            template_id = self.s.ledger.save_template(
                self.s.company_id, name, lines, memo=self.memo.text()
            )
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.s.notify(tr("Шаблон «{name}» сохранён", name=name.strip()))
        self.template_saved.emit(template_id)

    def insert_template(self, row: int, template_id: int) -> None:
        """ "#template" typed in a Dt cell: the template's lines take that row's place.
        A document that is otherwise empty becomes the template (with its memo)."""
        template = load_template(self.s.conn, self.s.company_id, template_id)
        others = [r for i, r in enumerate(self.model.rows) if i != row and not r.is_empty()]
        if not others:
            self._set_entry(template)
            return
        offset = row  # template formulas refer to their own lines: L1 -> L(row + 1)…

        def shift(text: str) -> str:
            return re.sub(r"[Ll](\d+)", lambda m: f"L{int(m[1]) + offset}", text)

        if self.model.rows[row].is_empty():
            self.model.remove_row(row)
        for i, ln in enumerate(template.lines):
            self.model.insert_row(
                row + i,
                PostingRow(
                    ln.debit_account_id,
                    list(ln.debit_subconto),
                    ln.credit_account_id,
                    list(ln.credit_subconto),
                    None,
                    ln.memo,
                    shift(ln.formula),
                ),
            )
        asks = formula.uses_amount([ln.formula for ln in template.lines])
        self.amount_caption.setVisible(asks)
        self.amount.setVisible(asks)
        if asks:
            self.amount.setFocus()
            self._amount_edited(self.amount.text())
        self.s.notify(tr("Шаблон «{name}» вставлен", name=template.name))
