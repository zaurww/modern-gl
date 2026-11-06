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
from tests.helpers.qt import running_app
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
    "CustomsPaymentDialog",
    "ItemDialog",
    "MonthRangeDialog",
    "NewItemsDialog",
    "NewNamesDialog",
    "PeriodDialog",
    "PickerDialog",
    "PortalLoginDialog",  # the portal's own page in a browser
    "ReasonDialog",
    "ReceiptPicker",
    "SplitLineDialog",
    "TagsDialog",
    "UnusedItemsDialog",
    "WaitingExpensesDialog",
    "ValueDialog",
}
# forms checked live by the general rules (test_the_form_is_as_designed below)
FORMS = {
    "ChangeAccountDialog",
    "CrashDialog",
    "FillBalanceDialog",
    "SplitAccountDialog",
    "VerificationDialog",
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
    unknown = sorted(set(found) - OTHER_DIALOGS - FORMS - IMPORT_WINDOWS - {"ImportWindow"})
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
    first = window.root.itemAt(0)
    if titles != [window.title] or first is None or first.widget() is not window.title:
        problems.append("заголовок — один, первым")
    primaries = [b for b in visible(window, QPushButton) if b.objectName() == "primary"]
    if len(primaries) > 1:
        problems.append(f"синих кнопок {len(primaries)}: {[b.text() for b in primaries]}")
    problems += [
        f"синяя кнопка «{b.text()}» не внизу справа"
        for b in primaries
        if window.footer_right.indexOf(b) < 0
    ]
    bar = [item.widget() for item in map(window.bar.itemAt, range(window.bar.count())) if item]
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
    theme.apply(running_app())
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


# ---- forms, live ---------------------------------------------------------------------


def crash_form() -> QWidget:
    from modern_gl.desktop.crash_dialog import CrashDialog

    return CrashDialog("Traceback (most recent call last):\n  ...\nValueError: x\n")


def verification_form() -> QWidget:
    """«Проверка книги» with a check passed, one with findings and the rebuild."""
    from modern_gl.application.verification import REBUILD, CheckResult, Finding
    from modern_gl.desktop.verification_dialog import VerificationDialog
    from modern_gl.infrastructure.db import connect

    conn = connect(":memory:")
    shop = make_shop(conn, "classic")
    cid = shop.company_id
    session = Session(conn, shop.ledger, cid, "Mağaza", Catalog(conn, cid))
    dialog = VerificationDialog(session, lambda _doc_id: None)
    dialog.show_results(
        [
            CheckResult("Файл компании цел", ()),
            CheckResult(
                "Проводки модулей совпадают с их документами",
                (Finding("№7 от 07.03.2026: проводки отличаются", 1), Finding("файл")),
                REBUILD,
            ),
        ]
    )
    return dialog


def change_account_form() -> QWidget:
    """«Сменить счёт у отмеченных» of the bank, nothing marked yet."""
    from modern_gl.desktop.bank_page.change_account import ChangeAccountDialog
    from modern_gl.infrastructure.db import connect

    conn = connect(":memory:")
    shop = make_shop(conn, "classic")
    cid = shop.company_id
    session = Session(conn, shop.ledger, cid, "Mağaza", Catalog(conn, cid))
    return ChangeAccountDialog(session, [])


def split_account_form() -> QWidget:
    """«Сделать счёт группой» — «Добавить субсчёт…» on an account with postings."""
    from modern_gl.desktop.split_account_dialog import SplitAccountDialog
    from modern_gl.infrastructure.db import connect

    conn = connect(":memory:")
    shop = make_shop(conn, "classic")
    cid = shop.company_id
    catalog = Catalog(conn, cid)
    session = Session(conn, shop.ledger, cid, "Mağaza", catalog)
    return SplitAccountDialog(session, catalog.by_code["76"])


def fill_balance_form() -> QWidget:
    """«Заполнить остатком» in a document, as it opens: the account is typed first."""
    from modern_gl.desktop.fill_balance_dialog import FillBalanceDialog
    from modern_gl.infrastructure.db import connect

    conn = connect(":memory:")
    shop = make_shop(conn, "classic")
    cid = shop.company_id
    catalog = Catalog(conn, cid)
    session = Session(conn, shop.ledger, cid, "Mağaza", catalog)
    return FillBalanceDialog(session, "2026-12-31", ("common",), None)


FORM_STEPS = {
    "ChangeAccountDialog": change_account_form,
    "FillBalanceDialog": fill_balance_form,
    "CrashDialog": crash_form,
    "SplitAccountDialog": split_account_form,
    "VerificationDialog": verification_form,
}


def form_problems(form: QWidget) -> list[str]:
    """A form in the theme's look: the general rules of a widget, and at most one blue
    button, the last one in its row (bottom right)."""
    tones = theme_tones()
    problems = [p for w in form.findChildren(QWidget) for p in widget_problems(w, tones)]
    primaries = [b for b in visible(form, QPushButton) if b.objectName() == "primary"]
    if len(primaries) > 1:
        problems.append(f"синих кнопок {len(primaries)}: {[b.text() for b in primaries]}")
    for b in primaries:
        row = [w for w in visible(form, QPushButton) if w.parent() is b.parent()]
        if max(row, key=lambda w: w.mapTo(form, w.rect().topRight()).x()) is not b:
            problems.append(f"синяя кнопка «{b.text()}» не справа")
    return problems


@pytest.mark.parametrize("name", sorted(FORM_STEPS))
def test_the_form_is_as_designed(qtbot, name):
    theme.apply(running_app())
    form = FORM_STEPS[name]()
    qtbot.addWidget(form)
    form.show()
    qtbot.wait(10)
    problems = form_problems(form)
    assert problems == [], (name, problems)


def test_every_form_is_checked_live():
    assert set(FORM_STEPS) == FORMS
