import sqlite3

import pytest

from modern_gl.application.chart_csv import apply_chart_template, import_chart_csv
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from tests.helpers.advances import add_advance_accounts


def classes(conn, cid):
    return {
        r["code"]: (r["account_class"], r["contra"])
        for r in conn.execute(
            "SELECT code, account_class, contra FROM accounts WHERE company_id = ?", (cid,)
        )
    }


def test_template_classes(ledger, conn):
    cid = ledger.create_company("Классы")
    apply_chart_template(ledger, cid, "1c77")
    c = classes(conn, cid)
    assert all(cls for cls, _ in c.values())  # every template account is classified
    assert c["01"] == ("asset", 0)
    assert c["02"] == ("asset", 1)  # accumulated depreciation: contra-asset
    assert c["60.1"] == ("liability", 0)
    assert c["62.1"] == ("asset", 0)
    assert "60.2" not in c  # one settlement account, no advance accounts (D185)
    assert c["80"] == ("equity", 0)
    assert c["90.1"] == ("revenue", 0)
    assert c["90.2"] == ("expense", 0)
    assert c["90.3"] == ("revenue", 1)  # VAT on sales reduces revenue
    assert c["26"] == ("expense", 0)


def test_new_account_inherits_class_and_two_sided(ledger, conn):
    cid = ledger.create_company("Классы")
    ledger.add_account(
        cid, "60", "Поставщики", is_group=True, account_class="liability", two_sided=True
    )
    ledger.add_account(cid, "60.9", "Прочие", parent="60")
    ledger.add_account(cid, "60.8", "Особые", parent="60", two_sided=False)
    ledger.add_account(cid, "76", "Разные")
    c = classes(conn, cid)
    assert c["60.9"][0] == "liability"  # from the parent
    assert c["76"][0] is None  # nothing to inherit: the user decides
    sided = dict(conn.execute("SELECT code, two_sided FROM accounts WHERE company_id = ?", (cid,)))
    assert sided == {"60": 1, "60.9": 1, "60.8": 0, "76": 0}
    with pytest.raises(ValidationError, match="класс"):
        ledger.add_account(cid, "99", "X", account_class="profit")


def test_csv_understands_1c_kind_column(ledger, conn, tmp_path):
    cid = ledger.create_company("CSV 1C")
    f = tmp_path / "chart.csv"
    lines = [
        "code;name;parent;kind;group;subconto",
        "50;Касса;;A;;",
        "66;Кредиты;;P;;",
        "76;Разные;;AP;;",
    ]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    import_chart_csv(ledger, cid, f)
    rows = {
        r["code"]: (r["account_class"], r["two_sided"])
        for r in conn.execute(
            "SELECT code, account_class, two_sided FROM accounts WHERE company_id = ?", (cid,)
        )
    }
    assert rows == {"50": ("asset", 0), "66": ("liability", 0), "76": (None, 1)}


def test_changing_group_class_moves_subaccounts_that_followed_it(ledger, conn):
    cid = ledger.create_company("Классы")
    apply_chart_template(ledger, cid, "1c77")
    add_advance_accounts(ledger, cid)
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
    assert c["777"] == ("asset", 0)  # not a template code: class from its old kind "A"
    sided = dict(conn.execute("SELECT code, two_sided FROM accounts WHERE company_id = 1"))
    assert sided["60.1"] == 1 and sided["01"] == 0  # the old "AP" became two-sided
    columns = [r[1] for r in conn.execute("PRAGMA table_info(accounts)")]
    assert "kind" not in columns
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
    with pytest.raises(ValidationError, match="субконто можно только добавить"):
        led.update_account(cid, "531", subconto=[])
    with pytest.raises(ValidationError, match="уже есть"):
        led.update_account(cid, "201", new_code="301")
    with pytest.raises(ValidationError, match="у группы есть субсчета"):
        led.update_account(cid, "22", is_group=False)
    # no postings yet: free to reshape
    led.add_account(cid, "55", "Спецсчёт", account_class="asset")
    led.update_account(cid, "55", is_group=True)
    led.add_account(cid, "55.1", "Аккредитив", parent="55")


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


@pytest.mark.parametrize(
    ("cls", "contra", "two_sided", "net", "wrong"),
    [
        ("asset", False, False, 100, False),
        ("asset", False, False, -100, True),  # cash in credit
        ("asset", True, False, -100, False),  # accumulated depreciation: credit is normal
        ("asset", True, False, 100, True),
        ("liability", False, False, 100, True),
        ("equity", False, False, -100, False),
        ("revenue", False, False, 100, True),
        ("expense", False, False, 100, False),
        ("liability", False, True, 100, False),  # two-sided: never flagged
        (None, False, False, -100, False),  # unclassified: no opinion
        ("asset", False, False, 0, False),
    ],
)
def test_wrong_side_rule(cls, contra, two_sided, net, wrong):
    from modern_gl.domain.accounts import wrong_side

    assert wrong_side(cls, contra, two_sided, net) is wrong


def test_trial_balance_flags_balance_on_wrong_side(demo, conn):
    from modern_gl.reporting.reports import trial_balance

    led, cid = demo.ledger, demo.company_id
    # Pay 12 000 from bank 221 that only has 7 000 left: the bank goes into credit.
    led.post_new(cid, "2026-02-25", [demo.p("721", "221", "12000")])
    osv = trial_balance(conn, cid, "2026-02-01", "2026-02-28")
    rows = {r.code: r for r in osv.rows}
    assert rows["221"].closing_wrong and not rows["221"].opening_wrong
    assert not rows["531"].closing_wrong  # supplier advance: two-sided account
    assert not rows["22"].closing_wrong  # groups are not judged
    assert [r.code for r in osv.wrong_side] == ["221"]
