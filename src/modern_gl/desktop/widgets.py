"""Small shared building blocks: page header, status chip, empty state, date prompt."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import ClassVar, cast

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.theme import P, dot_icon, fonts
from modern_gl.domain.accounts import ACCOUNT_TYPES, TYPE_NAMES
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

DATE_FORMAT = "dd.MM.yyyy"

__all__ = ["ru_date"]  # re-exported for the pages


def money(minor: int | None, blank_zero: bool = True) -> str:
    if minor is None or (blank_zero and minor == 0):
        return ""
    return format_minor(minor)


def balance_text(net: int) -> str:
    if net == 0:
        return "0.00"
    return f"{format_minor(abs(net))} {tr('Дт') if net > 0 else tr('Кт')}"


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def edited_date(edit: QDateEdit) -> date:
    """The date in a date editor (PySide types QDate.toPython() as object)."""
    return cast(date, edit.date().toPython())


def date_edit(value: date, parent: QWidget | None = None) -> QDateEdit:
    w = QDateEdit(to_qdate(value), parent)
    w.setDisplayFormat(DATE_FORMAT)
    w.setCalendarPopup(True)
    return w


def button(text: str, kind: str = "", tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


MenuItem = tuple[str, Callable[[], object]] | None  # None: a separator


def more_button(items: Callable[[], list[MenuItem]], tooltip: str = "") -> QPushButton:
    """ "⋯": the less frequent actions of a page in a menu, so one main action stands
    out (as in Things). `items()` is asked each time, so the menu fits the moment."""
    b = button("⋯", "more", tooltip or tr("Ещё"))

    def show() -> None:
        menu = QMenu(b)
        for item in items():
            if item is None:
                menu.addSeparator()
                continue
            text, fn = item
            menu.addAction(text).triggered.connect(lambda _=False, fn=fn: fn())
        menu.exec(b.mapToGlobal(b.rect().bottomLeft()))

    b.clicked.connect(show)
    return b


class Chip(QLabel):
    """Rounded status label: draft / posted / storno."""

    # palette names, read when shown: themes change the colors
    TONES: ClassVar[dict[str, tuple[str, str]]] = {
        "neutral": ("secondary", "subtle"),
        "green": ("green", "green_soft"),
        "amber": ("amber", "amber_soft"),
        "red": ("red", "red_soft"),
        "blue": ("accent", "accent_soft"),
    }

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setFont(fonts().small)
        self.set(text, tone)

    def set(self, text: str, tone: str) -> None:
        fg, bg = (getattr(P, name) for name in self.TONES[tone])
        self.setText(text)
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: 10px; padding: 3px 10px;"
        )


class ElidedLabel(QLabel):
    """One line that gives way to a narrow window, its end cut with "…"."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), 120), hint.height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        self.style().drawItemText(
            painter,
            rect,
            int(self.alignment()),
            self.palette(),
            self.isEnabled(),
            text,
            self.foregroundRole(),
        )


class PageHeader(QWidget):
    """Large title, quiet subtitle, actions on the right."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = ElidedLabel(title)
        self.title.setFont(fonts().title)
        self.subtitle = ElidedLabel(subtitle)
        self.subtitle.setObjectName("secondary")
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        outer.addLayout(text, 1)
        self.action_row = QHBoxLayout()
        self.action_row.setSpacing(14)
        outer.addLayout(self.action_row)

    def add_action(self, widget: QWidget) -> QWidget:
        self.action_row.addWidget(widget, 0, Qt.AlignmentFlag.AlignBottom)
        return widget


class EmptyState(QWidget):
    """Centered, quiet message shown instead of an empty table."""

    def __init__(self, glyph: str, title: str, hint: str) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(2)
        for text, font, color in (
            (glyph, None, P.hairline),
            (title, fonts().heading, P.secondary),
            (hint, fonts().body, P.tertiary),
        ):
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            if font is None:
                label.setStyleSheet(f"color: {color}; font-size: 48pt;")
            else:
                label.setFont(font)
                label.setStyleSheet(f"color: {color};")
            lay.addWidget(label)
        lay.addStretch(3)


def ask_date(parent: QWidget, title: str, prompt: str, default: date) -> date | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(12)
    lay.addWidget(QLabel(prompt))
    edit = date_edit(default, dlg)
    lay.addWidget(edit)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return edited_date(edit)


# Account classes (level 1 of statement classification): order, name, color (a palette name).
ACCOUNT_CLASSES = [
    ("asset", "Активы", "accent"),
    ("liability", "Обязательства", "amber"),
    ("equity", "Капитал", "violet"),
    ("revenue", "Доходы", "green"),
    ("expense", "Расходы", "red"),
]
CLASS_ORDER: dict[str | None, int] = {code: i for i, (code, _, _) in enumerate(ACCOUNT_CLASSES)}
_CLASS_ICONS: dict[str, QIcon] = {}


def class_name(account_class: str | None) -> str:
    names = {code: name for code, name, _ in ACCOUNT_CLASSES}
    return tr(names[account_class]) if account_class in names else tr("Без класса")


def type_name(account_class: str | None, account_type: str | None) -> str:
    """An account's type, or its class when the type is not set."""
    return tr(TYPE_NAMES[account_type]) if account_type else class_name(account_class)


def type_choices() -> list[tuple[str | None, str | None, str]]:
    """(class, type, name) for a type picker, grouped by class: each class first (the class
    alone, without a type), then its types; last "not set"."""
    choices: list[tuple[str | None, str | None, str]] = []
    for cls, name, _ in ACCOUNT_CLASSES:
        choices.append((cls, None, tr(name)))
        choices += [(cls, t, tr(n)) for t, c, n in ACCOUNT_TYPES if c == cls]
    choices.append((None, None, tr("Не задан")))
    return choices


def class_icon(account_class: str | None) -> QIcon:
    colors: dict[str | None, str] = {code: color for code, _, color in ACCOUNT_CLASSES}
    color = getattr(P, colors.get(account_class, "hairline"))
    if color not in _CLASS_ICONS:
        _CLASS_ICONS[color] = dot_icon(color, 10)
    return _CLASS_ICONS[color]
