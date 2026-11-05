"""«Вести количество» in the account's window (D201): the switch of quantity (D199) is
shown where the user thinks of it — the account — and stays its directory's."""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import AccountForm
from modern_gl.application.quantities import counted_accounts
from modern_gl.desktop import theme
from modern_gl.desktop.account_dialog import AccountDialog
from modern_gl.desktop.session import Session
from tests.helpers.qt import running_app


@pytest.fixture
def chart(ledger):
    cid = ledger.create_company("Ofis MMC")
    low = ledger.add_subconto_kind(cid, None, "Azqiymətlilər")
    cost = ledger.add_subconto_kind(cid, "cost_item", "Xərc maddələri")
    acc = {
        "12": ledger.add_account(
            cid, "12", "Azqiymətlilər", account_type="other_asset", subconto=[low]
        ),
        "13": ledger.add_account(
            cid, "13", "Köhnəlmə", account_type="other_asset", contra=True, subconto=[low]
        ),
        "26": ledger.add_account(
            cid, "26", "Xərclər", account_type="operating_expense", subconto=[cost]
        ),
    }
    return ledger, cid, low, cost, acc


def form_of(ledger, cid, account_id, counted) -> AccountForm:
    a = Catalog(ledger.conn, cid).accounts[account_id]
    return AccountForm(
        a.code,
        a.name,
        subconto=[k for k in a.sc_kinds if k is not None],
        account_class=a.account_class,
        account_type=a.account_type,
        contra=a.contra,
        counted=counted,
    )


def test_counting_an_account_makes_its_directory_one_of_objects(chart):
    ledger, cid, low, _, acc = chart
    assert counted_accounts(ledger.conn, cid) == set()
    ledger.save_account_form(cid, acc["12"], form_of(ledger, cid, acc["12"], True))
    assert Catalog(ledger.conn, cid).kind_per_line[low]
    assert counted_accounts(ledger.conn, cid) == {acc["12"]}  # 13 is its contra: no
    ledger.save_account_form(cid, acc["12"], form_of(ledger, cid, acc["12"], False))
    assert not Catalog(ledger.conn, cid).kind_per_line[low]
    assert counted_accounts(ledger.conn, cid) == set()


def test_left_as_it_is_without_the_switch(chart):
    ledger, cid, low, _, acc = chart
    ledger.set_subconto_kind_per_line(cid, low, True)
    ledger.save_account_form(cid, acc["12"], form_of(ledger, cid, acc["12"], None))
    assert Catalog(ledger.conn, cid).kind_per_line[low]


@pytest.fixture
def session(qtbot, chart):
    theme.apply(running_app())
    ledger, cid, *_ = chart
    return Session(ledger.conn, ledger, cid, "Ofis MMC", Catalog(ledger.conn, cid))


def test_the_switch_shows_only_on_an_asset_with_a_directory(session, chart, qtbot):
    _, _, _, _, acc = chart
    cat = session.catalog
    shown = {}
    for code in ("12", "13", "26"):
        dialog = AccountDialog(session, cat.accounts[acc[code]])
        qtbot.addWidget(dialog)
        shown[code] = dialog.counted.isVisibleTo(dialog)
    assert shown == {"12": True, "13": False, "26": False}


def test_ticked_in_the_window_and_said_which_directory(session, chart, qtbot):
    ledger, cid, _, _, acc = chart
    dialog = AccountDialog(session, session.catalog.accounts[acc["12"]])
    qtbot.addWidget(dialog)
    assert not dialog.counted.isChecked()
    dialog.counted.setChecked(True)
    assert dialog.counted_hint.text() == (
        "Справочник «Azqiymətlilər» — объекты: у каждой строки покупки свой элемент. "
        "Он же на счетах: 13"
    )
    dialog.save()
    assert counted_accounts(ledger.conn, cid) == {acc["12"]}


def test_a_new_account_with_a_new_directory_of_assets_suggests_counting(session, qtbot):
    """A new 10.9-like account of other assets with a directory nobody uses yet: ticked;
    an expense account: not even shown."""
    led, cid = session.ledger, session.company_id
    tools = led.add_subconto_kind(cid, None, "Alətlər")
    session.catalog.reload()
    dialog = AccountDialog(session, None)
    qtbot.addWidget(dialog)
    dialog.code.setText("12.1")
    dialog.name.setText("Alətlər")
    dialog.account_type.setCurrentIndex(dialog.account_type.findData("other_asset"))
    dialog.subconto[0].setCurrentIndex(dialog.subconto[0].findData(tools))
    assert dialog.counted.isChecked()
    dialog.save()
    assert Catalog(led.conn, cid).kind_per_line[tools]
    dialog = AccountDialog(session, None)
    qtbot.addWidget(dialog)
    dialog.account_type.setCurrentIndex(dialog.account_type.findData("operating_expense"))
    dialog.subconto[0].setCurrentIndex(dialog.subconto[0].findData(tools))
    assert not dialog.counted.isVisibleTo(dialog)
