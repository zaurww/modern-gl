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

from modern_gl import __version__
from modern_gl.desktop import icons
from modern_gl.desktop.reports_hub.catalog import HUB, PIN_KEYS
from modern_gl.desktop.shortcuts import key_line
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import Chip, button, trailing_icon
from modern_gl.i18n import N_, tr

KEY_ROLE = Qt.ItemDataRole.UserRole
# The sidebar's places by what they are for (D56): entry on top without a heading, then
# reports, then the lists the books are kept with; key and title (translated on display).
# Icons are grey, the selected place's — the accent (D86)
PLACES = [
    (("home",), "Сегодня"),
    (("journal",), "Журнал"),
    (("opening",), "Начальные остатки"),
]
# «Все отчёты» (D114): one place for every report; the pinned ones are shown under it
REPORTS_PLACES = [(HUB, N_("Все отчёты"))]
# the reports that are places (open once, not closed): opened from «Все отчёты», in the
# sidebar only when pinned
REPORT_PAGES = [("osv",), ("statements",), ("invoices",)]
LISTS = [
    (("chart",), "План счетов"),
    (("directories",), "Справочники"),
    (("templates",), "Шаблоны"),
    (("currencies",), "Валюты"),
]
# Modules: optional ways of working beside the journal (D30, D44, D46, D47), in a block of their own
MODULES = [
    (("purchases",), "Покупки"),
    (("sales",), "Продажи"),
    (("bank",), "Банк и касса"),
    (("inventory",), "Склад"),
]
# section heading (None: no heading) and its places, top to bottom
SECTIONS = [
    (None, PLACES),
    (N_("Отчёты"), REPORTS_PLACES),
    (N_("Списки"), LISTS),
    (N_("Модули"), MODULES),
]
SIDEBAR_KEYS = [key for _, places in SECTIONS for key, _ in places]
PLACE_KEYS = SIDEBAR_KEYS + REPORT_PAGES  # every place: opened once, never closed
# «Только склад» (D90): the warehouse first, then the lists it needs; the books are not shown
STOCK_SECTIONS = [
    (
        None,
        [
            (("home",), N_("Сегодня")),
            (("inventory",), N_("Склад")),
            (("purchases",), N_("Покупки")),
            (("sales",), N_("Продажи")),
        ],
    ),
    (N_("Отчёты"), REPORTS_PLACES),  # the warehouse's reports; those of the books are not there
    (N_("Списки"), [(("directories",), N_("Справочники")), (("currencies",), N_("Валюты"))]),
]


def sections(stock_only: bool) -> list:
    return STOCK_SECTIONS if stock_only else SECTIONS


def shown_places(stock_only: bool) -> set:
    """The places a company of this mode shows; the others stay closed."""
    places = {key for _, places in sections(stock_only) for key, _ in places}
    return places if stock_only else places | set(REPORT_PAGES)


# what the sidebar keeps whatever is open: the places and the pinned reports (D114)
FIXED_KEYS = set(PLACE_KEYS) | set(PIN_KEYS)


# «Open»: only the last few pages, the rest — under «All (N)…», a menu (D86)
ALL_OPEN = ("open_all",)
OPEN_SHOWN = 3  # with every place and the headings' air, still no scrolling at 840 px
# open pages: a quiet grey icon of what they are (a new document is the blue plus)
OPEN_ICONS = {"doc": "document", "new": "new", "template": "templates", "import": "import"}
OPEN_ICONS |= {"inventory_doc": "inventory", "new_inventory": "inventory"}
OPEN_ICONS |= {"conversion": "currencies", "new_conversion": "currencies"}
OPEN_ICONS |= {"books": "books"}  # «Сравнение книг» (D98)
OPEN_ICONS |= {"bank_op": "bank", "new_bank_op": "bank"}


def open_icon(key) -> QIcon:
    name = OPEN_ICONS.get(key[0], "report")
    return icons.icon(name, P.accent if name == "new" else P.secondary, selected=P.accent)


def place_icon(key) -> QIcon:
    if key == ("home",):  # «Bu gün»: the one place in color, yellow as the sun (D86)
        return icons.icon("today", P.amber)
    return icons.icon(key[0], P.secondary, selected=P.accent)


PageT = TypeVar("PageT", bound=QWidget)


@runtime_checkable
class NavKeyed(Protocol):
    """A place shown in the sidebar under another key (a view of the statements, D114)."""

    def nav_key(self) -> tuple: ...


class NavDelegate(QStyledItemDelegate):
    """Draws a small × on open items (on hover or when selected), like a tab's close button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    @staticmethod
    def closable(key) -> bool:
        return key is not None and key not in FIXED_KEYS and key != ALL_OPEN

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
        trailing_icon(self.company)  # it opens the company menu
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
        self.nav.setFont(fonts().body)  # words, not sums: no figures of one width
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lay.addWidget(self.nav, 1)
        self.nav.setMouseTracking(True)
        self.nav.setItemDelegate(NavDelegate(self.nav))
        # a newer version (desktop/updater.py): hidden until one is found, then a red
        # button — it must catch the eye (user, 2026-11-03: «красным цветом»)
        self.new_version = button("", "dangerSolid")
        self.new_version.setFont(fonts().small)
        update = QHBoxLayout()
        update.setContentsMargins(12, 0, 12, 8)
        update.addWidget(self.new_version)
        update.addStretch(1)
        lay.addLayout(update)
        self.new_version.hide()
        self.hint = QLabel()
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setContentsMargins(20, 0, 0, 0)
        lay.addWidget(self.hint)
        self.retranslate()

    def retranslate(self, read_only: bool = False, stock_only: bool = False) -> None:
        self.viewing.setText(tr("Только просмотр"))
        self.viewing.setVisible(read_only)
        journal = not (read_only or stock_only)  # Ctrl+N is a new journal document
        keys = ["palette", "new_document" if journal else None, "close_page"]
        lines = [key_line(k) for k in keys if k] + [f"Modern GL {__version__}"]
        self.hint.setText("\n".join(lines))

    def add_section(self, title: str) -> QListWidgetItem:
        """A heading as in Things: in words, not capitals, of the items' size but bold, with
        air above it and none below, so a group keeps to its heading."""
        item = QListWidgetItem(title)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setFont(fonts().bold)
        item.setForeground(QColor(P.text))
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        item.setSizeHint(QSize(0, 40))
        item.setData(KEY_ROLE, None)
        self.nav.addItem(item)
        return item

    def add_item(self, key, text: str, icon: QIcon) -> QListWidgetItem:
        item = QListWidgetItem(icon, text)
        item.setData(KEY_ROLE, key)
        item.setSizeHint(QSize(0, 32))
        self.nav.addItem(item)
        return item

    def set_pins(self, pins: list[tuple[tuple, str, QIcon]]) -> None:
        """The pinned reports (key, title, icon) right under «Все отчёты» (D114). Quietly:
        an item taken away moves the current one, and that would open a place."""
        self.nav.blockSignals(True)
        for i in reversed(range(self.nav.count())):
            if self.nav.item(i).data(KEY_ROLE) in PIN_KEYS:
                self.nav.takeItem(i)
        hub = self.item_for(HUB)
        row = self.nav.row(hub) if hub is not None else -1
        for offset, (key, text, icon) in enumerate(pins if hub else [], start=1):
            item = QListWidgetItem(icon, text)
            item.setData(KEY_ROLE, key)
            item.setSizeHint(QSize(0, 32))
            self.nav.insertItem(row + offset, item)
        self.nav.blockSignals(False)

    def arrange_open(self, recent: list) -> None:
        """Show the open pages of `recent` (newest first) up to OPEN_SHOWN; with more —
        the item «All (N)…» at the end."""
        rows = [self.nav.item(i) for i in range(self.nav.count())]
        open_items = [item for item in rows if NavDelegate.closable(item.data(KEY_ROLE))]
        headings = [item for item in rows if item.flags() == Qt.ItemFlag.NoItemFlags]
        if headings:  # «Open» is the last heading; with nothing open it is not shown
            headings[-1].setHidden(not open_items)
        shown = recent[:OPEN_SHOWN]
        for item in open_items:
            item.setHidden(item.data(KEY_ROLE) not in shown)
        if (old := self.item_for(ALL_OPEN)) is not None:
            self.nav.takeItem(self.nav.row(old))
        if len(open_items) > OPEN_SHOWN:
            item = self.add_item(
                ALL_OPEN,
                tr("Все ({n})…", n=len(open_items)),
                icons.icon("more", P.secondary),
            )
            item.setForeground(QColor(P.secondary))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable: it only opens a menu

    def item_for(self, key) -> QListWidgetItem | None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(KEY_ROLE) == key:
                return self.nav.item(i)
        return None
