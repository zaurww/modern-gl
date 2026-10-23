"""A name typed in a cell that its directory lacks: asked, added to the directory and put
into the cell — one way for the journal document, opening balances, templates, warehouse
documents and landed costs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QMessageBox, QWidget

from modern_gl.desktop.session import Session
from modern_gl.i18n import tr

Index = QModelIndex | QPersistentModelIndex


class CellTable(Protocol):
    def model(self) -> QAbstractItemModel: ...
    def edit_again(self, index: Index, text: str) -> None: ...
    def edit_next(self, index: Index) -> None: ...


def ask_add(parent: QWidget, text: str, directory: str) -> bool:
    """«“{text}” нет в справочнике … Добавить?» — Yes by default."""
    answer = QMessageBox.question(
        parent,
        tr("Новый элемент справочника"),
        tr("«{text}» нет в справочнике «{kind}». Добавить?", text=text, kind=directory),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes


def add_typed_value(
    session: Session, kind_id: int, text: str, owner_id: int | None = None, *, tell: bool = True
) -> int:
    """A new element of the directory (a contract of `owner_id`), in the lists at once;
    `tell` — a toast says where it went (pasted lines tell once for all)."""
    value_id = session.ledger.add_subconto_value(
        session.company_id, kind_id, text, owner_id=owner_id
    )
    session.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
    if tell:
        kind = session.catalog.kinds[kind_id]
        session.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
    return value_id


def offer_new_value(
    parent: QWidget,
    session: Session,
    table: CellTable,
    index: QPersistentModelIndex,
    kind_id: int,
    text: str,
    owner_at: Callable[[int, int], int | None],
) -> None:
    """Add `text` to its directory? Yes — added (a contract of the line's counterparty,
    `owner_at(row, column)`), put into the cell, on to the next one; No — back into the
    cell to correct it."""
    answer = ask_add(parent, text, session.catalog.kinds[kind_id])
    if not index.isValid():
        return
    if not answer:
        table.edit_again(index, text)
        return
    value_id = add_typed_value(session, kind_id, text, owner_at(index.row(), index.column()))
    model = table.model()
    model.setData(model.index(index.row(), index.column()), value_id)
    table.edit_next(index)
