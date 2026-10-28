"""«Проверка книги» (D175): each check finds the damage made by hand, and only it.

Hand-calculated:
Bank (tests/test_bank.py): a fee of 2.00 USD on 07.03 at 1.70 is 3.40; a rate of 1.75
  entered for 07.03 later makes the operation say 3.50 — the books still say 3.40.
Bank statement: Kapital AZN on 51, 10 000.00 in on 01.03, 1 200.00 out on 02.03; the
  bank says 8 800.00 at the end of 02.03 — reconciled. Then 50.00 out on 02.03 typed in
  the journal: the books 8 750.00, the bank 8 800.00, the difference 50.00.
ƏDV deposit (tests/test_deposit_reconciliation.py): 01–03.10 marked reconciled, out
  952.44; a fee of 5.00 on 02.10 since: out 957.44, at the end −268.44 → −273.44.
Warehouse (tests/helpers/sales.py): 10 bought for 120.00, 3 sold at 12.00 each: 84.00 on
  the warehouse and on 41. A journal posting Dt 41 / Ct 60 5.00 past the warehouse: the
  books 89.00, the warehouse 84.00, the difference −5.00.
"""

from __future__ import annotations

import pytest

from modern_gl.application.bank import bank_places, load_bank_operation
from modern_gl.application.bank.deposit_reconciliation import reconcile_deposit
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import load_document
from modern_gl.application.verification import REBUILD, rebuild_modules, verify
from modern_gl.domain.currency import parse_rate
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import connect, open_snapshot
from tests.helpers.bank import usd_fee
from tests.helpers.deposit import fee
from tests.helpers.sales import make_shop, two_lines
from tests.helpers.vat_deposit import operations

BANK = "Банк сходится с выписками банка"


def found(conn, company_id) -> dict[str, list[str]]:
    """What each check found, by its title: an empty list — the check passed."""
    return {r.title: [f.text for f in r.findings] for r in verify(conn, company_id)}


def problems(conn, company_id) -> list[str]:
    return [text for texts in found(conn, company_id).values() for text in texts]


def test_a_sound_company_passes_every_check(demo):
    results = verify(demo.ledger.conn, demo.company_id)
    assert [r.title for r in results] == [
        "Файл компании цел",
        "Проведённые документы соответствуют правилам проведения",
        "Сторно повторяют свои документы",
        "Проводки модулей совпадают с их документами",
        BANK,
        "Склад сходится со счетами запасов",
    ]
    assert all(r.ok for r in results)


def test_the_check_changes_nothing(demo):
    conn = demo.ledger.conn
    before = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    verify(conn, demo.company_id)
    assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before
    assert not conn.in_transaction


def test_a_posting_to_an_account_made_a_group_since(demo):
    """201 got postings, then a tool past the program made it a group of accounts."""
    conn = demo.ledger.conn
    conn.execute("UPDATE accounts SET is_group = 1 WHERE id = ?", (demo.acc["201"],))
    number = load_document(conn, demo.company_id, demo.docs[1]).number
    assert found(conn, demo.company_id)["Проведённые документы соответствуют правилам проведения"][
        0
    ] == (f"№{number} от 10.01.2026: строка 1, Дт 201: нельзя проводить на группу счетов")


def test_an_account_closed_since_is_no_error(demo):
    demo.ledger.conn.execute("UPDATE accounts SET active = 0 WHERE id = ?", (demo.acc["721"],))
    assert problems(demo.ledger.conn, demo.company_id) == []


def test_a_storno_that_does_not_mirror_its_document(demo):
    """The storno of 1 200.00 written by hand as −1 000.00."""
    conn, cid, original = demo.ledger.conn, demo.company_id, demo.docs[1]
    storno = demo.ledger.reverse(cid, original, "2026-01-31")
    good = problems(conn, cid)
    copy = connect(":memory:")  # rows rewritten the way only a tool could: a copy, edited
    conn.backup(copy)
    copy.execute("DROP TRIGGER postings_posted_no_update")
    copy.execute("UPDATE postings SET amount = -100000 WHERE document_id = ?", (storno,))
    numbers = [load_document(copy, cid, d).number for d in (storno, original)]
    assert good == []
    assert found(copy, cid)["Сторно повторяют свои документы"] == [
        f"№{numbers[0]} от 31.01.2026: проводки не повторяют документ №{numbers[1]} "
        "с обратным знаком"
    ]


def test_bank_postings_behind_a_fixed_rate_are_found_and_rebuilt(ledger, bank_firm):
    f, cid = bank_firm, bank_firm["cid"]
    op_id = ledger.bank.save_bank_operation(cid, usd_fee(f), post=True)
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    number = load_document(ledger.conn, cid, doc_id).number
    ledger.set_rate(cid, "USD", "2026-03-07", parse_rate("1.75"))

    [result] = [r for r in verify(ledger.conn, cid) if r.repair]
    assert result.repair == REBUILD
    assert [(x.text, x.document_id) for x in result.findings] == [
        (f"№{number} от 07.03.2026: проводки отличаются от документа раздела «Банк»", doc_id)
    ]
    assert [p.amount for p in load_document(ledger.conn, cid, doc_id).postings] == [340]

    assert rebuild_modules(ledger, cid) == [doc_id]
    assert [p.amount for p in load_document(ledger.conn, cid, doc_id).postings] == [350]
    assert problems(ledger.conn, cid) == []


@pytest.fixture
def kapital(ledger):
    cid = ledger.create_company("ООО Выписки")
    apply_chart_template(ledger, cid, "1c77", "ru")
    azn = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "bank_account"), "Kapital")
    owner = ledger.add_subconto_value(
        cid, ledger.subconto_kind_id(cid, "counterparty"), "Учредитель"
    )
    a51, a80 = ledger.account_id(cid, "51"), ledger.account_id(cid, "80")
    ledger.post_new(cid, "2026-03-01", [PostingInput(a51, a80, "10000", [azn], [owner])])
    ledger.post_new(cid, "2026-03-02", [PostingInput(a80, a51, "1200", [owner], [azn])])
    ledger.bank.set_bank_closing(cid, a51, azn, "2026-03-02", "2026-03-02", 880_000)
    return cid, a51, a80, azn, owner


def test_a_reconciled_statement_agrees_with_the_bank(ledger, kapital):
    assert problems(ledger.conn, kapital[0]) == []


def test_a_journal_posting_to_51_after_the_statement_was_reconciled(ledger, kapital):
    cid, a51, a80, azn, owner = kapital
    ledger.post_new(cid, "2026-03-02", [PostingInput(a80, a51, "50", [owner], [azn])])
    assert found(ledger.conn, cid)[BANK] == [
        "Kapital (51), выписка 02.03.2026: по банку 8 800.00, в программе 8 750.00, разница 50.00"
    ]


def test_a_reconciled_vat_deposit_period_changed_since(ledger, deposit_firm):
    """The days' statements differ from the portal too (no opening balance in the books,
    a draft) — here only the reconciled period is looked at."""

    def changes() -> list[str]:
        return [text for text in found(ledger.conn, cid)[BANK] if "сверен" in text]

    cid, place = deposit_firm["cid"], deposit_firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    seen = reconcile_deposit(
        ledger.conn, cid, place, operations(), 100000, "2026-10-01", "2026-10-03"
    )
    ledger.bank.mark_deposit_reconciled(cid, place, seen)
    assert changes() == []

    fee(ledger, deposit_firm, "2026-10-02")
    [place] = [p for p in bank_places(ledger.conn, cid) if p.key == place.key]
    assert changes() == [
        f"{place.name} ({place.account_code}): "
        + tr(
            "{period} сверен, но {side} изменилось: приход {was_in} → {now_in}, расход "
            "{was_out} → {now_out}, на конец {was_end} → {now_end}",
            period="01.10.2026–03.10.2026",
            side=tr("в программе"),
            was_in="684.00",
            now_in="684.00",
            was_out="952.44",
            now_out="957.44",
            was_end="-268.44",
            now_end="-273.44",
        )
    ]


@pytest.fixture
def shop(conn):
    shop = make_shop(conn, "classic")
    shop.receipt("2026-01-10", "10", "120.00")
    shop.sale("2026-01-20", two_lines(shop))
    return shop


def test_the_warehouse_agrees_with_41(shop):
    assert problems(shop.ledger.conn, shop.company_id) == []


def test_a_journal_posting_to_41_past_the_warehouse(shop):
    conn, cid = shop.ledger.conn, shop.company_id
    stock_side = conn.execute(
        "SELECT dt_sc1, dt_sc2, dt_sc3 FROM postings WHERE company_id = ? AND debit_account_id = ?",
        (cid, shop.acc["41"]),
    ).fetchone()
    shop.ledger.post_new(
        cid,
        "2026-01-25",
        [PostingInput(shop.acc["41"], shop.acc["60"], "5.00", tuple(stock_side), shop.supplier)],
    )
    assert found(conn, cid)["Склад сходится со счетами запасов"] == [
        "счёт 41: на складе 84.00, по книге 89.00, разница -5.00"
    ]


def test_a_company_open_for_viewing_is_checked_too(tmp_path, shop):
    path = tmp_path / "shop.gl"
    target = connect(path)
    shop.ledger.conn.backup(target)
    target.close()
    snapshot = open_snapshot(path)
    try:
        assert problems(snapshot, shop.company_id) == []
    finally:
        snapshot.close()
