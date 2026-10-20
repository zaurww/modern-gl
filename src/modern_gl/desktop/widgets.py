"""Small shared building blocks: page header, status chip, empty state, date prompt."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import ClassVar, cast

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QIcon
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
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

DATE_FORMAT = "dd.MM.yyyy"


def ru_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


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

    TONES: ClassVar[dict[str, tuple[str, str]]] = {
        "neutral": (P.secondary, P.subtle),
        "green": (P.green, P.green_soft),
        "amber": (P.amber, P.amber_soft),
        "red": (P.red, P.red_soft),
        "blue": (P.accent, P.accent_soft),
    }

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setFont(fonts().small)
        self.set(text, tone)

    def set(self, text: str, tone: str) -> None:
        fg, bg = self.TONES[tone]
        self.setText(text)
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: 10px; padding: 3px 10px;"
        )


class PageHeader(QWidget):
    """Large title, quiet subtitle, actions on the right."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(title)
        self.title.setFont(fonts().title)
        self.subtitle = QLabel(subtitle)
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


# Account classes (level 1 of statement classification): order, name, color.
ACCOUNT_CLASSES = [
    ("asset", "Активы", P.accent),
    ("liability", "Обязательства", P.amber),
    ("equity", "Капитал", P.violet),
    ("revenue", "Доходы", P.green),
    ("expense", "Расходы", P.red),
]
CLASS_ORDER: dict[str | None, int] = {code: i for i, (code, _, _) in enumerate(ACCOUNT_CLASSES)}
_CLASS_ICONS: dict[str | None, QIcon] = {}


def class_name(account_class: str | None) -> str:
    names = {code: name for code, name, _ in ACCOUNT_CLASSES}
    return tr(names[account_class]) if account_class in names else tr("Без класса")


def class_icon(account_class: str | None) -> QIcon:
    if account_class not in _CLASS_ICONS:
        colors: dict[str | None, str] = {code: color for code, _, color in ACCOUNT_CLASSES}
        _CLASS_ICONS[account_class] = dot_icon(colors.get(account_class, P.hairline), 10)
    return _CLASS_ICONS[account_class]
