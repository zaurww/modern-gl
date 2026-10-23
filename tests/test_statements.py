"""Финансовая отчётность (D99): the balance sheet and the profit and loss by account type.

A small company, worked out by hand (amounts in manat):
   1 15.01  Dt 51       Kt 80        10 000   capital paid in
   2 20.01  Dt 01       Kt 60 [A]     3 000   equipment from supplier A
   3 25.01  Dt 60 [B]   Kt 51           500   an advance to supplier B
   4 01.02  Dt 41       Kt 60 [A]     2 000   goods from A
   5 10.02  Dt 62 [C]   Kt 90.1       4 000   a sale to C
   6 10.02  Dt 90.2     Kt 41         1 500   its cost
   7 12.02  Dt 51       Kt 62 [C]     1 000   C pays a part
   8 15.02  Dt 26       Kt 02           100   depreciation
   9 20.02  Dt 26       Kt 76           300   an expense owed (76 has no type)
  10 25.02  Dt 50       Kt 91.1          50   other income in cash
  11 28.02  Dt 90.1     Kt 99         4 000   sales closed into the result
  12 28.02  Dt 99       Kt 90.2       1 500   cost closed into the result

Balance on 28.02: current assets — cash 50, bank 10 500, receivable 3 000, advance paid
500 (B's debit balance on 60), inventory 500 = 14 550; long-term — fixed assets 3 000 −
100 = 2 900; assets 17 450. Current liabilities — payable 5 000, untyped 300 = 5 300.
Equity — capital 10 000, result (99) 2 500, profit not closed: 26 (−400) + 91.1 (+50) =
−350; 12 150. 5 300 + 12 150 = 17 450.

Profit and loss of February: sales 4 000, cost −1 500 (the closing at 28.02 is not
income), gross 2 500; operating −400 → 2 100; other income 50 → 2 150 before tax; net
2 150. January has none."""

from __future__ import annotations

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.reporting.profit_loss import profit_and_loss
from modern_gl.reporting.statements import balance_sheet


@pytest.fixture
def books(ledger: Ledger):
    cid = ledger.create_company("Тест")
    cp = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    a, b, c = (ledger.add_subconto_value(cid, cp, n) for n in ("A", "B", "C"))
    acc = {}
    for code, kind, extra in [
        ("50", "cash", {}),
        ("51", "bank", {}),
        ("01", "fixed_asset", {}),
        ("02", "fixed_asset", {"contra": True}),
        ("41", "inventory", {}),
        ("60", "payable", {"subconto": [cp], "two_sided": True}),
        ("62", "receivable", {"subconto": [cp], "two_sided": True}),
        ("80", "share_capital", {}),
        ("90.1", "sales", {}),
        ("90.2", "cost_of_sales", {}),
        ("26", "operating_expense", {}),
        ("91.1", "other_income", {}),
        ("99", "profit_loss", {}),
    ]:
        acc[code] = ledger.add_account(cid, code, code, account_type=kind, **extra)
    acc["76"] = ledger.add_account(cid, "76", "76", account_class="liability")

    def p(dt, ct, amount, dt_sc=(), ct_sc=()):
        return PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)

    for day, posting in [
        ("2026-01-15", p("51", "80", "10000")),
        ("2026-01-20", p("01", "60", "3000", ct_sc=[a])),
        ("2026-01-25", p("60", "51", "500", dt_sc=[b])),
        ("2026-02-01", p("41", "60", "2000", ct_sc=[a])),
        ("2026-02-10", p("62", "90.1", "4000", dt_sc=[c])),
        ("2026-02-10", p("90.2", "41", "1500")),
        ("2026-02-12", p("51", "62", "1000", ct_sc=[c])),
        ("2026-02-15", p("26", "02", "100")),
        ("2026-02-20", p("26", "76", "300")),
        ("2026-02-25", p("50", "91.1", "50")),
        ("2026-02-28", p("90.1", "99", "4000")),
        ("2026-02-28", p("99", "90.2", "1500")),
    ]:
        ledger.post_new(cid, day, [posting])
    return ledger.conn, cid


def shown(statement) -> list[tuple[str, int | None]]:
    return [(ln.title, ln.amount if ln.kind != "heading" else None) for ln in statement.lines]


def test_balance_sheet_by_type(books):
    conn, cid = books
    sheet = balance_sheet(conn, cid, "2026-02-28")
    assert shown(sheet) == [
        ("Активы", None),
        ("Оборотные активы", None),
        ("Касса", 5_000),
        ("Банковские счета", 1_050_000),
        ("Покупатели и заказчики", 300_000),
        ("Авансы выданные", 50_000),
        ("Запасы", 50_000),
        ("Оборотные активы", 1_455_000),
        ("Долгосрочные активы", None),
        ("Основные средства", 290_000),
        ("Долгосрочные активы", 290_000),
        ("Итого активы", 1_745_000),
        ("Обязательства и капитал", None),
        ("Краткосрочные обязательства", None),
        ("Поставщики и подрядчики", 500_000),
        ("Счета без типа", 30_000),
        ("Краткосрочные обязательства", 530_000),
        ("Капитал", None),
        ("Уставный капитал", 1_000_000),
        ("Финансовый результат", 250_000),
        ("Прибыль (убыток) текущего периода", -35_000),
        ("Капитал", 1_215_000),
        ("Итого обязательства и капитал", 1_745_000),
    ]
    assert sheet.unbalanced == 0


def test_profit_and_loss_leaves_out_the_closing(books):
    conn, cid = books
    february = profit_and_loss(conn, cid, "2026-02-01", "2026-02-28")
    assert shown(february) == [
        ("Выручка", 400_000),
        ("Себестоимость продаж", -150_000),
        ("Валовая прибыль", 250_000),
        ("Операционные расходы", -40_000),
        ("Операционная прибыль", 210_000),
        ("Прочие доходы", 5_000),
        ("Прибыль до налогообложения", 215_000),
        ("Чистая прибыль (убыток)", 215_000),
    ]
    january = profit_and_loss(conn, cid, "2026-01-01", "2026-01-31")
    assert january.lines[-1].amount == 0


def test_the_ifrs_book_adds_its_adjustments(books, ledger):
    conn, cid = books
    ledger.set_parallel_books(cid, True)
    inventory, expense = (
        conn.execute(
            "SELECT id FROM accounts WHERE company_id = ? AND code = ?", (cid, c)
        ).fetchone()[0]
        for c in ("41", "26")
    )
    # IFRS writes the goods down by 200
    ledger.post_new(
        cid, "2026-02-28", [PostingInput(expense, inventory, "200")], "МСФО", "ifrs_adj"
    )
    common = balance_sheet(conn, cid, "2026-02-28")
    ifrs = balance_sheet(conn, cid, "2026-02-28", ("common", "ifrs_adj"))
    assert dict(shown(common))["Запасы"] == 50_000
    assert dict(shown(ifrs))["Запасы"] == 30_000
    assert dict(shown(ifrs))["Прибыль (убыток) текущего периода"] == -55_000
    assert ifrs.unbalanced == 0
    pl = profit_and_loss(conn, cid, "2026-02-01", "2026-02-28", ("common", "ifrs_adj"))
    assert pl.lines[-1].amount == 195_000


def test_every_title_of_the_statements_has_azerbaijani_translation(books):
    from modern_gl.i18n_az import AZ

    conn, cid = books
    titles = {ln.title for ln in balance_sheet(conn, cid, "2026-02-28").lines}
    titles |= {ln.title for ln in profit_and_loss(conn, cid, "2026-01-01", "2026-12-31").lines}
    titles |= {"Доходы без типа", "Расходы без типа"}
    assert sorted(t for t in titles if t not in AZ) == []


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from datetime import date

    from PySide6.QtWidgets import QApplication, QMessageBox

    from modern_gl.demo_data import create_demo_company
    from modern_gl.desktop import theme
    from modern_gl.desktop.main_window import MainWindow
    from modern_gl.infrastructure.db import connect
    from modern_gl.infrastructure.workspace import Workspace

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    conn = connect(tmp_path / "ДЕМО ООО.gl")
    create_demo_company(Ledger(conn))
    conn.close()
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def test_the_page_switches_between_the_balance_and_the_profit(window, qtbot):
    from modern_gl.desktop.reports_page import StatementsPage

    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    qtbot.waitUntil(lambda: bool(page.model.rows))
    assert page.model.rows[0].title == "Активы"
    assert page.footer.text().startswith("Актив и пассив сходятся")
    page.profit_button.click()
    qtbot.waitUntil(lambda: page.model.rows[0].title != "Активы")
    assert page.model.rows[-1].title == "Чистая прибыль (убыток)"
    window.set_stock_only(True)  # the books are not shown: no statements either
    assert window.sidebar.item_for(("statements",)) is None
