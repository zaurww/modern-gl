"""Multi-currency accounting: currency accounts, rates, revaluation, CBAR rates.

Example (hand-calculated), USD rates: 01.03 1.7000, 20.03 1.7100, 31.03 1.7200.
  1  05.03  Dt 52 [Bank USD]   Ct 51               1 000.00 USD × 1.70 = 1 700.00
  2  10.03  Dt 41              Ct 60 [Supplier]      500.00 USD × 1.70 =   850.00
  3  20.03  Dt 60 [Supplier]   Ct 52 [Bank USD]      300.00 USD × 1.71 =   513.00
Revaluation on 31.03 at 1.72:
  52: 700.00 USD -> 1 204.00, was 1 700 - 513 = 1 187.00:  Dt 52 Ct 80   17.00
  60: 200.00 USD Ct -> 344.00 Ct, was 850 - 513 = 337.00 Ct: Dt 80 Ct 60  7.00
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from modern_gl.application.currencies import latest_rates, list_currencies, rate_on
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.currency import format_rate, parse_rate, to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure import cbar
from modern_gl.reporting.reports import account_card, trial_balance


@pytest.fixture
def books(ledger):
    cid = ledger.create_company("ООО Валюта")
    banks = ledger.add_subconto_kind(cid, "bank_account", "Банковские счета")
    parties = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    supplier = ledger.add_subconto_value(cid, parties, "Supplier Ltd")
    acc = {
        "41": ledger.add_account(cid, "41", "Товары", account_class="asset"),
        "51": ledger.add_account(cid, "51", "Расчётный счёт", account_class="asset"),
        "52": ledger.add_account(
            cid, "52", "Валютный счёт", account_class="asset", subconto=[banks], currency=True
        ),
        "60": ledger.add_account(
            cid,
            "60",
            "Поставщики",
            account_class="liability",
            two_sided=True,
            subconto=[parties],
            currency=True,
        ),
        "80": ledger.add_account(cid, "80", "Прибыли и убытки", account_class="equity"),
    }
    usd = ledger.currency_id(cid, "USD")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.set_rate(cid, "USD", "2026-03-20", parse_rate("1.71"))
    ledger.set_rate(cid, "USD", "2026-03-31", parse_rate("1.72"))
    return cid, acc, usd, bank, supplier


def post_example(ledger, books):
    cid, acc, usd, bank, supplier = books
    ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["52"], acc["51"], "1700.00", (bank,), (), "", usd, "1000.00")],
    )
    ledger.post_new(
        cid,
        "2026-03-10",
        [PostingInput(acc["41"], acc["60"], "850.00", (), (supplier,), "", usd, "500.00")],
    )
    ledger.post_new(
        cid,
        "2026-03-20",
        [PostingInput(acc["60"], acc["52"], "513.00", (supplier,), (bank,), "", usd, "300.00")],
    )


def test_rates_are_exact():
    assert parse_rate("1,7") == 1_700_000
    assert parse_rate(" 1.7000 ") == 1_700_000
    assert format_rate(1_700_000) == "1.7000"
    assert format_rate(parse_rate("1.123456")) == "1.123456"
    assert format_rate(1_130_000, 100) == "0.0113"  # 100 JPY = 1.13 AZN
    assert unit_rate(1_130_000, 100) == Fraction(113, 10_000)
    # 123.45 USD × 1.70 = 209.865 -> 209.87 (half away from zero)
    assert to_base(12_345, unit_rate(1_700_000)) == 20_987
    assert to_base(-12_345, unit_rate(1_700_000)) == -20_987
    for bad in ("0", "-1.7", "abc", "1.1234567"):
        with pytest.raises(ValueError):
            parse_rate(bad)


def test_new_company_has_usual_currencies(ledger, conn):
    cid = ledger.create_company("ООО")
    assert [c.code for c in list_currencies(conn, cid)] == ["EUR", "GBP", "RUB", "TRY", "USD"]
    with pytest.raises(ValidationError, match="уже есть"):
        ledger.add_currency(cid, "usd")
    with pytest.raises(ValidationError, match="основная валюта"):
        ledger.add_currency(cid, "AZN")
    assert ledger.add_currency(cid, "gel") == ledger.currency_id(cid, "GEL")


def test_rate_on_a_day_is_the_latest_one_before_it(ledger, conn, books):
    cid, _, usd, _, _ = books
    assert rate_on(conn, cid, usd, "2026-02-28") is None
    assert rate_on(conn, cid, usd, "2026-03-19").rate == 1_700_000
    assert rate_on(conn, cid, usd, "2026-03-20").rate == 1_710_000
    ledger.set_rate(cid, usd, "2026-03-20", parse_rate("1.705"))  # replaced, not added
    assert rate_on(conn, cid, usd, "2026-03-25").rate == 1_705_000
    assert latest_rates(conn, cid)[usd].rate_date == "2026-03-31"
    ledger.delete_rate(cid, usd, "2026-03-31")
    assert latest_rates(conn, cid)[usd].rate_date == "2026-03-20"


def test_currency_account_needs_the_currency(ledger, books):
    cid, acc, usd, bank, _ = books
    with pytest.raises(ValidationError, match="Дт 52: не указана валюта"):
        ledger.post_new(cid, "2026-03-05", [PostingInput(acc["52"], acc["51"], "1", (bank,))])
    with pytest.raises(ValidationError, match="счета без валютного учёта"):
        ledger.post_new(
            cid, "2026-03-05", [PostingInput(acc["41"], acc["51"], "1", (), (), "", usd, "1")]
        )
    with pytest.raises(ValidationError, match="разных знаков"):
        ledger.post_new(
            cid,
            "2026-03-05",
            [PostingInput(acc["52"], acc["51"], "1", (bank,), (), "", usd, "-1")],
        )


def test_element_with_a_currency_accepts_only_it(ledger, books):
    cid, acc, usd, bank, _ = books
    eur = ledger.currency_id(cid, "EUR")
    ledger.set_subconto_value_currency(cid, bank, usd)
    with pytest.raises(ValidationError, match="«Kapital Bank USD» в валюте USD, а проводка в EUR"):
        ledger.post_new(
            cid,
            "2026-03-05",
            [PostingInput(acc["52"], acc["51"], "1", (bank,), (), "", eur, "1")],
        )
    ledger.post_new(
        cid, "2026-03-05", [PostingInput(acc["52"], acc["51"], "1", (bank,), (), "", usd, "1")]
    )


def test_currency_accounting_cannot_change_once_used(ledger, books):
    cid, acc, *_ = books
    post_example(ledger, books)
    with pytest.raises(ValidationError, match="валютный учёт менять нельзя"):
        ledger.update_account(cid, acc["52"], currency=False)
    ledger.update_account(cid, acc["80"], name="Прибыль")  # other changes still allowed


def test_subaccount_inherits_currency(ledger, books):
    cid, *_ = books
    group = ledger.add_account(cid, "55", "Специальные счета", is_group=True, currency=True)
    child = ledger.add_account(cid, "55.1", "Аккредитивы", parent=group)
    assert ledger.conn.execute("SELECT currency FROM accounts WHERE id = ?", (child,)).fetchone()[0]


def test_storno_reverses_the_currency_amount(ledger, books):
    cid, acc, usd, bank, _ = books
    doc = ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["52"], acc["51"], "1700.00", (bank,), (), "", usd, "1000.00")],
    )
    ledger.reverse(cid, doc, "2026-03-06")
    card = account_card(ledger.conn, cid, "52", "2026-03-01", "2026-03-31")
    assert [(ln.currency_debit, ln.debit) for ln in card.lines] == [
        (100_000, 170_000),
        (-100_000, -170_000),
    ]
    assert card.currency_closing == {"USD": 0}


def test_card_and_osv_show_currency(ledger, books):
    cid, acc, *_ = books
    post_example(ledger, books)
    card = account_card(ledger.conn, cid, "52", "2026-03-10", "2026-03-31")
    assert card.currency_opening == {"USD": 100_000}
    assert card.currency_closing == {"USD": 70_000}
    assert [(ln.currency, ln.currency_credit, ln.credit) for ln in card.lines] == [
        ("USD", 30_000, 51_300)
    ]
    osv = trial_balance(ledger.conn, cid, "2026-03-01", "2026-03-31")
    [usd52] = osv.currency[acc["52"]]
    assert (usd52.code, usd52.turnover_dt, usd52.turnover_ct, usd52.closing_dt) == (
        "USD",
        100_000,
        30_000,
        70_000,
    )
    [usd60] = osv.currency[acc["60"]]
    assert (usd60.turnover_dt, usd60.turnover_ct, usd60.closing_ct) == (30_000, 50_000, 20_000)
    assert acc["51"] not in osv.currency  # the manat side of a posting keeps no currency


def test_revaluation(ledger, conn, books):
    cid, acc, *_ = books
    post_example(ledger, books)
    doc = ledger.revalue(cid, "2026-03-31", "80")
    rows = conn.execute(
        "SELECT debit_account_id, credit_account_id, amount, currency_amount "
        "FROM postings WHERE document_id = ? ORDER BY line_no",
        (doc,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        (acc["52"], acc["80"], 1_700, 0),
        (acc["80"], acc["60"], 700, 0),
    ]
    osv = trial_balance(conn, cid, "2026-03-01", "2026-03-31")
    closing = {r.account_id: (r.closing_dt, r.closing_ct) for r in osv.rows}
    assert closing[acc["52"]] == (120_400, 0)  # 700 USD × 1.72
    assert closing[acc["60"]] == (0, 34_400)  # 200 USD × 1.72
    assert closing[acc["80"]] == (0, 1_000)  # 17.00 gain - 7.00 loss
    assert ledger.revalue(cid, "2026-03-31", "80") is None  # already at the rate


def test_revaluation_needs_a_rate_and_a_manat_account(ledger, books):
    cid, acc, usd, bank, _ = books
    eur = ledger.currency_id(cid, "EUR")
    ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["52"], acc["51"], "100.00", (bank,), (), "", eur, "50.00")],
    )
    with pytest.raises(ValidationError, match="нет курса EUR на 2026-03-31"):
        ledger.revalue(cid, "2026-03-31", "80")
    with pytest.raises(ValidationError, match="без валютного учёта"):
        ledger.revalue(cid, "2026-03-31", "52")


def test_currency_of_another_company_is_refused(ledger, books):
    cid, acc, _, bank, _ = books
    other = ledger.create_company("Другая")
    foreign_usd = ledger.currency_id(other, "USD")
    with pytest.raises(ValidationError, match="другой компании"):
        ledger.create_draft(
            cid,
            "2026-03-05",
            [PostingInput(acc["52"], acc["51"], "1", (bank,), (), "", foreign_usd, "1")],
        )


CBAR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ValCurs Date="17.10.2026" Name="AZN məzənnələri" Description="Rəsmi məzənnələr">
  <ValType Type="Bank metalları">
    <Valute Code="XAU"><Nominal>1 t.u.</Nominal><Name>Qızıl</Name><Value>4321.5</Value></Valute>
  </ValType>
  <ValType Type="Xarici valyutalar">
    <Valute Code="USD"><Nominal>1</Nominal><Name>ABŞ dolları</Name><Value>1.7</Value></Valute>
    <Valute Code="EUR"><Nominal>1</Nominal><Name>Avro</Name><Value>1.9845</Value></Valute>
    <Valute Code="JPY"><Nominal>100</Nominal><Name>Yen</Name><Value>1.1301</Value></Valute>
  </ValType>
</ValCurs>
""".encode()


def test_cbar_rates_are_parsed_without_metals():
    assert cbar.parse(CBAR_XML) == {
        "USD": (1_700_000, 1),
        "EUR": (1_984_500, 1),
        "JPY": (1_130_100, 100),
    }
    with pytest.raises(cbar.RatesUnavailable):
        cbar.parse(b"<html>not found</html>")


def test_imported_rates_go_to_the_company_currencies(ledger, conn):
    cid = ledger.create_company("ООО")
    assert ledger.import_rates(cid, "2026-10-17", cbar.parse(CBAR_XML)) == 2  # USD, EUR
    eur = rate_on(conn, cid, ledger.currency_id(cid, "EUR"), "2026-10-17")
    assert (eur.rate, eur.nominal, eur.source) == (1_984_500, 1, "cbar")


def test_migration_gives_existing_companies_their_currencies(tmp_path):
    import sqlite3

    from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect, schema_version

    path = tmp_path / "v7.gl"
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("PRAGMA foreign_keys = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 7:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.execute(
        "INSERT INTO companies (name, base_currency, created_at) VALUES ('Old', 'AZN', 'now')"
    )
    old.close()
    upgraded = connect(path)
    try:
        assert schema_version(upgraded) == 8
        codes = [c.code for c in list_currencies(upgraded, 1)]
        assert codes == ["EUR", "GBP", "RUB", "TRY", "USD"]
    finally:
        upgraded.close()


def test_split_shared_file_keeps_each_company_currencies(tmp_path):
    from modern_gl.application.ledger import Ledger
    from modern_gl.infrastructure.db import connect
    from modern_gl.infrastructure.workspace import Workspace, open_company

    shared = tmp_path / "shared.db"
    conn = connect(shared)
    ledger = Ledger(conn)
    a = ledger.create_company("A")
    ledger.create_company("B")
    ledger.set_rate(a, "USD", "2026-03-01", parse_rate("1.7"))
    conn.close()
    files = Workspace(tmp_path / "data").add_file(shared)
    c, cid = open_company(files[0])
    try:
        assert len(list_currencies(c, cid)) == 5
        assert rate_on(c, cid, Ledger(c).currency_id(cid, "USD"), "2026-03-02").rate == 1_700_000
    finally:
        c.close()
