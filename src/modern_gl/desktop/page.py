"""What the window asks of every page it shows (D160): one protocol instead of
`getattr(page, "is_dirty", …)` and chains of `isinstance`. A page inherits `PageWidget`
and overrides what it does differently; the window calls the protocol only."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from PySide6.QtWidgets import QVBoxLayout, QWidget

from modern_gl.desktop.widgets import EmptyState


@runtime_checkable
class Page(Protocol):
    """A page in the window's stack."""

    @property
    def key(self) -> tuple[Any, ...]:
        """What the page is kept under: a place («journal»,), a document («doc», id)…"""
        ...

    def title(self) -> str:
        """Shown in the sidebar's «Открытые» («•» at the end — unsaved)."""
        ...

    def is_dirty(self) -> bool:
        """Unsaved changes: closing asks."""
        ...

    def save(self, post: bool) -> bool:
        """«Сохранить» on closing a dirty page; True when it went through."""
        ...

    def refresh(self) -> None:
        """Read again and show."""
        ...

    def activated(self) -> None:
        """The page was brought to the front (opened, shown again, after «Undo»)."""
        ...

    def on_postings_changed(self, doc_id: int) -> None:
        """Postings of a document were written somewhere else in the window."""
        ...


class PageWidget(QWidget):
    """The page's defaults: nothing to save, nothing to refresh, the table takes the
    focus when the page is shown. A page overrides what it needs."""

    # a tuple; typed Any so that a page may compute it (a document's, once it is saved)
    key: Any = ()

    def title(self) -> str:
        return ""

    def is_dirty(self) -> bool:
        return False

    def save(self, post: bool) -> bool:
        return True

    def refresh(self) -> None:
        pass

    def focus_table(self) -> None:
        """The cursor where the work is (the table, the first field)."""

    def activated(self) -> None:
        self.focus_table()

    def on_postings_changed(self, doc_id: int) -> None:
        pass


class EmptyPage(PageWidget):
    """A page that only says why there is nothing here (no company, no opening balances
    while viewing)."""

    def __init__(self, key: tuple[Any, ...], title: str, hint: str) -> None:
        super().__init__()
        self.key = key
        self._title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(EmptyState("○", title, hint))

    def title(self) -> str:
        return self._title
