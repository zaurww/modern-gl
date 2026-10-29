"""Under a statement: its balances, and the balance by the bank's own statement typed in —
equal, the statement is reconciled; not, the difference says which way to look (D78)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import DIFF, OK, BankStatement
from modern_gl.desktop.theme import fonts
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr


class ReconcileBar(QWidget):
    entered = Signal(object)  # the bank's closing balance, minor units; None: cleared

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        root.addWidget(rule)
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(2)
        self.figures: dict[str, QLabel] = {}
        captions = (
            ("opening", tr("На начало")),
            ("in", tr("Приход")),
            ("out", tr("Расход")),
            ("closing", tr("На конец · программа")),
        )
        for column, (key, caption) in enumerate(captions):
            label = QLabel(caption)
            label.setObjectName("tertiary")
            label.setFont(fonts().small)
            figure = QLabel()
            figure.setFont(fonts().cell_bold)
            grid.addWidget(label, 0, column)
            grid.addWidget(figure, 1, column)
            self.figures[key] = figure
        caption = QLabel(tr("На конец · выписка банка"))  # the one to type: plain text
        caption.setFont(fonts().small)
        self.bank = QLineEdit()
        self.bank.setPlaceholderText(tr("из выписки банка"))
        self.bank.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bank.setFixedWidth(160)
        self.bank.editingFinished.connect(self._typed)
        grid.addWidget(caption, 0, len(captions))
        grid.addWidget(self.bank, 1, len(captions))
        grid.setColumnStretch(len(captions) + 1, 1)
        root.addLayout(grid)
        row = QHBoxLayout()
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        row.addWidget(self.verdict, 1)
        root.addLayout(row)
        self._shown: int | None = None

    def show_statement(self, s: BankStatement) -> None:
        for key, value in (
            ("opening", s.opening),
            ("in", s.money_in),
            ("out", s.money_out),
            ("closing", s.closing),
        ):
            self.figures[key].setText(format_minor(value))
        self._shown = s.bank_closing
        if not self.bank.hasFocus():
            self.bank.setText("" if s.bank_closing is None else format_minor(s.bank_closing))
        if s.status == OK:
            self.verdict.setObjectName("reconciled")
            self.verdict.setText(tr("✓ Сверена: программа и банк сходятся."))
        elif s.status == DIFF and s.drafts:  # the drafts do not move the balance
            self.verdict.setObjectName("error")
            self.verdict.setText(
                tr(
                    "Расхождение {amount}: черновиков {n} — они не двигают остаток; "
                    "проведите их или удалите",
                    amount=format_minor(s.difference or 0),
                    n=s.drafts,
                )
            )
        elif s.status == DIFF:
            difference = s.difference or 0
            self.verdict.setObjectName("error")
            self.verdict.setText(
                tr(
                    "Расхождение {amount}: в банке денег меньше — не внесён расход (комиссия?)",
                    amount=format_minor(difference),
                )
                if difference < 0
                else tr(
                    "Расхождение {amount}: в банке денег больше — не внесён приход",
                    amount=format_minor(difference),
                )
            )
        else:
            self.verdict.setObjectName("warning")  # waiting: louder than what is done
            self.verdict.setText(
                tr("Впишите остаток из выписки банка: сойдётся — выписка сверена.")
            )
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)

    def _typed(self) -> None:
        text = self.bank.text().strip()
        try:
            amount = to_minor(text) if text else None
        except ValueError:
            self.verdict.setObjectName("error")
            self.verdict.setText(tr("Сумму пишут так: 12 450.00"))
            self.verdict.style().unpolish(self.verdict)
            self.verdict.style().polish(self.verdict)
            return
        if amount != self._shown:
            self._shown = amount
            self.entered.emit(amount)
