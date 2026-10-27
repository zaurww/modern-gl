"""Shared from test_entry_keys.py (moved here: other test modules use it too)."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit, QWidget

from tests.helpers import qt


def focused() -> QWidget | None:
    return QApplication.focusWidget()


def editor() -> QLineEdit:
    """The open cell editor (it has the focus)."""
    return qt.focused(QLineEdit)


def type_text(editor: QWidget | None, text: str) -> None:
    assert isinstance(editor, QLineEdit), editor
    editor.setText(text)
    editor.textEdited.emit(text)


def shown_list(qtbot) -> QAbstractItemView:
    def popup() -> QAbstractItemView | None:
        return next(
            (
                w
                for w in QApplication.topLevelWidgets()
                if isinstance(w, QAbstractItemView)
                and w.objectName() == "completer"
                and w.isVisible()
            ),
            None,
        )

    qtbot.waitUntil(lambda: popup() is not None)
    shown = popup()
    assert shown is not None
    return shown


def items(popup: QAbstractItemView) -> list[str]:
    m = popup.model()
    return [m.index(i, 0).data() for i in range(m.rowCount())]
