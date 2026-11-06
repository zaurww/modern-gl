"""Editing a table cell 1C-like: a line editor with a searchable list, Enter and Tab
move on, a name the list lacks is offered to be added."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QStringListModel,
    Qt,
    QTimer,
    SignalInstance,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCompleter,
    QLineEdit,
    QTableView,
)

from modern_gl.application.catalog import Catalog, search
from modern_gl.i18n import fold, tr

TEMPLATE_MARK = "#"  # a list shows templates only after it
TABS = (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)


ENTERED = (
    Qt.FocusReason.MouseFocusReason,
    Qt.FocusReason.OtherFocusReason,  # the program moved the cursor here
    Qt.FocusReason.ShortcutFocusReason,
)


class WholeOnEntry(QObject):
    """Coming into a field selects what it holds, so typing replaces it, as in 1C (D78):
    "70" typed over "60 Malsatan…" is "70", not "7060 Malsatan…". Qt does it only for Tab;
    this adds a click and the program's own moves. A second click places the cursor. Cell
    editors are left to the table: it selects them itself, and the key that opened one
    is already typed in it."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.FocusIn
            and isinstance(watched, QLineEdit)
            and event.reason() in ENTERED  # pyright: ignore[reportAttributeAccessIssue]
            and not watched.isReadOnly()
            and watched.text()
            and not isinstance(watched.parent(), QAbstractSpinBox)
            and not _in_table(watched)
        ):
            QTimer.singleShot(0, lambda: _select_whole(watched))
        return False


def _in_table(edit: QLineEdit) -> bool:
    parent = edit.parent()
    return parent is not None and isinstance(parent.parent(), QAbstractItemView)


def _select_whole(edit: QLineEdit) -> None:
    try:
        if edit.hasFocus():
            edit.selectAll()
    except RuntimeError:  # the field closed meanwhile
        pass


def select_whole_on_entry(app: QApplication) -> None:
    """Once for the application: every field selects its text on entering it."""
    if app.property("gl_whole_on_entry"):
        return
    app.setProperty("gl_whole_on_entry", True)
    app.installEventFilter(WholeOnEntry(app))


def adding_label(text: str) -> str:
    return tr("+ Добавить «{text}»", text=text)


def names_it(label: str, text: str) -> bool:
    """The list item is the typed name itself (a counterparty's label adds its VÖEN)."""
    return fold(label.split("  ·  ", 1)[0]) == fold(text)


def exact_choice(choices: list[tuple[int, str]], text: str) -> int | None:
    """The item a text names in full: its label, name or code. No guessing by a fragment:
    a name pasted from a declaration must not land on another item."""
    needle = fold(text)
    for choice_id, label in choices:
        if needle in {fold(label), fold(label.split("  ", 1)[-1]), fold(label.split("  ", 1)[0])}:
            return choice_id
    return None


def resolve_choice(choices: list[tuple[int, str]], text: str) -> int | None:
    """The item a typed text names in a list of (id, label), labels as «code  name»: the
    exact label, name or code, else the one fragment (or the one it starts); None if
    nothing matches, LookupError if several do."""
    exact = exact_choice(choices, text)
    if exact is not None:
        return exact
    needle = fold(text)
    partial = [(choice_id, label) for choice_id, label in choices if needle in fold(label)]
    if len(partial) > 1:
        starts = [choice for choice in partial if fold(choice[1]).startswith(needle)]
        partial = starts if len(starts) == 1 else partial
    if len(partial) > 1:
        names = ", ".join(label for _, label in partial[:5])
        raise LookupError(tr("«{text}» подходит к нескольким: {names}", text=text, names=names))
    return partial[0][0] if partial else None


def edit_current(view: QTableView) -> None:
    """The current cell (the first one, if none) opened for typing: a cell reached from
    the keyboard shows its cursor, so it is clear that typing goes there."""
    model = view.model()
    if view.state() == QAbstractItemView.State.EditingState or model.rowCount() == 0:
        return
    index = view.currentIndex()
    if not index.isValid():
        first = next(
            (
                c
                for c in range(model.columnCount())
                if not view.isColumnHidden(c)
                and model.flags(model.index(0, c)) & Qt.ItemFlag.ItemIsEditable
            ),
            None,
        )
        if first is None:
            return
        index = model.index(0, first)
        view.setCurrentIndex(index)
    if index.flags() & Qt.ItemFlag.ItemIsEditable:
        view.edit(index)


def edit_next(view: QAbstractItemView, index: QModelIndex | QPersistentModelIndex) -> None:
    """From this cell on to the next one, open for typing, after a question that kept
    the cursor in the cell — as Enter would have gone (the view's `closeEditor` adds a
    row after the last cell)."""
    if not index.isValid():
        return
    idx = view.model().index(index.row(), index.column())
    view.setCurrentIndex(idx)
    view.edit(idx)
    editor = view.indexWidget(idx)
    if editor is not None:
        view.closeEditor(editor, QAbstractItemDelegate.EndEditHint.EditNextItem)


def edit_again(
    view: QAbstractItemView, index: QModelIndex | QPersistentModelIndex, text: str
) -> None:
    """Back into the cell with what was typed, to correct it."""
    if not index.isValid():
        return
    idx = view.model().index(index.row(), index.column())
    view.setCurrentIndex(idx)
    view.edit(idx)
    editor = view.indexWidget(idx)
    if isinstance(editor, QLineEdit):
        editor.setText(text)
        editor.selectAll()


def tabbed_in(event) -> bool:
    return event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)


class PickWithKeys(QObject):
    """On the open list, Enter or Tab takes the highlighted item."""

    KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab)

    def __init__(self, popup, choose) -> None:
        super().__init__(popup)
        self.choose = choose
        popup.installEventFilter(self)  # installed after QCompleter's, so it runs first

    def eventFilter(self, popup, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() in self.KEYS:
            index = popup.currentIndex()
            if popup.isVisible() and index.isValid():
                popup.hide()
                self.choose(index.data())
                return True
        return False


def fit_popup(popup: QAbstractItemView, rows: int, most: int = 12) -> None:
    """Height for exactly the rows shown: Qt does not count the popup's padding, so a
    short list would get a scroll bar."""
    shown = min(rows, most)
    margins = popup.contentsMargins()
    padding = 8 + margins.top() + margins.bottom()  # theme: QListView#completer padding 4px
    popup.setFixedHeight(popup.sizeHintForRow(0) * shown + padding)


def attach_list(
    editor: QLineEdit,
    items: list[str],
    show_all: bool,
    chosen,
    subaccounts: Callable[[str], list[str] | None] | None = None,
    can_add: bool = False,
) -> Callable[[], None]:
    """Completion list under a cell editor; `chosen(editor, text)` gets the picked item.
    `subaccounts(text)` lists the accounts of a group typed in full ("68"): they are
    offered with none taken, so Enter does not pick 68.1 behind the user's back.
    `can_add`: a typed name the list does not have is offered last as "+ Добавить «…»"
    (the only item, so Enter takes it, when nothing matches); picking it gives `chosen`
    the name, with the editor's "gl_add" property set.
    Returns `pick_first()`: the list again with its first item highlighted."""
    model = QStringListModel(editor)
    completer = QCompleter(model, editor)
    completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
    completer.setMaxVisibleItems(12)
    completer.setWidget(editor)  # filtering is ours (search), not Qt's prefix matching
    popup = cast(QAbstractItemView, completer.popup())
    popup.setObjectName("completer")
    adding = {"label": "", "text": ""}  # the "+ Добавить" item now in the list

    def refresh(text: str, pick_first: bool = False) -> None:
        try:
            # asked anew each time: PySide may drop a kept wrapper of the parentless popup
            popup = cast(QAbstractItemView, completer.popup())
            typed = bool(text.strip())
            group = subaccounts(text) if subaccounts and typed else None
            if group is not None:
                matches = group
            else:
                matches = search(items, text) if (typed or show_all) else []
            if not text.strip().startswith(TEMPLATE_MARK):  # templates only after "#"
                matches = [m for m in matches if not m.startswith(TEMPLATE_MARK)]
            name = text.strip()
            new = can_add and typed and not any(names_it(m, name) for m in matches)
            adding.update(label=adding_label(name) if new else "", text=name)
            if new:
                matches = [*matches, adding["label"]]
            model.setStringList(matches)
            if not matches:
                popup.hide()
                return
            rect = editor.rect()
            rect.setWidth(max(rect.width(), 380))
            completer.complete(rect)
            fit_popup(popup, len(matches))
            if (typed and group is None) or pick_first:  # Enter takes the best match
                popup.setCurrentIndex(model.index(0))
            else:  # the completer puts its cursor on the first row on showing the list
                popup.selectionModel().clear()
        except RuntimeError:  # editor already closed
            pass

    def pick(item: str) -> None:
        if adding["label"] and item == adding["label"]:
            editor.setProperty("gl_add", True)
            item = adding["text"]
        chosen(editor, item)

    editor.textEdited.connect(refresh)
    # mouse click; the str overload of the signal is not in the PySide6 stubs
    completer.activated[str].connect(pick)  # pyright: ignore[reportIndexIssue]
    # Enter / Tab on a highlighted item: Qt would hand the key to the editor *before*
    # reporting the choice, so the editor would commit what was typed (often nothing).
    PickWithKeys(popup, pick)
    QTimer.singleShot(0, lambda: refresh(editor.text()))
    return lambda: refresh(editor.text(), pick_first=True)


class CellEditor(QLineEdit):
    """A cell editor; an account cell keeps how to reopen its list on a group."""

    pick_first: Callable[[], None] | None = None
    catalog: Catalog | None = None


def attach_account_list(editor: CellEditor, items: list[str], catalog: Catalog, chosen) -> None:
    """The list of an account cell: suggestions from the first typed character, and a
    group typed in full ("68") lists its accounts (see `holds_on_group`)."""

    def subaccounts(text: str) -> list[str] | None:
        group = catalog.group_named(text)
        return [a.label for a in catalog.subaccounts(group)] if group else None

    editor.catalog = catalog
    editor.pick_first = attach_list(editor, items, False, chosen, subaccounts)


def holds_on_group(editor: QLineEdit, error: SignalInstance) -> bool:
    """Enter on a group in an account cell: a group is not posted to, so the editor
    stays open, says so, and highlights the group's first account. True if held."""
    if not isinstance(editor, CellEditor) or editor.catalog is None or not editor.pick_first:
        return False
    group = editor.catalog.group_named(editor.text())
    if group is None:
        return False
    error.emit(tr("{code} — группа: выберите субсчёт из списка", code=group.short))
    QTimer.singleShot(0, editor.pick_first)  # after the completer hides its popup
    return True
