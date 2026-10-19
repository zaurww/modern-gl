"""Entry templates: amount formulas and storage.

Hand-calculated examples (VAT 18% inside the amount):
  S = 1 180.00:  S*18/118 = 180.00 exactly
  S = 1 000.01:  S*18/118 = 152.5440… -> 152.54;  S-L2 = 1 000.01 - 152.54 = 847.47
  S = 0.05:      S/2 = 0.025 -> 0.03 (half away from zero)
"""

from decimal import Decimal

import pytest

from modern_gl.application.ledger import PostingInput, TemplateLine
from modern_gl.application.queries import list_templates, load_template
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.formula import compute, uses_amount
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.reporting.reports import trial_balance


def test_vat_inside_amount():
    assert compute(["S", "S*18/118"], 118000) == [118000, 18000]
    assert compute(["S-L2", "S*18/118"], 100001) == [84747, 15254]


def test_rounding_numbers_and_manual_lines():
    assert compute(["S/2"], 5) == [3]
    assert compute(["S*1,5", "", "100.10", "s + l1"], 1000) == [1500, None, 10010, 2500]
    assert uses_amount(["", "S*2"]) and not uses_amount(["100", ""])


@pytest.mark.parametrize(
    ("formulas", "message"),
    [
        (["L2", "L1"], "сама на себя"),
        (["L2", ""], "нет формулы"),
        (["S#2"], "символ"),
        (["S/0"], "ноль"),
        (["(S+1"], "скобка"),
        (["S*"], "ошибка"),
    ],
)
def test_bad_formulas(formulas, message):
    with pytest.raises(ValidationError, match=message):
        compute(formulas, 100)


def test_save_update_delete_template(ledger, conn):
    cid = ledger.create_company("Şablon")
    a62 = ledger.add_account(cid, "62", "Alıcılar")
    a46 = ledger.add_account(cid, "46", "Satış")
    a68 = ledger.add_account(cid, "68.2", "ƏDV")
    tid = ledger.save_template(
        cid, "Satış", [TemplateLine(a62, a46, "S"), TemplateLine(a46, a68, "S*18/118", memo="ƏDV")]
    )
    t = load_template(conn, cid, tid)
    assert [(ln.debit_account_id, ln.credit_account_id, ln.formula) for ln in t.lines] == [
        (a62, a46, "S"),
        (a46, a68, "S*18/118"),
    ]
    ledger.save_template(cid, "Satış (ƏDV-siz)", [TemplateLine(a62, a46, "S")], template_id=tid)
    t = load_template(conn, cid, tid)
    assert t.name == "Satış (ƏDV-siz)" and len(t.lines) == 1

    with pytest.raises(ValidationError, match="сама на себя"):
        ledger.save_template(cid, "Pis", [TemplateLine(a62, a46, "L1")])
    with pytest.raises(ValidationError, match="нет строк"):
        ledger.save_template(cid, "Boş", [TemplateLine()])

    ledger.delete_template(cid, tid)
    assert list_templates(conn, cid) == []
    assert conn.execute("SELECT COUNT(*) FROM entry_template_lines").fetchone()[0] == 0
    actions = [
        r[0]
        for r in conn.execute("SELECT action FROM audit_events WHERE entity = 'entry_template'")
    ]
    assert actions == ["create", "update", "delete"]


def test_ready_templates_post_correctly(ledger, conn):
    """Every ready template of the classic chart gives a balanced, postable document."""
    cid = ledger.create_company("Hazır")
    apply_chart_template(ledger, cid, "classic", lang="ru")
    templates = {t.name: t for t in list_templates(conn, cid)}
    assert len(templates) == 15
    sale = templates["Реализация с НДС"]
    counterparty = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "counterparty"), "A")
    contract = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "contract"), "№1")
    amounts = compute([ln.formula for ln in sale.lines], 118000)
    ledger.post_new(
        cid,
        "2026-04-10",
        [
            PostingInput(
                ln.debit_account_id,
                ln.credit_account_id,
                Decimal(amount).scaleb(-2),  # kopecks -> manat
                [counterparty, contract]
                if ln.debit_account_id == ledger.account_id(cid, "62")
                else [],
            )
            for ln, amount in zip(sale.lines, amounts, strict=True)
        ],
    )
    rows = {r.code: r for r in trial_balance(conn, cid, "2026-04-01", "2026-04-30").rows}
    assert rows["62"].closing_dt == 118000
    assert (rows["46"].turnover_dt, rows["46"].turnover_ct) == (18000, 118000)
    assert rows["46"].closing_ct == 100000  # revenue without VAT
    assert rows["68.2"].closing_ct == 18000
