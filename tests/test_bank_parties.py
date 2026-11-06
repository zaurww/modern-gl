"""The other side of a statement's line (D205): the bank's file never adds a
counterparty — the bank's spelling is a hint, the name comes from the tax portal. A line
whose sender the directory lacks waits as a draft that keeps the sender's VÖEN and name;
the counterparty is found by them once it is there.

One company (VÖEN 1400000001), Kapital AZN on 51, opening 5 000.00. Hand-calculated:

File of 01.08–05.08:
  03.08  −300.00  BETA MMC, VÖEN 2200000002, «avans»           → draft, no counterparty
  03.08  −118.00  BETA MMC, «MT260800000007»                   → draft, no counterparty
  05.08  +500.00  VIAL-CAS-BEL abroad, no VÖEN                 → draft, no counterparty

Then the purchases come (as the e-qaimə import brings them): «BETA TREYD MMC» with that
VÖEN, 02.08 — MT260800000007 for 118.00 and MT260800000009 for 200.00. The drafts find it:
  −300.00, no number: over the unpaid ones, oldest first — 118.00 [..07] + 182.00 [..09]
  −118.00, «..07»: unpaid 118.00, not exceeded — 118.00 [..07]
"""

from __future__ import annotations

import pytest

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.bank.file_import import iban_places
from modern_gl.application.bank.files import read_bank_file
from modern_gl.application.bank.imported import DRAFT
from modern_gl.application.bank.operations import BankOperationInput
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.i18n import tr
from tests.helpers.kapital import AZN_IBAN, OWN_TIN, VIAL, kapital_file

BETA_TIN = "2200000002"
BETA = f"AZ44AIIB00000000000000000002 / BETA MMC / {BETA_TIN}"
ABROAD = f"BY35PJCB30120763801000000978 / {VIAL}"
LINES = [
    ("2026-08-03", "1003 / 502", BETA, "-300", "-300", "muqavileye esasen avans"),
    ("2026-08-03", "1004 / 503", BETA, "-118", "-118", "MT260800000007 e-qaimeye esasen"),
    ("2026-08-05", "1007 / 506", ABROAD, "500", "500", "PAYMENT FOR ETIKET CONTRACT 2407"),
]
LATER = [
    ("2026-08-05", "1101 / 601", BETA, "-50", "-50", "muqavileye esasen"),
    ("2026-08-05", "1102 / 602", ABROAD, "200", "200", "PAYMENT FOR ETIKET CONTRACT 2407"),
]


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Стороны выписки")
    ledger.set_company_tax_id(cid, OWN_TIN)
    apply_chart_template(ledger, cid, "1c77", "ru")
    acc = {c: ledger.account_id(cid, c) for c in ("26", "51", "60.1", "62.1", "80")}
    bank = ledger.bank.add_bank_account(cid, "Kapital AZN", acc["51"], "current", iban=AZN_IBAN)
    kind = ledger.subconto_kind_id(cid, "counterparty")
    owner = ledger.add_subconto_value(cid, kind, "Учредитель")
    cost = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    ledger.post_new(
        cid, "2026-08-01", [PostingInput(acc["51"], acc["80"], "5000", [bank], [owner])]
    )
    places = iban_places(ledger.conn, cid)
    return {"cid": cid, "acc": acc, "kind": kind, "cost": cost, "places": places}


@pytest.fixture
def file(tmp_path):
    return read_bank_file(kapital_file(tmp_path / "azn.xlsx", AZN_IBAN, "AZN", "5000", LINES))


def operations(ledger, cid):
    """reference -> the operation."""
    rows = ledger.conn.execute(
        "SELECT id, reference FROM bank_operations WHERE company_id = ?", (cid,)
    )
    return {r["reference"]: load_bank_operation(ledger.conn, cid, r["id"]) for r in rows}


def lines(ledger, op):
    codes = {r["id"]: r["code"] for r in ledger.conn.execute("SELECT id, code FROM accounts")}
    return [(codes.get(x.account_id), x.amount, x.invoice) for x in op.lines]


def counterparties(ledger, firm) -> int:
    return ledger.conn.execute(
        "SELECT COUNT(*) FROM subconto_values WHERE company_id = ? AND kind_id = ?",
        (firm["cid"], firm["kind"]),
    ).fetchone()[0]


def purchases_of_beta(ledger, firm) -> int:
    """Beta as the e-qaimə import adds it — the portal's name, the VÖEN — and its two
    purchases of 02.08: 118.00 and 200.00."""
    cid, acc = firm["cid"], firm["acc"]
    beta = ledger.add_subconto_value(cid, firm["kind"], "BETA TREYD MMC")
    ledger.set_subconto_value_tax(cid, beta, BETA_TIN)
    ledger.post_new(
        cid,
        "2026-08-02",
        [
            PostingInput(
                acc["26"], acc["60.1"], "118", [firm["cost"]], [beta], invoice="MT260800000007"
            ),
            PostingInput(
                acc["26"], acc["60.1"], "200", [firm["cost"]], [beta], invoice="MT260800000009"
            ),
        ],
    )
    return beta


def test_the_file_adds_no_counterparty(ledger, firm, file):
    cid = firm["cid"]
    before = counterparties(ledger, firm)
    done = ledger.bank.import_bank_files(cid, [file], firm["places"])
    assert counterparties(ledger, firm) == before  # the owner alone, as it was
    assert (done.posted, done.drafts, done.unknown_parties) == (0, 3, 2)
    reasons = {row.op.reference: (row.state, row.reason) for row in done.rows}
    waits = tr("контрагента нет в справочнике: {name}, VÖEN {tin}", name="BETA MMC", tin=BETA_TIN)
    assert reasons["1003"] == (DRAFT, waits)
    assert reasons["1004"] == (DRAFT, waits)
    assert reasons["1007"] == (DRAFT, tr("контрагента нет в справочнике: {name}", name=VIAL))

    ops = operations(ledger, cid)
    advance, named, abroad = ops["1003"], ops["1004"], ops["1007"]
    for op in (advance, named, abroad):
        assert (op.status, op.counterparty_id) == ("draft", None)
        assert all(not any(line.subconto) for line in op.lines)  # nobody else's either
    assert (advance.party_tin, advance.party_name) == (BETA_TIN, "BETA MMC")
    assert (abroad.party_tin, abroad.party_name) == ("", VIAL)
    assert lines(ledger, advance) == [("60.1", 30000, "")]
    assert lines(ledger, named) == [("60.1", 11800, "MT260800000007")]
    assert lines(ledger, abroad) == [("62.1", 50000, "")]


def test_the_drafts_find_the_counterparty_once_it_is_there(ledger, firm, file):
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [file], firm["places"])
    assert ledger.bank.adopt_parties(cid) == 0  # nobody to find yet
    beta = purchases_of_beta(ledger, firm)

    assert ledger.bank.adopt_parties(cid) == 2
    ops = operations(ledger, cid)
    advance, named, abroad = ops["1003"], ops["1004"], ops["1007"]
    assert (advance.status, advance.counterparty_id) == ("draft", beta)
    assert lines(ledger, advance) == [
        ("60.1", 11800, "MT260800000007"),
        ("60.1", 18200, "MT260800000009"),
    ]
    assert (named.status, named.counterparty_id) == ("draft", beta)
    assert lines(ledger, named) == [("60.1", 11800, "MT260800000007")]
    assert abroad.counterparty_id is None  # not Beta's
    notes = {
        r["reference"]: r["note"]
        for r in ledger.conn.execute("SELECT reference, note FROM bank_operations")
    }
    assert notes["1003"] == tr("в назначении нет e-qaimə — разложено по старым")
    assert notes["1004"] == ""
    assert ledger.bank.adopt_parties(cid) == 0  # nothing left to find
    assert (
        ledger.conn.execute("SELECT name FROM subconto_values WHERE id = ?", (beta,)).fetchone()[0]
        == "BETA TREYD MMC"
    )  # the portal's name: the bank's is not written


def test_the_next_file_finds_it_before_its_lines(ledger, firm, file, tmp_path):
    """The purchases came between two files: the second file's line of Beta is Beta's at
    once, and the first file's drafts find it as the second is loaded."""
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [file], firm["places"])
    beta = purchases_of_beta(ledger, firm)
    later = read_bank_file(kapital_file(tmp_path / "later.xlsx", AZN_IBAN, "AZN", "5082", LATER))
    done = ledger.bank.import_bank_files(cid, [later], firm["places"])
    assert done.unknown_parties == 1  # VIAL-CAS-BEL still
    ops = operations(ledger, cid)
    assert [ops[ref].counterparty_id for ref in ("1003", "1004", "1101")] == [beta] * 3
    assert counterparties(ledger, firm) == 2  # the owner and Beta


def test_a_sender_without_voen_is_known_as_last_time(ledger, firm, file, tmp_path):
    """VIAL-CAS-BEL has no VÖEN: a person gives its line the counterparty «Vial» (their
    own name for it) — the next file's line of the same sender is Vial's."""
    cid, acc = firm["cid"], firm["acc"]
    ledger.bank.import_bank_files(cid, [file], firm["places"])
    vial = ledger.add_subconto_value(cid, firm["kind"], "Vial")
    abroad = operations(ledger, cid)["1007"]
    data = BankOperationInput(  # as the form saves it: it knows nothing of the bank's name
        doc_date=abroad.doc_date,
        direction=abroad.direction,
        account_id=abroad.account_id,
        lines=abroad.lines,
        kind=abroad.kind,
        subconto=abroad.subconto,
        counterparty_id=vial,
        memo=abroad.memo,
        reference=abroad.reference,
    )
    ledger.bank.save_bank_operation(cid, data, abroad.id, post=True, checked=True)
    saved = operations(ledger, cid)["1007"]
    assert (saved.status, saved.party_name) == ("posted", VIAL)  # the file's fact stays

    later = read_bank_file(kapital_file(tmp_path / "later.xlsx", AZN_IBAN, "AZN", "5082", LATER))
    done = ledger.bank.import_bank_files(cid, [later], firm["places"])
    again = operations(ledger, cid)["1102"]
    assert again.counterparty_id == vial
    assert lines(ledger, again) == [("62.1", 20000, "")]
    reasons = {row.op.reference: row.reason for row in done.rows}
    assert reasons["1102"] == tr("в назначении нет e-qaimə и долга нет — аванс?")
    assert acc["62.1"] == again.lines[0].account_id


def test_loading_again_adds_nothing(ledger, firm, file):
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [file], firm["places"])
    before = counterparties(ledger, firm)
    again = ledger.bank.import_bank_files(cid, [file], firm["places"])
    assert (again.posted, again.drafts, again.known, again.unknown_parties) == (0, 0, 3, 0)
    assert counterparties(ledger, firm) == before


# ---- the form -------------------------------------------------------------------------


@pytest.fixture
def session(ledger, firm):
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.session import Session

    cid = firm["cid"]
    s = Session(ledger.conn, ledger, cid, "ООО Тест", Catalog(ledger.conn, cid), notify=print)
    s.working_date = date(2026, 8, 5)
    return s


def test_the_form_names_the_sender_and_adds_it(qtbot, ledger, firm, file, session, monkeypatch):
    """The draft of −300.00 opened: «В выписке: BETA MMC, VÖEN 2200000002 — в справочнике
    нет». The button opens the directory's window with the bank's name and VÖEN to check;
    accepted — Beta is the counterparty of this line and of its other waiting line."""
    from PySide6.QtWidgets import QDialog

    from modern_gl.desktop.bank_operation_page import BankOperationPage
    from modern_gl.desktop.directories_page import ValueDialog

    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [file], firm["places"])
    advance = operations(ledger, cid)["1003"]
    page = BankOperationPage(session, advance.id)
    qtbot.addWidget(page)
    who = tr("{name}, VÖEN {tin}", name="BETA MMC", tin=BETA_TIN)
    assert not page.party_note.isHidden()
    assert page.party_text.text() == tr("В выписке: {who} — в справочнике нет", who=who)
    assert page.btn_party.text() == tr("Добавить в справочник…")
    shown = {}

    def exec_(dialog):
        shown.update(name=dialog.name.text(), tin=dialog.tax_id.text())
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", exec_)
    page.btn_party.click()
    assert shown == {"name": "BETA MMC", "tin": BETA_TIN}
    beta = ledger.conn.execute(
        "SELECT id, name, legal_name FROM subconto_values WHERE company_id = ? AND tax_id = ?",
        (cid, BETA_TIN),
    ).fetchone()
    assert (beta["name"], beta["legal_name"]) == ("BETA MMC", None)  # no official name yet
    assert page.counterparty == beta["id"]
    assert page.party_note.isHidden()
    assert not page.dirty  # as the import would have made it: saved already
    ops = operations(ledger, cid)
    assert [ops[ref].counterparty_id for ref in ("1003", "1004")] == [beta["id"]] * 2
    assert ops["1007"].counterparty_id is None


def test_the_form_offers_the_one_found_meanwhile(qtbot, ledger, firm, file, session):
    """Beta came with its purchases while the draft waited: the form says who it is in
    the directory; «Подставить» — the lines over its unpaid e-qaimə."""
    from modern_gl.desktop.bank_operation_page import BankOperationPage

    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [file], firm["places"])
    beta = purchases_of_beta(ledger, firm)
    session.catalog.reload()
    advance = operations(ledger, cid)["1003"]
    page = BankOperationPage(session, advance.id)
    qtbot.addWidget(page)
    who = tr("{name}, VÖEN {tin}", name="BETA MMC", tin=BETA_TIN)
    assert page.party_text.text() == tr(
        "В выписке: {who} — в справочнике это «{name}»", who=who, name="BETA TREYD MMC"
    )
    assert page.btn_party.text() == tr("Подставить")
    assert operations(ledger, cid)["1003"].counterparty_id is None  # opening wrote nothing
    page.btn_party.click()
    assert page.counterparty == beta
    assert lines(ledger, operations(ledger, cid)["1003"]) == [
        ("60.1", 11800, "MT260800000007"),
        ("60.1", 18200, "MT260800000009"),
    ]


def test_a_posted_or_hand_made_operation_has_no_note(qtbot, ledger, firm, file, session):
    from modern_gl.desktop.bank_operation_page import BankOperationPage

    page = BankOperationPage(session)
    qtbot.addWidget(page)
    assert page.party_note.isHidden()


def test_a_customer_is_found_the_same_way(ledger, firm, tmp_path):
    """Sales, by hand: 03.08 +236.00 from GAMMA MMC (VÖEN 3300000003), «MT260800000011»,
    the directory lacks it — a draft on 62.1, nobody added. Then its sale of 02.08 for
    236.00 under the portal's name: the draft is Gamma's, 236.00 on that e-qaimə."""
    cid, acc = firm["cid"], firm["acc"]
    other = "AZ55AIIB00000000000000000003 / GAMMA MMC / 3300000003"
    money = ("2026-08-03", "1201 / 701", other, "236", "236", "MT260800000011 e-qaimeye esasen")
    path = kapital_file(tmp_path / "in.xlsx", AZN_IBAN, "AZN", "5000", [money])
    before = counterparties(ledger, firm)
    done = ledger.bank.import_bank_files(cid, [read_bank_file(path)], firm["places"])
    assert (done.drafts, done.unknown_parties) == (1, 1)
    assert counterparties(ledger, firm) == before
    waiting = operations(ledger, cid)["1201"]
    assert (waiting.status, waiting.counterparty_id) == ("draft", None)
    assert lines(ledger, waiting) == [("62.1", 23600, "MT260800000011")]

    gamma = ledger.add_subconto_value(cid, firm["kind"], "GAMMA TİCARƏT MMC")
    ledger.set_subconto_value_tax(cid, gamma, "3300000003")
    ledger.post_new(
        cid,
        "2026-08-02",
        [PostingInput(acc["62.1"], acc["80"], "236", [gamma], [gamma], invoice="MT260800000011")],
    )
    assert ledger.bank.adopt_parties(cid) == 1
    found = operations(ledger, cid)["1201"]
    assert (found.status, found.counterparty_id) == ("draft", gamma)
    assert lines(ledger, found) == [("62.1", 23600, "MT260800000011")]
