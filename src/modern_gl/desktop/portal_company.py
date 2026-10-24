"""The tax portal signed in for this company, not another (D113): everything loaded from
the portal — e-qaimə, their reconciliation, the ƏDV deposit account — asks for the token
here. A company with a VÖEN takes only a token of that VÖEN (the portal's window waits
until that firm is chosen); one without — the first sign-in offers the portal's VÖEN."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from modern_gl.application.queries import company_tax_id
from modern_gl.desktop import portal_login
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.tax_id import resident_tax_id
from modern_gl.i18n import tr

TITLE = "Портал e-taxes"


def ask_tax_id(parent: QWidget, current: str = "") -> str | None:
    """The company's VÖEN typed: 10 digits or empty (not known yet); None — cancelled."""
    text = current
    while True:
        text, ok = QInputDialog.getText(
            parent,
            tr("VÖEN компании"),
            tr("VÖEN компании (10 цифр; можно оставить пустым — его предложит портал):"),
            text=text,
        )
        if not ok:
            return None
        try:
            return resident_tax_id(text) or ""
        except ValidationError as e:
            QMessageBox.warning(parent, tr("VÖEN компании"), str(e))


def company_token(
    parent: QWidget, session: Session, ask: Callable[..., str | None] | None = None
) -> str | None:
    """A live token of the portal for the session's company, or None (cancelled, another
    firm on the portal — said to the user)."""
    own = company_tax_id(session.conn, session.company_id)
    token = portal_login.portal_token(parent, ask, own or "")
    if not token:
        return None
    tin = portal_login.company_tin(token)
    name = portal_login.company_name(token) or "—"
    if own:
        if tin == own:
            return token
        QMessageBox.warning(
            parent,
            tr(TITLE),
            tr(
                "Портал открыт для «{name}» · VÖEN {tin}, а это компания «{company}» · "
                "VÖEN {own}. Ничего не загружено: выберите на портале нужную фирму.",
                name=name,
                tin=tin,
                company=session.company_name,
                own=own,
            ),
        )
        return None
    question = tr(
        "Портал открыт для «{name}» · VÖEN {tin}.\n\nЭто компания «{company}»? VÖEN "
        "запомнится, и данные другой фирмы в неё уже не загрузятся.",
        name=name,
        tin=tin,
        company=session.company_name,
    )
    if QMessageBox.question(parent, tr(TITLE), question) != QMessageBox.StandardButton.Yes:
        return None
    try:
        session.ledger.set_company_tax_id(session.company_id, tin)
    except LedgerError as e:
        QMessageBox.warning(parent, tr(TITLE), str(e))
        return None
    return token
