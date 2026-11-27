"""«Объединить с…»: a counterparty entered twice becomes one (D233).
The extra one is chosen in the list, the one that stays — in the window; what will move
is shown before anything does."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.application.counterparties import same_named
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


def can_merge(session: Session, value: SubcontoInfo) -> bool:
    return (
        not session.read_only
        and not value.is_group
        and session.catalog.kind_codes.get(value.kind_id) == "counterparty"
    )


def merge_value(
    session: Session, parent: QWidget, value: SubcontoInfo, done: Callable[[int], None]
) -> None:
    """`value` is the extra one: the person picks the one that stays (one of the same
    name is offered first), sees what moves and confirms. `done(kept)` — after it."""
    cid = session.company_id
    alike = set(same_named(session.conn, cid, value.name))
    others = [
        v for v in session.catalog.all_values(value.kind_id) if v.id != value.id and not v.is_group
    ]
    if not others:
        return
    others.sort(key=lambda v: v.id not in alike)  # the namesakes first
    labels = [v.label for v in others]
    choice, ok = QInputDialog.getItem(
        parent,
        tr("Объединить"),
        tr("«{name}» — это тот же контрагент, что и:", name=value.name),
        labels,
        0,
        False,
    )
    if not ok:
        return
    keep = others[labels.index(choice)]
    try:
        plan = session.ledger.counterparty_merge_plan(cid, keep.id, value.id)
    except LedgerError as e:
        session.notify(str(e))
        return
    lines = [
        tr("«{extra}» станет «{kept}» во всех документах.", extra=value.name, kept=keep.name),
        tr("Документов: {n}, договоров: {m}.", n=plan.documents, m=plan.contracts),
    ]
    if plan.takes_tax_id:
        lines.append(
            tr("«{kept}» получит VÖEN {tax_id}.", kept=keep.name, tax_id=plan.takes_tax_id)
        )
    lines.append(
        tr("«{extra}» будет удалён из справочника. Отменить это нельзя.", extra=value.name)
    )
    question = "\n".join(lines)
    if QMessageBox.question(parent, tr("Объединить"), question) != QMessageBox.StandardButton.Yes:
        return
    try:
        session.ledger.merge_counterparties(cid, keep.id, value.id)
    except LedgerError as e:
        session.notify(str(e))
        return
    session.catalog.reload()
    session.notify(tr("«{extra}» объединён с «{kept}»", extra=value.name, kept=keep.name))
    done(keep.id)
