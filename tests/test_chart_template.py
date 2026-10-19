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
        "SELECT a.code, a.kind, a.is_group, p.code AS parent "
        "FROM accounts a LEFT JOIN accounts p ON p.id = a.parent_id WHERE a.company_id = ?",
        (company,),
    ).fetchall()
    by_code = {r["code"]: r for r in rows}
    assert len(rows) == 92
    assert by_code["60"]["is_group"] == 1
    assert by_code["60.1"]["parent"] == "60"
    assert by_code["26"]["is_group"] == 0
    assert by_code["02"]["kind"] == "P"
    assert by_code["76.5"]["kind"] == "AP"


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
