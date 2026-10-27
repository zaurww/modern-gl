"""Every window looks as DESIGN.md says (D147): a new window is not done until it is
here. A window that loads from outside — the portal's e-qaimə and ƏDV DH, their
reconciliations, a bank's files — is an `ImportWindow` (DESIGN.md §7) and is checked
live, at its first step and with rows: one title, the bar without buttons, one blue
button bottom right, the theme's own tones, no italics, no style of its own, the period
not left selected. Any other new dialog fails `test_every_dialog_is_known` until it is
given its place here."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTreeWidget,
    QWidget,
)

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import DepositFetched, parse_operation
from modern_gl.application.catalog import Catalog
from modern_gl.application.eqaime import parse_invoice
from modern_gl.desktop import theme
from modern_gl.desktop.import_window import MARGINS, SPACING, ImportWindow
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.theme.css import stylesheet
from modern_gl.reporting.eqaime_reconciliation import reconcile
from tests.helpers.eqaime import received
from tests.helpers.sales import make_shop
from tests.helpers.vat_deposit import OWN_TIN, PORTAL

DESKTOP = Path(__file__).parent.parent / "src" / "modern_gl" / "desktop"
DIALOG = re.compile(r"^class (\w+)\((\w+)\):", re.MULTILINE)

# The dialogs that are not loading windows: forms and pickers. Checked by their own tests
# for now; a new one is added to IMPORT_WINDOWS, or here with a line in «Долг» 7.
OTHER_DIALOGS = {
    "AccountDialog",
    "AccountPrompt",
    "AdvanceOffsetDialog",
    "BackupsDialog",
    "BankAccountDialog",
    "BankSettingsDialog",
    "BatchCostDialog",
    "BatchPostDialog",
    "CommandPalette",
    "ConversionAccountsDialog",
    "HistoryDialog",
    "InventorySettingsDialog",
    "InvoicePicker",
    "ItemDialog",
    "MonthRangeDialog",
    "NewNamesDialog",
    "PeriodDialog",
    "PickerDialog",
    "PortalLoginDialog",  # the portal's own page in a browser
    "ReasonDialog",
    "SplitLineDialog",
    "TagsDialog",
    "ValueDialog",
}
IMPORT_WINDOWS = {
    "EqaimeImportForm",
    "EqaimeImportDialog",
    "EqaimeReconciliationDialog",
    "DepositDialog",
    "DepositReconcileDialog",
    "BankFileDialog",
}


def test_every_dialog_is_known():
    found = {
        name: base
        for path in DESKTOP.rglob("*.py")
        for name, base in DIALOG.findall(path.read_text(encoding="utf-8"))
        if base in {"QDialog", "ImportWindow", *IMPORT_WINDOWS} or name.endswith("Dialog")
    }
    unknown = sorted(set(found) - OTHER_DIALOGS - IMPORT_WINDOWS - {"ImportWindow"})
    assert unknown == [], "новое окно — в tests/test_window_design.py (DESIGN.md §7)"
    loose = sorted(n for n in IMPORT_WINDOWS if found.get(n) == "QDialog")
    assert loose == [], "окно загрузки — на ImportWindow (DESIGN.md §7)"


# ---- the windows, live ---------------------------------------------------------------


@pytest.fixture
def shop_session(conn):
    shop = make_shop(conn, "1c77")
    cid = shop.company_id
    shop.ledger.set_company_tax_id(cid, OWN_TIN)
    session = Session(
        conn, shop.ledger, cid, "Mağaza", Catalog(conn, cid), working_date=date(2026, 10, 3)
    )
    deposit = shop.ledger.account_id(cid, "55")
    shop.ledger.set_account_type(cid, deposit, "vat_deposit")
    value = shop.ledger.bank.add_bank_account(cid, "ƏDV depozit", deposit, "vat_deposit")
    place = BankPlace(deposit, value, "ƏDV depozit", "55", None, "", "vat_deposit")
    return session, place


def eqaime_import(session, _place):
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog

    dialog = EqaimeImportDialog(session, today=date(2026, 3, 20))
    yield dialog
    dialog.show_invoices([parse_invoice(*received(), outgoing=False)])
    yield dialog


def eqaime_reconciliation(session, _place):
    from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog

    dialog = EqaimeReconciliationDialog(session, today=date(2026, 4, 1))
    yield dialog
    first, last = dialog.period_field.period()
    dialog.show_result(reconcile(session.conn, session.company_id, False, first, last, []))
    yield dialog


def deposit_fetched() -> DepositFetched:
    operations = [parse_operation(row, OWN_TIN) for row in PORTAL]
    return DepositFetched(operations, 100_000, "2026-10-01", "2026-10-03")


def deposit(session, place):
    from modern_gl.desktop.bank_page.portal import DepositDialog

    dialog = DepositDialog(session, place, today=date(2026, 10, 3))
    yield dialog
    dialog._loaded(deposit_fetched())
    yield dialog


def deposit_reconcile(session, place):
    from modern_gl.desktop.bank_page.deposit_reconcile import DepositReconcileDialog

    dialog = DepositReconcileDialog(session, place, today=date(2026, 10, 3))
    yield dialog
    dialog._fetched(deposit_fetched())
    yield dialog


def bank_file(session, _place):
    from modern_gl.desktop.bank_page.file_dialog import BankFileDialog

    yield BankFileDialog(session, ["missing.xlsx"])


STEPS = {
    "EqaimeImportDialog": eqaime_import,
    "EqaimeReconciliationDialog": eqaime_reconciliation,
    "DepositDialog": deposit,
    "DepositReconcileDialog": deposit_reconcile,
    "BankFileDialog": bank_file,
}


def theme_tones() -> set[str]:
    """The object names of labels the theme draws: a label has one of these, or none."""
    return {"", *re.findall(r"QLabel#(\w+)", stylesheet())}


def is_title(label: QLabel) -> bool:
    font, title = label.font(), fonts().title
    return font.pointSize() == title.pointSize() and font.weight() == title.weight()


def visible(window: QWidget, kind: type) -> list:
    return [w for w in window.findChildren(kind) if w.isVisibleTo(window)]


def layout_problems(window: ImportWindow) -> list[str]:
    """The skeleton: the margins, one title first, one blue button bottom right, the bar
    without buttons."""
    problems = []
    margins = window.root.contentsMargins()
    shown = (margins.left(), margins.top(), margins.right(), margins.bottom())
    if shown != MARGINS or window.root.spacing() != SPACING:
        problems.append(f"поля окна {shown}, а не {MARGINS}")
    titles = [label for label in visible(window, QLabel) if is_title(label)]
    if titles != [window.title] or window.root.itemAt(0).widget() is not window.title:
        problems.append("заголовок — один, первым")
    primaries = [b for b in visible(window, QPushButton) if b.objectName() == "primary"]
    if len(primaries) > 1:
        problems.append(f"синих кнопок {len(primaries)}: {[b.text() for b in primaries]}")
    problems += [
        f"синяя кнопка «{b.text()}» не внизу справа"
        for b in primaries
        if window.footer_right.indexOf(b) < 0
    ]
    bar = [window.bar.itemAt(n).widget() for n in range(window.bar.count())]
    if any(isinstance(widget, QPushButton) for widget in bar):
        problems.append("кнопка в панели: действия — внизу")
    return problems


def widget_problems(widget: QWidget, tones: set[str]) -> list[str]:
    """A widget in the theme's look: no style of its own, no italics, a tone the theme
    knows, the period's text not left selected, no zebra."""
    name, problems = type(widget).__name__, []
    if widget.styleSheet():
        problems.append(f"свой стиль у {name}: {widget.styleSheet()}")
    if widget.font().style() == QFont.Style.StyleItalic:
        problems.append(f"курсив у {name}")
    if isinstance(widget, QLabel) and widget.objectName() not in tones:
        problems.append(f"тон «{widget.objectName()}» не из темы: {widget.text()[:30]}")
    if isinstance(widget, QLineEdit) and widget.isVisible() and widget.hasSelectedText():
        problems.append(f"текст поля выделен: {widget.text()}")
    if isinstance(widget, QTreeWidget | QTableWidget) and widget.alternatingRowColors():
        problems.append(f"зебра в {name}")
    return problems


def design_problems(window: ImportWindow) -> list[str]:
    """What in the window is not as DESIGN.md says."""
    tones = theme_tones()
    problems = layout_problems(window)
    for widget in window.findChildren(QWidget):
        problems += widget_problems(widget, tones)
    return problems


@pytest.mark.parametrize("name", sorted(STEPS))
def test_the_window_is_as_designed(qtbot, shop_session, name):
    theme.apply(QApplication.instance())
    session, place = shop_session
    steps = STEPS[name](session, place)
    for n, window in enumerate(steps, 1):
        if n == 1:
            qtbot.addWidget(window)
            window.show()
        qtbot.wait(10)
        assert design_problems(window) == [], f"{name}, шаг {n}"


def test_every_import_window_is_checked_live():
    assert set(STEPS) == IMPORT_WINDOWS - {"EqaimeImportForm"}
