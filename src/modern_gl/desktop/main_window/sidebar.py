"""The sidebar (D56): the company, the places by what they are for, the open pages."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from PySide6.QtCore import (
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop import icons
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import Chip
from modern_gl.i18n import tr, upper

KEY_ROLE = Qt.ItemDataRole.UserRole
# The sidebar's places by what they are for (D56): entry on top without a heading, then
# reports, then the lists the books are kept with; key, title (translated on display), icon
# color (a palette name: themes change it)
PLACES = [
    (("journal",), "Журнал", "accent"),
    (("opening",), "Начальные остатки", "accent"),
]
REPORTS_PLACES = [
    (("osv",), "ОСВ", "green"),
    (("invoices",), "E-qaimələr", "accent"),
]
LISTS = [
    (("chart",), "План счетов", "violet"),
    (("directories",), "Справочники", "teal"),
    (("templates",), "Шаблоны", "amber"),
    (("currencies",), "Валюты", "green"),
]
# Modules: optional ways of working beside the journal (D30, D44, D46, D47), in a block of their own
MODULES = [
    (("purchases",), "Покупки", "green"),
    (("sales",), "Продажи", "accent"),
    (("bank",), "Банк", "teal"),
    (("inventory",), "Склад", "amber"),
]
# section heading (None: no heading) and its places, top to bottom
SECTIONS = [
    (None, PLACES),
    ("Отчёты", REPORTS_PLACES),
    ("Списки", LISTS),
    ("Модули", MODULES),
]
PLACE_KEYS = [key for _, places in SECTIONS for key, _, _ in places]
# open pages: a quiet grey icon of what they are (a new document is the blue plus)
OPEN_ICONS = {"doc": "document", "new": "new", "template": "templates", "import": "import"}
OPEN_ICONS |= {"inventory_doc": "inventory", "new_inventory": "inventory"}
OPEN_ICONS |= {"conversion": "currencies", "new_conversion": "currencies"}
OPEN_ICONS |= {"bank_op": "bank", "new_bank_op": "bank"}


def open_icon(key) -> QIcon:
    name = OPEN_ICONS.get(key[0], "report")
    return icons.icon(name, P.accent if name == "new" else P.secondary)


PageT = TypeVar("PageT", bound=QWidget)


@runtime_checkable
class TitledPage(Protocol):
    """A page shown as an item in the sidebar's "Open" section."""

    def title(self) -> str: ...


@runtime_checkable
class FocusablePage(Protocol):
    def focus_table(self) -> None: ...


class NavDelegate(QStyledItemDelegate):
    """Draws a small × on open items (on hover or when selected), like a tab's close button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    @staticmethod
    def closable(key) -> bool:
        return key is not None and key not in PLACE_KEYS

    @staticmethod
    def close_rect(rect: QRect) -> QRect:
        return QRect(rect.right() - 32, rect.center().y() - 8, 16, 16)

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        state = option.state
        hot = state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected)
        if not hot or not self.closable(index.data(KEY_ROLE)):
            return
        r = QRectF(self.close_rect(option.rect)).adjusted(4.5, 4.5, -4.5, -4.5)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(P.secondary), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())
        painter.restore()


class Sidebar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(250)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)
        self.company = QPushButton()
        self.company.setObjectName("company")
        self.company.setFont(fonts().heading)
        self.company.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.company)
        # a company open for viewing only (D80): said once, under its name
        self.viewing = Chip(tr("Только просмотр"), "blue")
        self.viewing.setToolTip(tr("Снимок файла: изменения не сохраняются"))
        viewing = QHBoxLayout()
        viewing.setContentsMargins(20, 0, 0, 8)
        viewing.addWidget(self.viewing)
        viewing.addStretch(1)
        lay.addLayout(viewing)
        self.viewing.hide()
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lay.addWidget(self.nav, 1)
        self.nav.setMouseTracking(True)
        self.nav.setItemDelegate(NavDelegate(self.nav))
        self.hint = QLabel()
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setContentsMargins(20, 0, 0, 0)
        lay.addWidget(self.hint)
        self.retranslate()

    def retranslate(self, read_only: bool = False) -> None:
        self.viewing.setText(tr("Только просмотр"))
        self.viewing.setVisible(read_only)
        self.hint.setText(
            tr("Ctrl+W  закрыть") if read_only else tr("Ctrl+N  новый документ\nCtrl+W  закрыть")
        )

    def add_section(self, title: str) -> None:
        item = QListWidgetItem(upper(title))
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setFont(fonts().caption)
        item.setForeground(QColor(P.tertiary))
        item.setSizeHint(QSize(0, 34))
        item.setData(KEY_ROLE, None)
        self.nav.addItem(item)

    def add_item(self, key, text: str, icon: QIcon) -> QListWidgetItem:
        item = QListWidgetItem(icon, text)
        item.setData(KEY_ROLE, key)
        item.setSizeHint(QSize(0, 34))
        self.nav.addItem(item)
        return item

    def item_for(self, key) -> QListWidgetItem | None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(KEY_ROLE) == key:
                return self.nav.item(i)
        return None
