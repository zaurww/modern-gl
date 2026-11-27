"""Two elements that are one counterparty become one (D-new-merge-counterparties).

The bank firm (tests/helpers/bank.py), March 2026, hand-calculated. ALFA MMC has the VÖEN
1234567890 and «Договор 1»; the purchase of 02.03: Dt 26 / Ct 60.1 [ALFA, Договор 1]
1 180.00, MT001. A second element, «Alfa» (no VÖEN), was entered by mistake:

  05.03  bank, posted:  Dt 60.1 [Alfa] / Ct 51 [Kapital AZN]   1 000.00
  06.03  journal draft: Dt 26 [Аренда] / Ct 60.1 [Alfa]           50.00
  «Договор А» belongs to Alfa.

60.1 before: ALFA Ct 1 180.00, Alfa Dt 1 000.00 — the trial balance shows 60 two-sided,
Dt 1 000.00 and Ct 1 180.00. Merged into ALFA: ALFA Ct 180.00, 60 is Ct 180.00; the net
of every account as it was."""

from __future__ import annotations

import pytest

from modern_gl.application.bank import (
    OUT,
    SUPPLIER,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.ledger import PostingInput
from modern_gl.application.rebuild import module_rebuilders
from modern_gl.domain.errors import PeriodClosedError, ValidationError
from modern_gl.reporting.reports import trial_balance


@pytest.fixture
def firm(ledger, bank_firm):
    f = bank_firm
    cid, acc, v = f["cid"], f["acc"], f["v"]
    kind = ledger.subconto_kind_id(cid, "counterparty")
    twin = ledger.add_subconto_value(cid, kind, "Alfa")
    contract = ledger.add_subconto_value(
        cid, ledger.subconto_kind_id(cid, "contract"), "Договор А", owner_id=twin
    )
    paid = ledger.bank.save_bank_operation(
        cid,
        BankOperationInput(
            doc_date="2026-03-05",
            direction=OUT,
            account_id=acc["51"],
            subconto=(v["azn"],),
            kind=SUPPLIER,
            counterparty_id=twin,
            lines=(BankLine(acc["60.1"], 100000, (None, None)),),
            memo="avans",
        ),
        post=True,
    )
    draft = ledger.create_draft(
        cid, "2026-03-06", [PostingInput(acc["26"], acc["60.1"], "50", [v["rent"]], [twin])]
    )
    return {**f, "twin": twin, "twin_contract": contract, "paid": paid, "draft": draft}


def on_60(ledger, f) -> dict[int | None, int]:
    """Counterparty -> the posted balance of 60.1, debit minus credit, in qəpik."""
    acc = f["acc"]["60.1"]
    rows = ledger.conn.execute(
        "SELECT who, SUM(amount) AS total FROM ("
        "SELECT p.dt_sc1 AS who, p.amount AS amount FROM postings p "
        "JOIN documents d ON d.id = p.document_id AND d.status = 'posted' "
        "WHERE p.debit_account_id = ? "
        "UNION ALL SELECT p.ct_sc1, -p.amount FROM postings p "
        "JOIN documents d ON d.id = p.document_id AND d.status = 'posted' "
        "WHERE p.credit_account_id = ?) t GROUP BY who",
        (acc, acc),
    )
    return {r["who"]: r["total"] for r in rows}


def totals(ledger, cid):
    report = trial_balance(ledger.conn, cid, "2026-03-01", "2026-03-31")
    return {r.code: (r.closing_dt, r.closing_ct) for r in report.rows}


def documents(ledger, cid):
    rows = ledger.conn.execute(
        "SELECT id, number, doc_date, status, posted_at FROM documents WHERE company_id = ? "
        "ORDER BY id",
        (cid,),
    )
    return [tuple(r) for r in rows]


def test_the_extra_one_becomes_the_one_that_stays(ledger, firm):
    cid, v, twin = firm["cid"], firm["v"], firm["twin"]
    assert on_60(ledger, firm) == {v["alfa"]: -118000, twin: 100000}
    accounts, before = totals(ledger, cid), documents(ledger, cid)

    plan = ledger.counterparty_merge_plan(cid, v["alfa"], twin)
    assert (plan.keep_name, plan.drop_name) == ("ALFA MMC", "Alfa")
    assert (plan.documents, plan.contracts, plan.takes_tax_id) == (2, 1, None)
    assert on_60(ledger, firm) == {v["alfa"]: -118000, twin: 100000}  # a plan moves nothing

    ledger.merge_counterparties(cid, v["alfa"], twin)
    assert on_60(ledger, firm) == {v["alfa"]: -18000}  # 1 000.00 − 1 180.00
    after = totals(ledger, cid)
    # 60 is two-sided: an advance of one and a debt to the other are now one debt
    assert (accounts["60"], after["60"]) == ((100000, 118000), (0, 18000))
    assert {c: dt - ct for c, (dt, ct) in after.items()} == {
        c: dt - ct for c, (dt, ct) in accounts.items()
    }
    assert documents(ledger, cid) == before  # numbers, dates, statuses, the time of posting
    gone = ledger.conn.execute("SELECT 1 FROM subconto_values WHERE id = ?", (twin,))
    assert gone.fetchone() is None
    assert load_bank_operation(ledger.conn, cid, firm["paid"]).counterparty_id == v["alfa"]
    draft = ledger.conn.execute(
        "SELECT ct_sc1 FROM postings WHERE document_id = ?", (firm["draft"],)
    ).fetchone()
    assert draft["ct_sc1"] == v["alfa"]
    owner = ledger.conn.execute(
        "SELECT owner_id FROM subconto_values WHERE id = ?", (firm["twin_contract"],)
    ).fetchone()
    assert owner["owner_id"] == v["alfa"]
    assert ledger.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    for name, module in module_rebuilders(ledger).items():  # the modules would post the same
        assert module.rebuild_postings(cid, "2026-03-01") == [], name


def test_the_merge_is_in_the_action_log(ledger, firm):
    cid, v, twin = firm["cid"], firm["v"], firm["twin"]
    numbers = [
        r["number"]
        for r in ledger.conn.execute(
            "SELECT d.number FROM documents d JOIN postings p ON p.document_id = d.id "
            "WHERE ? IN (p.dt_sc1, p.ct_sc1) ORDER BY d.id",
            (twin,),
        )
    ]
    ledger.merge_counterparties(cid, v["alfa"], twin)
    event = ledger.conn.execute(
        "SELECT entity_id, details FROM audit_events WHERE action = 'merge'"
    ).fetchone()
    assert event["entity_id"] == v["alfa"]
    import json

    details = json.loads(event["details"])
    assert details["from"] == {"id": twin, "name": "Alfa", "tax_id": None, "legal_name": None}
    assert details["documents"] == numbers


def test_the_one_that_stays_takes_the_voen_it_lacks(ledger, firm):
    """The other way round: «Alfa» stays, ALFA MMC with the VÖEN goes."""
    cid, v, twin = firm["cid"], firm["v"], firm["twin"]
    ledger.set_subconto_value_legal_name(cid, v["alfa"], "ALFA MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ")
    assert ledger.counterparty_merge_plan(cid, twin, v["alfa"]).takes_tax_id == "1234567890"
    ledger.merge_counterparties(cid, twin, v["alfa"])
    kept = ledger.conn.execute(
        "SELECT name, tax_id, legal_name FROM subconto_values WHERE id = ?", (twin,)
    ).fetchone()
    assert tuple(kept) == ("Alfa", "1234567890", "ALFA MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ")
    assert on_60(ledger, firm) == {twin: -18000}


def test_two_voen_are_two_counterparties(ledger, firm):
    cid, v, twin = firm["cid"], firm["v"], firm["twin"]
    ledger.set_subconto_value_tax(cid, twin, "9999999999")
    with pytest.raises(ValidationError, match="разные VÖEN"):
        ledger.merge_counterparties(cid, v["alfa"], twin)
    assert on_60(ledger, firm) == {v["alfa"]: -118000, twin: 100000}


def test_a_closed_period_is_not_touched(ledger, firm):
    cid, v, twin = firm["cid"], firm["v"], firm["twin"]
    ledger.set_closed_through(cid, "2026-03-05")
    with pytest.raises(PeriodClosedError, match=r"в закрытом периоде \(по 05\.03\.2026\): 1"):
        ledger.merge_counterparties(cid, v["alfa"], twin)
    assert on_60(ledger, firm) == {v["alfa"]: -118000, twin: 100000}
    ledger.set_closed_through(cid, None)  # opened: merged
    ledger.merge_counterparties(cid, v["alfa"], twin)
    assert on_60(ledger, firm) == {v["alfa"]: -18000}


def test_only_counterparties_are_merged(ledger, firm):
    cid, v = firm["cid"], firm["v"]
    with pytest.raises(ValidationError, match="только контрагенты"):
        ledger.merge_counterparties(cid, v["azn"], v["pasha"])
    with pytest.raises(ValidationError, match="один и тот же"):
        ledger.merge_counterparties(cid, v["alfa"], v["alfa"])


# ---- the directory's page ---------------------------------------------------------------


def test_the_directory_merges_from_its_menu(qtbot, ledger, firm, monkeypatch):
    """«Объединить с…» on «Alfa»: the namesake ALFA MMC is offered first; the question
    says what moves — 2 documents, 1 contract; Yes — one element is left."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.directories_page import DirectoriesPage
    from modern_gl.desktop.directories_page.merge import can_merge
    from modern_gl.desktop.session import Session
    from modern_gl.i18n import tr

    cid, v, twin = firm["cid"], firm["v"], firm["twin"]
    ledger.set_subconto_value_legal_name(cid, v["alfa"], '"ALFA" MMC')
    told: list[str] = []
    s = Session(ledger.conn, ledger, cid, "ООО Банк", Catalog(ledger.conn, cid), notify=told.append)
    page = DirectoriesPage(s)
    qtbot.addWidget(page)
    extra = s.catalog.value(twin)
    assert can_merge(s, extra)
    assert not can_merge(s, s.catalog.value(v["azn"]))  # a bank account is not a counterparty
    asked: dict[str, object] = {}

    def get_item(_parent, _title, label, items, *_):
        asked.update(label=label, first=items[0], count=len(items))
        return items[0], True

    def question(_parent, _title, text, *_):
        asked["question"] = text
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(get_item))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    page.merge_value(extra)
    assert asked["first"] == "ALFA MMC  ·  1234567890"
    assert asked["count"] == 3  # ALFA, BETA, Учредитель: not itself
    assert asked["question"] == "\n".join(
        [
            tr("«{extra}» станет «{kept}» во всех документах.", extra="Alfa", kept="ALFA MMC"),
            tr("Документов: {n}, договоров: {m}.", n=2, m=1),
            tr("«{extra}» будет удалён из справочника. Отменить это нельзя.", extra="Alfa"),
        ]
    )
    assert on_60(ledger, firm) == {v["alfa"]: -18000}
    assert told == [tr("«{extra}» объединён с «{kept}»", extra="Alfa", kept="ALFA MMC")]
    assert twin not in {x.id for x in s.catalog.all_values(extra.kind_id)}


def test_a_snapshot_offers_no_merge(ledger, firm):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.directories_page.merge import can_merge
    from modern_gl.desktop.session import Session

    cid = firm["cid"]
    s = Session(ledger.conn, ledger, cid, "ООО Банк", Catalog(ledger.conn, cid), notify=print)
    s.read_only = True
    assert not can_merge(s, s.catalog.value(firm["twin"]))
