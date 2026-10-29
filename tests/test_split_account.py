"""«Разделить счёт» (D-new-split-account): an account with postings becomes a group, its
history going on as the first subaccount. Hand-calculated, March 2026:

01.03  Dt 51 / Kt 75 [Учредитель]  1 000.00
05.03  Dt 51 / Kt 75 [Учредитель]    500.00
75 split: 75 «Расчёты с учредителями» — a group; the old account is 75.1 «Вклады».
10.03  Dt 75.2 [Учредитель] / Kt 51  200.00   (75.2 «Выплата доходов», added after)

Closing: 75.1 Kt 1 500.00; 75.2 Dt 200.00; the group 75: Kt 1 500.00 and Dt 200.00
(its rows summed); 51 Dt 1 300.00. Not a posting changed: the two went on by the id.
"""

from __future__ import annotations

import pytest

from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import trial_balance


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Учредитель")
    cp = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    owner = ledger.add_subconto_value(cid, cp, "Учредитель")
    bank = ledger.add_account(cid, "51", "Расчётный счёт", account_class="asset")
    old = ledger.add_account(
        cid,
        "75",
        "Расчёты с учредителями",
        subconto=[cp],
        account_class="liability",
        two_sided=True,
    )
    for day, amount in (("2026-03-01", "1000"), ("2026-03-05", "500")):
        ledger.post_new(cid, day, [PostingInput(bank, old, amount, [], [owner])])
    return {"cid": cid, "cp": cp, "owner": owner, "bank": bank, "old": old}


def account(ledger, cid, account_id):
    return ledger.conn.execute(
        "SELECT * FROM accounts WHERE company_id = ? AND id = ?", (cid, account_id)
    ).fetchone()


def test_the_history_goes_on_as_the_first_subaccount(ledger, firm):
    cid, old = firm["cid"], firm["old"]
    ledger.set_account_role(cid, BANK_FEE, old)  # a setting on the account stays with it
    before = ledger.conn.execute("SELECT * FROM postings ORDER BY id").fetchall()
    group = ledger.split_account(cid, "75", "75.1", "Вклады")
    assert [tuple(r) for r in ledger.conn.execute("SELECT * FROM postings ORDER BY id")] == [
        tuple(r) for r in before
    ]
    g, sub = account(ledger, cid, group), account(ledger, cid, old)
    assert (g["code"], g["name"], g["is_group"], g["parent_id"]) == (
        "75",
        "Расчёты с учредителями",
        1,
        None,
    )
    assert (g["account_class"], g["two_sided"]) == ("liability", 1)
    assert (sub["code"], sub["name"], sub["is_group"], sub["parent_id"]) == (
        "75.1",
        "Вклады",
        0,
        group,
    )
    assert sub["sc1_kind_id"] == firm["cp"]
    assert ledger.account_role(cid, BANK_FEE) == old
    second = ledger.add_account(cid, "75.2", "Выплата доходов", parent="75", subconto=[firm["cp"]])
    ledger.post_new(cid, "2026-03-10", [PostingInput(second, firm["bank"], "200", [firm["owner"]])])
    rows = {r.code: r for r in trial_balance(ledger.conn, cid, "2026-03-01", "2026-03-31").rows}
    assert (rows["75.1"].closing_dt, rows["75.1"].closing_ct) == (0, 150000)
    assert (rows["75.2"].closing_dt, rows["75.2"].closing_ct) == (20000, 0)
    assert (rows["75"].closing_dt, rows["75"].closing_ct) == (20000, 150000)
    assert rows["75"].is_group and rows["51"].closing_dt == 130000
    event = ledger.conn.execute(
        "SELECT action FROM audit_events WHERE entity = 'account' AND entity_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (group,),
    ).fetchone()
    assert event["action"] == "split"


def test_a_subaccount_of_a_group_splits_in_place(ledger, firm):
    """60 (a group) › 60.1 with postings: 60.1 becomes a group under 60, the history
    goes on as 60.1.1."""
    cid = firm["cid"]
    parent = ledger.add_account(cid, "60", "Поставщики", is_group=True)
    sub = ledger.add_account(cid, "60.1", "Расчёты", parent=parent, subconto=[firm["cp"]])
    ledger.post_new(cid, "2026-03-02", [PostingInput(firm["bank"], sub, "10", [], [firm["owner"]])])
    group = ledger.split_account(cid, sub, "60.1.1", "Расчёты в манатах")
    assert account(ledger, cid, group)["parent_id"] == parent
    assert account(ledger, cid, sub)["parent_id"] == group


def test_what_is_not_split(ledger, firm):
    cid = firm["cid"]
    ledger.add_account(cid, "60", "Поставщики", is_group=True)
    with pytest.raises(ValidationError, match="уже группа"):
        ledger.split_account(cid, "60", "60.1", "x")
    with pytest.raises(ValidationError, match="уже есть"):
        ledger.split_account(cid, "75", "51", "x")
    with pytest.raises(ValidationError, match="название"):
        ledger.split_account(cid, "75", "75.1", " ")
    with pytest.raises(ValidationError, match="код"):
        ledger.split_account(cid, "75", "75", "x")
    # nothing changed by the refusals
    assert account(ledger, cid, firm["old"])["code"] == "75"
    assert (
        ledger.conn.execute(
            "SELECT count(*) FROM accounts WHERE company_id = ? AND code = '75'", (cid,)
        ).fetchone()[0]
        == 1
    )


@pytest.fixture
def window(desktop_window):
    return desktop_window


def test_add_subaccount_to_an_account_with_postings(window, monkeypatch):
    """«Добавить субсчёт…» on a used account of the demo: the window names the first
    subaccount (76.1 offered), the account becomes a group, the form of the next one opens
    under it with 76.2 — the account's postings stay where they were."""
    from modern_gl.desktop.account_dialog import AccountDialog
    from modern_gl.desktop.split_account_dialog import SplitAccountDialog

    window.show_place(("chart",))
    chart = window.stack.currentWidget()
    s = window.session
    used = next(
        a
        for a in s.catalog.accounts.values()
        if not a.is_group and s.catalog.has_postings(a.id) and a.code and "." not in a.code
    )
    shown: dict[str, object] = {}

    def split(dialog):
        shown["code"] = dialog.code.text()
        dialog.name.setText("Первый")
        dialog.save()
        return dialog.result()

    def next_one(dialog):
        shown["next"] = dialog.code.text()
        shown["parent"] = dialog.parent_box.currentData()
        return 0

    monkeypatch.setattr(SplitAccountDialog, "exec", split)
    monkeypatch.setattr(AccountDialog, "exec", next_one)
    chart.add_subaccount(used)
    group = s.catalog.by_code[used.code]
    assert shown["code"] == f"{used.code}.1" and group.is_group
    assert shown == {"code": f"{used.code}.1", "next": f"{used.code}.2", "parent": group.id}
    first = s.catalog.accounts[used.id]
    assert (first.code, first.name, first.parent_id) == (f"{used.code}.1", "Первый", group.id)
    assert s.catalog.has_postings(used.id)
