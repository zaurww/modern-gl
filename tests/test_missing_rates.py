"""«На дату курс не загружен» — one rule and one text for the document, the bank
operation and the conversion («Долг» 14)."""

from __future__ import annotations

from modern_gl.application.currencies import missing_rates_text
from modern_gl.domain.currency import parse_rate


def test_each_currency_without_a_rate_of_the_day_is_named_once(ledger, conn):
    cid = ledger.create_company("Курсы")
    usd, eur, rub = (ledger.currency_id(cid, c) for c in ("USD", "EUR", "RUB"))
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))  # an older one
    ledger.set_rate(cid, "EUR", "2026-03-05", parse_rate("1.85"))  # of the day
    text = missing_rates_text(conn, cid, [usd, eur, rub, usd], "2026-03-05")
    assert text == "На 05.03.2026 курс не загружен: нет курса RUB, курс USD от 01.03.2026"
    assert missing_rates_text(conn, cid, [eur], "2026-03-05") == ""
    assert missing_rates_text(conn, cid, [], "2026-03-05") == ""
