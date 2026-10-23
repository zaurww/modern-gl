"""Building the books again from the documents of the modules (D101). Hand-calculated:

Bank (tests/test_bank.py): a fee of 2.00 USD on 07.03 at 1.70 (the rate of 01.03) is 3.40;
  a rate of 1.75 entered for 07.03 later makes it 2.00 × 1.75 = 3.50.
Conversion (tests/test_conversion.py): 1 000 USD sold for 1 695.00 AZN on 02.03 at 1.70,
  credited on 03.03: Dt 57 / Ct 52 1 700.00, loss Dt 91.2 / Ct 57 5.00; the credit
  Dt 51 / Ct 57 1 695.00 on 03.03. 02.03's rate fixed to 1.69: Dt 57 / Ct 52 1 690.00 and
  a gain of 1 695.00 − 1 690.00 = 5.00 (Dt 57 / Ct 91.1); the credit is the same.
Warehouse (tests/test_sales.py): 10 bought for 120.00, 3 sold: cost 36.00, Dt 46 / Ct 41;
  with the cost of sales moved to 48 in the settings — Dt 48 / Ct 41 36.00.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.conversions import load_conversion
from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import load_document
from modern_gl.application.rebuild import module_rebuilders, rebuild_postings
from modern_gl.demo_year import create_year_demo
from modern_gl.domain.accounts import COST_OF_SALES
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from tests.test_bank import firm as bank_firm  # noqa: F401 — a fixture
from tests.test_bank import postings as bank_postings
from tests.test_bank import usd_fee
from tests.test_conversion import firm as conversion_firm  # noqa: F401 — a fixture
from tests.test_conversion import postings as conversion_postings
from tests.test_conversion import sale as currency_sale
from tests.test_sales import make_shop, two_lines


def audit_count(conn, action: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM audit_events WHERE action = ?", (action,)).fetchone()[
        0
    ]


def test_every_module_that_makes_gl_documents_can_rebuild_them(ledger):
    """The rule of D101: a module that adds itself to `document_owners` as the maker of GL
    documents adds itself to `module_rebuilders` too."""
    view = [
        p.read_text(encoding="utf-8")
        for p in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if "VIEW document_owners" in p.read_text(encoding="utf-8")
    ][-1]
    makers = set(re.findall(r"'(\w+)'(?: AS module)?, 'made'", view))
    assert makers == {"bank", "conversion", "inventory"}
    assert set(module_rebuilders(ledger)) == makers


@pytest.fixture(scope="module")
def year():
    conn = connect(":memory:")
    ledger = Ledger(conn)
    cid = create_year_demo(ledger)
    ledger.set_closed_through(cid, None)  # the whole year, the closed half too
    yield ledger, cid
    conn.close()


def test_rebuild_of_a_whole_year_changes_nothing(year):
    """What every module has just posted is what it builds again: on the year demo
    (every module, every day) a rebuild from the first day leaves every document."""
    ledger, cid = year
    reposts = audit_count(ledger.conn, "repost")
    for name, module in module_rebuilders(ledger).items():
        assert module.rebuild_postings(cid, "2026-01-01") == [], name
    assert audit_count(ledger.conn, "repost") == reposts


def test_bank_follows_a_fixed_rate(ledger, bank_firm):  # noqa: F811
    f = bank_firm
    cid = f["cid"]
    op_id = ledger.bank.save_bank_operation(cid, usd_fee(f), post=True)
    assert [p.amount for p in bank_postings(ledger, f, op_id)] == [340]
    document_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    number = load_document(ledger.conn, cid, document_id).number

    ledger.set_rate(cid, "USD", "2026-03-07", parse_rate("1.75"))
    assert rebuild_postings(ledger, cid, "2026-03-01") == [document_id]

    [p] = bank_postings(ledger, f, op_id)
    assert (p.amount, p.currency_amount) == (350, 200)
    assert load_document(ledger.conn, cid, document_id).number == number
    assert audit_count(ledger.conn, "repost") == 1  # the old postings are kept there
    assert rebuild_postings(ledger, cid, "2026-03-01") == []


def test_closed_period_is_not_rebuilt(ledger, bank_firm):  # noqa: F811
    f = bank_firm
    cid = f["cid"]
    op_id = ledger.bank.save_bank_operation(cid, usd_fee(f), post=True)
    ledger.set_closed_through(cid, "2026-03-31")
    ledger.set_rate(cid, "USD", "2026-03-07", parse_rate("1.75"))

    assert rebuild_postings(ledger, cid, "2026-01-01") == []
    assert [p.amount for p in bank_postings(ledger, f, op_id)] == [340]


def test_an_error_names_the_document_and_changes_nothing(ledger, bank_firm):  # noqa: F811
    f = bank_firm
    cid = f["cid"]
    ledger.bank.save_bank_operation(cid, usd_fee(f), post=True)
    first = ledger.bank.save_bank_operation(
        cid, replace(usd_fee(f), doc_date="2026-03-02"), post=True
    )
    number = load_bank_operation(ledger.conn, cid, first).number
    ledger.set_rate(cid, "USD", "2026-03-07", parse_rate("1.75"))
    ledger.delete_rate(cid, "USD", "2026-03-01")  # no rate on 02.03 any more

    with pytest.raises(ValidationError, match=rf"банковская операция №{number} от 02\.03\.2026"):
        rebuild_postings(ledger, cid, "2026-03-01")
    assert audit_count(ledger.conn, "repost") == 0


def test_conversion_follows_a_fixed_rate(ledger, conn, conversion_firm):  # noqa: F811
    f = conversion_firm
    cid, acc = f["cid"], f["acc"]
    data = currency_sale(f, target_date="2026-03-03", fees=())
    conversion = load_conversion(conn, cid, ledger.conversion.save_conversion(cid, data, post=True))
    assert conversion_postings(conn, cid, conversion.document_id) == [
        (acc["57"], acc["52"], 170_000, 100_000),
        (acc["91.2"], acc["57"], 500, None),
    ]

    ledger.set_rate(cid, "USD", "2026-03-02", parse_rate("1.69"))
    assert ledger.conversion.rebuild_postings(cid, "2026-03-01") == [conversion.document_id]

    assert conversion_postings(conn, cid, conversion.document_id) == [
        (acc["57"], acc["52"], 169_000, 100_000),
        (acc["57"], acc["91.1"], 500, None),
    ]
    assert conversion.credit_document_id is not None
    assert conversion_postings(conn, cid, conversion.credit_document_id) == [
        (acc["51"], acc["57"], 169_500, None)
    ]


def test_a_conversion_error_names_the_conversion(ledger, conn, conversion_firm):  # noqa: F811
    f = conversion_firm
    cid = f["cid"]
    conversion = load_conversion(
        conn, cid, ledger.conversion.save_conversion(cid, currency_sale(f), post=True)
    )
    number = load_document(conn, cid, conversion.document_id).number
    ledger.delete_rate(cid, "USD", "2026-03-02")  # no rate on 02.03 any more

    with pytest.raises(ValidationError, match=rf"конвертация №{number} от 02\.03\.2026"):
        ledger.conversion.rebuild_postings(cid, "2026-03-01")
    assert audit_count(conn, "repost") == 0


def test_warehouse_follows_a_fixed_setting(conn):
    shop = make_shop(conn, "classic")
    receipt = shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale("2026-01-20", two_lines(shop))
    assert shop.postings(sale)[-1][:3] == ("46", "41", 3_600)
    gl = shop.inventory.load_document(shop.company_id, sale).gl_document_id

    shop.ledger.set_account_role(shop.company_id, COST_OF_SALES, shop.acc["48"])
    inventory = Inventory(conn, actor="test")
    assert inventory.rebuild_postings(shop.company_id, "2026-01-01") == [gl]

    sold = shop.postings(sale)
    assert sold[-1][:3] == ("48", "41", 3_600)
    assert [p[2] for p in sold[:3]] == [7_080, 2_950, 1_530]  # the revenue stays
    assert shop.postings(receipt)[0][:3] == ("41", "60", 12_000)
    assert inventory.rebuild_postings(shop.company_id, "2026-01-21") == []
