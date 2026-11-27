"""Yapı Kredi Bank's statement file (D146): its form read, its lines loaded into the bank.

The company (VÖEN 1400000001) has two manat accounts on 51: Kapital AZN and Yapı Kredi
AZN. Yapı Kredi's file, opening 0.00 — hand-calculated:

  20.06.2025     +30.00  nobody named, «HESAB AÇILIŞ KOM/AKD»      30.00  money in: no fee
  21.06.2025  +5 000.00  ALFA MMC, «avans»                      5 030.00  a customer
  30.07.2025    −300.00  ALFA MMC, «MT2507 12133151 QAIME»      4 730.00  a supplier
  30.07.2025      −2.50  nobody, «Com. ALFA MMC»                4 727.50  the bank's fee
  30.07.2025      −9.84  nobody, «PAYMENT ORDER COMMISSION»     4 717.66  the bank's fee
  05.09.2025  −3 274.01  the company's Kapital account          1 443.65  a transfer
  05.09.2025      −4.91  nobody, «Com. NUMUNE MMC»              1 438.74  the bank's fee

The form has no number of a line: the reference is the day, the amount and the balance.
Kapital's file has the same transfer as its own line, +3 274.01 under Kapital's number:
whichever file comes second, the transfer is one operation — Kapital holds 3 274.01."""

from __future__ import annotations

import pytest

from modern_gl.application.bank import CUSTOMER, FEE, SUPPLIER, TRANSFER
from modern_gl.application.bank.file_import import file_operations, iban_places
from modern_gl.application.bank.files import BankFileError, read_bank_file
from modern_gl.application.bank.imported import KNOWN, POSTED
from modern_gl.application.bank.statement import place_balance
from modern_gl.application.chart_csv import apply_chart_template
from tests.helpers.kapital import AZN_IBAN, OWN_NAME, OWN_TIN, kapital_file
from tests.helpers.yapikredi import YK_IBAN, yapikredi_file

ALFA_IBAN = "AZ33UBAZ00000000000000000001"
TRANSFER_REF = "YK20250905/-327401/144365"
YK_LINES = [
    ("2025-06-20", "", "", "NUMUNE MMC HESAB AÇILIŞ KOM/AKD", "30"),
    ("2025-06-21", "ALFA MMC", ALFA_IBAN, "avans", "5000"),
    ("2025-07-30", "ALFA MMC", ALFA_IBAN, "MT2507 12133151 QAIME", "-300"),
    ("2025-07-30", "", "", "Com. ALFA MMC", "-2.5"),
    ("2025-07-30", "", "", "PAYMENT ORDER COMMISSION", "-9.84"),
    ("2025-09-05", "NUMUNE MMC", AZN_IBAN, "DIGER BANK HESABININ MOHKEMLENDIRIL MESI", "-3274.01"),
    ("2025-09-05", "", "", "Com. NUMUNE MMC", "-4.91"),
]
KAPITAL_LINE = (
    "2025-09-05",
    "3100 / 900",
    f"{YK_IBAN} / {OWN_NAME} / {OWN_TIN}",
    "3274.01",
    "3274.01",
    "DIGER BANK HESABININ MOHKEMLENDIRIL MESI IB2509050147",
)


@pytest.fixture
def yk(tmp_path):
    return read_bank_file(yapikredi_file(tmp_path / "yk.xlsx", "0", YK_LINES))


@pytest.fixture
def kapital(tmp_path):
    return read_bank_file(kapital_file(tmp_path / "k.xlsx", AZN_IBAN, "AZN", "0", [KAPITAL_LINE]))


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Два банка")
    ledger.set_company_tax_id(cid, OWN_TIN)
    apply_chart_template(ledger, cid, "1c77", "ru")
    bank = ledger.account_id(cid, "51")
    ledger.bank.add_bank_account(cid, "Kapital AZN", bank, "current", iban=AZN_IBAN)
    ledger.bank.add_bank_account(cid, "Yapı Kredi AZN", bank, "current", iban=YK_IBAN)
    return {"cid": cid, "places": iban_places(ledger.conn, cid)}


def transfers(ledger, cid) -> int:
    count = ledger.conn.execute(
        "SELECT COUNT(*) FROM bank_operations WHERE company_id = ? AND kind = ?", (cid, TRANSFER)
    )
    return count.fetchone()[0]


def test_the_file_is_read_as_the_bank_shows_it(yk):
    assert (yk.bank, yk.iban, yk.currency, yk.owner_tin) == ("Yapı Kredi Bank", YK_IBAN, "AZN", "")
    assert (yk.date_from, yk.date_to, yk.opening, yk.closing) == (
        "2025-01-01",
        "2026-01-31",
        0,
        143874,
    )
    assert [(x.day, x.amount, x.balance, x.fee) for x in yk.lines] == [
        ("2025-06-20", 3000, 3000, False),  # money in is no fee, whatever it says
        ("2025-06-21", 500000, 503000, False),
        ("2025-07-30", -30000, 473000, False),
        ("2025-07-30", -250, 472750, True),
        ("2025-07-30", -984, 471766, True),
        ("2025-09-05", -327401, 144365, False),
        ("2025-09-05", -491, 143874, True),
    ]
    third = yk.lines[2]
    assert (third.name, third.iban, third.tin, third.memo) == (
        "ALFA MMC",
        ALFA_IBAN,
        "",
        "MT2507 12133151 QAIME",
    )
    # no number in the form: the day, the amount and the balance after the line
    assert third.reference == "YK20250730/-30000/473000"
    assert len({x.reference for x in yk.lines}) == 7
    assert len({x.group for x in yk.lines}) == 7  # nobody's fee is taken into a conversion


def test_a_file_whose_balances_do_not_agree_is_not_loaded(tmp_path):
    from openpyxl import load_workbook

    from tests.helpers.excel import active_sheet

    path = yapikredi_file(tmp_path / "bad.xlsx", "0", YK_LINES[:2])
    book = load_workbook(path)
    active_sheet(book)["H18"] = "5.031,00"  # the balance after the second line: 5 030.00
    book.save(path)
    with pytest.raises(BankFileError, match=r"строка 2: остаток 5 031\.00.*по строкам 5 030\.00"):
        read_bank_file(path)


def test_what_each_line_is(firm, yk):
    ops = file_operations([yk], firm["places"], OWN_TIN)
    assert [(op.kind, op.direction, op.amount) for op in ops] == [
        (CUSTOMER, "in", 3000),  # nobody named is not the bank: the form has no VÖEN
        (CUSTOMER, "in", 500000),
        (SUPPLIER, "out", 30000),
        (FEE, "out", 250),
        (FEE, "out", 984),
        (TRANSFER, "out", 327401),
        (FEE, "out", 491),
    ]
    assert ops[5].target == firm["places"][AZN_IBAN]


def test_the_fees_and_the_transfer_are_posted_and_known_again(ledger, firm, yk):
    """Posted unseen: the three fees (2.50 + 9.84 + 4.91 = 17.25 on 91.2) and the transfer,
    Dt 51 Kapital / Kt 51 Yapı Kredi 3 274.01."""
    cid = firm["cid"]
    done = ledger.bank.import_bank_files(cid, [yk], firm["places"])
    states = {row.op.reference: row.state for row in done.rows}
    posted = [
        "YK20250730/-250/472750",
        "YK20250730/-984/471766",
        TRANSFER_REF,
        "YK20250905/-491/143874",
    ]
    assert [states[reference] for reference in posted] == [POSTED] * 4
    fee = ledger.account_id(cid, "91.2")
    [[on_fees]] = ledger.conn.execute(
        "SELECT SUM(amount) FROM postings WHERE company_id = ? AND debit_account_id = ?",
        (cid, fee),
    )
    assert on_fees == 1725
    assert place_balance(ledger.conn, cid, firm["places"][AZN_IBAN], "2025-09-05") == 327401

    count = ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    again = ledger.bank.import_bank_files(cid, [yk], firm["places"])
    assert {row.state for row in again.rows} == {KNOWN}
    assert ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == count


def test_a_transfer_the_other_banks_file_brought_is_not_doubled(ledger, firm, yk, kapital):
    """Kapital's file first: Dt 51 Kapital / Kt 51 Yapı Kredi 3 274.01 under Kapital's
    number 3100. Yapı Kredi's line of it has another reference — the books hold it all
    the same: one transfer, Kapital 3 274.01, not 6 548.02."""
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [kapital], firm["places"])
    assert transfers(ledger, cid) == 1

    seen = ledger.bank.preview_bank_files(cid, [yk], firm["places"])
    assert {row.op.reference: row.state for row in seen.rows}[TRANSFER_REF] == KNOWN
    done = ledger.bank.import_bank_files(cid, [yk], firm["places"])
    assert {row.op.reference: row.state for row in done.rows}[TRANSFER_REF] == KNOWN
    assert transfers(ledger, cid) == 1
    assert place_balance(ledger.conn, cid, firm["places"][AZN_IBAN], "2025-09-05") == 327401
    again = ledger.bank.import_bank_files(cid, [yk, kapital], firm["places"])
    assert {row.state for row in again.rows} == {KNOWN}


def test_the_other_banks_file_second_finds_the_transfer(ledger, firm, yk, kapital):
    """The other way round: Yapı Kredi's file posts the transfer, Kapital's line of it
    is in the books — and the two files together post it once."""
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [yk], firm["places"])
    done = ledger.bank.import_bank_files(cid, [kapital], firm["places"])
    assert [(row.op.kind, row.state) for row in done.rows] == [(TRANSFER, KNOWN)]
    assert transfers(ledger, cid) == 1
    assert place_balance(ledger.conn, cid, firm["places"][AZN_IBAN], "2025-09-05") == 327401


def test_two_equal_transfers_of_a_day_are_two(ledger, firm, tmp_path, kapital):
    """Kapital's file brought one transfer of 3 274.01 on 05.09; Yapı Kredi's has two such
    lines that day: the first is the one in the books, the second is new — Kapital holds
    6 548.02."""
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, [kapital], firm["places"])
    twice = [YK_LINES[1], YK_LINES[5], YK_LINES[5]]  # 5 000.00 in, 3 274.01 out twice
    file = read_bank_file(yapikredi_file(tmp_path / "two.xlsx", "10000", twice))
    done = ledger.bank.import_bank_files(cid, [file], firm["places"])
    assert [row.state for row in done.rows if row.op.kind == TRANSFER] == [KNOWN, POSTED]
    assert transfers(ledger, cid) == 2
    assert place_balance(ledger.conn, cid, firm["places"][AZN_IBAN], "2025-09-05") == 654802
