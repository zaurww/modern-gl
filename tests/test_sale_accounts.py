"""The accounts a sale of goods posts to, by the stock account of the goods
(D210): the warehouse's own table over the company's roles.

The shop of the classic chart: «Printer» is goods (41), «Kağız» is materials (10). The
company's sale accounts are 46 for all three roles — the revenue with the VAT, the VAT
charged from it, the cost of sales. Bought on 10.01.2026: 10 printers for 120.00 (12.00 a
piece) and 20 packs of paper for 100.00 (5.00 a pack). Every figure is worked out by hand
in the test's docstring."""

from __future__ import annotations

import pytest

from modern_gl.application.inventory import (
    SALE_ACCOUNT_ROLES,
    SALE_RETURN,
    STANDARD_VAT_RATE,
    ReceiptLine,
    ReturnLine,
    SaleLine,
)
from modern_gl.domain.accounts import COST_OF_SALES, SALES_REVENUE
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import sale_account_rows
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def add_paper(shop: Shop, conn) -> int:
    """«Kağız» on 10 «Материалы», 20 packs bought for 100.00 on 10.01; the printers too."""
    cid = shop.company_id
    unit = conn.execute(
        "SELECT unit_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    paper = shop.inventory.add_item(cid, "Kağız", unit, shop.acc["10"])
    shop.receipt("2026-01-10", "10", "120")
    shop.inventory.post_receipt(
        cid,
        "2026-01-10",
        [ReceiptLine(paper, shop.main, "20", "100")],
        shop.acc["60"],
        shop.supplier,
    )
    return paper


def materials_on_48(shop: Shop) -> None:
    """The sales of what is on 10 go to 48 «Реализация прочих активов», both sides."""
    stock = shop.acc["10"]
    shop.inventory.set_sale_accounts(
        shop.company_id,
        {(stock, SALES_REVENUE): shop.acc["48"], (stock, COST_OF_SALES): shop.acc["48"]},
    )


def january_sale(shop: Shop, paper: int) -> int:
    """20.01: 3 printers for 60.00 + 10.80, 4 packs for 30.00 + 5.40, a delivery for
    25.00 + 4.50."""
    return shop.sale(
        "2026-01-20",
        [
            SaleLine(shop.item, shop.main, "3", "60", "10.80"),
            SaleLine(paper, shop.main, "4", "30", "5.40"),
            SaleLine(None, None, None, "25", "4.50", "Çatdırılma"),
        ],
        invoice="MT2601002",
    )


def test_goods_and_materials_are_sold_on_their_own_accounts(shop, conn):
    """10 has 48 for the revenue and the cost of sales; 41 has none of its own, a service
    has no stock account — both take the company's 46:
      62 / 46    70.80  Printer      (60.00 + 10.80)
      62 / 48    35.40  Kağız        (30.00 + 5.40)
      62 / 46    29.50  Çatdırılma   (25.00 + 4.50)
      46 / 68.2  15.30  НДС          (10.80 + 4.50: charged from the revenue it is in)
      48 / 68.2   5.40  НДС          (the paper's)
      46 / 41    36.00  Printer      (3 × 12.00)
      48 / 10    20.00  Kağız        (4 × 5.00)
    48 nets 35.40 - 5.40 - 20.00 = 10.00 = 30.00 revenue - 20.00 cost."""
    paper = add_paper(shop, conn)
    materials_on_48(shop)

    sale = january_sale(shop, paper)

    assert shop.postings(sale) == [
        ("62", "46", 7_080, "Printer", "MT2601002"),
        ("62", "48", 3_540, "Kağız", "MT2601002"),
        ("62", "46", 2_950, "Çatdırılma", "MT2601002"),
        ("46", "68.2", 1_530, "НДС", "MT2601002"),
        ("48", "68.2", 540, "НДС", "MT2601002"),
        ("46", "41", 3_600, "Printer", None),
        ("48", "10", 2_000, "Kağız", None),
    ]


def test_a_stock_account_with_one_account_of_its_own_takes_the_other_from_the_company(shop, conn):
    """10 has only the revenue on 48; the cost of the paper sold goes to the company's 46:
    62 / 48  35.40,  48 / 68.2  5.40,  46 / 10  20.00."""
    paper = add_paper(shop, conn)
    shop.inventory.set_sale_accounts(
        shop.company_id, {(shop.acc["10"], SALES_REVENUE): shop.acc["48"]}
    )

    sale = shop.sale("2026-01-20", [SaleLine(paper, shop.main, "4", "30", "5.40")])

    assert [p[:3] for p in shop.postings(sale)] == [
        ("62", "48", 3_540),
        ("48", "68.2", 540),
        ("46", "10", 2_000),
    ]


def test_changing_the_table_posts_the_sales_again(shop, conn):
    """The paper was sold while 10 had no accounts of its own — all on 46. Then 10 gets
    48: the same GL document says what the first test says; cleared — it is back on 46."""
    cid = shop.company_id
    paper = add_paper(shop, conn)
    sale = january_sale(shop, paper)
    gl = shop.inventory.load_document(cid, sale).gl_document_id
    on_46 = shop.postings(sale)
    assert ("62", "46", 3_540, "Kağız", "MT2601002") in on_46
    assert ("46", "68.2", 2_070, "НДС", "MT2601002") in on_46  # 10.80 + 5.40 + 4.50

    materials_on_48(shop)

    assert shop.inventory.load_document(cid, sale).gl_document_id == gl
    assert shop.postings(sale) == [
        ("62", "46", 7_080, "Printer", "MT2601002"),
        ("62", "48", 3_540, "Kağız", "MT2601002"),
        ("62", "46", 2_950, "Çatdırılma", "MT2601002"),
        ("46", "68.2", 1_530, "НДС", "MT2601002"),
        ("48", "68.2", 540, "НДС", "MT2601002"),
        ("46", "41", 3_600, "Printer", None),
        ("48", "10", 2_000, "Kağız", None),
    ]

    stock = shop.acc["10"]
    shop.inventory.set_sale_accounts(
        cid, {(stock, SALES_REVENUE): None, (stock, COST_OF_SALES): None}
    )
    assert shop.postings(sale) == on_46
    assert sale_account_rows(conn, cid)[0].own == {}


def test_the_closed_period_keeps_its_postings(shop, conn):
    """January is closed with the paper sold on 46. In February 2 packs more are sold for
    16.00 + 2.88, then 10 gets 48: January stays as it was, February moves —
      62 / 48  18.88,  48 / 68.2  2.88,  48 / 10  10.00  (2 × 5.00)."""
    cid = shop.company_id
    paper = add_paper(shop, conn)
    january = january_sale(shop, paper)
    closed = shop.postings(january)
    shop.ledger.set_closed_through(cid, "2026-01-31")
    february = shop.sale("2026-02-05", [SaleLine(paper, shop.main, "2", "16", "2.88")])
    assert [p[:3] for p in shop.postings(february)] == [
        ("62", "46", 1_888),
        ("46", "68.2", 288),
        ("46", "10", 1_000),
    ]

    materials_on_48(shop)

    assert shop.postings(january) == closed
    assert [p[:3] for p in shop.postings(february)] == [
        ("62", "48", 1_888),
        ("48", "68.2", 288),
        ("48", "10", 1_000),
    ]


def test_a_return_of_a_sale_goes_back_through_the_same_accounts(shop, conn):
    """4 packs sold on 20.01, 1 comes back on 25.01 for 7.50 + 1.35 (no sale named: the
    average cost of the 16 packs left, 80.00 / 16 = 5.00):
      48 / 62     8.85  the revenue back, with its VAT
      10 / 48     5.00  the pack back at its cost
      68.2 / 48   1.35  the VAT back to the account it was charged from."""
    cid = shop.company_id
    paper = add_paper(shop, conn)
    materials_on_48(shop)
    january_sale(shop, paper)

    back = shop.inventory.post_return(
        cid,
        "2026-01-25",
        SALE_RETURN,
        [ReturnLine(paper, shop.main, "1", "7.50", "1.35")],
        shop.acc["62"],
        [shop.customer, shop.contract],
        vat_rate=STANDARD_VAT_RATE,
        invoice="MT2601003",
    )

    assert [p[:3] for p in shop.postings(back)] == [
        ("48", "62", 885),
        ("10", "48", 500),
        ("68.2", "48", 135),
    ]


def test_the_vat_charged_from_an_account_of_its_own_stays_there(conn):
    """The chart of 1C 7.7 charges the VAT from 90.3, not from the revenue: Dt 62.1 /
    Kt 90.1 with the VAT, Dt 90.3 / Kt 68.2. Goods on 41.1 get a revenue account of their
    own (91.3 here: it asks for no directory): the VAT is still charged from 90.3. 10
    printers for 120.00, 3 sold for 60.00 + 10.80:
      62.1 / 91.3  70.80,  90.3 / 68.2  10.80,  90.2 / 41.1  36.00."""
    shop = make_shop(conn, "1c77")
    shop.acc["62"] = shop.acc["62.1"]
    shop.receipt("2026-01-10", "10", "120")
    shop.inventory.set_sale_accounts(
        shop.company_id, {(shop.acc["41.1"], SALES_REVENUE): shop.acc["91.3"]}
    )

    sale = shop.sale("2026-01-20", [SaleLine(shop.item, shop.main, "3", "60", "10.80")])

    assert [p[:3] for p in shop.postings(sale)] == [
        ("62.1", "91.3", 7_080),
        ("90.3", "68.2", 1_080),
        ("90.2", "41.1", 3_600),
    ]


def test_what_the_table_refuses(shop, conn):
    cid = shop.company_id
    stock, sales = shop.acc["10"], shop.acc["48"]
    set_accounts = shop.inventory.set_sale_accounts
    with pytest.raises(ValidationError, match="счёт запасов"):  # goods are no revenue
        set_accounts(cid, {(stock, SALES_REVENUE): shop.acc["41"]})
    with pytest.raises(ValidationError, match="субконто Товар и Склад"):  # 44 holds no goods
        set_accounts(cid, {(shop.acc["44"], SALES_REVENUE): sales})
    with pytest.raises(ValidationError, match="активный счёт проводок"):  # 68 is a group
        set_accounts(cid, {(stock, SALES_REVENUE): shop.acc["68"]})
    with pytest.raises(ValidationError, match="неизвестная роль"):
        set_accounts(cid, {(stock, "output_vat"): sales})
    assert conn.execute("SELECT COUNT(*) FROM inventory_sale_accounts").fetchone()[0] == 0


def test_a_sale_that_does_not_post_on_the_new_account_keeps_the_table(shop, conn):
    """47 asks for a fixed asset no sale line has: the sale of the paper cannot be posted
    there, so nothing changes — neither the table nor the postings."""
    cid = shop.company_id
    paper = add_paper(shop, conn)
    sale = january_sale(shop, paper)
    before = shop.postings(sale)

    with pytest.raises(ValidationError, match="после изменения не проводится"):
        shop.inventory.set_sale_accounts(cid, {(shop.acc["10"], SALES_REVENUE): shop.acc["47"]})

    assert shop.postings(sale) == before
    assert conn.execute("SELECT COUNT(*) FROM inventory_sale_accounts").fetchone()[0] == 0


def test_the_table_is_written_to_the_action_log_once(shop, conn):
    """The same accounts saved again change nothing and leave no trace."""
    cid = shop.company_id

    def events() -> list[tuple[str, int]]:
        return [
            (row["action"], row["entity_id"])
            for row in conn.execute(
                "SELECT action, entity_id FROM audit_events "
                "WHERE company_id = ? AND entity = 'inventory_sale_account' ORDER BY id",
                (cid,),
            )
        ]

    materials_on_48(shop)
    materials_on_48(shop)
    assert events() == [("set", shop.acc["10"]), ("set", shop.acc["10"])]  # two roles, once
    shop.inventory.set_sale_accounts(cid, {(shop.acc["10"], SALES_REVENUE): None})
    assert events()[-1] == ("clear", shop.acc["10"])


def test_the_settings_show_the_stock_accounts_in_use(shop, conn):
    """Only «Printer» on 41 yet: one row. «Kağız» on 10 adds its account; 40 «Готовая
    продукция» has no goods, but with accounts of its own it is shown too."""
    cid = shop.company_id

    def shown() -> list[str]:
        return [row.stock_account.label.split()[0] for row in sale_account_rows(conn, cid)]

    assert shown() == ["41"]
    add_paper(shop, conn)
    assert shown() == ["10", "41"]
    shop.inventory.set_sale_accounts(cid, {(shop.acc["40"], COST_OF_SALES): shop.acc["48"]})
    rows = sale_account_rows(conn, cid)
    assert shown() == ["10", "40", "41"]
    assert rows[1].own == {COST_OF_SALES: shop.acc["48"]}


def test_a_company_without_goods_is_shown_every_stock_account(conn, ledger):
    from modern_gl.application.chart_csv import apply_chart_template

    cid = ledger.create_company("classic")
    apply_chart_template(ledger, cid, "classic", "ru")
    labels = [row.stock_account.label.split()[0] for row in sale_account_rows(conn, cid)]
    assert labels == ["10", "40", "41"]


def test_a_sale_line_is_asked_for_the_subconto_of_an_own_account(shop, conn):
    """47 has the fixed asset directory: once it is the revenue of a stock account, the
    sale form asks its lines for a fixed asset too (D61)."""
    cid = shop.company_id
    fixed_asset = shop.ledger.subconto_kind_id(cid, "fixed_asset")
    assert fixed_asset not in shop.inventory.sale_kinds(cid)
    shop.inventory.set_sale_accounts(cid, {(shop.acc["40"], SALES_REVENUE): shop.acc["47"]})
    assert fixed_asset in shop.inventory.sale_kinds(cid)


# ---- the settings window ----------------------------------------------------------------


def settings_dialog(shop: Shop, conn, qtbot):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.inventory_page import InventorySettingsDialog
    from modern_gl.desktop.session import Session

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    dialog = InventorySettingsDialog(session)
    qtbot.addWidget(dialog)
    return dialog


def test_the_settings_window_saves_the_table(shop, conn, qtbot):
    """4 packs sold for 30.00 + 5.40 on the company's 46. The window shows a row for 10 and
    for 41, every cell «— общий —»; 48 picked for both cells of 10 and saved — the sale is
    on 48: 62 / 48 35.40, 48 / 68.2 5.40, 48 / 10 20.00. Opened again, it shows 48."""
    paper = add_paper(shop, conn)
    sale = shop.sale("2026-01-20", [SaleLine(paper, shop.main, "4", "30", "5.40")])
    dialog = settings_dialog(shop, conn, qtbot)
    assert set(dialog.sale_accounts) == {
        (shop.acc[code], role) for code in ("10", "41") for role in SALE_ACCOUNT_ROLES
    }
    assert all(combo.currentData() is None for combo in dialog.sale_accounts.values())

    for role in SALE_ACCOUNT_ROLES:
        combo = dialog.sale_accounts[shop.acc["10"], role]
        combo.setCurrentIndex(combo.findData(shop.acc["48"]))
    dialog._save()

    assert dialog.result() == dialog.DialogCode.Accepted
    assert [p[:3] for p in shop.postings(sale)] == [
        ("62", "48", 3_540),
        ("48", "68.2", 540),
        ("48", "10", 2_000),
    ]
    again = settings_dialog(shop, conn, qtbot)
    assert again.sale_accounts[shop.acc["10"], SALES_REVENUE].currentData() == shop.acc["48"]
    assert again.sale_accounts[shop.acc["41"], SALES_REVENUE].currentData() is None


def test_the_settings_window_stays_open_when_a_sale_does_not_post(shop, conn, qtbot):
    """47 asks for a fixed asset: the window says why and keeps the choice to correct."""
    paper = add_paper(shop, conn)
    sale = shop.sale("2026-01-20", [SaleLine(paper, shop.main, "4", "30", "5.40")])
    before = shop.postings(sale)
    dialog = settings_dialog(shop, conn, qtbot)
    combo = dialog.sale_accounts[shop.acc["10"], SALES_REVENUE]
    combo.setCurrentIndex(combo.findData(shop.acc["47"]))

    dialog._save()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert shop.postings(sale) == before
