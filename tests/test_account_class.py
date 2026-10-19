import sqlite3

import pytest

from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template, import_chart_csv
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect


def classes(conn, cid):
    return {
        r["code"]: (r["account_class"], r["contra"])
        for r in conn.execute(
            "SELECT code, account_class, contra FROM accounts WHERE company_id = ?", (cid,)
        )
    }


def test_template_classes(ledger, conn):
    cid = ledger.create_company("Классы")
    apply_chart_template(ledger, cid)
    c = classes(conn, cid)
    assert all(cls for cls, _ in c.values())  # every template account is classified
    assert c["01"] == ("asset", 0)
    assert c["02"] == ("asset", 1)  # accumulated depreciation: contra-asset
    assert c["60.1"] == ("liability", 0)
    assert c["60.2"] == ("asset", 0)  # advances paid
    assert c["62.2"] == ("liability", 0)  # advances received
    assert c["80"] == ("equity", 0)
    assert c["90.1"] == ("revenue", 0)
    assert c["90.2"] == ("expense", 0)
    assert c["90.3"] == ("revenue", 1)  # VAT on sales reduces revenue
    assert c["26"] == ("expense", 0)


def test_new_account_inherits_or_infers_class(ledger, conn):
    cid = ledger.create_company("Классы")
    ledger.add_account(cid, "60", "Поставщики", kind="AP", is_group=True, account_class="liability")
    ledger.add_account(cid, "60.9", "Прочие", kind="AP", parent_code="60")
    ledger.add_account(cid, "50", "Касса", kind="A")
    ledger.add_account(cid, "66", "Кредиты", kind="P")
    ledger.add_account(cid, "76", "Разные", kind="AP")
    c = classes(conn, cid)
    assert c["60.9"][0] == "liability"  # from the parent
    assert c["50"][0] == "asset"  # from the kind
    assert c["66"][0] == "liability"
    assert c["76"][0] is None  # active-passive without a hint: user decides
    with pytest.raises(ValidationError, match="класс"):
        ledger.add_account(cid, "99", "X", account_class="profit")


def test_changing_group_class_moves_subaccounts_that_followed_it(ledger, conn):
    cid = ledger.create_company("Классы")
    apply_chart_template(ledger, cid)
    ledger.set_account_class(cid, "62.2", "equity")  # set differently on purpose
    ledger.set_account_class(cid, "62", "revenue")
    c = classes(conn, cid)
    assert c["62"][0] == c["62.1"][0] == "revenue"
    assert c["62.2"][0] == "equity"  # kept: it did not follow the group
    ledger.set_account_class(cid, "02", "asset", contra=False)
    assert classes(conn, cid)["02"] == ("asset", 0)
    actions = [
        r[0] for r in conn.execute("SELECT action FROM audit_events WHERE action = 'set_class'")
    ]
    assert len(actions) == 3


def test_csv_class_columns_are_optional(ledger, conn, tmp_path):
    cid = ledger.create_company("CSV")
    f = tmp_path / "chart.csv"
    f.write_text(
        "code;name;parent;kind;group;subconto;class;contra\n"
        "1;Assets;;A;1;;;\n"
        "1.1;Equipment;1;A;;;;\n"
        "1.2;Depreciation;1;P;;;asset;1\n"
        "9;Sales;;P;;;revenue;\n",
        encoding="utf-8",
    )
    import_chart_csv(ledger, cid, f)
    c = classes(conn, cid)
    assert c == {"1": ("asset", 0), "1.1": ("asset", 0), "1.2": ("asset", 1), "9": ("revenue", 0)}


def test_migration_classifies_existing_template_companies(tmp_path):
    """A database created before classes existed gets them on first open."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    first = sorted(MIGRATIONS_DIR.glob("*.sql"))[0].read_text(encoding="utf-8")
    old.executescript(f"BEGIN;\n{first}\nPRAGMA user_version = 1;\nCOMMIT;")
    old.execute("INSERT INTO companies (id, name, created_at) VALUES (1, 'Old', 'now')")
    for code, kind in (("01", "A"), ("02", "P"), ("60.1", "AP"), ("777", "A")):
        old.execute(
            "INSERT INTO accounts (company_id, code, name, kind) VALUES (1, ?, ?, ?)",
            (code, code, kind),
        )
    old.commit()
    old.close()

    conn = connect(path)
    c = classes(conn, 1)
    assert c["01"] == ("asset", 0)
    assert c["02"] == ("asset", 1)
    assert c["60.1"] == ("liability", 0)
    assert c["777"] == (None, 0)  # not a template code: left for the user
    conn.close()


def test_update_account_protects_history(demo, conn):
    led, cid = demo.ledger, demo.company_id
    led.update_account(cid, "221", new_code="221.01", name="Основной банк")
    row = conn.execute(
        "SELECT code, name FROM accounts WHERE id = ?", (demo.acc["221"],)
    ).fetchone()
    assert tuple(row) == ("221.01", "Основной банк")  # postings follow: they reference the id
    with pytest.raises(ValidationError, match="не может стать группой"):
        led.update_account(cid, "201", is_group=True)  # 201 has postings
    with pytest.raises(ValidationError, match="субконто менять нельзя"):
        led.update_account(cid, "531", subconto=[])
    with pytest.raises(ValidationError, match="уже есть"):
        led.update_account(cid, "201", new_code="301")
    with pytest.raises(ValidationError, match="у группы есть субсчета"):
        led.update_account(cid, "22", is_group=False)
    led.add_account(cid, "55", "Спецсчёт", kind="A")  # no postings yet: free to reshape
    led.update_account(cid, "55", is_group=True)
    led.add_account(cid, "55.1", "Аккредитив", kind="A", parent_code="55")


def test_hidden_account_keeps_history_but_takes_no_new_postings(demo, conn):
    from modern_gl.application.catalog import Catalog
    from modern_gl.reporting.reports import trial_balance

    led, cid = demo.ledger, demo.company_id
    led.set_account_active(cid, "721", False)
    cat = Catalog(conn, cid)
    assert "721" not in [a.code for a in cat.leaf_accounts]
    with pytest.raises(LookupError, match="скрыт"):
        cat.resolve_account("721")
    with pytest.raises(ValidationError, match="не активен"):
        led.post_new(cid, "2026-03-01", [demo.p("721", "221", "1")])
    rows = {r.code for r in trial_balance(conn, cid, "2026-02-01", "2026-02-28").rows}
    assert "721" in rows  # history still reported
    led.set_account_active(cid, "721", True)
    led.post_new(cid, "2026-03-01", [demo.p("721", "221", "1")])


def test_trial_balance_split_by_first_subconto(demo, conn):
    from modern_gl.reporting.reports import trial_balance

    osv = trial_balance(conn, demo.company_id, "2026-02-01", "2026-02-28")
    split = osv.subconto[demo.acc["531"]]
    assert [(s.name, s.closing_ct) for s in split] == [
        ("Поставщик A", 20000),
        ("Поставщик B", 50000),
    ]
    assert demo.acc["201"] not in osv.subconto  # no subconto on that account
