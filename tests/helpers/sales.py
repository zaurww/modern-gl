"""Shared from test_sales.py (moved here: other test modules use it too)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.inventory import (
    STANDARD_VAT_RATE,
    Inventory,
    ReceiptLine,
    SaleLine,
)
from modern_gl.application.ledger import Ledger
from modern_gl.desktop.inventory_document_page import (
    InventoryDocumentPage,
)
from modern_gl.desktop.session import Session


@dataclass
class Shop:
    ledger: Ledger
    inventory: Inventory
    company_id: int
    acc: dict[str, int]
    item: int
    main: int
    supplier: list[int]
    customer: int
    contract: int

    def receipt(self, day: str, quantity: str, amount: str) -> int:
        return self.inventory.post_receipt(
            self.company_id,
            day,
            [ReceiptLine(self.item, self.main, quantity, amount)],
            self.acc["60"],
            self.supplier,
        )

    def sale(self, day: str, lines: list[SaleLine], **kwargs) -> int:
        return self.inventory.post_sale(
            self.company_id,
            day,
            lines,
            self.acc["62"],
            [self.customer, self.contract],
            "Продажа",
            vat_rate=STANDARD_VAT_RATE,
            **kwargs,
        )

    def postings(self, inv_doc: int) -> list[tuple]:
        """(Dt code, Kt code, amount, memo, invoice) of a warehouse document's GL document."""
        gl = self.inventory.load_document(self.company_id, inv_doc).gl_document_id
        code = {v: k for k, v in self.acc.items()}
        return [
            (
                code[p["debit_account_id"]],
                code[p["credit_account_id"]],
                p["amount"],
                p["memo"],
                p["invoice"],
            )
            for p in self.ledger.conn.execute(
                "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl,)
            )
        ]


def make_shop(conn: sqlite3.Connection, template: str) -> Shop:
    ledger = Ledger(conn, actor="test")
    company_id = ledger.create_company(template)
    apply_chart_template(ledger, company_id, template, "ru")
    acc = {
        row["code"]: row["id"]
        for row in conn.execute(
            "SELECT code, id FROM accounts WHERE company_id = ? AND code IS NOT NULL",
            (company_id,),
        )
    }
    if template == "1c77":  # the codes the tests use, as in the classic chart
        acc |= {"60": acc["60.1"], "62": acc["62.1"]}
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(company_id, "əd", "Ədəd", precision=0)
    inventory_account = acc["41.1"] if template == "1c77" else acc["41"]
    item = inventory.add_item(company_id, "Printer", unit, inventory_account)
    main = inventory.add_warehouse(company_id, "Əsas anbar")
    counterparty = ledger.subconto_kind_id(company_id, "counterparty")
    contract_kind = ledger.subconto_kind_id(company_id, "contract")
    supplier = ledger.add_subconto_value(company_id, counterparty, "Təchizatçı")
    supply = ledger.add_subconto_value(company_id, contract_kind, "Tədarük", owner_id=supplier)
    customer = ledger.add_subconto_value(company_id, counterparty, "Alfa")
    contract = ledger.add_subconto_value(company_id, contract_kind, "Müqavilə 1", owner_id=customer)
    return Shop(
        ledger, inventory, company_id, acc, item, main, [supplier, supply], customer, contract
    )


def two_lines(shop: Shop) -> list[SaleLine]:
    return [
        SaleLine(shop.item, shop.main, "3", "60", "10.80"),
        SaleLine(None, None, None, "25", "4.50", "Çatdırılma"),
    ]


def sale_page(shop: Shop, conn, qtbot) -> InventoryDocumentPage:
    session = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        working_date=date(2026, 1, 20),
    )
    page = InventoryDocumentPage(session, doc_type="sale")
    qtbot.addWidget(page)
    return page
