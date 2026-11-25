"""D212: one payment to the customs. Declaration 0126: fees 100.00, the terminal 118.00 (100
and its ƏDV 18), ƏDV 500.00 of the declaration; counted by hand."""

from datetime import date

import pytest
from PySide6.QtWidgets import QDialog

from modern_gl.application.bank import (
    OTHER,
    OUT,
    BankLine,
    BankOperationInput,
    CustomsPayment,
    load_bank_operation,
)
from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.inventory import Inventory, ReceiptLine
from modern_gl.application.ledger import Ledger
from modern_gl.application.vat.facts import numbered_facts
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.landed_cost_page.waiting_expenses import WaitingExpensesDialog
from modern_gl.desktop.session import Session
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT, INPUT_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import CUSTOMS_DUTY, CUSTOMS_EXCISE, CUSTOMS_FEES
from modern_gl.i18n import trd
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.inventory import (
    customs_declarations,
    last_customs_party,
    receipt_line_choices,
    waiting_expenses,
)
from modern_gl.reporting.reports import trial_balance


class Firm:
    def __init__(self) -> None:
        self.conn = connect(":memory:")
        self.ledger = Ledger(self.conn, actor="test")
        self.cid = self.ledger.create_company("Firma")
        apply_chart_template(self.ledger, self.cid, "1c77", "ru")
        accounts = {
            r["code"].split(".")[0]: r["id"]  # the first posting account of each group
            for r in self.conn.execute(
                "SELECT id, code FROM accounts WHERE is_group = 0 ORDER BY code DESC"
            )
        }
        self.acc = accounts
        self.ledger.set_account_role(self.cid, BATCH_EXPENSES_ACCOUNT, accounts["15"])
        self.ledger.set_account_role(self.cid, INPUT_VAT, accounts["19"])
        kind = self.ledger.subconto_kind_id(self.cid, "counterparty")
        self.supplier = self.ledger.add_subconto_value(self.cid, kind, "Vial Kas")
        self.terminal = self.ledger.add_subconto_value(self.cid, kind, "AZƏRTERMİNAL")
        self.customs = self.ledger.add_subconto_value(self.cid, kind, "Gömrük")
        bank_kind = self.ledger.subconto_kind_id(self.cid, "bank_account")
        self.bank_sc = (self.ledger.add_subconto_value(self.cid, bank_kind, "Kapital"),)
        inventory = Inventory(self.conn, actor="test")
        unit = inventory.add_unit(self.cid, "ədəd", "ədəd")
        item = inventory.add_item(self.cid, "Datçik", unit, accounts["41"])
        main = inventory.add_warehouse(self.cid, "Əsas anbar")
        inventory.post_receipt(
            self.cid,
            "2026-09-21",
            [ReceiptLine(item, main, "10", "1000")],
            accounts["60"],
            [self.supplier],
            invoice="0126",
            invoice_kind="customs",
        )

    def pay(self, **amounts) -> int:
        return self.ledger.bank.save_customs_payment(
            self.cid,
            CustomsPayment(
                "2026-09-22",
                self.acc["51"],
                self.bank_sc,
                self.acc["60"],
                terminal_party=self.terminal,
                customs_party=self.customs,
                **amounts,
            ),
        )

    def closing(self, code: str) -> int:
        """The balance, debit positive."""
        osv = trial_balance(self.conn, self.cid, date(2026, 1, 1), date(2026, 12, 31))
        rows = [r for r in osv.rows if r.code == code]
        return sum(r.closing_dt - r.closing_ct for r in rows)


@pytest.fixture
def firm():
    made = Firm()
    yield made
    made.conn.close()


def test_one_payment_splits_by_what_it_pays(firm):
    """51: -718.00. 15: +100.00. 19: +500.00. 60: -1 000.00 goods + 118.00 paid to the
    terminal ahead of its e-qaimə; the customs' 500.00 owed and paid."""
    firm.pay(declaration="0126", fees=10_000, terminal=11_800, vat=50_000)
    assert firm.closing("51") == -71_800
    assert firm.closing("15") == 10_000
    assert firm.closing("19") == 50_000
    assert firm.closing("60") == -100_000 + 11_800


def test_the_vat_is_credited_as_paid_under_the_declaration(firm):
    """The credit reads the number: 500.00 on the day of the payment."""
    firm.pay(declaration="0126", vat=50_000)
    facts = numbered_facts(firm.conn, firm.cid, "2026-12-31")[("customs", "0126")]
    assert (facts.vat, sum(p.vat for p in facts.payments)) == (50_000, 50_000)


def test_the_short_declaration_pays_the_terminal_only(firm):
    """Its ƏDV is in the terminal's e-qaimə: no ƏDV of its own, no number needed."""
    firm.pay(terminal=3_540)
    assert firm.closing("19") == 0
    assert firm.closing("51") == -3_540


def loaded_line(firm: Firm, amount: int) -> int:
    """A line of a loaded statement nobody has told the account of: a draft."""
    return firm.ledger.bank.save_bank_operation(
        firm.cid,
        BankOperationInput(
            "2026-09-22",
            OUT,
            firm.acc["51"],
            (BankLine(None, amount),),
            OTHER,
            firm.bank_sc,
            memo="DGK ödəniş",
            reference="1370756096",
        ),
        post=False,
    )


def payment(firm: Firm, **amounts) -> CustomsPayment:
    return CustomsPayment(
        "2026-01-01",  # the line's own day counts
        firm.acc["51"],
        firm.bank_sc,
        firm.acc["60"],
        terminal_party=firm.terminal,
        customs_party=firm.customs,
        **amounts,
    )


def test_a_loaded_line_is_split_and_stays_one_line(firm):
    """718.00 of the statement: 100.00 + 118.00 + 500.00, the same line, reference and day."""
    line = loaded_line(firm, 71_800)
    saved = firm.ledger.bank.save_customs_payment(
        firm.cid,
        payment(firm, declaration="0126", fees=10_000, terminal=11_800, vat=50_000),
        line,
    )
    assert saved == line
    operation = load_bank_operation(firm.conn, firm.cid, line)
    assert (operation.reference, operation.doc_date) == ("1370756096", "2026-09-22")
    assert (operation.status, operation.total, operation.memo) == ("posted", 71_800, "DGK ödəniş")
    assert firm.closing("51") == -71_800
    assert firm.closing("19") == 50_000
    facts = numbered_facts(firm.conn, firm.cid, "2026-12-31")[("customs", "0126")]
    assert [(p.day, p.vat) for p in facts.payments] == [("2026-09-22", 50_000)]


def test_a_loaded_line_must_add_up_to_the_bank(firm):
    """718.00 in the bank, 700.00 typed: 18.00 short, nothing is written."""
    line = loaded_line(firm, 71_800)
    with pytest.raises(ValidationError, match=r"18\.00"):
        firm.ledger.bank.save_customs_payment(
            firm.cid, payment(firm, declaration="0126", fees=20_000, vat=50_000), line
        )
    assert firm.closing("19") == 0


def test_vat_needs_a_declaration(firm):
    with pytest.raises(ValidationError):
        firm.pay(vat=50_000)
    assert firm.closing("51") == 0


def test_a_payment_of_nothing_is_refused(firm):
    with pytest.raises(ValidationError):
        firm.pay()


def test_the_form_offers_the_declarations_and_the_last_customs(firm):
    assert customs_declarations(firm.conn, firm.cid) == ["0126"]
    assert last_customs_party(firm.conn, firm.cid) is None
    firm.pay(declaration="0126", vat=50_000)
    assert last_customs_party(firm.conn, firm.cid) == firm.customs


# ---- D221: the customs' bill line by line ------------------------------------------------


def test_duty_excise_and_fees_are_lines_of_their_own(firm):
    """The customs' bill for declaration 0126 (goods 1 000.00): duty 15% 150.00, excise
    20.00, fees 61.00, ƏDV 18% of 1 170.00 = 210.60; paid 441.60 at once.
    15: +231.00 in three lines, each under its name. 19: +210.60. 51: -441.60."""
    firm.pay(declaration="0126", duty=15_000, excise=2_000, fees=6_100, vat=21_060)
    assert firm.closing("51") == -44_160
    assert firm.closing("15") == 23_100
    assert firm.closing("19") == 21_060
    waiting = waiting_expenses(firm.conn, firm.cid, only_waiting=True)
    assert {row.memo: row.left for row in waiting} == {
        trd(CUSTOMS_DUTY): 15_000,
        trd(CUSTOMS_EXCISE): 2_000,
        trd(CUSTOMS_FEES): 6_100,
    }
    assert all("0126" in row.about for row in waiting)  # the batch finds them by the number


def test_the_lines_keep_their_names_when_the_operation_is_saved_again(firm):
    """The operation opened and saved as it is (the full form does so): the three names stay."""
    operation_id = firm.pay(declaration="0126", duty=15_000, fees=6_100, vat=21_060)
    loaded = load_bank_operation(firm.conn, firm.cid, operation_id)
    assert [line.memo for line in loaded.lines] == [trd(CUSTOMS_DUTY), trd(CUSTOMS_FEES), ""]
    firm.ledger.bank.save_bank_operation(
        firm.cid,
        BankOperationInput(
            loaded.doc_date,
            OUT,
            loaded.account_id,
            tuple(loaded.lines),
            OTHER,
            loaded.subconto,
            memo=loaded.memo,
        ),
        operation_id,
        post=True,
    )
    again = load_bank_operation(firm.conn, firm.cid, operation_id)
    assert [line.memo for line in again.lines] == [trd(CUSTOMS_DUTY), trd(CUSTOMS_FEES), ""]
    assert firm.closing("15") == 21_100


def test_a_split_statement_line_is_still_found_by_the_declaration(firm):
    """The statement's own text («DGK ödəniş») stays and names no declaration; the ƏDV line
    of the same payment does — the duty of 150.00 is found by it."""
    line = loaded_line(firm, 36_060)
    firm.ledger.bank.save_customs_payment(
        firm.cid, payment(firm, declaration="0126", duty=15_000, vat=21_060), line
    )
    (duty,) = waiting_expenses(firm.conn, firm.cid, only_waiting=True)
    assert (duty.memo, duty.left) == (trd(CUSTOMS_DUTY), 15_000)
    assert "0126" in duty.about


def test_the_batch_takes_them_under_their_kinds(firm, qtbot, monkeypatch):
    """Chosen for the purchase of declaration 0126, the duty 150.00 and the fees 61.00 come
    ticked and take the kinds of their names — made, as the directory had none; by value
    the ten pieces of 1 000.00 get all 211.00: Dt 41 / Kt 15, and 15 is empty again."""
    firm.pay(declaration="0126", duty=15_000, fees=6_100, vat=21_060)
    session = Session(firm.conn, firm.ledger, firm.cid, "Firma", Catalog(firm.conn, firm.cid))
    rows = waiting_expenses(firm.conn, firm.cid, only_waiting=True)
    dialog = WaitingExpensesDialog(rows, {"0126"})
    qtbot.addWidget(dialog)
    assert sorted(row.left for row in dialog.chosen()) == [6_100, 15_000]

    monkeypatch.setattr(WaitingExpensesDialog, "exec", lambda _self: QDialog.DialogCode.Accepted)
    page = LandedCostPage(session)
    qtbot.addWidget(page)
    page.targets.add(receipt_line_choices(firm.conn, firm.cid))
    page.add_waiting({"0126"})
    kinds = page.charges.cost_types
    taken = [row for row in page.charges.rows if row.taken]
    # not the ƏDV 210.60, though its postings name the declaration too
    assert {kinds.get(row.cost_type_id or 0): row.amount for row in taken} == {
        trd(CUSTOMS_DUTY): 15_000,
        trd(CUSTOMS_FEES): 6_100,
    }
    page.charges.rows[:] = [row for row in page.charges.rows if row.taken]
    assert page.save(True), page.error.text()
    assert firm.closing("15") == 0
    assert firm.closing("41") == 100_000 + 21_100
