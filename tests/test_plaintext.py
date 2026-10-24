"""The plain-text journal (hledger format, D79): exact text on the golden example, and the
balances recomputed from the text alone equal the ОСВ (here and through hledger itself)."""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from collections import defaultdict

import pytest

from modern_gl.application.books import IFRS
from modern_gl.application.ledger import PostingInput
from modern_gl.reporting.plaintext import account_name, hledger_journal
from modern_gl.reporting.report_common import _accounts
from modern_gl.reporting.reports import trial_balance
from tests.test_currency import books, post_example  # noqa: F401  (fixture)

HEADER = """\
; ООО Тест
; Журнал проводок по 2026-12-31 — книга: {book}
; Выгружено 2026-10-22 из Modern GL

commodity 1000.00 AZN

account 201 Материалы  ; type: A
account 22 Банковские счета  ; type: A
account 22 Банковские счета:221 Банк 1  ; type: A
account 22 Банковские счета:222 Банк 2  ; type: A
account 301 Капитал  ; type: E
account 531 Поставщики  ; type: L
account 721 Адм. расходы  ; type: X
"""

# The golden example of conftest, one transaction per document.
GOLDEN = """
2026-01-05 (1)
    22 Банковские счета:221 Банк 1  10000.00 AZN
    301 Капитал  -10000.00 AZN

2026-01-10 (2)
    201 Материалы  1200.00 AZN
    531 Поставщики  -1200.00 AZN  ; Контрагенты: Поставщик A

2026-01-15 (3)
    531 Поставщики  1000.00 AZN  ; Контрагенты: Поставщик A
    22 Банковские счета:221 Банк 1  -1000.00 AZN

2026-02-03 (4)
    201 Материалы  500.00 AZN
    531 Поставщики  -500.00 AZN  ; Контрагенты: Поставщик B

2026-02-04 (5)
    22 Банковские счета:222 Банк 2  2000.00 AZN
    22 Банковские счета:221 Банк 1  -2000.00 AZN

2026-02-20 (6)
    721 Адм. расходы  300.00 AZN
    201 Материалы  -300.00 AZN
"""


def journal(demo, layers=("common",)) -> str:
    return hledger_journal(demo.ledger.conn, demo.company_id, "2026-12-31", layers, "2026-10-22")


def balances(text: str) -> dict[str, int]:
    """Net balance (Dt - Ct, qəpik) of each account, read from the journal text alone."""
    result: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        if not line.startswith("    "):
            continue
        account, amount = line.split(";")[0].strip().split("  ")
        whole, frac = amount.removesuffix(" AZN").lstrip("-").split(".")
        minor = int(whole) * 100 + int(frac)
        result[account] += -minor if amount.startswith("-") else minor
    return {account: net for account, net in result.items() if net}


def osv_balances(conn, company_id, layers=("common",)) -> dict[str, int]:
    accounts = _accounts(conn, company_id)
    osv = trial_balance(conn, company_id, "2026-01-01", "2026-12-31", layers)
    return {
        account_name(accounts, r.account_id): r.closing_dt - r.closing_ct
        for r in osv.rows
        if not r.is_group and (r.closing_dt or r.closing_ct)
    }


def test_golden_example_text(demo):
    assert journal(demo) == HEADER.format(book="Общий учёт") + GOLDEN


def test_storno_draft_and_memo(demo):
    led, cid = demo.ledger, demo.company_id
    led.reverse(cid, demo.docs[5], "2026-02-25")
    led.create_draft(cid, "2026-03-01", [demo.p("721", "201", "50.00")])  # not exported
    led.post_new(
        cid,
        "2026-03-02",
        [PostingInput(demo.acc["721"], demo.acc["201"], "10.00", memo="бумага; 2 пачки")],
        memo="Списание  офис",
    )
    assert journal(demo).endswith(
        """
2026-02-25 (7) Сторно документа №6  ; сторно: 6
    721 Адм. расходы  -300.00 AZN
    201 Материалы  300.00 AZN

2026-03-02 (9) Списание офис
    721 Адм. расходы  10.00 AZN  ; примечание: бумага, 2 пачки
    201 Материалы  -10.00 AZN
"""
    )


def test_currency_side_carries_its_amount(ledger, books):  # noqa: F811
    cid = books[0]
    post_example(ledger, books)
    ledger.revalue(cid, "2026-03-31", "80")
    text = hledger_journal(ledger.conn, cid, "2026-03-31")
    # 1 000.00 USD × 1.70 = 1 700.00; only the currency side (52) shows USD
    assert (
        "2026-03-05 (1)\n"
        "    52 Валютный счёт  1700.00 AZN"
        "  ; Банковские_счета: Kapital Bank USD, валюта: 1000.00 USD\n"
        "    51 Расчётный счёт  -1700.00 AZN\n"
    ) in text
    # Hand-calculated (test_currency): 52 = 1 700 - 513 + 17 = 1 204.00 AZN after revaluation
    assert balances(text)["52 Валютный счёт"] == 120_400
    assert balances(text) == osv_balances(ledger.conn, cid)


def test_balances_from_text_equal_the_osv(demo):
    led, cid = demo.ledger, demo.company_id
    led.reverse(cid, demo.docs[5], "2026-02-25")
    led.post_new(cid, "2026-03-01", [demo.p("721", "221", "40.00")], layer="ifrs_adj")
    for layers in (("common",), IFRS):
        assert balances(journal(demo, layers)) == osv_balances(led.conn, cid, layers)
    # hand-calculated: 221 = 10 000 - 1 000 - 2 000 (- 40 in IFRS)
    assert balances(journal(demo))["22 Банковские счета:221 Банк 1"] == 700_000
    assert balances(journal(demo, IFRS))["22 Банковские счета:221 Банк 1"] == 696_000
    assert "2026-03-01 (8)  ; слой: " in journal(demo, IFRS)
    assert "(8)" not in journal(demo)


def test_names_do_not_break_the_syntax(ledger):
    cid = ledger.create_company("ООО")
    a = ledger.add_account(cid, "1", "Касса: основная;  старая", account_class="asset")
    b = ledger.add_account(cid, None, "(без кода)", account_class="equity")
    accounts = _accounts(ledger.conn, cid)
    assert account_name(accounts, a) == "1 Касса, основная, старая"
    assert account_name(accounts, b) == "без кода"


@pytest.mark.skipif(shutil.which("hledger") is None, reason="hledger не установлен")
def test_hledger_reads_the_journal_and_agrees(demo, tmp_path):
    led, cid = demo.ledger, demo.company_id
    led.reverse(cid, demo.docs[5], "2026-02-25")
    path = tmp_path / "company.journal"
    path.write_text(journal(demo), encoding="utf-8")
    subprocess.run(["hledger", "-f", str(path), "check", "--strict"], check=True)
    out = subprocess.run(
        ["hledger", "-f", str(path), "bal", "--flat", "--no-total", "-O", "csv"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    rows = list(csv.reader(io.StringIO(out)))[1:]
    by_hledger = {name: int(amount.removesuffix(" AZN").replace(".", "")) for name, amount in rows}
    assert by_hledger == osv_balances(led.conn, cid)
