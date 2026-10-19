"""Golden example. Account codes are test-only, not a real chart.

Common layer:
  1  2026-01-05  Dt 221        Ct 301          10 000.00  capital paid in
  2  2026-01-10  Dt 201        Ct 531 [A]       1 200.00  materials from supplier A
  3  2026-01-15  Dt 531 [A]    Ct 221           1 000.00  paid supplier A
  4  2026-02-03  Dt 201        Ct 531 [B]         500.00  materials from supplier B
  5  2026-02-04  Dt 222        Ct 221           2 000.00  transfer between banks
  6  2026-02-20  Dt 721        Ct 201             300.00  materials written off

Expected ОСВ for February 2026 (hand-calculated):
  account  opening Dt/Ct   turnover Dt/Ct   closing Dt/Ct
  201      1 200 / -          500 / 300       1 400 / -
  22       9 000 / -        2 000 / 2 000     9 000 / -     (group)
   221     9 000 / -            - / 2 000     7 000 / -
   222         - / -        2 000 / -         2 000 / -
  301          - / 10 000       - / -             - / 10 000
  531          - / 200          - / 500           - / 700
  721          - / -          300 / -           300 / -
  total   10 200 / 10 200   2 800 / 2 800    10 700 / 10 700
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

# UI tests run without a screen; point Qt at the system fonts so text measures realistically.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ["WINDIR"], "Fonts"))

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.i18n import set_language
from modern_gl.infrastructure.db import connect


@dataclass
class Demo:
    ledger: Ledger
    company_id: int
    acc: dict[str, int]
    supplier_a: int
    supplier_b: int
    docs: list[int]

    def p(self, dt: str, ct: str, amount: str, dt_sc=(), ct_sc=()) -> PostingInput:
        return PostingInput(self.acc[dt], self.acc[ct], amount, dt_sc, ct_sc)


@pytest.fixture(autouse=True)
def russian_interface():
    """Tests assert Russian messages; test_i18n covers the Azerbaijani catalog."""
    set_language("ru")
    yield
    set_language("ru")


@pytest.fixture
def conn():
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def ledger(conn) -> Ledger:
    return Ledger(conn, actor="test")


def build_demo(ledger: Ledger, name: str = "ООО Тест") -> Demo:
    cid = ledger.create_company(name)
    cp = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    a = ledger.add_subconto_value(cid, cp, "Поставщик A")
    b = ledger.add_subconto_value(cid, cp, "Поставщик B")
    acc = {
        "201": ledger.add_account(cid, "201", "Материалы", kind="A"),
        "22": ledger.add_account(cid, "22", "Банковские счета", kind="A", is_group=True),
    }
    acc["221"] = ledger.add_account(cid, "221", "Банк 1", kind="A", parent_code="22")
    acc["222"] = ledger.add_account(cid, "222", "Банк 2", kind="A", parent_code="22")
    acc["301"] = ledger.add_account(cid, "301", "Капитал", kind="P")
    acc["531"] = ledger.add_account(cid, "531", "Поставщики", kind="AP", subconto=[cp])
    acc["721"] = ledger.add_account(cid, "721", "Адм. расходы", kind="A")
    demo = Demo(ledger, cid, acc, a, b, [])
    p = demo.p
    for doc_date, posting in [
        ("2026-01-05", p("221", "301", "10000.00")),
        ("2026-01-10", p("201", "531", "1200.00", ct_sc=[a])),
        ("2026-01-15", p("531", "221", "1000.00", dt_sc=[a])),
        ("2026-02-03", p("201", "531", "500.00", ct_sc=[b])),
        ("2026-02-04", p("222", "221", "2000.00")),
        ("2026-02-20", p("721", "201", "300.00")),
    ]:
        demo.docs.append(ledger.post_new(cid, doc_date, [posting]))
    return demo


@pytest.fixture
def demo(ledger) -> Demo:
    return build_demo(ledger)
