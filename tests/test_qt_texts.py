"""Qt's own buttons speak the interface language."""

from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

from modern_gl.desktop import qt_texts
from modern_gl.i18n import set_language
from tests.helpers.qt import running_app


def test_standard_buttons_follow_the_language(qtbot):
    qt_texts.install(running_app())
    set_language("az")  # texts are taken when a button is made
    box = QMessageBox()
    qtbot.addWidget(box)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    assert box.button(QMessageBox.StandardButton.Yes).text().replace("&", "") == "Bəli"
    set_language("ru")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    qtbot.addWidget(buttons)
    assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Отмена"
