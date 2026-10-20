"""Qt's own button texts (OK, Cancel, Yes, No, Save…) in the interface language.

Message boxes and dialog button boxes take them from Qt, which ships no Azerbaijani
and is not given its Russian catalog here — so they came out in English. A translator
installed once answers those few texts through `tr`, following language switches.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QTranslator

from modern_gl.i18n import tr

# Qt's English text (without the "&" accelerator) -> our Russian source text
STANDARD = {
    "OK": "ОК",
    "Cancel": "Отмена",
    "Yes": "Да",
    "No": "Нет",
    "Save": "Сохранить",
    "Discard": "Не сохранять",
    "Don't Save": "Не сохранять",
    "Close": "Закрыть",
    "Apply": "Применить",
}


class StandardTexts(QTranslator):
    def translate(self, context, source_text, disambiguation=None, n=-1):
        if context not in ("QPlatformTheme", "QDialogButtonBox", "QMessageBox"):
            return ""
        key = STANDARD.get(source_text.replace("&", ""))
        return tr(key) if key else ""

    def isEmpty(self) -> bool:
        return False


def install(app: QCoreApplication) -> None:
    translator = StandardTexts(app)  # parented: lives as long as the application
    app.installTranslator(translator)
