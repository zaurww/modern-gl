"""Tags of the company («Связанная сторона», «Арендодатель»): pills of an element, added,
renamed, deleted right there (D64)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import FlowLayout, button
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class TagPicker(QWidget):
    """The tags of an element as pills: a click puts one on or off; «+ Метка» makes a new
    one (it is on at once); the menu of a pill renames or deletes it for the company."""

    def __init__(self, session: Session, chosen: frozenset[int] = frozenset()) -> None:
        super().__init__()
        self.s = session
        self._chosen = set(chosen)
        self.flow = FlowLayout(self)
        self.pills: dict[int, QPushButton] = {}
        self.add = button(tr("+ Метка"), "flat", tr("Новая метка, например «Связанная сторона»"))
        self.add.clicked.connect(self.new_tag)
        self._fill()

    def chosen(self) -> set[int]:
        return {tag_id for tag_id, pill in self.pills.items() if pill.isChecked()}

    def _fill(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None and widget is not self.add:
                widget.deleteLater()
        self.pills = {}
        for tag_id, name in self.s.catalog.sorted_tags():
            pill = button(name, "tag")
            pill.setCheckable(True)
            pill.setChecked(tag_id in self._chosen)
            pill.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            pill.customContextMenuRequested.connect(
                lambda pos, tag_id=tag_id, pill=pill: self._menu(tag_id, pill, pos)
            )
            self.pills[tag_id] = pill
            self.flow.addWidget(pill)
        self.flow.addWidget(self.add)
        self.updateGeometry()

    def _ask(self, title: str, text: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, tr("Название метки:"), text=text)
        return name.strip() if ok and name.strip() else None

    def new_tag(self) -> None:
        name = self._ask(tr("Новая метка"))
        if name is None:
            return
        try:
            tag_id = self.s.ledger.add_tag(self.s.company_id, name)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self._chosen = self.chosen() | {tag_id}
        self.s.catalog.reload()
        self._fill()

    def _menu(self, tag_id: int, pill: QPushButton, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr("Переименовать…")).triggered.connect(lambda: self._rename(tag_id))
        menu.addAction(tr("Удалить метку…")).triggered.connect(lambda: self._delete(tag_id))
        menu.exec(pill.mapToGlobal(pos))

    def _rename(self, tag_id: int) -> None:
        name = self._ask(tr("Переименовать"), self.s.catalog.tags[tag_id])
        if name is None:
            return
        self._change(lambda: self.s.ledger.rename_tag(self.s.company_id, tag_id, name))

    def _delete(self, tag_id: int) -> None:
        name = self.s.catalog.tags[tag_id]
        question = tr("Удалить метку «{name}»? Она снимется со всех элементов.", name=name)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        self._change(lambda: self.s.ledger.delete_tag(self.s.company_id, tag_id))

    def _change(self, action) -> None:
        try:
            action()
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self._chosen = self.chosen()
        self.s.catalog.reload()
        self._fill()


class TagsDialog(QDialog):
    """The tags of an element of a directory that has no window of its own (cost items)."""

    def __init__(self, session: Session, value: SubcontoInfo, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Метки"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(16)
        heading = QLabel(value.name)
        heading.setFont(fonts().heading)
        lay.addWidget(heading)
        self.picker = TagPicker(session, value.tags)
        lay.addWidget(self.picker)
        note = QLabel(tr("По метке отбирается ОСВ по субконто: например, все связанные стороны."))
        note.setObjectName("secondary")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = button(tr("Отмена"))
        save = button(tr("Сохранить"), "primary")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)
