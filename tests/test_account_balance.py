"""One balance «account + subconto element on a day» for the bank statement and the
payment (`application/bank/balance.py`). Hand-calculated, Dt − Kt of 60 on 31.03:
Alfa: −1 000.00 (bought) + 400.00 (paid) = −600.00; Beta: −250.00; all 60: −850.00.
A purchase of 05.04 is after the day; a draft does not count."""

from decimal import Decimal

from modern_gl.application.bank.balance import account_balance
from modern_gl.application.ledger import PostingInput


def test_balance_of_an_element_and_of_the_whole_account(ledger):
    cid = ledger.create_company("Остаток")
    partners = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    payable = ledger.add_account(
        cid, "60", "Поставщики", subconto=[partners], account_class="liability"
    )
    goods = ledger.add_account(cid, "41", "Товары", account_class="asset")
    bank = ledger.add_account(cid, "51", "Банк", account_class="asset")
    alfa = ledger.add_subconto_value(cid, partners, "Alfa")
    beta = ledger.add_subconto_value(cid, partners, "Beta")

    def buy(who: int, amount: str) -> PostingInput:
        return PostingInput(goods, payable, Decimal(amount), (), (who,))

    ledger.post_new(cid, "2026-03-02", [buy(alfa, "1000"), buy(beta, "250")])
    ledger.post_new(cid, "2026-03-10", [PostingInput(payable, bank, Decimal("400"), (alfa,))])
    ledger.post_new(cid, "2026-04-05", [buy(alfa, "70")])
    ledger.create_draft(cid, "2026-03-15", [buy(alfa, "5")])

    assert account_balance(ledger.conn, cid, payable, alfa, "2026-03-31") == -60_000
    assert account_balance(ledger.conn, cid, payable, beta, "2026-03-31") == -25_000
    assert account_balance(ledger.conn, cid, payable, None, "2026-03-31") == -85_000
    assert account_balance(ledger.conn, cid, bank, None, "2026-03-31") == -40_000
    assert account_balance(ledger.conn, cid, payable, alfa, "2026-04-05") == -67_000
