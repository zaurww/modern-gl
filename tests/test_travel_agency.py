"""A travel agency on the 1C 7.7 chart: one directory «Sifarişlər» (orders, no owner) as the
third subconto of 60.1, 62.1 and 90.1 links the client, the suppliers and the commission
of one case. Hand-calculated example (agency model: the client's money passes through,
revenue is the commission), June 2026:

  S-001  Zaur, a tour: price 2 000.00, the operator's net 1 800.00, commission 200.00
  1  01.06  Dt 51            Ct 62.1 [Zaur, -, S-001]       2 000.00  paid by the client
  2  02.06  Dt 62.1 [Zaur, -, S-001]  Ct 60.1 [TurOp, -, S-001]  1 800.00  the tour
  3  02.06  Dt 62.1 [Zaur, -, S-001]  Ct 90.1 [S-001]        200.00  commission
  4  03.06  Dt 60.1 [TurOp, -, S-001] Ct 51                 1 800.00  paid to the operator
  S-002  Firma MMC, a ticket: price 1 000.00, the airline's 950.00, commission 50.00
  5  05.06  Dt 51            Ct 62.1 [Firma, -, S-002]        500.00  part paid
  6  06.06  Dt 62.1 [Firma, -, S-002] Ct 60.1 [Hava, -, S-002]  950.00  the ticket
  7  06.06  Dt 62.1 [Firma, -, S-002] Ct 90.1 [S-002]         50.00  commission

By order (June):            62.1 Dt / Ct → closing     60.1 Dt / Ct → closing   90.1 Ct
  S-001 (closed)          2 000 / 2 000 →   0        1 800 / 1 800 →   0        200
  S-002 (open)            1 000 /   500 → 500 Dt         0 /   950 → 950 Ct      50
"""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import Inventory, ReceiptLine, SaleLine
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.reporting.reports import subconto_balance

JUNE = ("2026-06-01", "2026-06-30")


@pytest.fixture
def agency(ledger):
    return make_agency(ledger)


def make_agency(ledger):
    """The agency on the 1C 7.7 chart with «Sifarişlər» as the third subconto of 60.1,
    62.1 and 90.1: (company, accounts by code, elements by name, kinds by code, the order
    kind)."""
    cid = ledger.create_company("Səyahət MMC")
    apply_chart_template(ledger, cid, "1c77", "az")
    kind = {
        c: ledger.subconto_kind_id(cid, c) for c in ("counterparty", "contract", "bank_account")
    }
    order = ledger.add_subconto_kind(cid, "order", "Sifarişlər")
    for code in ("60.1", "62.1"):
        ledger.update_account(cid, code, subconto=[kind["counterparty"], kind["contract"], order])
    ledger.update_account(cid, "90.1", subconto=[order])
    acc = {c: ledger.account_id(cid, c) for c in ("51", "60.1", "62.1", "90.1")}
    v = {
        name: ledger.add_subconto_value(cid, kind["counterparty"], name)
        for name in ("Zaur", "Firma MMC", "TurOp", "Hava Yolları")
    }
    v["S-001"] = ledger.add_subconto_value(cid, order, "S-001 Zaur, Antalya")
    v["S-002"] = ledger.add_subconto_value(cid, order, "S-002 Firma MMC, bilet")
    v["bank"] = ledger.add_subconto_value(cid, kind["bank_account"], "Kapital Bank AZN")
    return cid, acc, v, kind, order


def _post_cases(ledger, agency) -> None:
    cid, acc, v, _, _ = agency
    bank = (v["bank"],)
    zaur = (v["Zaur"], None, v["S-001"])
    turop = (v["TurOp"], None, v["S-001"])
    firma = (v["Firma MMC"], None, v["S-002"])
    hava = (v["Hava Yolları"], None, v["S-002"])
    for day, dt, ct, amount, dt_sc, ct_sc in (
        ("2026-06-01", "51", "62.1", "2000", bank, zaur),
        ("2026-06-02", "62.1", "60.1", "1800", zaur, turop),
        ("2026-06-02", "62.1", "90.1", "200", zaur, (v["S-001"],)),
        ("2026-06-03", "60.1", "51", "1800", turop, bank),
        ("2026-06-05", "51", "62.1", "500", bank, firma),
        ("2026-06-06", "62.1", "60.1", "950", firma, hava),
        ("2026-06-06", "62.1", "90.1", "50", firma, (v["S-002"],)),
    ):
        ledger.post_new(cid, day, [PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)])


def _by_order(conn, cid, account, position=3) -> dict[str, tuple[int, int, int, int]]:
    rows = subconto_balance(conn, cid, account, *JUNE, position=position)
    return {r.name[:5]: (r.turnover_dt, r.turnover_ct, r.closing_dt, r.closing_ct) for r in rows}


def test_one_order_links_the_client_and_the_suppliers(ledger, conn, agency):
    cid, acc, *_ = agency
    _post_cases(ledger, agency)
    assert _by_order(conn, cid, acc["62.1"]) == {
        "S-001": (200000, 200000, 0, 0),
        "S-002": (100000, 50000, 50000, 0),
    }
    assert _by_order(conn, cid, acc["60.1"]) == {
        "S-001": (180000, 180000, 0, 0),
        "S-002": (0, 95000, 0, 95000),
    }
    assert _by_order(conn, cid, acc["90.1"], position=1) == {
        "S-001": (0, 20000, 0, 20000),
        "S-002": (0, 5000, 0, 5000),
    }


def test_order_is_required_where_attached_and_the_contract_stays_optional(ledger, agency):
    cid, acc, v, _, _ = agency
    with pytest.raises(ValidationError, match="Sifarişlər"):
        ledger.post_new(
            cid,
            "2026-06-01",
            [PostingInput(acc["51"], acc["62.1"], "100", (v["bank"],), (v["Zaur"],))],
        )
    ledger.post_new(
        cid,
        "2026-06-01",
        [PostingInput(acc["51"], acc["62.1"], "100", (v["bank"],), (v["Zaur"], None, v["S-001"]))],
    )


def test_a_contract_cannot_serve_as_the_case_on_the_supplier_side(ledger, agency):
    """Why a separate directory: a contract belongs to the client, so it is refused next
    to the supplier on 60.1 — the case could not be seen from both sides."""
    cid, acc, v, kind, _ = agency
    case = ledger.add_subconto_value(cid, kind["contract"], "S-003", owner_id=v["Zaur"])
    with pytest.raises(ValidationError, match="относится к «Zaur»"):
        ledger.post_new(
            cid,
            "2026-06-02",
            [
                PostingInput(
                    acc["62.1"],
                    acc["60.1"],
                    "1800",
                    (v["Zaur"], case, v["S-001"]),
                    (v["TurOp"], case, v["S-001"]),
                )
            ],
        )


def test_sale_form_asks_for_the_order_and_fills_both_sides(ledger, conn, agency):
    """The commission as a service sale (D61): the order is asked once per line and goes to
    the revenue account and to the customer's account by kind."""
    cid, acc, v, _, order = agency
    inventory = Inventory(conn, actor="test")
    assert inventory.sale_kinds(cid) == [order]
    doc = inventory.create_sale_draft(
        cid,
        "2026-06-06",
        [SaleLine(None, None, None, "50", memo="Komissiya", sale_subconto=[v["S-002"]])],
        acc["62.1"],
        (v["Firma MMC"], None, v["S-002"]),
    )
    inventory.post_document(cid, doc)
    assert _by_order(conn, cid, acc["62.1"]) == {"S-002": (5000, 0, 5000, 0)}
    assert _by_order(conn, cid, acc["90.1"], position=1) == {"S-002": (0, 5000, 0, 5000)}


def test_purchase_of_a_ticket_for_the_client_carries_the_order(ledger, conn, agency):
    """The ticket bought for the client: a purchase line without an item, its value owed
    by the client on 62.1 — both sides carry the order."""
    cid, acc, v, _, _ = agency
    inventory = Inventory(conn, actor="test")
    doc = inventory.create_receipt_draft(
        cid,
        "2026-06-06",
        [
            ReceiptLine(
                None,
                None,
                None,
                "950",
                memo="Bilet BAK-IST",
                expense_account_id=acc["62.1"],
                expense_subconto=(v["Firma MMC"], None, v["S-002"]),
            )
        ],
        acc["60.1"],
        (v["Hava Yolları"], None, v["S-002"]),
    )
    inventory.post_document(cid, doc)
    assert _by_order(conn, cid, acc["60.1"]) == {"S-002": (0, 95000, 0, 95000)}
    assert _by_order(conn, cid, acc["62.1"]) == {"S-002": (95000, 0, 95000, 0)}


def test_catalog_shows_the_order_as_a_plain_directory(agency, conn):
    cid, _acc, _, _, order = agency
    cat = Catalog(conn, cid)
    assert order not in cat.owner_kinds
    assert cat.by_code["62.1"].sc_kinds[2] == order


def _shown_headers(page) -> list[str]:
    from PySide6.QtCore import Qt

    model = page.model
    return [
        str(model.headerData(c, Qt.Orientation.Horizontal))
        for c in range(len(model.columns))
        if page._shown(c)
    ]


def test_sale_form_asks_for_the_order_once(ledger, conn, agency, qtbot):
    """The sale form: the order is a column of the line, asked once — not as the customer's
    third subconto and again as the revenue account's (D61)."""
    from datetime import date

    from modern_gl.desktop.inventory_document_page import (
        AMOUNT,
        MEMO,
        SALE1,
        SC1,
        InventoryDocumentPage,
    )
    from modern_gl.desktop.inventory_document_page.columns import SC3
    from modern_gl.desktop.session import Session

    cid, acc, v, _, _ = agency
    session = Session(
        conn, ledger, cid, "Səyahət", Catalog(conn, cid), working_date=date(2026, 6, 6)
    )
    page = InventoryDocumentPage(session, doc_type="sale")
    qtbot.addWidget(page)
    model = page.model

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value)

    _without_vat(page)
    put(0, MEMO, "Komissiya")
    put(0, AMOUNT, 5_000)
    put(0, SC1, v["Firma MMC"])
    put(0, SC3, v["S-002"])
    headers = _shown_headers(page)
    assert headers.count("Sifarişlər") == 1, headers
    assert not page._shown(model.columns.index(SALE1))  # the customer's order serves 90.1
    assert page.save(post=True), page.error.text()
    assert _by_order(conn, cid, acc["90.1"], position=1) == {"S-002": (0, 5000, 0, 5000)}
    assert _by_order(conn, cid, acc["62.1"]) == {"S-002": (5000, 0, 5000, 0)}


def _without_vat(page) -> None:
    """The commission without ƏDV: the form offers 18 % by default (the chart has 68.2)."""
    for i in range(page.vat_rate.count()):
        if not page.vat_rate.itemData(i):
            page.vat_rate.setCurrentIndex(i)
            page.vat_rate.activated.emit(i)  # as a choice by hand: the lines follow
            return
    raise AssertionError("no «without VAT» choice")


def test_purchase_form_takes_the_ticket_for_the_client(ledger, conn, agency, qtbot):
    """The purchase form: a service line owed by the client on 62.1 («Корр. счёт» 62.1 with
    its subconto columns) — the order is asked on both the supplier's and the client's side."""
    from datetime import date

    from modern_gl.desktop.inventory_document_page import (
        AMOUNT,
        EXPENSE,
        MEMO,
        SC1,
        InventoryDocumentPage,
    )
    from modern_gl.desktop.inventory_document_page.columns import ESC1, ESC3, SC3
    from modern_gl.desktop.session import Session

    cid, acc, v, _, _ = agency
    session = Session(
        conn, ledger, cid, "Səyahət", Catalog(conn, cid), working_date=date(2026, 6, 6)
    )
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value), key

    _without_vat(page)
    put(0, MEMO, "Bilet BAK-IST")
    put(0, AMOUNT, 95_000)
    put(0, SC1, v["Hava Yolları"])
    put(0, SC3, v["S-002"])
    put(0, EXPENSE, acc["62.1"])
    put(0, ESC1, v["Firma MMC"])
    put(0, ESC3, v["S-002"])
    headers = _shown_headers(page)
    assert headers.count("Sifarişlər") == 2, headers  # the supplier's and the client's
    assert page.save(post=True), page.error.text()
    assert _by_order(conn, cid, acc["60.1"]) == {"S-002": (0, 95000, 0, 95000)}
    assert _by_order(conn, cid, acc["62.1"]) == {"S-002": (95000, 0, 95000, 0)}
