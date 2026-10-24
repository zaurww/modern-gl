"""«Əlavə xərclər» by declaration: price, each kind of expense, total and the percent added
(the expected figures are worked out by hand in the comments)."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QPushButton

from modern_gl.application.inventory import (
    Inventory,
    LandedCostCharge,
    LandedCostTarget,
    ReceiptLine,
)
from modern_gl.application.ledger import Ledger
from modern_gl.demo_year import create_year_demo
from modern_gl.desktop import theme, widgets
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.landed_cost_report_page import LandedCostReportPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.domain.currency import CURRENCY_OPTIONAL
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import Workspace
from modern_gl.reporting.inventory import landed_cost_report


@pytest.fixture
def declaration(ledger: Ledger, conn):
    """Declaration AZ1 on 01.04 in USD at 1.7: A 10 pcs for $100 (170.00), B 5 pcs for
    $75 (127.50) — 297.50. Customs by value: duty 29.75 and fee 11.90; freight $30 (51.00)
    by quantity. A local receipt without expenses and a declaration of May are not in
    April's report."""
    cid = ledger.create_company("Импорт")
    item_kind = ledger.add_subconto_kind(cid, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    counterparty = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    stock = ledger.add_account(
        cid, "41", "Товары", subconto=[item_kind, warehouse_kind], account_class="asset"
    )
    suppliers = ledger.add_account(
        cid,
        "60",
        "Поставщики",
        subconto=[counterparty],
        account_class="liability",
        currency=CURRENCY_OPTIONAL,
    )
    customs_account = ledger.add_account(
        cid, "76", "Таможня", subconto=[counterparty], account_class="liability"
    )
    supplier = ledger.add_subconto_value(cid, counterparty, "Supplier Ltd")
    local = ledger.add_subconto_value(cid, counterparty, "Местный")
    customs = ledger.add_subconto_value(cid, counterparty, "Таможня")
    usd = ledger.currency_id(cid, "USD")
    inv = Inventory(conn, actor="test")
    unit = inv.add_unit(cid, "шт", "Штука")
    a = inv.add_item(cid, "Товар A", unit, stock)
    b = inv.add_item(cid, "Товар B", unit, stock)
    main = inv.add_warehouse(cid, "Основной")
    duty = inv.add_landed_cost_type(cid, "Пошлина")
    fee = inv.add_landed_cost_type(cid, "Сбор")
    freight = inv.add_landed_cost_type(cid, "Доставка")

    def receipt(day: str, lines, **kw) -> int:
        return inv.post_receipt(cid, day, lines, suppliers, [kw.pop("partner", supplier)], **kw)

    imported = receipt(
        "2026-04-01",
        [
            ReceiptLine(a, main, "10", None, currency_amount="100"),
            ReceiptLine(b, main, "5", None, currency_amount="75"),
        ],
        currency_id=usd,
        currency_rate="1.7",
        invoice="AZ1",
        invoice_kind="customs",
    )
    receipt("2026-04-02", [ReceiptLine(a, main, "1", "20")], partner=local)
    receipt(
        "2026-05-05",
        [ReceiptLine(a, main, "1", None, currency_amount="10")],
        currency_id=usd,
        currency_rate="1.7",
        invoice="AZ2",
        invoice_kind="customs",
    )
    lines = [line.id for line in inv.load_document(cid, imported).lines]
    on_customs = {"account_id": customs_account, "subconto": [customs]}
    customs_doc = inv.create_landed_cost_draft(
        cid,
        "2026-04-01",
        [LandedCostTarget(line) for line in lines],
        [
            LandedCostCharge("29.75", cost_type_id=duty, **on_customs),
            LandedCostCharge("11.90", cost_type_id=fee, **on_customs),
        ],
        "value",
    )
    inv.post_document(cid, customs_doc)
    freight_doc = inv.create_landed_cost_draft(
        cid,
        "2026-04-03",
        [LandedCostTarget(line) for line in lines],
        [
            LandedCostCharge(
                None,
                suppliers,
                [supplier],
                cost_type_id=freight,
                currency_id=usd,
                currency_rate="1.7",
                currency_amount="30",
            )
        ],
        "quantity",
    )
    inv.post_document(cid, freight_doc)
    return conn, cid, (customs_doc, freight_doc)


def test_declaration_price_expenses_total_and_percent(declaration):
    conn, cid, documents = declaration
    kinds, rows = landed_cost_report(conn, cid, "2026-04-01", "2026-04-30")
    assert kinds == ["Пошлина", "Сбор", "Доставка"]
    assert len(rows) == 1  # the local receipt has no expenses, AZ2 is in May
    (d,) = rows
    assert (d.invoice, d.invoice_kind, d.supplier, d.currency, d.rate) == (
        "AZ1",
        "customs",
        "Supplier Ltd",
        "USD",
        1_700_000,
    )
    a, b = d.lines
    # by value 170 : 127.50 — duty 17.00 + 12.75, fee 6.80 + 5.10;
    # by quantity 10 : 5 — freight 34.00 + 17.00
    assert a.expenses == {"Пошлина": 1700, "Сбор": 680, "Доставка": 3400}
    assert b.expenses == {"Пошлина": 1275, "Сбор": 510, "Доставка": 1700}
    assert (a.cost, a.added, a.total, a.percent) == (17000, 5780, 22780, 3400)  # 34.00%
    # 34.85 / 127.50 = 27.33%
    assert (b.cost, b.added, b.total, b.percent) == (12750, 3485, 16235, 2733)
    assert (a.currency_amount, b.currency_amount, d.currency_amount) == (10000, 7500, 17500)
    # 92.65 / 297.50 = 31.14%
    assert (d.cost, d.added, d.total, d.percent) == (29750, 9265, 39015, 3114)
    assert d.expenses == {"Пошлина": 2975, "Сбор": 1190, "Доставка": 5100}
    assert [doc_id for doc_id, _n, _d in d.expense_documents] == list(documents)


def test_a_declaration_without_expenses_yet_is_shown_with_nothing_added(declaration):
    conn, cid, _documents = declaration
    kinds, rows = landed_cost_report(conn, cid, "2026-05-01", "2026-05-31")
    assert kinds == []
    (d,) = rows
    assert (d.invoice, d.cost, d.added, d.percent) == ("AZ2", 1700, 0, 0)


def test_an_unposted_expense_document_is_not_counted(declaration):
    conn, cid, (customs_doc, _freight) = declaration
    Inventory(conn, actor="test").unpost_document(cid, customs_doc)
    _kinds, (d,) = landed_cost_report(conn, cid, "2026-04-01", "2026-04-30")
    assert d.expenses == {"Доставка": 5100}


@pytest.fixture
def year_window(qtbot, tmp_path, monkeypatch):
    """The year demo open for viewing (D80): the report is read-only anyway."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    ws = Workspace(tmp_path / "data")
    path = ws.new_path("Year")
    conn = connect(path)
    create_year_demo(Ledger(conn))
    conn.close()
    theme.apply(QApplication.instance())
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.view_company(path)
    win.open_session.working_date = date(2026, 12, 31)
    win.show()
    yield win
    win.shutdown()


def test_the_warehouse_opens_the_report_and_a_row_opens_its_receipt(year_window, monkeypatch):
    win = year_window
    win.show_place(("inventory",))
    inventory = win.stack.currentWidget()
    shown: list[list[str]] = []

    class FirstChosen(QMenu):  # the real menu would wait for a click
        def exec(self, *_args):  # type: ignore[override]
            shown.append([a.text() for a in self.actions()])
            self.actions()[0].trigger()

    monkeypatch.setattr(widgets, "QMenu", FirstChosen)
    reports = next(
        b for b in inventory.findChildren(QPushButton) if b.text().startswith(tr("Отчёты"))
    )
    assert reports.isVisible()  # a report, so also when only viewing
    reports.click()
    assert shown == [[tr("Дополнительные расходы по декларациям")]]
    page = win.stack.currentWidget()
    assert isinstance(page, LandedCostReportPage)
    rows = page.model.rows
    headers = [r for r in rows if r.is_header]
    assert len(headers) == 7 and rows[-1].is_total
    assert rows[-1].added == sum(r.added for r in headers)
    titles = [c.title for c in page.model.columns]
    assert titles[:4] == [
        tr("Декларация / товар"),
        tr("Количество"),
        tr("В валюте"),
        tr("Стоимость"),
    ]
    assert "Sertifikatlaşdırma" in titles
    page.search.setText("shenzhen")
    assert sum(1 for r in page.model.rows if r.is_header) == 3
    page.drill(page.model.rows[1])  # a good of the first Chinese declaration
    opened = win.stack.currentWidget()
    assert isinstance(opened, InventoryDocumentPage)
    assert opened.doc is not None and opened.doc.invoice.startswith("AZ2604")
    assert "\t".join([tr("Декларация / товар"), tr("Количество")]) in page.text()


def test_the_supplier_is_the_counterparty_not_the_first_subconto(ledger: Ledger, conn):
    """A settlement account whose first subconto is not a counterparty (here 60 by
    contract, then counterparty): the declaration names the supplier, not the contract —
    the same rule as the purchase list (debt 12)."""
    cid = ledger.create_company("Импорт по договорам")
    item_kind = ledger.add_subconto_kind(cid, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    contract_kind = ledger.add_subconto_kind(cid, "other", "Договоры поставки")
    counterparty = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    stock = ledger.add_account(
        cid, "41", "Товары", subconto=[item_kind, warehouse_kind], account_class="asset"
    )
    suppliers = ledger.add_account(
        cid, "60", "Поставщики", subconto=[contract_kind, counterparty], account_class="liability"
    )
    contract = ledger.add_subconto_value(cid, contract_kind, "Договор №7")
    supplier = ledger.add_subconto_value(cid, counterparty, "Supplier Ltd")
    inv = Inventory(conn, actor="test")
    a = inv.add_item(cid, "Товар A", inv.add_unit(cid, "шт", "Штука"), stock)
    main = inv.add_warehouse(cid, "Основной")
    inv.post_receipt(
        cid,
        "2026-04-01",
        [ReceiptLine(a, main, "1", "20")],
        suppliers,
        [contract, supplier],
        invoice="AZ7",
        invoice_kind="customs",
    )
    _kinds, (d,) = landed_cost_report(conn, cid, "2026-04-01", "2026-04-30")
    assert (d.invoice, d.supplier) == ("AZ7", "Supplier Ltd")
