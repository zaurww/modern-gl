"""«AI-помощник» (D83, D84, D234): connect the books to the AI programs of this computer
without a terminal — where (Claude Desktop, Claude Code) and what the AI is allowed
(read · drafts · edits). The window writes only the AI program's settings
(`infrastructure/assistant_clients.py`); the books themselves it does not touch."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, caption, segments
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure import assistant_clients as ai
from modern_gl.infrastructure.assistant_clients import Client, ClientError

MODE_NAMES = {ai.READ: N_("Только чтение"), ai.DRAFTS: N_("Черновики"), ai.EDITS: N_("Правки")}
MODE_NOTES = {
    ai.READ: N_("AI читает отчёты, документы и справочники. Изменить ничего не может."),
    ai.DRAFTS: N_("AI ещё и готовит черновики документов журнала. Проводите их вы."),
    ai.EDITS: N_(
        "AI ещё и исправляет проведённое в открытом периоде, на что вы указали: по одному "
        "документу, с причиной, и каждый раз спрашивает разрешение. Перед первой правкой "
        "делается копия файла. Не удаляет и не проводит черновики."
    ),
}
EXAMPLES = (
    N_("Какие e-qaimə не оплачены на конец месяца?"),
    N_("Проверь ОСВ за сентябрь: есть ли сальдо не на своей стороне и откуда оно?"),
    N_("Заведи черновик оплаты поставщику по e-qaimə с расчётного счёта 5 февраля."),
)


class AssistantDialog(QDialog):
    def __init__(
        self,
        load: Callable[[], list[Client]] = ai.clients,
        command: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.load, self.command = load, command
        self.clients: list[Client] = []
        self.boxes: dict[str, QCheckBox] = {}
        self.states: dict[str, QLabel] = {}
        self.setWindowTitle(tr("AI-помощник"))
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(8)
        self.status = QLabel()
        self.status.setFont(fonts().heading)
        root.addWidget(self.status)
        self._note(root).setText(
            tr(
                "AI отвечает на вопросы по вашим книгам: остатки, неоплаченные e-qaimə, "
                "ошибки в проводках. Проводит документы только человек."
            )
        )
        self._heading(root, tr("Что разрешено AI"))
        box, self.mode_buttons = segments(list(MODE_NAMES.items()), self.update_texts)
        root.addLayout(_left(box))
        self.mode_note = self._note(root)
        self._heading(root, tr("Где"))
        for key in ai.NAMES:
            root.addLayout(self._client_row(key))
        self._heading(root, tr("Что спросить"))
        for text in EXAMPLES:
            self._note(root).setText("«" + tr(text) + "»")
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.hide()
        root.addWidget(self.message)
        root.addStretch(1)
        root.addLayout(self._buttons())
        self.read_state()

    # ---- the form ------------------------------------------------------------------------

    def _heading(self, root: QVBoxLayout, text: str) -> None:
        root.addSpacing(14)
        label = QLabel(text)
        label.setFont(fonts().bold)
        root.addWidget(label)

    def _note(self, root: QVBoxLayout) -> QLabel:
        label = caption()
        label.setWordWrap(True)
        root.addWidget(label)
        return label

    def _client_row(self, key: str) -> QHBoxLayout:
        row = QHBoxLayout()
        box = QCheckBox(ai.NAMES[key])
        box.setMinimumWidth(150)  # the states stand in a column
        box.toggled.connect(lambda _=False: self.update_texts())
        self.boxes[key], self.states[key] = box, caption()
        row.addWidget(box)
        row.addSpacing(12)
        row.addWidget(self.states[key])
        row.addStretch(1)
        return row

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        close = button(tr("Закрыть"))
        self.apply_button = button(tr("Применить"), "primary")
        close.clicked.connect(self.accept)
        self.apply_button.clicked.connect(lambda _=False: self.apply())
        row.addWidget(close)
        row.addWidget(self.apply_button)
        return row

    # ---- what is connected ---------------------------------------------------------------

    def read_state(self) -> None:
        """The form as the AI programs are set now; nothing connected yet — the first
        installed program is ticked, so «Применить» connects it."""
        self.clients = self.load()
        connected = [c for c in self.clients if c.mode is not None]
        installed = [c for c in self.clients if c.config is not None]
        ticked = {c.key for c in connected} or {c.key for c in installed[:1]}
        mode = connected[0].mode if connected else ai.READ
        for client in self.clients:
            box = self.boxes[client.key]
            box.blockSignals(True)
            box.setChecked(client.key in ticked)
            box.setEnabled(client.config is not None)
            box.blockSignals(False)
        self.mode_buttons[mode or ai.READ].setChecked(True)
        self.update_texts()

    def mode(self) -> str:
        return next(key for key, b in self.mode_buttons.items() if b.isChecked())

    def changes(self) -> list[tuple[Client, str | None]]:
        """What «Применить» would do: each program whose state differs from the form, with
        the mode to set (None — disconnect)."""
        wanted = self.mode()
        found: list[tuple[Client, str | None]] = []
        for client in self.clients:
            if client.config is None:
                continue
            target = wanted if self.boxes[client.key].isChecked() else None
            if target != client.mode:
                found.append((client, target))
        return found

    def update_texts(self) -> None:
        connected = [c for c in self.clients if c.mode is not None]
        if connected:
            names = ", ".join(c.name for c in connected)
            self.status.setText(tr("AI подключён: {names}", names=names))
        else:
            self.status.setText(tr("AI не подключён"))
        self.mode_note.setText(tr(MODE_NOTES[self.mode()]))
        for client in self.clients:
            self.states[client.key].setText(_state(client))
        missing = self.command is None
        if missing:
            self._say(tr("Сервер AI не найден рядом с программой — переустановите программу."))
        self.apply_button.setEnabled(not missing and bool(self.changes()))

    def apply(self) -> None:
        """Write what the form says to each AI program; the first failure stops and is told."""
        command = self.command
        if command is None:
            return
        changed = self.changes()
        try:
            for client, mode in changed:
                if mode is None:
                    ai.disconnect(client)
                else:
                    ai.connect(client, command, mode)
        except ClientError as e:
            self.read_state()
            self._say(str(e))
            return
        self.read_state()
        names = ", ".join(client.name for client, _ in changed)
        text = tr("Готово. Изменение подействует после перезапуска: {names}.", names=names)
        if any(client.key == ai.DESKTOP for client, _ in changed):
            text += " " + tr("Claude Desktop закрывается полностью: значок у часов → Quit.")
        self._say(text, warn=False)

    def _say(self, text: str, warn: bool = True) -> None:
        self.message.setObjectName("warning" if warn else "secondary")
        self.message.setStyleSheet("")  # the object name changed: the style is read again
        self.message.setText(text)
        self.message.show()


def _state(client: Client) -> str:
    if client.config is None:
        return tr("не установлен на этом компьютере")
    if client.mode is None:
        return tr("не подключён")
    return tr("подключён · {mode}", mode=tr(MODE_NAMES[client.mode]).lower())


def _left(widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(widget)
    row.addStretch(1)
    return row
