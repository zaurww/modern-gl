"""Account types (D35): what an account means, whatever its code; the class follows."""

import sqlite3

import pytest

from modern_gl.domain.accounts import ACCOUNT_TYPES, TYPE_CLASS, is_current
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n_az import AZ
from modern_gl.infrastructure.chart_csv import apply_chart_template, import_chart_csv
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect


def kinds(conn, cid):
    return {
        r["code"] or r["name"]: (r["account_type"], r["account_class"])
        for r in conn.execute(
            "SELECT code, name, account_type, account_class FROM accounts WHERE company_id = ?",
            (cid,),
        )
    }


def test_every_type_has_a_class_and_a_translation():
    assert len(ACCOUNT_TYPES) == len(TYPE_CLASS) == 34
    assert {cls for _, cls, _ in ACCOUNT_TYPES} == {
        "asset",
        "liability",
        "equity",
        "revenue",
        "expense",
    }
    assert all(name in AZ for _, _, name in ACCOUNT_TYPES)


@pytest.mark.parametrize("template", ["classic", "1c77"])
def test_template_accounts_all_typed_and_type_agrees_with_class(ledger, conn, template):
    cid = ledger.create_company("Типы")
    apply_chart_template(ledger, cid, template)
    k = kinds(conn, cid)
    assert all(t for t, _ in k.values()), [c for c, (t, _) in k.items() if not t]
    assert all(TYPE_CLASS[t] == cls for t, cls in k.values())


def test_template_types(ledger, conn):
    cid = ledger.create_company("Классика")
    apply_chart_template(ledger, cid, "classic")
    k = kinds(conn, cid)
    assert k["50"] == ("cash", "asset")
    assert k["51"] == ("bank", "asset")
    assert k["62"] == ("receivable", "asset")
    assert k["60"] == ("payable", "liability")
    assert k["46"] == ("sales", "revenue")
    assert k["80"] == ("profit_loss", "equity")  # classic: 80 is profit and loss
    assert k["68.2"] == ("tax_payable", "liability")
    cid2 = ledger.create_company("1С")
    apply_chart_template(ledger, cid2, "1c77")
    k2 = kinds(conn, cid2)
    assert k2["80"] == ("share_capital", "equity")  # 1C 7.7: 80 is share capital
    assert k2["46"] == ("inventory", "asset")
    assert k2["90.2"] == ("cost_of_sales", "expense")
    assert k2["60.2"] == ("advance_paid", "asset")


def test_type_gives_class_and_subaccounts_inherit(ledger, conn):
    cid = ledger.create_company("Типы")
    ledger.add_account(cid, "211", "Alıcılar", is_group=True, account_type="receivable")
    ledger.add_account(cid, "211.1", "Yerli alıcılar", parent="211")
    ledger.add_account(cid, "211.9", "Verilmiş avanslar", parent="211", account_class="liability")
    ledger.add_account(cid, None, "Kapital Bank", account_type="bank")
    ledger.add_account(cid, "999", "Без типа", account_class="asset")
    k = kinds(conn, cid)
    assert k["211"] == ("receivable", "asset")
    assert k["211.1"] == ("receivable", "asset")  # from the parent
    assert k["211.9"] == (None, "liability")  # another class: the parent's type does not fit
    assert k["Kapital Bank"] == ("bank", "asset")  # no code: the type still says what it is
    assert k["999"] == (None, "asset")  # a class alone is allowed


def test_type_must_agree_with_class(ledger):
    cid = ledger.create_company("Типы")
    with pytest.raises(ValidationError, match="не подходит"):
        ledger.add_account(cid, "50", "Касса", account_type="cash", account_class="liability")
    with pytest.raises(ValidationError, match="тип"):
        ledger.add_account(cid, "50", "Касса", account_type="money")


def test_set_type_changes_class_and_follows_to_subaccounts(ledger, conn):
    cid = ledger.create_company("Типы")
    ledger.add_account(cid, "76", "Разные", is_group=True, account_type="other_liability")
    ledger.add_account(cid, "76.1", "Страхование", parent="76")
    ledger.add_account(cid, "76.2", "Претензии", parent="76", account_type="other_receivable")
    ledger.set_account_type(cid, "76", "other_receivable")
    k = kinds(conn, cid)
    assert k["76"] == ("other_receivable", "asset")
    assert k["76.1"] == ("other_receivable", "asset")  # had the group's type: follows
    assert k["76.2"] == ("other_receivable", "asset")  # was set on purpose: stays
    ledger.set_account_type(cid, "76.1", None)  # clearing the type keeps the class
    assert kinds(conn, cid)["76.1"] == (None, "asset")
    log = conn.execute(
        "SELECT action FROM audit_events WHERE entity = 'account' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert log["action"] == "set_type"


def test_vat_deposit_type(ledger, conn):
    """ƏDV depozit hesabı (D41): an asset of its own type, not a bank account."""
    cid = ledger.create_company("Типы")
    ledger.add_account(cid, "55", "Специальные счета", is_group=True, account_type="bank")
    ledger.add_account(cid, "55.1", "ƏDV depozit hesabı", parent="55")
    ledger.set_account_type(cid, "55.1", "vat_deposit")
    k = kinds(conn, cid)
    assert k["55.1"] == ("vat_deposit", "asset")
    assert k["55"] == ("bank", "asset")
    assert AZ["Депозитный счёт НДС"] == "ƏDV depozit hesabı"


def test_changing_class_clears_a_type_of_another_class(ledger, conn):
    cid = ledger.create_company("Типы")
    ledger.add_account(cid, "50", "Касса", account_type="cash")
    ledger.set_account_class(cid, "50", "asset", contra=True)  # same class: type stays
    assert kinds(conn, cid)["50"] == ("cash", "asset")
    ledger.set_account_class(cid, "50", "liability")
    assert kinds(conn, cid)["50"] == (None, "liability")


def test_csv_type_column(ledger, conn, tmp_path):
    cid = ledger.create_company("CSV")
    f = tmp_path / "chart.csv"
    lines = [
        "code;name;parent;group;subconto;type",
        "101;Kassa;;;;cash",
        "211;Alıcılar;;1;;receivable",
        "211.1;Yerli;211;;;",
        "601;Satış;;;;sales",
    ]
    f.write_text("\n".join(lines), encoding="utf-8")
    import_chart_csv(ledger, cid, f)
    k = kinds(conn, cid)
    assert k["101"] == ("cash", "asset")
    assert k["211.1"] == ("receivable", "asset")
    assert k["601"] == ("sales", "revenue")


@pytest.mark.parametrize("template", ["classic", "1c77"])
def test_migration_types_old_companies_like_the_template(ledger, conn, template):
    """Files made before account types get the same types as a new company would."""
    cid = ledger.create_company("Старая")
    apply_chart_template(ledger, cid, template)
    ledger.add_account(cid, "68.7", "Свой субсчёт", parent="68")  # inherits tax_payable
    expected = kinds(conn, cid)
    conn.execute("UPDATE accounts SET account_type = NULL")
    sql = (MIGRATIONS_DIR / "0012_account_type.sql").read_text(encoding="utf-8")
    conn.executescript(sql[sql.index("CREATE TEMP TABLE") :])
    # 0019: the transit account of conversions (a role since 0018) becomes "transit"
    sql = (MIGRATIONS_DIR / "0019_transit_type.sql").read_text(encoding="utf-8")
    conn.executescript(sql[sql.index("UPDATE accounts") :])
    # 0035: the long-term types (D89) — 0012 typed 09 and 77 as other assets and liabilities
    sql = (MIGRATIONS_DIR / "0035_long_term_types.sql").read_text(encoding="utf-8")
    conn.executescript(sql[sql.index("UPDATE accounts") :])
    # 76H came with D65 (0031), the ƏDV deposit 54 with the templates later: files typed by
    # 0012 had no such accounts
    later = {"76H", "54"}
    assert {code: k for code, k in kinds(conn, cid).items() if code not in later} == {
        code: k for code, k in expected.items() if code not in later
    }


def test_current_or_long_term_follows_from_the_type():
    """The balance sheet splits assets and liabilities by the type (D89)."""
    assert is_current("cash") is True
    assert is_current("other_asset") is True  # kept its code, now "other current assets"
    assert is_current("investment") is True
    assert is_current("fixed_asset") is False
    assert is_current("long_term_investment") is False
    assert is_current("other_noncurrent_asset") is False
    assert is_current("other_liability") is True
    assert is_current("long_term_loan") is False
    assert is_current("other_long_term_liability") is False
    assert is_current("share_capital") is None  # equity: neither
    assert is_current("sales") is None
    assert is_current(None) is None


def test_1c77_template_long_term_accounts(ledger, conn):
    cid = ledger.create_company("1С")
    apply_chart_template(ledger, cid, "1c77")
    k = kinds(conn, cid)
    assert k["09"] == ("other_noncurrent_asset", "asset")  # deferred tax assets
    assert k["77"] == ("other_long_term_liability", "liability")  # deferred tax liabilities
    assert k["97"] == ("other_asset", "asset")  # deferred expenses: current
    assert k["58"] == ("investment", "asset")  # short-term unless the user says otherwise
    assert k["76"] == ("other_liability", "liability")


def test_migration_moves_deferred_taxes_to_long_term(tmp_path):
    """A file of version 34: 09 and 77 (and their subaccounts) become long-term; another
    other asset stays current, and so does 090: only 09 and its subaccounts move."""
    path = tmp_path / "old.gl"
    old = sqlite3.connect(path)
    for script in sorted(MIGRATIONS_DIR.glob("*.sql"))[:34]:
        old.executescript(f"BEGIN;\n{script.read_text(encoding='utf-8')}\nCOMMIT;")
    old.execute("PRAGMA user_version = 34")
    old.execute("INSERT INTO companies (id, name, created_at) VALUES (1, 'Old', 'now')")
    rows = [
        (1, "09", "other_asset", "asset"),
        (2, "09.1", "other_asset", "asset"),
        (3, "77", "other_liability", "liability"),
        (4, "97", "other_asset", "asset"),
        (5, "76", "other_liability", "liability"),
        (6, "090", "other_asset", "asset"),
    ]
    old.executemany(
        "INSERT INTO accounts (id, company_id, code, name, account_type, account_class) "
        "VALUES (?, 1, ?, 'x', ?, ?)",
        rows,
    )
    old.commit()
    old.close()

    conn = connect(path)
    types = dict(conn.execute("SELECT code, account_type FROM accounts").fetchall())
    conn.close()
    assert types == {
        "09": "other_noncurrent_asset",
        "09.1": "other_noncurrent_asset",
        "77": "other_long_term_liability",
        "97": "other_asset",
        "76": "other_liability",
        "090": "other_asset",
    }
