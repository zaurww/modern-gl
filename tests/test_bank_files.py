"""Bank statement files (D146): Kapital Bank's form read, its lines loaded into the bank.

Two files of one company (VÖEN 1400000001), as the internet bank gives them. Hand-calculated:

AZN account (51, Kapital AZN), 01.08–05.08.2026, opening 5 000.00:
  03.08  −1 000.00  Alfa, «MT2608 00000001» (unpaid 1 180.00)   → posted: 60.1 1 000.00
  03.08      −1.00  the bank's fee                               → posted: 91.2
  03.08    −300.00  Beta, a new counterparty, no e-qaimə         → draft
  03.08    −100.00  Alfa, «MT260899999999» — not unpaid          → draft
  04.08     −52.00  DSMF (Treasury), budget code 4121211         → draft: no tax account yet
  04.08  +1 925.00  from the EUR account                         → conversion, posted
  05.08    −180.00  Alfa, «MT260800000001» (still 180.00)        → posted: 60.1 180.00
  balances: 03.08 3 599.00, 04.08 5 472.00, 05.08 5 292.00

EUR account (52, Kapital EUR), opening 2 000.00 EUR:
  04.08  −1 000.00  to the AZN account (the same reference)      → the conversion's source
  04.08      −6.00  «Konvertasiya üzrə xidmət haqqı»             → the conversion's fee
  05.08    +500.00  VIAL-CAS-BEL abroad, no VÖEN                 → draft: a new counterparty
  balances: 04.08 994.00, 05.08 1 494.00

The conversion: 1 000.00 EUR (at 2.0000 — 2 000.00 ₼) → 1 925.00 ₼, fee 6.00 EUR.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from modern_gl.application.bank import (
    CUSTOMER,
    FEE,
    OTHER,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankPlace,
    load_bank_operation,
)
from modern_gl.application.bank.file_import import (
    CONVERSION,
    budget_code,
    file_operations,
    iban_places,
)
from modern_gl.application.bank.files import BankFileError, read_bank_file
from modern_gl.application.bank.files.kapital import other_side
from modern_gl.application.bank.imported import DRAFT, KNOWN, POSTED
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.conversion.calc import load_conversion
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.currency import parse_rate
from modern_gl.i18n import tr
from tests.helpers.excel import active_sheet
from tests.helpers.qt import tree_item

OWN_TIN = "1400000001"
PERIOD = "01/08/2026 - 05/08/2026"
VIAL = "LLC 'VIAL-CAS-BEL' / NOVODVORSKIJ S"
AZN_IBAN = "AZ11AIIB40040000000000000001"
EUR_IBAN = "AZ22AIIB40140000000000000002"
OWN_NAME = "″ALFA-BETA TEST″ MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ"
BANK = "KAPITAL / 9900003611"
HEADERS = [
    "№",
    "Tarix",
    "Sənədin nömrəsi",
    "Əks hesabın nömrəsi, adı və vöen-i",
    "Məbləğ",
    "Valyuta",
    "AZN dəyəri",
    "Balans",
    "Təyinat",
]


def kapital_file(path, iban, currency, opening, lines, tin=OWN_TIN):
    """A statement in Kapital Bank's form: `lines` — (day, number, other side, amount,
    base amount, purpose); the balances are counted as the bank shows them."""
    book = Workbook()
    sheet = active_sheet(book)
    sheet.title = "Hesabdan Çıxarış"
    sheet["A1"] = "Hesabdan çıxarış / Account statement"
    closing = Decimal(opening) + sum(Decimal(x[3]) for x in lines)
    header = [
        ("Müştərinin Adı / Client's name", OWN_NAME, "Çıxarışın tarixi / Statement date", "x"),
        ("Hesab nömrəsi / Account number", iban, "Hesabın valyutası / Account currency", currency),
        (
            "Hesabın tipi / Account type",
            "Cari hesab",
            "Dövr üçün / For period",
            "01/08/2026 - 05/08/2026",
        ),
        ("VÖEN / Tax id", tin, "Filial adı / Branch name", "Port Baku (290)"),
        ("Cəmi dövriyyələr kredit", "0 AZN", "Cəmi dövriyyələr debit", "0 AZN"),
        ("İlkin qalıq", f"{opening} {currency} (0 AZN)", "Son qalıq", f"{closing} {currency}"),
    ]
    for n, row in enumerate(header, 4):
        for column, value in zip("ABCD", row, strict=True):
            sheet[f"{column}{n}"] = value
    for column, value in zip("ABCDEFGHI", HEADERS, strict=True):
        sheet[f"{column}13"] = value
    balance = Decimal(opening)
    for n, (day, number, other, amount, base, memo) in enumerate(lines, 1):
        balance += Decimal(amount)
        values = [n, datetime.fromisoformat(day), number, other, Decimal(amount), currency]
        values += [Decimal(base), balance, memo]
        for column, value in zip("ABCDEFGHI", values, strict=True):
            sheet[f"{column}{13 + n}"] = value
    book.save(path)
    return path


AZN_LINES = [
    (
        "2026-08-03",
        "1001 / 501",
        "AZ33UBAZ00000000000000000001 / ALFA MMC / 1100000001",
        "-1000",
        "-1000",
        "MT2608 00000001 e-qaimeye esasen",
    ),
    (
        "2026-08-03",
        "1002 / 501",
        f"AZ96AIIB00000670130001944290 / {BANK}",
        "-1",
        "-1",
        "501 saylı əməliyyat üzrə xidmət haqqı",
    ),
    (
        "2026-08-03",
        "1003 / 502",
        "AZ44AIIB00000000000000000002 / BETA MMC / 2200000002",
        "-300",
        "-300",
        "muqavileye esasen avans",
    ),
    (
        "2026-08-03",
        "1004 / 503",
        "AZ33UBAZ00000000000000000001 / ALFA MMC / 1100000001",
        "-100",
        "-100",
        "MT260899999999 e-qaimeye esasen",
    ),
    (
        "2026-08-04",
        "1005 / 504",
        "AZ36CTRE00000000000007017617 / DSMF MERKEZI SOSIAL SIGORTA FUI / 1300115511",
        "-52",
        "-52",
        "41212112026 IYUL DSMF 3 FAIZ SOSIAL AYIRMALAR",
    ),
    (
        "2026-08-04",
        "2001 / 600",
        f"{EUR_IBAN} / {OWN_NAME} / {OWN_TIN}",
        "1925",
        "1925",
        "Hesabin mohkemlendirilmesi-Valyuta mubadilesi",
    ),
    (
        "2026-08-05",
        "1006 / 505",
        "AZ33UBAZ00000000000000000001 / ALFA MMC / 1100000001",
        "-180",
        "-180",
        "MT260800000001",
    ),
]
EUR_LINES = [
    (
        "2026-08-04",
        "2001 / 600",
        f"{AZN_IBAN} / {OWN_NAME} / {OWN_TIN}",
        "-1000",
        "-2000",
        "Hesabin mohkemlendirilmesi-Valyuta mubadilesi",
    ),
    (
        "2026-08-04",
        "2002 / 600",
        f"AZ41AIIB00000680200001978290 / {BANK}",
        "-6",
        "-12",
        "Konvertasiya üzrə xidmət haqqı 6.00(EUR)",
    ),
    (
        "2026-08-05",
        "2003 / 601",
        f"BY35PJCB30120763801000000978 / {VIAL}",
        "500",
        "1000",
        "PAYMENT FOR ETIKET CONTRACT 2407",
    ),
]


@pytest.fixture
def files(tmp_path):
    azn = kapital_file(tmp_path / "azn.xlsx", AZN_IBAN, "AZN", "5000", AZN_LINES)
    eur = kapital_file(tmp_path / "eur.xlsx", EUR_IBAN, "EUR", "2000", EUR_LINES)
    return read_bank_file(azn), read_bank_file(eur)


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Тест выписок")
    ledger.set_company_tax_id(cid, OWN_TIN)
    apply_chart_template(ledger, cid, "1c77", "ru")
    acc = {c: ledger.account_id(cid, c) for c in ("26", "51", "52", "60.1", "80", "91.2")}
    eur = ledger.currency_id(cid, "EUR")
    azn_bank = ledger.bank.add_bank_account(cid, "Kapital AZN", acc["51"], "current", iban=AZN_IBAN)
    eur_bank = ledger.bank.add_bank_account(
        cid, "Kapital EUR", acc["52"], "currency", currency_id=eur, iban=EUR_IBAN
    )
    counterparty = ledger.subconto_kind_id(cid, "counterparty")
    alfa = ledger.add_subconto_value(cid, counterparty, "Альфа")
    ledger.set_subconto_value_tax(cid, alfa, "1100000001")
    owner = ledger.add_subconto_value(cid, counterparty, "Учредитель")
    cost = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    for day in ("2026-08-01", "2026-08-04", "2026-08-05"):
        ledger.set_rate(cid, "EUR", day, parse_rate("2"))
    ledger.post_new(
        cid,
        "2026-08-01",
        [
            PostingInput(acc["51"], acc["80"], "5000", [azn_bank], [owner]),
            PostingInput(acc["52"], acc["80"], "4000", [eur_bank], [owner], "", eur, "2000"),
            PostingInput(acc["26"], acc["60.1"], "1180", [cost], [alfa], invoice="MT260800000001"),
        ],
    )
    places = iban_places(ledger.conn, cid)
    return {"cid": cid, "acc": acc, "eur": eur, "alfa": alfa, "places": places}


def by_reference(ledger, cid):
    return {
        r["reference"]: r["id"]
        for r in ledger.conn.execute(
            "SELECT id, reference FROM bank_operations WHERE company_id = ?", (cid,)
        )
    }


def lines(ledger, cid, operation_id):
    op = load_bank_operation(ledger.conn, cid, operation_id)
    codes = {r["id"]: r["code"] for r in ledger.conn.execute("SELECT id, code FROM accounts")}
    return op, [(codes.get(x.account_id), x.amount, x.invoice) for x in op.lines]


# ---- the form -------------------------------------------------------------------------


def test_the_file_is_read_as_the_bank_shows_it(files):
    azn, eur = files
    assert (azn.bank, azn.iban, azn.currency, azn.owner_tin) == (
        "Kapital Bank",
        AZN_IBAN,
        "AZN",
        OWN_TIN,
    )
    assert (azn.date_from, azn.date_to, azn.opening, azn.closing) == (
        "2026-08-01",
        "2026-08-05",
        500000,
        529200,
    )
    first = azn.lines[0]
    assert (first.reference, first.group, first.day, first.amount, first.balance) == (
        "1001",
        "501",
        "2026-08-03",
        -100000,
        400000,
    )
    assert (first.iban, first.name, first.tin) == (
        "AZ33UBAZ00000000000000000001",
        "ALFA MMC",
        "1100000001",
    )
    # the amount is the account's currency, whatever the «Valyuta» column says
    assert (eur.currency, eur.lines[0].amount, eur.lines[0].base_amount) == (
        "EUR",
        -100000,
        -200000,
    )
    assert eur.closing == 149400


def test_the_other_side_abroad_keeps_its_name():
    assert other_side("BY35PJCB3012 / LLC 'VIAL-CAS-BEL' / NOVODVORSKIJ S") == (
        "BY35PJCB3012",
        "LLC 'VIAL-CAS-BEL' / NOVODVORSKIJ S",
        "",
    )
    assert other_side("769273913707 / SHENZHEN JASSWAY INFOTECH CO., LTD. /") == (
        "769273913707",
        "SHENZHEN JASSWAY INFOTECH CO., LTD.",
        "",
    )
    assert other_side("AZ31AIIB450190N9446485926290 / POS terminal /") == (
        "AZ31AIIB450190N9446485926290",
        "POS terminal",
        "",
    )


def test_a_file_whose_balances_do_not_agree_is_not_loaded(tmp_path):
    path = kapital_file(tmp_path / "bad.xlsx", AZN_IBAN, "AZN", "5000", AZN_LINES[:2])
    from openpyxl import load_workbook

    book = load_workbook(path)
    active_sheet(book)["H15"] = Decimal("3998")  # the bank's balance after the second line
    book.save(path)
    with pytest.raises(BankFileError, match=r"строка 2: остаток 3 998\.00"):
        read_bank_file(path)


def test_a_form_of_another_bank_is_said_so(tmp_path):
    book = Workbook()
    active_sheet(book)["A1"] = "Çıxarış"
    book.save(tmp_path / "other.xlsx")
    with pytest.raises(BankFileError, match=r"форма выписки не распознана.*Kapital Bank"):
        read_bank_file(tmp_path / "other.xlsx")


# ---- what a line is -------------------------------------------------------------------


def test_what_each_line_is(firm, files):
    ops = file_operations(files, firm["places"], OWN_TIN)
    assert [(op.reference, op.kind, op.direction, op.amount) for op in ops] == [
        ("1001", SUPPLIER, "out", 100000),
        ("1002", FEE, "out", 100),
        ("1003", SUPPLIER, "out", 30000),
        ("1004", SUPPLIER, "out", 10000),
        ("1005", TAX, "out", 5200),
        ("2001", CONVERSION, "in", 192500),
        ("1006", SUPPLIER, "out", 18000),
        ("2001", CONVERSION, "out", 100000),  # its fee 2002 is taken into the conversion
        ("2003", CUSTOMER, "in", 50000),
    ]
    assert [f.reference for f in ops[7].fees] == ["2002"]
    assert ops[0].invoices == (("MT260800000001", None),)


def test_the_bank_the_treasury_and_own_accounts(firm, files, tmp_path):
    other = [
        (
            "2026-08-03",
            "3001 / 701",
            f"AZ19AIIB00000450190086944290 / {BANK}",
            "-577.72",
            "-577.72",
            "38810944014592560199 AGAYEV ROVSAN Amak haqqi",
        ),
        (
            "2026-08-03",
            "3002 / 701",
            f"AZ63AIIB00000450190089944290 / {BANK}",
            "-4.62",
            "-4.62",
            "AGAYEV ROVSAN Amak haqqi - XIDMƏT HAQQI",
        ),
        (
            "2026-08-03",
            "3003 / 702",
            "AZ48CTRE00000000000000014001 / ALFA MMC / 1100000001",
            "-180",
            "-180",
            "EDV odenisi MT2608 00000001",
        ),
        (
            "2026-08-03",
            "3004 / 703",
            "AZ24AIIB45019019440048941000 / KAPITAL BANK ASC / 9900003611",
            "-26.31",
            "-26.31",
            "VID=497;İcbari Sığorta Bürosu",
        ),
        (
            "2026-08-03",
            "3005 / 704",
            "AZ31AIIB450190N9446485926290 / POS terminal /",
            "0.09",
            "0.09",
            "Pos-Terminal üzrə əməliyyatlar",
        ),
        (
            "2026-08-03",
            "3006 / 705",
            f"AZ99AIIB40040000000000000099 / {OWN_NAME} / {OWN_TIN}",
            "100",
            "100",
            "Hesabin mohkemlendirilmesi",
        ),
    ]
    found = read_bank_file(kapital_file(tmp_path / "x.xlsx", AZN_IBAN, "AZN", "1000", other))
    ops = file_operations([found], firm["places"], OWN_TIN)
    assert [(op.kind, op.pays_vat) for op in ops] == [
        (SALARY, False),
        (FEE, False),
        (SUPPLIER, True),  # to the supplier's ƏDV deposit: the ƏDV of the e-qaimə
        (OTHER, False),  # paid through the bank: the user says what it is
        (OTHER, False),  # cards' takings by the POS
        (TRANSFER, False),  # the company's account the books do not know
    ]
    assert ops[5].target is None
    assert budget_code("41212112026 IYUL DSMF") == "4121211"
    assert budget_code("IYUL DSMF") == ""


# ---- the import -----------------------------------------------------------------------


def test_the_import_posts_what_is_sure_and_drafts_the_rest(ledger, firm, files):
    cid = firm["cid"]
    done = ledger.bank.import_bank_files(cid, files, firm["places"])
    states = {(row.op.reference, row.op.direction): (row.state, row.reason) for row in done.rows}
    assert {k: s for k, (s, _) in states.items()} == {
        ("1001", "out"): POSTED,
        ("1002", "out"): POSTED,
        ("1003", "out"): DRAFT,
        ("1004", "out"): DRAFT,
        ("1005", "out"): DRAFT,
        ("2001", "in"): POSTED,
        ("2001", "out"): POSTED,
        ("2002", "out"): POSTED,  # the conversion's fee
        ("1006", "out"): POSTED,
        ("2003", "in"): DRAFT,
    }
    assert states[("1003", "out")][1] == "новый контрагент — проверьте"
    assert (
        states[("1004", "out")][1] == "e-qaimə MT260899999999 нет среди неоплаченных у контрагента"
    )
    assert states[("1005", "out")][1] == "налог: проверьте счёт (код бюджета 4121211)"
    assert states[("2003", "in")][1] == "новый контрагент — проверьте"
    assert (done.posted, done.drafts, done.known, done.counterparties) == (6, 4, 0, 2)

    ids = by_reference(ledger, cid)
    alfa, alfa_lines = lines(ledger, cid, ids["1001"])
    assert (alfa.status, alfa.counterparty_id) == ("posted", firm["alfa"])
    assert alfa_lines == [("60.1", 100000, "MT260800000001")]
    assert lines(ledger, cid, ids["1006"])[1] == [("60.1", 18000, "MT260800000001")]
    fee, fee_lines = lines(ledger, cid, ids["1002"])
    assert (fee.kind, fee.status, fee_lines) == (FEE, "posted", [("91.2", 100, "")])
    assert "2001" not in ids  # a conversion, not a bank operation

    [conversion_id] = [r[0] for r in ledger.conn.execute("SELECT id FROM currency_conversions")]
    conversion = load_conversion(ledger.conn, cid, conversion_id)
    assert conversion.status == "posted"
    assert conversion.source is not None and conversion.target is not None
    assert (conversion.source.amount, conversion.source.currency_id) == (100000, firm["eur"])
    assert (conversion.target.amount, conversion.target.reference) == (192500, "2001")
    assert [f.amount for f in conversion.fees] == [600]


def test_every_day_gets_the_banks_balance(ledger, firm, files):
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, files, firm["places"])
    closings = {
        (r["account_id"], r["date_from"]): (r["bank_closing"], r["source"])
        for r in ledger.conn.execute("SELECT * FROM bank_statements WHERE company_id = ?", (cid,))
    }
    acc = firm["acc"]
    assert closings == {
        (acc["51"], "2026-08-03"): (359900, "file"),
        (acc["51"], "2026-08-04"): (547200, "file"),
        (acc["51"], "2026-08-05"): (529200, "file"),
        (acc["52"], "2026-08-04"): (99400, "file"),
        (acc["52"], "2026-08-05"): (149400, "file"),
    }


def test_loading_again_adds_nothing(ledger, firm, files):
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, files, firm["places"])
    count = ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    again = ledger.bank.import_bank_files(cid, files, firm["places"])
    assert {row.state for row in again.rows} == {KNOWN}
    assert (again.posted, again.drafts, again.counterparties) == (0, 0, 0)
    assert ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == count


def test_the_preview_writes_nothing(ledger, firm, files):
    cid = firm["cid"]
    count = ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    seen = ledger.bank.preview_bank_files(cid, files, firm["places"])
    assert (seen.posted, seen.drafts) == (6, 4)
    assert all(row.document_id is None for row in seen.rows)
    assert ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == count
    assert ledger.conn.execute("SELECT COUNT(*) FROM bank_statements").fetchone()[0] == 0


def test_only_the_lines_taken_are_loaded(ledger, firm, files):
    cid = firm["cid"]
    done = ledger.bank.import_bank_files(cid, files, firm["places"], take={"1001", "2001"})
    assert done.counterparties == 0  # Beta and VIAL-CAS-BEL were left out: not added
    assert sorted((row.op.reference, row.state) for row in done.rows) == [
        ("1001", POSTED),
        ("2001", POSTED),
        ("2001", POSTED),
        ("2002", POSTED),
    ]


def test_a_conversion_waits_for_the_other_file(ledger, firm, files):
    """The AZN file alone: the conversion is a draft with its side; the EUR file finishes
    it and posts it."""
    cid = firm["cid"]
    azn, eur = files
    first = ledger.bank.import_bank_files(cid, [azn], firm["places"])
    [row] = [r for r in first.rows if r.op.reference == "2001"]
    assert (row.state, row.reason) == (DRAFT, "вторая сторона — в выписке другого счёта")
    [conversion_id] = [r[0] for r in ledger.conn.execute("SELECT id FROM currency_conversions")]
    draft = load_conversion(ledger.conn, cid, conversion_id)
    assert (draft.status, draft.source, draft.target is not None) == ("draft", None, True)

    second = ledger.bank.import_bank_files(cid, [eur], firm["places"])
    states = sorted((r.op.reference, r.state) for r in second.rows)
    assert states == [("2001", POSTED), ("2002", POSTED), ("2003", DRAFT)]
    done = load_conversion(ledger.conn, cid, conversion_id)
    assert done.status == "posted"
    assert done.source is not None and done.source.amount == 100000
    assert [f.amount for f in done.fees] == [600]
    assert ledger.conn.execute("SELECT COUNT(*) FROM currency_conversions").fetchone()[0] == 1


SEPTEMBER_DSMF = (
    "2026-09-04",
    "1105 / 604",
    "AZ36CTRE00000000000007017617 / DSMF MERKEZI SOSIAL SIGORTA FUI / 1300115511",
    "-55",
    "-55",
    "41212112026 AVQUST DSMF 3 FAIZ",
)


def test_a_tax_is_posted_as_the_last_one_with_its_code(ledger, firm, files, tmp_path):
    """August's DSMF is a draft — its account a guess, September's waits too; given its
    account (69) and posted, September's goes there itself."""
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, files[:1], firm["places"])
    path = kapital_file(tmp_path / "sep.xlsx", AZN_IBAN, "AZN", "5292", [SEPTEMBER_DSMF])
    september = read_bank_file(path)
    seen = ledger.bank.preview_bank_files(cid, [september], firm["places"])
    assert [r.state for r in seen.rows] == [DRAFT]

    tax_id = by_reference(ledger, cid)["1005"]
    op = load_bank_operation(ledger.conn, cid, tax_id)
    fixed = replace(op.lines[0], account_id=ledger.account_id(cid, "69"))
    ledger.bank.save_bank_operation(cid, replace(op, lines=(fixed,)), tax_id, post=True)
    done = ledger.bank.import_bank_files(cid, [september], firm["places"])
    assert [(r.state, r.lines[0][0]) for r in done.rows] == [(POSTED, "69")]


SEPTEMBER_FEE = (
    "2026-09-04",
    "1106 / 605",
    f"AZ96AIIB00000670130001944290 / {BANK}",
    "-2",
    "-2",
    "605 saylı əməliyyat üzrə xidmət haqqı",
)


def test_a_fee_goes_to_the_account_of_the_settings_not_as_last_time(ledger, firm, files, tmp_path):
    """August's fee went to 91.2; the settings then say 26 — September's goes to 26."""
    cid = firm["cid"]
    ledger.bank.import_bank_files(cid, files[:1], firm["places"])
    ledger.set_account_role(cid, BANK_FEE, firm["acc"]["26"])
    path = kapital_file(tmp_path / "sep.xlsx", AZN_IBAN, "AZN", "5292", [SEPTEMBER_FEE])
    done = ledger.bank.import_bank_files(cid, [read_bank_file(path)], firm["places"])
    assert [(r.state, r.lines[0][0]) for r in done.rows] == [(POSTED, "26")]
    assert lines(ledger, cid, by_reference(ledger, cid)["1106"])[1] == [("26", 200, "")]


def test_the_lines_marked_go_to_another_account(ledger, firm, files):
    """The fee 1.00 loaded onto 91.2 goes to 26 with the item «Комиссия банка»: still
    posted, its posting is Dt 26 Kt 51 1.00; Alfa's payment, marked too, has no 91.2."""
    cid, acc = firm["cid"], firm["acc"]
    ledger.bank.import_bank_files(cid, files[:1], firm["places"])
    ids = by_reference(ledger, cid)
    moved = ledger.bank.change_line_account(cid, [ids["1001"], ids["1002"]], acc["91.2"], acc["26"])
    assert moved == 1
    fee, fee_lines = lines(ledger, cid, ids["1002"])
    assert (fee.status, fee_lines) == ("posted", [("26", 100, "")])
    item = ledger.conn.execute(
        "SELECT name FROM subconto_values WHERE id = ?", (fee.lines[0].subconto[0],)
    ).fetchone()
    assert item["name"] == "Комиссия банка"
    postings = ledger.conn.execute(
        "SELECT debit_account_id, credit_account_id, amount FROM postings WHERE document_id = ?",
        (fee.document_id,),
    ).fetchall()
    assert [tuple(r) for r in postings] == [(acc["26"], acc["51"], 100)]
    assert lines(ledger, cid, ids["1001"])[1] == [("60.1", 100000, "MT260800000001")]


def test_a_file_of_another_firm_is_not_loaded(ledger, firm, tmp_path):
    path = kapital_file(
        tmp_path / "x.xlsx", AZN_IBAN, "AZN", "5000", AZN_LINES[:1], tin="1999999999"
    )
    with pytest.raises(BankFileError, match="выписка счёта другой фирмы"):
        ledger.bank.import_bank_files(firm["cid"], [read_bank_file(path)], firm["places"])


def test_the_account_chosen_for_a_file_keeps_its_iban(ledger, tmp_path):
    cid = ledger.create_company("ООО Без IBAN")
    apply_chart_template(ledger, cid, "1c77", "ru")
    account = ledger.account_id(cid, "51")
    value = ledger.bank.add_bank_account(cid, "Kapital", account, "current")
    place = BankPlace(account, value, "Kapital", "51", None, "", "bank")
    assert iban_places(ledger.conn, cid) == {}
    path = kapital_file(tmp_path / "x.xlsx", AZN_IBAN, "AZN", "0", [])
    ledger.bank.import_bank_files(cid, [read_bank_file(path)], {AZN_IBAN: place})
    assert list(iban_places(ledger.conn, cid)) == [AZN_IBAN]


# ---- the window -----------------------------------------------------------------------


@pytest.fixture
def session(ledger, firm):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.session import Session

    messages: list[str] = []
    cid = firm["cid"]
    s = Session(
        ledger.conn, ledger, cid, "ООО Тест", Catalog(ledger.conn, cid), notify=messages.append
    )
    s.working_date = date(2026, 8, 5)
    return s, messages


def test_the_window_shows_the_lines_to_check_first_and_posts(qtbot, firm, session, tmp_path):
    """Both files: each finds its account by the IBAN; the drafts above with why; the
    Treasury's line unticked stays out; the balances by the bank beside the books'."""
    from PySide6.QtCore import Qt

    from modern_gl.desktop.bank_page.file_dialog import BankFileDialog

    s, _messages = session
    azn = kapital_file(tmp_path / "azn.xlsx", AZN_IBAN, "AZN", "5000", AZN_LINES)
    eur = kapital_file(tmp_path / "eur.xlsx", EUR_IBAN, "EUR", "2000", EUR_LINES)
    dialog = BankFileDialog(s, [azn, eur])
    qtbot.addWidget(dialog)
    assert [box.currentData() for box in dialog.accounts.values()] == [
        firm["places"][AZN_IBAN],
        firm["places"][EUR_IBAN],
    ]
    rows = dialog.rows.rows()
    assert [r.state for r in rows[:4]] == [DRAFT] * 4  # what to check — above
    assert {r.state for r in rows[4:]} == {POSTED}
    assert by_reference(s.ledger, s.company_id) == {}  # nothing written yet
    # after the posted lines the books have 5 000 − 1 000 − 1 + 1 925 − 180 = 5 744.00:
    # the drafts (−300 − 100 − 52) are the difference with the bank's 5 292.00
    drafts = tr(" — сойдётся, когда будут проведены черновики ({drafts})", drafts="-452.00")
    assert drafts in dialog.balances.text()
    assert dialog.balances.objectName() == "secondary"  # no alarm: the drafts make it

    tax = next(n for n, r in enumerate(rows) if r.op.reference == "1005")
    tree_item(dialog.rows, tax).setCheckState(0, Qt.CheckState.Unchecked)
    # the DSMF's 52.00 left out: the books will not meet the bank — said so
    assert tr(" — разница {diff}", diff="-452.00") in dialog.balances.text()
    dialog.post_button.click()
    assert dialog.imported is not None
    assert (dialog.imported.posted, dialog.imported.drafts) == (6, 3)
    assert "1005" not in by_reference(s.ledger, s.company_id)
    assert dialog.close_button.text() == tr("Готово")
    row = next(r for r in dialog.rows.rows() if r.op.reference == "1001")
    item = dialog.rows.topLevelItem(dialog.rows.rows().index(row))
    dialog.rows.itemDoubleClicked.emit(item, 0)
    assert dialog.chosen_document == row.document_id is not None


def test_a_file_of_an_account_not_known_waits_for_the_choice(qtbot, ledger, session, tmp_path):
    from modern_gl.desktop.bank_page.file_dialog import BankFileDialog

    s, _messages = session
    other = "AZ55AIIB40040000000000000077"
    path = kapital_file(tmp_path / "x.xlsx", other, "AZN", "0", [])
    dialog = BankFileDialog(s, [path, tmp_path / "missing.xlsx"])
    qtbot.addWidget(dialog)
    box = dialog.accounts[other]
    assert box.currentData() is None
    assert dialog.status.text().startswith(tr("Выберите счёт для: {files}.", files="x.xlsx"))
    assert "missing.xlsx" in dialog.errors.text()  # a file not read is said
    box.setCurrentIndex(1)  # Kapital AZN: the only manat account
    assert not dialog.status.text().startswith(tr("Выберите счёт"))


def test_the_bank_page_loads_files_from_its_menu(qtbot, firm, session, monkeypatch, tmp_path):
    from modern_gl.desktop.bank_page import BankPage
    from modern_gl.desktop.bank_page import file_dialog as module

    s, _messages = session
    page = BankPage(s)
    qtbot.addWidget(page)
    titles = [item[0] for item in page.more_items() if item]
    assert tr("Загрузить выписку из файла…") in titles

    def run(dialog):
        dialog.post_button.click()
        return dialog.result()

    monkeypatch.setattr(module.BankFileDialog, "exec", run)
    azn = kapital_file(tmp_path / "azn.xlsx", AZN_IBAN, "AZN", "5000", AZN_LINES)
    page.load_bank_files([str(azn)])
    assert "1001" in by_reference(s.ledger, s.company_id)
