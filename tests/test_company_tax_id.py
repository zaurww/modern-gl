"""The company's VÖEN, and the tax portal checked against it (D111): data of another
firm is never loaded by mistake."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.queries import company_tax_id
from modern_gl.desktop import portal_login, theme
from modern_gl.desktop.portal_company import company_token
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import IntegrityError
from tests.test_eqaime_import import fake_token

OURS, OTHER = "1402375141", "1700000001"


def test_the_company_vöen_is_ten_digits_and_audited(ledger):
    cid = ledger.create_company("ООО VÖEN")
    assert company_tax_id(ledger.conn, cid) is None
    ledger.set_company_tax_id(cid, " 1402 375141 ")
    assert company_tax_id(ledger.conn, cid) == OURS
    with pytest.raises(ValidationError, match="10 цифр"):
        ledger.set_company_tax_id(cid, "14023")
    ledger.set_company_tax_id(cid, "")
    assert company_tax_id(ledger.conn, cid) is None
    actions = [
        r[0]
        for r in ledger.conn.execute(
            "SELECT action FROM audit_events WHERE entity = 'company' ORDER BY id"
        )
    ]
    assert actions.count("set_tax_id") == 2
    with pytest.raises(IntegrityError):  # the schema checks it too
        ledger.conn.execute("UPDATE companies SET tax_id = '14023x7890' WHERE id = ?", (cid,))


@pytest.fixture
def session(qtbot, ledger, monkeypatch):
    theme.apply(QApplication.instance())
    cid = ledger.create_company("ACCOUNTING MMC")
    portal_login.forget_token()
    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda _p, _t, text: warned.append(text))
    )
    s = Session(ledger.conn, ledger, cid, "ACCOUNTING MMC", Catalog(ledger.conn, cid))
    s.warned = warned  # type: ignore[attr-defined]
    yield s
    portal_login.forget_token()


def answer(monkeypatch, yes: bool) -> list[str]:
    asked: list[str] = []

    def question(_parent, _title, text):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


def test_the_first_sign_in_offers_the_portal_vöen(qtbot, session, monkeypatch):
    asked = answer(monkeypatch, yes=True)
    token = fake_token(OURS, "ACCOUNTİNG.AZ MMC")
    assert company_token(None, session, lambda _p: token) == token
    assert "VÖEN 1402375141" in asked[0] and "ACCOUNTING MMC" in asked[0]
    assert company_tax_id(session.conn, session.company_id) == OURS


def test_a_refused_vöen_is_not_remembered(qtbot, session, monkeypatch):
    answer(monkeypatch, yes=False)
    assert company_token(None, session, lambda _p: fake_token(OTHER)) is None
    assert company_tax_id(session.conn, session.company_id) is None


def test_a_token_of_another_firm_loads_nothing(qtbot, session, monkeypatch):
    asked = answer(monkeypatch, yes=True)
    session.ledger.set_company_tax_id(session.company_id, OURS)
    assert company_token(None, session, lambda _p: fake_token(OTHER, "BAŞQA MMC")) is None
    assert asked == [] and "BAŞQA MMC" in session.warned[0] and OURS in session.warned[0]
    assert company_tax_id(session.conn, session.company_id) == OURS


def test_the_open_session_is_used_only_for_its_firm(qtbot, session, monkeypatch):
    """The token kept in memory serves the company with its VÖEN; another company signs
    in again — the portal's window then waits for that firm."""
    session.ledger.set_company_tax_id(session.company_id, OURS)
    ours = fake_token(OURS)
    assert company_token(None, session, lambda _p: ours) == ours
    calls: list[str] = []
    assert company_token(None, session, lambda _p: calls.append("asked")) == ours
    assert calls == []  # signed in already
    wanted: list[str] = []
    monkeypatch.setattr(
        portal_login, "sign_in", lambda _parent, company="": wanted.append(company) or None
    )
    assert portal_login.portal_token(None, None, OTHER) is None
    assert wanted == [OTHER]
