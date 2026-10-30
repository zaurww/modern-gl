"""Books with counterparties and their contracts, for the reports by subconto and the
trial balance opened by place (60 = [Контрагенты, Договоры], 26 = [Статьи затрат]):
  1  20.02  Dt 26 [Аренда]      Ct 60 [Альфа, Д1]   1 000.00   e-qaimə MM001
  2  05.03  Dt 26 [Аренда]      Ct 60 [Альфа, Д2]     400.00   e-qaimə MM002
  3  10.03  Dt 60 [Альфа, Д1]   Ct 26 [Аренда]        300.00   paid on MM001
  4  12.03  Dt 26 [Аренда]      Ct 60 [Бета, —]       200.00   no e-qaimə
"""

from __future__ import annotations

from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.infrastructure.db import Connection, connect


def contract_books() -> tuple[Connection, Ledger, int, dict[str, int]]:
    """(connection, ledger, company id, the directory elements by name)."""
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    cp = ledger.subconto_kind_id(cid, "counterparty")
    contract = ledger.subconto_kind_id(cid, "contract")
    v = {name: ledger.add_subconto_value(cid, cp, name) for name in ("Альфа", "Бета")}
    v["Аренда"] = ledger.add_subconto_value(
        cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"
    )
    for name in ("Д1", "Д2"):
        v[name] = ledger.add_subconto_value(cid, contract, name, owner_id=v["Альфа"])
    acc = {code: ledger.account_id(cid, code) for code in ("26", "60")}
    rent = (v["Аренда"],)
    for day, dt, ct, amount, dt_sc, ct_sc, invoice in (
        ("2026-02-20", "26", "60", "1000", rent, (v["Альфа"], v["Д1"]), "MM001"),
        ("2026-03-05", "26", "60", "400", rent, (v["Альфа"], v["Д2"]), "MM002"),
        ("2026-03-10", "60", "26", "300", (v["Альфа"], v["Д1"]), rent, "MM001"),
        ("2026-03-12", "26", "60", "200", rent, (v["Бета"],), ""),
    ):
        line = PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc, invoice=invoice)
        ledger.post_new(cid, day, [line])
    return conn, ledger, cid, v
