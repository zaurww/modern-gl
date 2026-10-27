"""Shared from test_entry_keys.py (moved here: other test modules use it too)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


def focused():
    return QApplication.focusWidget()


def type_text(editor, text: str) -> None:
    editor.setText(text)
    editor.textEdited.emit(text)


def shown_list(qtbot):
    def popup():
        return next(
            (
                w
                for w in QApplication.topLevelWidgets()
                if w.objectName() == "completer" and w.isVisible()
            ),
            None,
        )

    qtbot.waitUntil(lambda: popup() is not None)
    return popup()


def items(popup) -> list[str]:
    m = popup.model()
    return [m.index(i, 0).data() for i in range(m.rowCount())]
