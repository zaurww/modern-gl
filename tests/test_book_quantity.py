"""Quantity in the books (D199): how many objects are on 12 «Azqiymətlilər», 01…

By hand (account 12, its directory of objects, each line its own element):
  10.01  Dt 12 [Kreslo] / Ct 60   290.00   2 pcs     (145.00 each)
  12.01  Dt 12 [Stul]   / Ct 60   175.00   5 pcs     ( 35.00 each)
  05.02  Dt 26 / Ct 12 [Stul]      70.00   2 pcs     (2 × 35.00)
ОСВ по субконто 12, February:
  Kreslo  opening 290.00 / 2 pcs,  no moves,           closing 290.00 / 2
  Stul    opening 175.00 / 5 pcs,  out 70.00 / 2 pcs,  closing 105.00 / 3
  total   opening 465.00 / 7,      out 70.00 / 2,      closing 395.00 / 5
Card of 12, January–February: quantity after each line 2, 7, 5.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from modern_gl.application.balance_fill import balance_lines
from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import ReceiptLine
from modern_gl.application.ledger import PostingInput
from modern_gl.application.quantities import counted_accounts
from modern_gl.desktop import theme
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.document_page.fill import balance_row
from modern_gl.desktop.postings import AMOUNT, QUANTITY
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.quantity import QUANTITY_FACTOR as Q
from modern_gl.reporting.reports import account_card, subconto_balance
from tests.helpers.qt import running_app
from tests.helpers.sales import make_shop


class Books:
    def __init__(self, ledger, cid: int) -> None:
        self.ledger, self.cid = ledger, cid
        low = ledger.add_subconto_kind(cid, None, "Azqiymətlilər", per_line=True)
        cost = ledger.add_subconto_kind(cid, "cost_item", "Xərc maddələri")
        party = ledger.add_subconto_kind(cid, "counterparty", "Kontragentlər")
        self.kreslo = ledger.add_subconto_value(cid, low, "Kreslo")
        self.stul = ledger.add_subconto_value(cid, low, "Stul")
        self.office = ledger.add_subconto_value(cid, cost, "Ofis")
        self.supplier = ledger.add_subconto_value(cid, party, "Mebel MMC")
        self.acc = {
            "12": ledger.add_account(cid, "12", "Azqiymətlilər", account_class="asset",
                                     subconto=[low]),
            "13": ledger.add_account(cid, "13", "Azqiymətlilərin köhnəlməsi",
                                     account_class="asset", contra=True, subconto=[low]),
            "26": ledger.add_account(cid, "26", "Ümumtəsərrüfat xərcləri",
                                     account_class="expense", subconto=[cost]),
            "60": ledger.add_account(cid, "60", "Malsatanlar", account_class="liability",
                                     two_sided=True, subconto=[party]),
        }  # fmt: skip

    def p(self, dt, ct, amount, dt_sc=(), ct_sc=(), quantity=None) -> PostingInput:
        return PostingInput(self.acc[dt], self.acc[ct], amount, dt_sc, ct_sc, quantity=quantity)

    def example(self) -> list[int]:
        post = self.ledger.post_new
        return [
            post(self.cid, "2026-01-10", [self.p("12", "60", "290", [self.kreslo],
                                                 [self.supplier], "2")]),
            post(self.cid, "2026-01-12", [self.p("12", "60", "175", [self.stul],
                                                 [self.supplier], "5")]),
            post(self.cid, "2026-02-05", [self.p("26", "12", "70", [self.office],
                                                 [self.stul], "2")]),
        ]  # fmt: skip


@pytest.fixture
def books(ledger) -> Books:
    return Books(ledger, ledger.create_company("Ofis MMC"))


def test_objects_are_counted_not_their_contra_nor_expenses(books):
    assert counted_accounts(books.ledger.conn, books.cid) == {books.acc["12"]}


def test_the_subconto_balance_counts_each_object(books):
    books.example()
    rows = subconto_balance(books.ledger.conn, books.cid, "12", "2026-02-01", "2026-02-28")
    got = {
        r.name: (r.closing_dt, r.quantity.opening, r.quantity.outgoing, r.quantity.closing)
        for r in rows
        if r.quantity is not None
    }
    assert got == {"Kreslo": (29000, 2 * Q, 0, 2 * Q), "Stul": (10500, 5 * Q, 2 * Q, 3 * Q)}


def test_the_card_counts_after_each_line(books):
    books.example()
    card = account_card(books.ledger.conn, books.cid, "12", "2026-01-01", "2026-02-28")
    assert card.quantity_opening == 0
    assert [ln.quantity_balance for ln in card.lines] == [2 * Q, 7 * Q, 5 * Q]
    assert [(ln.quantity_debit, ln.quantity_credit) for ln in card.lines] == [
        (2 * Q, 0),
        (5 * Q, 0),
        (0, 2 * Q),
    ]
    february = account_card(books.ledger.conn, books.cid, "12", "2026-02-01", "2026-02-28")
    assert (february.quantity_opening, february.quantity_closing) == (7 * Q, 5 * Q)
    expenses = account_card(books.ledger.conn, books.cid, "26", "2026-01-01", "2026-02-28")
    assert expenses.quantity_opening is None  # 26 keeps no quantity


def test_a_storno_takes_the_quantity_back(books):
    _, _, write_off = books.example()
    books.ledger.reverse(books.cid, write_off, "2026-02-20")
    rows = subconto_balance(books.ledger.conn, books.cid, "12", "2026-02-01", "2026-02-28")
    stul = next(r for r in rows if r.name == "Stul")
    assert stul.quantity is not None and stul.quantity.closing == 5 * Q
    assert stul.closing_dt == 17500


def test_a_quantity_only_on_a_counted_account_and_with_the_amounts_sign(books):
    led, cid = books.ledger, books.cid
    with pytest.raises(ValidationError, match="строка 1: количество — только у счёта объектов"):
        led.post_new(cid, "2026-01-10", [books.p("26", "60", "10", [books.office],
                                                 [books.supplier], "1")])  # fmt: skip
    with pytest.raises(ValidationError, match="у количества и суммы должен быть один знак"):
        led.post_new(cid, "2026-01-10", [books.p("12", "60", "10", [books.stul],
                                                 [books.supplier], "-1")])  # fmt: skip


def test_the_balance_filled_in_brings_its_quantity_and_average(books):
    books.example()
    lines = balance_lines(books.ledger.conn, books.cid, books.acc["12"], "2026-02-28")
    assert [(ln.subconto[0], ln.amount, ln.quantity) for ln in lines] == [
        (books.kreslo, 29000, 2 * Q),
        (books.stul, 10500, 3 * Q),
    ]
    row = balance_row(lines[1], books.acc["26"])
    assert (row.quantity, row.unit_cost) == (3 * Q, Fraction(10500, 3 * Q))


@pytest.fixture
def session(qtbot, books):
    theme.apply(running_app())
    conn = books.ledger.conn
    return Session(conn, books.ledger, books.cid, "Ofis MMC", Catalog(conn, books.cid))


def test_fewer_written_off_take_their_share_at_the_average(session, books, qtbot):
    """1 chair of the 3 left (105.00): 35.00; the rest stays — 2 chairs, 70.00."""
    books.example()
    page = DocumentPage(session)
    qtbot.addWidget(page)
    lines = balance_lines(books.ledger.conn, books.cid, books.acc["12"], "2026-02-28")
    page.add_balance([lines[1]], books.acc["26"])
    m = page.model
    assert not page.table.isColumnHidden(QUANTITY)
    assert m.data(m.index(0, QUANTITY)) == "3"
    m.setData(m.index(0, QUANTITY), m.parse(0, QUANTITY, "1"))
    assert m.rows[0].amount == 3500
    m.setData(m.index(0, AMOUNT), m.parse(0, AMOUNT, "36"))  # the amount stays editable
    assert m.rows[0].amount == 3600
    m.setData(m.index(0, 1), books.office)
    page.date.setDate(page.date.date().fromString("2026-02-28", "yyyy-MM-dd"))
    assert page.save(post=True), page.error.text()
    rows = subconto_balance(books.ledger.conn, books.cid, "12", "2026-02-01", "2026-02-28")
    stul = next(r for r in rows if r.name == "Stul")
    assert (stul.closing_dt, stul.quantity and stul.quantity.closing) == (6900, 2 * Q)


def test_the_quantity_column_hides_without_a_counted_line(session, books, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    assert page.table.isColumnHidden(QUANTITY)
    assert not page.model.applies(0, QUANTITY)


def test_a_purchase_line_on_12_posts_its_quantity(conn):
    """A purchase line without an item, to 12 with its object: 2 chairs, 290.00."""
    shop = make_shop(conn, "classic")
    led, cid = shop.ledger, shop.company_id
    low = led.add_subconto_kind(cid, None, "Azqiymətlilər", per_line=True)
    kreslo = led.add_subconto_value(cid, low, "Kreslo")
    account = led.add_account(cid, "12A", "Azqiymətlilər", account_class="asset", subconto=[low])
    receipt = shop.inventory.post_receipt(
        cid,
        "2026-03-05",
        [
            ReceiptLine(
                None,
                None,
                "2",
                "290",
                "Kreslo",
                expense_account_id=account,
                expense_subconto=[kreslo],
                vat_amount="0",
            )
        ],
        shop.acc["60"],
        shop.supplier,
    )
    gl = shop.inventory.load_document(cid, receipt).gl_document_id
    posting = conn.execute(
        "SELECT * FROM postings WHERE document_id = ? AND debit_account_id = ?", (gl, account)
    ).fetchone()
    assert (posting["amount"], posting["quantity"]) == (29000, 2 * Q)
