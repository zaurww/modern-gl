"""Small shared building blocks: page header, status chip, empty state, date prompt."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import ClassVar, cast

from PySide6.QtCore import QDate, QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics, QHelpEvent, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.icons import status_mark
from modern_gl.desktop.theme import P, check_icon, dot_icon, fonts
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


class DateEdit(QDateEdit):
    """Tab leaves the field, as from any other (Qt's own walks day → month → year);
    the parts are typed one after another: a full part moves on to the next."""

    def focusNextPrevChild(self, next: bool) -> bool:
        return QWidget.focusNextPrevChild(self, next)


ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def enter_goes_on(page: QWidget, event) -> bool:
    """Enter in a field of a form goes on to the next field, as Tab does (D54) — the same
    in every form: a document, a bank operation, a conversion, a stock document.
    Cell editors of a table keep their own Enter. True if the key was used."""
    focused = QApplication.focusWidget()
    field = isinstance(focused, QLineEdit | QAbstractSpinBox | QComboBox)
    if (
        event.key() not in ENTER_KEYS
        or event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        or not field
        or focused is None
        or not page.isAncestorOf(focused)
    ):
        return False
    parent = focused.parentWidget()
    while parent is not None and parent is not page:
        if isinstance(parent, QAbstractItemView):  # a cell editor
            return False
        parent = parent.parentWidget()
    page.focusNextChild()
    return True


def date_edit(value: date, parent: QWidget | None = None) -> QDateEdit:
    w = DateEdit(to_qdate(value), parent)
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


def hide_when_viewing(read_only: bool, *widgets: QWidget) -> None:
    """A company open for viewing only (D80): what would change it is not shown."""
    if read_only:
        for w in widgets:
            w.hide()


MenuItem = tuple[str, Callable[[], object]] | None  # None: a separator


def more_button(items: Callable[[], list[MenuItem]], tooltip: str = "") -> QPushButton:
    """ "⋯": the less frequent actions of a page in a menu, so one main action stands
    out (as in Things). `items()` is asked each time, so the menu fits the moment."""
    return menu_button(button("⋯", "more", tooltip or tr("Ещё")), items)


def menu_button(b: QPushButton, items: Callable[[], list[MenuItem]]) -> QPushButton:
    """A button that opens a menu of `items()` under it."""

    def show() -> None:
        entries = items()
        if not entries:  # nothing to do now (a company open for viewing…)
            return
        menu = QMenu(b)
        for item in entries:
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

    # a draft and a posted one are shown as in the lists — Things' check circle, no pill
    CHECKS: ClassVar[dict[str, bool]] = {"amber": False, "green": True}

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setFont(fonts().small)
        self._check: bool | None = None
        self.set(text, tone)

    def set(self, text: str, tone: str) -> None:
        self.setText(text)
        self._check = self.CHECKS.get(tone)
        if self._check is not None:
            color = P.secondary if self._check else P.text
            self.setStyleSheet(f"color: {color}; background: transparent; padding: 3px 0 3px 22px;")
            self.update()
            return
        fg, bg = (getattr(P, name) for name in self.TONES[tone])
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: 10px; padding: 3px 10px;"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._check is None:
            return
        painter = QPainter(self)
        icon = status_icon(self._check)
        icon.paint(painter, 0, (self.height() - 16) // 2, 16, 16)
        painter.end()


class FlowLayout(QLayout):
    """Widgets in a row that wraps to the next line when the row is full (tags)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


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


class CutCellTips(QObject):
    """A table cell whose text does not fit shows it whole under the mouse; a cell that
    fits shows nothing (a tip repeating what is already seen is noise)."""

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self.view = view
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return False
        pos = cast(QHelpEvent, event).pos()
        index = self.view.indexAt(pos)
        text = str(index.data() or "") if index.isValid() else ""
        if not text or index.data(Qt.ItemDataRole.ToolTipRole):
            return False  # the model's own tip, if it has one
        font = index.data(Qt.ItemDataRole.FontRole) or self.view.font()
        room = self.view.visualRect(index).width() - 12  # the cell's padding
        if QFontMetrics(font).horizontalAdvance(text) <= room:
            QToolTip.hideText()
        else:
            QToolTip.showText(cast(QHelpEvent, event).globalPos(), text, self.view)
        return True


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


def tick_icon(ticked: bool) -> QIcon:
    """A row the user ticks to choose it, as Things marks a to-do: a hollow circle, the
    accent circle with a check once ticked."""
    key = f"check-{ticked}-{P.accent}-{P.tertiary}"  # themes change the colors
    if key not in _CLASS_ICONS:
        _CLASS_ICONS[key] = check_icon(ticked)
    return _CLASS_ICONS[key]


def status_icon(posted: bool) -> QIcon:
    """A document's status in a list: an accent check for a posted one, an amber dot for a
    draft. Nothing like a checkbox: users clicked the hollow circle to tick it (D73)."""
    key = f"status-{posted}-{P.accent}-{P.amber}"  # themes change the colors
    if key not in _CLASS_ICONS:
        _CLASS_ICONS[key] = status_mark(posted, P.accent, P.amber)
    return _CLASS_ICONS[key]


def class_icon(account_class: str | None) -> QIcon:
    colors: dict[str | None, str] = {code: color for code, _, color in ACCOUNT_CLASSES}
    color = getattr(P, colors.get(account_class, "hairline"))
    if color not in _CLASS_ICONS:
        _CLASS_ICONS[color] = dot_icon(color, 10)
    return _CLASS_ICONS[color]
