import pytest

from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.reporting.reports import trial_balance


@pytest.fixture
def company(ledger):
    cid = ledger.create_company("Шаблон 1С")
    apply_chart_template(ledger, cid, "1c77")
    return cid


def test_template_structure(company, conn):
    rows = conn.execute(
        "SELECT a.code, a.two_sided, a.is_group, p.code AS parent "
        "FROM accounts a LEFT JOIN accounts p ON p.id = a.parent_id WHERE a.company_id = ?",
        (company,),
    ).fetchall()
    by_code = {r["code"]: r for r in rows}
    assert len(rows) == 94
    assert by_code["60"]["is_group"] == 1
    assert by_code["60.1"]["parent"] == "60"
    assert by_code["26"]["is_group"] == 0
    assert by_code["02"]["two_sided"] == 0
    assert by_code["76.5"]["two_sided"] == 1
    assert by_code["76H"]["parent"] == "76"  # accrued expenses (D65)


def test_typical_entries_on_template(ledger, conn, company):
    acc = {c: ledger.account_id(company, c) for c in ("51", "80", "26", "60.1", "60")}
    k = {
        c: ledger.subconto_kind_id(company, c)
        for c in ("counterparty", "contract", "cost_item", "bank_account")
    }
    supplier = ledger.add_subconto_value(company, k["counterparty"], "Поставщик")
    contract = ledger.add_subconto_value(company, k["contract"], "Договор №1")
    rent = ledger.add_subconto_value(company, k["cost_item"], "Аренда")
    bank = ledger.add_subconto_value(company, k["bank_account"], "Основной счёт")
    founder = ledger.add_subconto_value(company, k["counterparty"], "Учредитель")

    ledger.post_new(
        company,
        "2026-01-10",
        [
            PostingInput(acc["51"], acc["80"], "5000", [bank], [founder]),
        ],
    )
    ledger.post_new(
        company,
        "2026-01-31",
        [
            PostingInput(acc["26"], acc["60.1"], "1000", [rent], [supplier, contract]),
            PostingInput(acc["60.1"], acc["51"], "1000", [supplier, contract], [bank]),
        ],
    )
    with pytest.raises(ValidationError, match="группу"):
        ledger.post_new(
            company,
            "2026-01-31",
            [
                PostingInput(acc["26"], acc["60"], "1", [rent]),
            ],
        )

    rows = {r.code: r for r in trial_balance(conn, company, "2026-01-01", "2026-01-31").rows}
    assert rows["51"].closing_dt == 400000
    assert rows["80"].closing_ct == 500000
    assert rows["26"].closing_dt == 100000
    assert rows["60"].turnover_dt == rows["60"].turnover_ct == 100000
    assert "60.2" not in rows


def test_unknown_template(ledger):
    cid = ledger.create_company("X")
    with pytest.raises(ValidationError, match="нет шаблона"):
        apply_chart_template(ledger, cid, "nope")


def test_salary_in_one_sum_without_an_employee(ledger, conn, company):
    """70's employee may stay empty (D78): payroll paid in one sum, 1 500.00 from the bank;
    one employee paid separately still shows by name. ОСВ on 70: Dt 1 500.00 + 200.00."""
    acc = {c: ledger.account_id(company, c) for c in ("51", "70")}
    bank = ledger.add_subconto_value(
        company, ledger.subconto_kind_id(company, "bank_account"), "ABB"
    )
    employee = ledger.add_subconto_value(
        company, ledger.subconto_kind_id(company, "employee"), "Əli"
    )
    ledger.post_new(
        company,
        "2026-03-05",
        [
            PostingInput(acc["70"], acc["51"], "1500", (), (bank,)),
            PostingInput(acc["70"], acc["51"], "200", (employee,), (bank,)),
        ],
    )
    rows = trial_balance(conn, company, "2026-03-01", "2026-03-31")
    assert next(r for r in rows.rows if r.code == "70").turnover_dt == 170_000


def test_an_optional_subconto_turns_required_only_while_nothing_left_it_empty(ledger, company):
    acc = {c: ledger.account_id(company, c) for c in ("51", "70", "71")}
    bank = ledger.add_subconto_value(
        company, ledger.subconto_kind_id(company, "bank_account"), "ABB"
    )
    ledger.set_optional_subconto(company, "71", {0})  # nothing posted on 71: any change
    ledger.set_optional_subconto(company, "71", set())
    ledger.post_new(company, "2026-03-05", [PostingInput(acc["70"], acc["51"], "10", (), (bank,))])
    with pytest.raises(ValidationError, match="без «"):
        ledger.set_optional_subconto(company, "70", set())
    with pytest.raises(ValidationError, match="нет субконто 2"):
        ledger.set_optional_subconto(company, "70", {1})


@pytest.mark.parametrize("name", ["1c77", "classic"])
@pytest.mark.parametrize("lang", ["ru", "az"])
def test_both_templates_leave_70s_employee_optional(ledger, conn, name, lang):
    from modern_gl.i18n import set_language

    set_language(lang)
    cid = ledger.create_company(f"{name} {lang}")
    apply_chart_template(ledger, cid, name)
    row = conn.execute(
        "SELECT sc_optional FROM accounts WHERE company_id = ? AND code = '70'", (cid,)
    ).fetchone()
    assert row["sc_optional"] == 1


@pytest.mark.parametrize(
    ("name", "paid", "received"), [("classic", "61", "64"), ("1c77", "60.2", "62.2")]
)
def test_the_templates_name_their_advance_accounts(ledger, name, paid, received):
    """An overpayment goes to an account of its own (D78): 61 / 64 of the classic chart."""
    from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED

    cid = ledger.create_company(name)
    apply_chart_template(ledger, cid, name)
    assert ledger.account_role(cid, ADVANCE_PAID) == ledger.account_id(cid, paid)
    assert ledger.account_role(cid, ADVANCE_RECEIVED) == ledger.account_id(cid, received)


def test_an_old_company_gets_its_only_advance_account(ledger, conn):
    """Migration 0034: the one active account of a type becomes the role; two such
    accounts — none, the user chooses in the bank's settings."""
    from modern_gl.infrastructure.db import MIGRATIONS_DIR

    cid = ledger.create_company("Old")
    apply_chart_template(ledger, cid, "classic")
    ledger.add_account(cid, "61.9", "Ещё авансы", account_type="advance_received")
    conn.execute("DELETE FROM account_roles WHERE role LIKE 'advance%'")  # as before 0034
    conn.executescript((MIGRATIONS_DIR / "0034_advance_roles.sql").read_text(encoding="utf-8"))
    roles = dict(
        conn.execute(
            "SELECT role, account_id FROM account_roles "
            "WHERE company_id = ? AND role LIKE 'advance%'",
            (cid,),
        ).fetchall()
    )
    assert roles == {"advance_paid": ledger.account_id(cid, "61")}  # 64 and 61.9: two
