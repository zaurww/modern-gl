"""The frame every document form shares (D213, step 2): the journal's document, a bank
operation, a conversion, a warehouse document (purchase, sale…), a landed cost.

Top to bottom: the head — the number (grey), the memo as the document's title, the
status chip, «⋯»; the form's own fields and lines; the summary — the keys under the
table on the left, the figures on the right, the main one last and largest; the
actions — the quiet ones on the left, «Сохранить черновик» and the one blue «Провести»
on the right (D86). A form builds its parts with these methods; what is the same
looks and works the same in every document."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from modern_gl.application.history import document_history
from modern_gl.desktop.history_dialog import HistoryDialog
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import Chip, MenuItem, button, caption, more_button
from modern_gl.i18n import tr

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class DocumentShell:
    """The shared parts of a document form; the form sets them up with `build_*`."""

    number: QLabel
    memo: QLineEdit
    status: Chip
    btn_more: QPushButton  # «⋯»: in the head, made by `build_head` when there is a menu
    hint: QLabel
    total: QLabel
    btn_save: QPushButton
    btn_post: QPushButton

    def menu_items(self) -> list[MenuItem]:
        """What «⋯» offers for the document as it is now (the page answers)."""
        return []

    def history_item(self, session: Session, gl_document_id: int | None, title: str) -> MenuItem:
        """«История изменений» of the document's postings — every document has one."""

        def show() -> None:
            if gl_document_id is not None:
                events = document_history(session.conn, session.company_id, gl_document_id)
                HistoryDialog(title, events, self if isinstance(self, QWidget) else None).exec()

        return (tr("История изменений"), show)

    def build_head(
        self,
        root: QVBoxLayout,
        placeholder: str = "",
        menu: Callable[[], list[MenuItem]] | None = None,
    ) -> QHBoxLayout:
        """Number · title · status · «⋯» (when the form has a menu)."""
        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = QLineEdit()
        self.memo.setObjectName("titleEdit")
        self.memo.setFont(fonts().title)
        if placeholder:
            self.memo.setPlaceholderText(placeholder)
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        if menu is not None:
            self.btn_more = more_button(menu, tr("Действия с документом"))
            # off the Tab path: Enter and Tab go from field to field (D106)
            self.btn_more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            top.addWidget(self.btn_more)
        root.addLayout(top)
        return top

    def build_summary(self, root: QVBoxLayout, hint: str, *, keep_hint_place: bool = False):
        """The keys on the left; the figures are added with `add_figure`."""
        summary = QHBoxLayout()
        self.hint = QLabel(hint)
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setWordWrap(True)  # never widens the window
        if keep_hint_place:  # a hidden hint keeps the figures where they were
            keep = self.hint.sizePolicy()
            keep.setRetainSizeWhenHidden(True)
            self.hint.setSizePolicy(keep)
        summary.addWidget(self.hint, 1)
        root.addLayout(summary)
        return summary

    @staticmethod
    def add_figure(
        summary: QHBoxLayout, text: str, *, main: bool = False, width: int = 90
    ) -> tuple[QLabel, QLabel]:
        """A caption and its figure; the main one — larger, last, 130 px."""
        label = caption(text)
        value = QLabel()
        value.setAlignment(RIGHT)
        value.setMinimumWidth(130 if main else width)
        if main:
            value.setFont(fonts().total)
        summary.addWidget(label)
        summary.addWidget(value)
        return label, value

    def build_actions(self, root: QVBoxLayout, quiet: Sequence[QWidget] = ()) -> QHBoxLayout:
        """The quiet actions on the left; «Сохранить черновик» and «Провести» on the right."""
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for b in quiet:
            actions.addWidget(b)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)
        return actions
