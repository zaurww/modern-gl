"""The statement's window advises to load the e-qaimə first: only when a sender is not in
the directory and the company knows no e-qaimə of the file's months (D205, D206). The file:
03.08, −300.00 to BETA MMC, whom the directory lacks."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.bank.file_import import iban_places
from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.invoices import eqaime_known
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.desktop.session import Session
from tests.helpers.kapital import AZN_IBAN, OWN_TIN, kapital_file

BETA_TIN = "2200000002"
LINE = (
    "2026-08-03",
    "1 / 1",
    f"AZ44AIIB00000000000000000002 / BETA MMC / {BETA_TIN}",
    "-300",
    "-300",
    "muqavileye esasen",
)


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Подсказка")
    ledger.set_company_tax_id(cid, OWN_TIN)
    apply_chart_template(ledger, cid, "1c77", "ru")
    ledger.bank.add_bank_account(
        cid, "Kapital AZN", ledger.account_id(cid, "51"), "current", iban=AZN_IBAN
    )
    assert iban_places(ledger.conn, cid)
    return cid


@pytest.fixture
def window(qtbot, ledger, firm, tmp_path):
    def opened():
        from modern_gl.desktop.bank_page.file_dialog import BankFileDialog

        s = Session(ledger.conn, ledger, firm, "ООО", Catalog(ledger.conn, firm), notify=print)
        s.working_date = date(2026, 8, 5)
        path = kapital_file(tmp_path / "azn.xlsx", AZN_IBAN, "AZN", "5000", [LINE])
        dialog = BankFileDialog(s, [path])
        qtbot.addWidget(dialog)
        return dialog

    return opened


def portal_row(ledger, cid, day: str) -> None:
    ledger.conn.execute(
        "INSERT INTO eqaime_portal (company_id, outgoing, number, doc_date, status, total, vat, "
        "first_seen, last_seen) VALUES (?, 0, 'MT260800000001', ?, 'x', 100, 0, ?, ?)",
        (cid, day, day, day),
    )


def test_nothing_known_it_advises(window):
    note = window().eqaime_note
    assert not note.isHidden()
    assert "e-qaimə" in note.text()


def test_an_eqaime_of_the_month_is_enough(ledger, firm, window):
    portal_row(ledger, firm, "2026-08-01")
    assert window().eqaime_note.isHidden()


def test_last_months_eqaime_does_not_count(ledger, firm, window):
    portal_row(ledger, firm, "2026-07-31")
    assert not window().eqaime_note.isHidden()


def test_every_sender_known_says_nothing(ledger, firm, window):
    kind = ledger.subconto_kind_id(firm, "counterparty")
    beta = ledger.add_subconto_value(firm, kind, "BETA MMC")
    ledger.set_subconto_value_tax(firm, beta, BETA_TIN)
    assert window().eqaime_note.isHidden()


def test_a_posting_with_a_number_counts(ledger, firm):
    cid = firm
    assert not eqaime_known(ledger.conn, cid, "2026-08-01", "2026-08-05")
    kind = ledger.subconto_kind_id(cid, "counterparty")
    beta = ledger.add_subconto_value(cid, kind, "Бета")
    cost = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    cost_account, supplier = (ledger.account_id(cid, c) for c in ("26", "60.1"))
    posting = PostingInput(cost_account, supplier, "10", [cost], [beta], invoice="MT260800000001")
    ledger.post_new(cid, "2026-08-02", [posting])
    assert eqaime_known(ledger.conn, cid, "2026-08-01", "2026-08-05")
    assert not eqaime_known(ledger.conn, cid, "2026-08-03", "2026-08-05")
