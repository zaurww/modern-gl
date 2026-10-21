"""Contracts belong to counterparties; 60 / 62 take manat or a currency.

Example (hand-calculated) on the classic chart, USD 01.03 1.7000, 31.03 1.7200:
  1  05.03  Dt 26 [Аренда]   Ct 60 [Альфа, Фактура 15 (Альфа)]     400.00 AZN
  2  10.03  Dt 26 [Аренда]   Ct 60 [Gamma GmbH, Invoice 7]   500.00 USD × 1.70 = 850.00
Revaluation on 31.03 at 1.72: only the dollar debt is revalued —
  500.00 USD Ct -> 860.00 Ct, was 850.00 Ct: Dt 80 Ct 60  10.00;  Альфа's 400 AZN stays.
60 closes at 400 + 850 + 10 = 1 260.00 Ct.
"""

from __future__ import annotations

import sqlite3

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.application.quick_entry import parse, suggest
from modern_gl.domain.currency import CURRENCY_OPTIONAL, parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from modern_gl.reporting.reports import account_card


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    kind = {code: ledger.subconto_kind_id(cid, code) for code in ("counterparty", "contract")}
    cost = ledger.subconto_kind_id(cid, "cost_item")
    v = {
        "Альфа": ledger.add_subconto_value(cid, kind["counterparty"], "Альфа"),
        "Бета": ledger.add_subconto_value(cid, kind["counterparty"], "Бета"),
        "Gamma": ledger.add_subconto_value(cid, kind["counterparty"], "Gamma GmbH"),
        "Аренда": ledger.add_subconto_value(cid, cost, "Аренда"),
    }
    v["Ф15 Альфа"] = ledger.add_subconto_value(
        cid, kind["contract"], "Фактура 15", owner_id=v["Альфа"]
    )
    v["Ф15 Бета"] = ledger.add_subconto_value(
        cid, kind["contract"], "Фактура 15", owner_id=v["Бета"]
    )
    v["Invoice 7"] = ledger.add_subconto_value(
        cid, kind["contract"], "Invoice 7", owner_id=v["Gamma"]
    )
    v["Общий"] = ledger.add_subconto_value(cid, kind["contract"], "Без договора")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.set_rate(cid, "USD", "2026-03-31", parse_rate("1.72"))
    acc = {code: ledger.account_id(cid, code) for code in ("26", "60", "80", "51")}
    return cid, acc, v, Catalog(ledger.conn, cid)


def test_template_makes_contracts_belong_to_counterparties(firm):
    *_, cat = firm
    contract = cat.by_code["60"].sc_kinds[1]
    assert cat.owner_kinds[contract] == cat.by_code["60"].sc_kinds[0]
    assert cat.by_code["60"].currency_optional and cat.by_code["62"].currency_optional
    assert cat.by_code["52"].currency == 1


def test_contract_of_another_counterparty_is_refused(ledger, firm):
    cid, acc, v, _ = firm
    rent = (v["Аренда"],)
    ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["26"], acc["60"], "400", rent, (v["Альфа"], v["Ф15 Альфа"]))],
    )
    with pytest.raises(ValidationError, match="«Фактура 15» относится к «Альфа», а не к «Бета»"):
        ledger.post_new(
            cid,
            "2026-03-05",
            [PostingInput(acc["26"], acc["60"], "1", rent, (v["Бета"], v["Ф15 Альфа"]))],
        )
    for partner in ("Альфа", "Бета"):  # a common contract goes with anyone
        ledger.post_new(
            cid,
            "2026-03-05",
            [PostingInput(acc["26"], acc["60"], "1", rent, (v[partner], v["Общий"]))],
        )


def test_owner_cannot_be_given_to_a_contract_used_with_another(ledger, firm):
    cid, acc, v, _ = firm
    ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["26"], acc["60"], "1", (v["Аренда"],), (v["Бета"], v["Общий"]))],
    )
    with pytest.raises(ValidationError, match="уже есть в проводках с «Бета»"):
        ledger.set_subconto_value_owner(cid, v["Общий"], v["Альфа"])
    ledger.set_subconto_value_owner(cid, v["Общий"], v["Бета"])
    with pytest.raises(ValidationError, match="из справочника «Контрагенты»"):
        ledger.set_subconto_value_owner(cid, v["Общий"], v["Аренда"])


def test_catalog_offers_the_counterparty_s_contracts(firm):
    _, _, v, cat = firm
    contract = cat.by_code["60"].sc_kinds[1]
    names = {x.id for x in cat.values(contract, v["Бета"])}
    assert names == {v["Ф15 Бета"], v["Общий"]}
    assert cat.resolve_value(contract, "фактура 15", v["Альфа"]) == v["Ф15 Альфа"]
    with pytest.raises(LookupError, match="есть у нескольких"):
        cat.resolve_value(contract, "Фактура 15")


def test_60_in_manat_and_in_dollars_revalues_only_the_dollars(ledger, firm):
    cid, acc, v, _ = firm
    usd = ledger.currency_id(cid, "USD")
    rent = (v["Аренда"],)
    ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["26"], acc["60"], "400", rent, (v["Альфа"], v["Ф15 Альфа"]))],
    )
    ledger.post_new(
        cid,
        "2026-03-10",
        [
            PostingInput(
                acc["26"], acc["60"], "850", rent, (v["Gamma"], v["Invoice 7"]), "", usd, "500"
            )
        ],
    )
    doc = ledger.revalue(cid, "2026-03-31", acc["80"], acc["80"])
    row = ledger.conn.execute(
        "SELECT debit_account_id, credit_account_id, amount, ct_sc1 FROM postings "
        "WHERE document_id = ?",
        (doc,),
    ).fetchall()
    assert [tuple(r) for r in row] == [(acc["80"], acc["60"], 1_000, v["Gamma"])]  # 10.00
    card = account_card(ledger.conn, cid, "60", "2026-03-01", "2026-03-31")
    assert card.closing == -126_000  # 1 260.00 Ct
    assert card.currency_closing == {"USD": -50_000}


def test_element_currency_still_asks_for_the_currency(ledger, firm):
    cid, acc, v, _ = firm
    ledger.set_subconto_value_currency(cid, v["Invoice 7"], ledger.currency_id(cid, "EUR"))
    with pytest.raises(ValidationError, match="«Invoice 7» в валюте EUR — укажите сумму в валюте"):
        ledger.post_new(
            cid,
            "2026-03-10",
            [PostingInput(acc["26"], acc["60"], "1", (v["Аренда"],), (v["Gamma"], v["Invoice 7"]))],
        )


def test_52_still_needs_a_currency(ledger, firm):
    cid, acc, *_ = firm
    bank = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "bank_account"), "USD")
    with pytest.raises(ValidationError, match="не указана валюта"):
        ledger.post_new(
            cid,
            "2026-03-10",
            [PostingInput(ledger.account_id(cid, "52"), acc["51"], "1", (bank,), (bank,))],
        )


def test_quick_entry_takes_manat_on_60_and_names_with_numbers(firm):
    _, _, v, cat = firm
    entry = parse("26 аренда / 60 бета, Фактура 15 400 Услуги", cat)
    [ln] = entry.lines
    assert ln.credit_sc[:2] == [v["Бета"], v["Ф15 Бета"]]  # Бета's own «Фактура 15»
    assert (ln.amount, ln.currency_id, ln.memo) == (40_000, None, "Услуги")


def test_quick_entry_new_contract_belongs_to_the_line_s_counterparty(firm):
    _, _, v, cat = firm
    entry = parse("26 аренда / 60 +Delta, +Договор 1/26 10", cat)
    partner, contract = entry.new_values
    assert contract.owner is partner
    entry = parse("26 аренда / 60 бета, +Договор 2 10", cat)
    assert entry.new_values[0].owner == v["Бета"]


def suggestions(cat: Catalog, text: str) -> list[str]:
    return [i.insert for i in suggest(text, len(text), cat).items]


def test_suggestions_follow_the_line(firm):
    _, _, _, cat = firm
    assert suggestions(cat, "26 ") == ["Аренда / "]  # after 26: its cost items
    assert suggestions(cat, "26 Аренда / 6")[:2] == ["60 ", "61 "]
    assert suggestions(cat, "26 Аренда / 60 бе") == ["Бета, ", "+бе, "]  # or a new one
    assert suggestions(cat, "26 Аренда / 60 бета") == ["Бета, "]  # it is there: nothing new
    assert suggestions(cat, "26 Аренда / 60 Бета, ") == ["Без договора ", "Фактура 15 "]
    assert suggestions(cat, "26 Аренда / 60 Бета, Фактура 15 400 us") == ["USD "]
    assert suggestions(cat, "26 Аренда / 60 Бета, Фактура 15 400 Услуги") == []
    assert suggestions(cat, "05.03 26 ар") == ["Аренда / ", "+ар / "]


def test_new_element_is_offered_right_in_the_line(firm):
    """A new company has no banks yet: "51 " offers to add one, "+Kapital" — only it."""
    _, _, _, cat = firm
    found = suggest("50 / 51 ", 8, cat)
    assert [i.insert for i in found.items] == ["+"]
    assert "Банковские счета" in found.items[0].label
    assert suggestions(cat, "50 / 51 Kapital") == ["+Kapital "]
    assert suggestions(cat, "50 / 51 +Kap") == ["+Kap "]
    assert suggestions(cat, "50 / 51 +") == []
    assert suggestions(cat, "50 / 51 Kapital 100") == []  # the amount, not a name
    assert suggestions(cat, "51 +Pasha / 60 +ARİF 5000 test") == []  # the same after "+"
    assert suggestions(cat, "51 +Pasha / 60 ARİF 5000") == []
    entry = parse("50 / 51 +Kapital 100", cat)
    assert entry.new_values[0].name == "Kapital"


def test_migration_gives_contracts_their_counterparty(tmp_path):
    """A version 8 file: contracts without owners, 60 / 62 manat only."""
    path = tmp_path / "v8.gl"
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("PRAGMA foreign_keys = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 8:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.executescript(
        """
        BEGIN;
        INSERT INTO companies (id, name, created_at) VALUES (1, 'Old', 'now');
        INSERT INTO layers (id, company_id, code, name) VALUES (1, 1, 'common', 'Общий');
        INSERT INTO currencies (id, company_id, code, name) VALUES (1, 1, 'USD', 'Dollar');
        INSERT INTO subconto_kinds (id, company_id, code, name) VALUES
            (1, 1, 'counterparty', 'Контрагенты'), (2, 1, 'contract', 'Договоры'),
            (3, 1, 'bank_account', 'Банки');
        -- 1 Альфа, 2 Бета, 3 №1 (Альфа only), 4 Общий (Альфа and Бета), 5 bank
        INSERT INTO subconto_values (id, company_id, kind_id, name) VALUES
            (1, 1, 1, 'Альфа'), (2, 1, 1, 'Бета'), (3, 1, 2, '№1'), (4, 1, 2, 'Общий'),
            (5, 1, 3, 'Bank USD');
        INSERT INTO accounts (id, company_id, code, name, sc1_kind_id, sc2_kind_id, currency)
        VALUES (1, 1, '26', 'Расходы', NULL, NULL, 0), (2, 1, '60', 'Поставщики', 1, 2, 0),
               (3, 1, '62', 'Покупатели', 1, 2, 0), (4, 1, '52', 'Валютный', 3, NULL, 1);
        INSERT INTO documents (id, company_id, number, doc_date, status, layer_id, created_at)
        VALUES (1, 1, 1, '2026-03-05', 'draft', 1, 'now');
        INSERT INTO postings (company_id, document_id, line_no, debit_account_id,
            credit_account_id, amount, ct_sc1, ct_sc2, dt_sc1, currency_id, currency_amount)
        VALUES (1, 1, 1, 1, 2, 100, 1, 3, NULL, NULL, NULL),
               (1, 1, 2, 1, 2, 100, 1, 4, NULL, NULL, NULL),
               (1, 1, 3, 1, 2, 100, 2, 4, NULL, NULL, NULL),
               -- 62 already carries the dollars of 52: it stays manat only
               (1, 1, 4, 4, 3, 170, 2, 4, 5, 1, 100);
        COMMIT;
        """
    )
    old.close()
    conn = connect(path)
    try:
        cat = Catalog(conn, 1)
        assert cat.owner_kinds == {2: 1}
        assert cat.value(3).owner_id == 1  # used with Альфа only
        assert cat.value(4).owner_id is None  # used with both: stays common
        assert cat.accounts[2].currency == CURRENCY_OPTIONAL
        assert cat.accounts[3].currency == 0
    finally:
        conn.close()


def test_a_posting_without_a_contract_is_allowed_but_not_without_a_counterparty(ledger, firm):
    """Many suppliers have no contract, only the e-qaimə: Dt 26 [Аренда] / Kt 60 [Бета, —]
    300.00 posts; 60 by contract closes at 300.00 Kt under «not given». The counterparty
    itself stays required."""
    from modern_gl.reporting.reports import subconto_balance

    cid, acc, v, _ = firm
    rent = (v["Аренда"],)
    ledger.post_new(
        cid, "2026-03-05", [PostingInput(acc["26"], acc["60"], "300", rent, (v["Бета"],))]
    )
    rows = subconto_balance(ledger.conn, cid, "60", "2026-03-01", "2026-03-31", position=2)
    assert [(r.name, r.closing_ct) for r in rows] == [("<не указано>", 30_000)]
    with pytest.raises(ValidationError, match="не заполнено субконто 1"):
        ledger.post_new(
            cid, "2026-03-05", [PostingInput(acc["26"], acc["60"], "1", rent, (None, v["Общий"]))]
        )
