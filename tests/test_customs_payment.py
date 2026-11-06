"""D212: one payment to the customs. Declaration 0126: fees 100.00, the terminal 118.00 (100
and its ƏDV 18), ƏDV 500.00 of the declaration; counted by hand."""

from datetime import date

import pytest

from modern_gl.application.bank import CustomsPayment
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.inventory import Inventory, ReceiptLine
from modern_gl.application.ledger import Ledger
from modern_gl.application.vat.facts import numbered_facts
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT, INPUT_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.inventory import customs_declarations, last_customs_party
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
