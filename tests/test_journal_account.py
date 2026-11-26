"""«Сменить счёт у отмеченных» in the journal (D225): expenses entered on
20 go to 26 in the marked documents — the journal's own and the purchases — in one step."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QDialog

from modern_gl.application.account_change import AccountChange, accounts_used, change_account
from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import ReceiptLine
from modern_gl.application.ledger import PostingInput
from modern_gl.desktop.change_account_dialog import AccountChangeDialog
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def turnover(conn, account_id: int) -> tuple[int, int]:
    """(debit, credit) of the account in posted documents, kopecks."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN p.debit_account_id = :a THEN p.amount END), 0), "
        "COALESCE(SUM(CASE WHEN p.credit_account_id = :a THEN p.amount END), 0) "
        "FROM postings p JOIN documents d ON d.id = p.document_id WHERE d.status = 'posted'",
        {"a": account_id},
    ).fetchone()
    return row[0], row[1]


def books(shop: Shop, conn) -> tuple[int, int, int, int]:
    """The rent 1 744.19 typed in the journal on 20, a service 300.00 + ƏDV 54.00 bought on
    20, and goods for 100.00 on 41: (the rent's GL document, the service's, the goods',
    the cost item «İcarə»)."""
    cid = shop.company_id
    rent = shop.ledger.add_subconto_value(
        cid, shop.ledger.subconto_kind_id(cid, "cost_item"), "İcarə"
    )
    operation = shop.ledger.post_new(
        cid,
        "2026-03-31",
        [PostingInput(shop.acc["20"], shop.acc["60"], "1744.19", (rent,), shop.supplier)],
        "Aylıq icarə",
    )
    service = shop.inventory.post_receipt(
        cid,
        "2026-03-05",
        [
            ReceiptLine(
                None,
                None,
                None,
                "300",
                "Xidmət haqqı",
                expense_account_id=shop.acc["20"],
                expense_subconto=[rent],
                vat_amount="54",
            )
        ],
        shop.acc["60"],
        shop.supplier,
    )
    goods = shop.receipt("2026-03-01", "1", "100")

    def gl(document_id: int) -> int:
        return conn.execute(
            "SELECT gl_document_id FROM inventory_documents WHERE id = ?", (document_id,)
        ).fetchone()[0]

    return operation, gl(service), gl(goods), rent


def test_marked_documents_go_from_20_to_26(shop, conn):
    """1 744.19 + 300.00 = 2 044.19 leaves 20 for 26 with its cost item; the ƏDV 54.00 and
    the goods 100.00 stay where they were; what is owed on 60 is the same 2 198.19."""
    operation, service, goods, rent = books(shop, conn)
    cid, a20, a26 = shop.company_id, shop.acc["20"], shop.acc["26"]
    marked = [operation, service, goods]
    assert accounts_used(conn, cid, marked)[0] == shop.acc["60"]
    assert turnover(conn, a20) == (204_419, 0)
    numbers = conn.execute("SELECT id, number, status FROM documents ORDER BY id").fetchall()

    done = change_account(shop.ledger, cid, marked, a20, a26)

    assert done == AccountChange(changed=2, left=1)
    assert turnover(conn, a20) == (0, 0)
    assert turnover(conn, a26) == (204_419, 0)
    assert turnover(conn, shop.acc["41"]) == (10_000, 0)
    assert turnover(conn, shop.acc["60"]) == (0, 219_819)
    after = conn.execute("SELECT id, number, status FROM documents ORDER BY id").fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in numbers]
    kept = conn.execute(
        "SELECT DISTINCT dt_sc1 FROM postings WHERE debit_account_id = ?", (a26,)
    ).fetchall()
    assert [r[0] for r in kept] == [rent]
    line = conn.execute(
        "SELECT cost_account_id, cost_sc1 FROM inventory_lines WHERE item_id IS NULL"
    ).fetchone()
    assert tuple(line) == (a26, rent)  # the purchase itself says 26 now, not only its postings
    audit = conn.execute(
        "SELECT action FROM audit_events WHERE entity = 'document' AND entity_id = ? "
        "ORDER BY id DESC",
        (operation,),
    ).fetchone()
    assert audit["action"] in ("post", "repost")


def test_all_or_none(shop, conn):
    """A storno among the marked refuses the change: the rent before it stays on 20."""
    operation, _service, _goods, _rent = books(shop, conn)
    cid, a20 = shop.company_id, shop.acc["20"]
    storno = shop.ledger.reverse(cid, operation, "2026-03-31")
    with pytest.raises(ValidationError):
        change_account(shop.ledger, cid, [operation, storno], a20, shop.acc["26"])
    assert turnover(conn, a20) == (30_000, 0)  # 1 744.19 − 1 744.19 + the service 300.00
    assert turnover(conn, shop.acc["26"]) == (0, 0)


def test_a_draft_stays_a_draft(shop, conn):
    cid, a20, a26 = shop.company_id, shop.acc["20"], shop.acc["26"]
    draft = shop.ledger.create_draft(
        cid, "2026-03-10", [PostingInput(a20, shop.acc["60"], "10", (), shop.supplier)]
    )
    assert change_account(shop.ledger, cid, [draft], a20, a26) == AccountChange(1, 0)
    row = conn.execute(
        "SELECT d.status, p.debit_account_id FROM documents d JOIN postings p "
        "ON p.document_id = d.id WHERE d.id = ?",
        (draft,),
    ).fetchone()
    assert tuple(row) == ("draft", a26)


def test_the_journal_changes_the_marked_rows(shop, conn, qtbot, monkeypatch):
    operation, service, _goods, _rent = books(shop, conn)
    cid, a20, a26 = shop.company_id, shop.acc["20"], shop.acc["26"]
    said: list[str] = []
    session = Session(conn, shop.ledger, cid, "Firma", Catalog(conn, cid), notify=said.append)
    page = JournalPage(session)
    qtbot.addWidget(page)
    page.show()
    seen: dict[str, object] = {}

    def choose(dialog: AccountChangeDialog) -> QDialog.DialogCode:
        seen["old"] = [dialog.old.itemData(i) for i in range(dialog.old.count())]
        dialog.old.setCurrentIndex(dialog.old.findData(a20))
        dialog.new.setCurrentIndex(dialog.new.findData(a26))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AccountChangeDialog, "exec", choose)

    page.change_account_selected()  # one row is the cursor's, nothing is marked
    assert turnover(conn, a26) == (0, 0) and "Отметьте" in said[-1]

    rows = [i for i, d in enumerate(page.model.docs) if d.id in (operation, service)]
    selection = page.table.selectionModel()
    selection.clearSelection()
    for row in rows:
        selection.select(
            page.model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    page.change_account_selected()
    assert a20 in seen["old"]  # type: ignore[operator]
    assert turnover(conn, a20) == (0, 0)
    assert turnover(conn, a26) == (204_419, 0)
    assert said[-1] == "Счёт сменён в документах: 2"
