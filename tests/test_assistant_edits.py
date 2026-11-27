"""Edits by the assistant (--allow-edits): a posted document of an open period is changed
or unposted through Ledger and the bank module, with the trail naming the AI.

Journal — the golden example of conftest: documents 1–6, 531 closes February at Ct 700
(A 1200 − 1000 = 200, B 500).

Bank — `bank_firm` (March 2026): №1 Dt 51 / Ct 80 10 000.00, №3 Dt 26 / Ct 60.1 [ALFA]
1 180.00 e-qaimə MT001; added here:
  №4 journal Dt 26 / Ct 60.1 [ALFA] 590.00, e-qaimə MT002
  №5 bank, 05.03: paid to ALFA 1 180.00 — by mistake against MT002
  №6 bank, 05.03: the same payment once more (a duplicate)
Kapital AZN: 10 000 − 1 180 − 1 180 = 7 640.00; without the duplicate 8 820.00.
E-qaimə, debit − credit of 60.1: MT001 −1 180.00, MT002 2 360 − 590 = +1 770.00;
№5 moved to MT001 and №6 unposted: MT001 0.00, MT002 −590.00.
"""

import json

import pytest

from modern_gl.application.bank import (
    OUT,
    SUPPLIER,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.history import document_history
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import document_by_number, load_document
from modern_gl.application.workspace import Workspace
from modern_gl.assistant.companies import Companies
from modern_gl.assistant.drafts import Drafts
from modern_gl.assistant.edits import Edits
from modern_gl.assistant.protocol import Server, Session
from modern_gl.assistant.server import build_tools
from modern_gl.infrastructure.db import connect
from tests.conftest import build_demo

PAY_B = {"debit": "201", "credit": "531", "credit_subconto": ["Поставщик B"], "amount": "450.00"}


@pytest.fixture
def conn(tmp_path):
    """The company in a file: the assistant writes beside the program's connection."""
    (tmp_path / "data").mkdir()
    c = connect(tmp_path / "data" / "Firma.gl")
    yield c
    c.close()


@pytest.fixture
def server(conn, tmp_path):
    companies = Companies(Workspace(tmp_path / "data"))
    session = Session()
    drafts = Drafts(companies, lambda: session.client)
    tools = build_tools(companies, drafts, Edits(drafts))
    server = Server("modern-gl", "test", tools, session=session)
    server.handle(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"clientInfo": {"name": "Claude"}},
        }
    )
    yield server
    companies.close()


def call(server, tool, **arguments):
    answer = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    )
    result = answer["result"]
    if result.get("isError"):
        return result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


def closing(server, code, date_from, date_to):
    osv = call(server, "trial_balance", date_from=date_from, date_to=date_to)
    return {r["code"]: r for r in osv["rows"]}[code]["closing"]


def history(conn, cid, number):
    events = document_history(conn, cid, document_by_number(conn, cid, number))
    return [(e.actor, e.action, e.reason) for e in events]


# ---- the journal ------------------------------------------------------------------------


def test_edit_tools_come_only_with_their_flag(conn, ledger, tmp_path):
    build_demo(ledger, "Alfa MMC")
    companies = Companies(Workspace(tmp_path / "data"))
    drafts = Drafts(companies, lambda: "Claude")
    listed = Server("modern-gl", "test", build_tools(companies, drafts)).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert listed is not None
    names = {t["name"] for t in listed["result"]["tools"]}
    companies.close()
    assert not names & {"change_document", "set_e_qaime", "unpost_document"}


def test_edit_tools_are_marked_destructive(server, ledger):
    build_demo(ledger, "Alfa MMC")
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    marks = {t["name"]: t["annotations"] for t in listed["result"]["tools"]}
    for name in ("change_document", "set_e_qaime", "unpost_document"):
        assert marks[name] == {"readOnlyHint": False, "destructiveHint": True}
    assert marks["create_draft"]["destructiveHint"] is False


def test_a_posted_document_is_changed_in_place_with_the_reason(server, conn, ledger):
    demo = build_demo(ledger, "Alfa MMC")
    answer = call(
        server,
        "change_document",
        number=4,
        date="2026-02-03",
        memo="Материалы от B",
        postings=[PAY_B],
        reason="сумма по накладной 450, не 500",
    )
    assert answer["before"]["postings"][0]["amount"] == "500.00"
    assert answer["after"]["postings"][0]["amount"] == "450.00"
    assert answer["after"]["status"] == "posted" and answer["after"]["number"] == 4
    # 531: A 200 + B 450
    assert closing(server, "531", "2026-02-01", "2026-02-28")["credit"] == "650.00"
    assert history(conn, demo.company_id, 4)[-1] == (
        "AI · Claude",
        "Исправлен и проведён",
        "сумма по накладной 450, не 500",
    )


def test_a_reason_is_asked(server, ledger):
    build_demo(ledger, "Alfa MMC")
    refused = call(server, "unpost_document", number=4, reason="  ")
    assert refused == "укажите причину правки (reason) — она остаётся в истории документа"


def test_a_closed_period_is_not_touched(server, conn, ledger):
    demo = build_demo(ledger, "Alfa MMC")
    ledger.set_closed_through(demo.company_id, "2026-01-31")
    refused = call(server, "unpost_document", number=2, reason="дубль")
    assert "закрыт" in refused
    assert load_document(conn, demo.company_id, demo.docs[1]).status == "posted"
    refused = call(
        server,
        "change_document",
        number=2,
        date="2026-02-01",
        memo="",
        postings=[PAY_B],
        reason="x",
    )
    assert "закрыт" in refused


def test_a_duplicate_is_unposted_not_deleted(server, conn, ledger):
    demo = build_demo(ledger, "Alfa MMC")
    twin = ledger.post_new(
        demo.company_id, "2026-02-03", [demo.p("201", "531", "500.00", ct_sc=[demo.supplier_b])]
    )
    assert closing(server, "531", "2026-02-01", "2026-02-28")["credit"] == "1200.00"

    answer = call(server, "unpost_document", number=7, reason="дубль документа №4")
    assert answer["after"]["status"] == "draft"
    assert answer["after"]["postings"][0]["amount"] == "500.00"  # kept, as a draft
    assert closing(server, "531", "2026-02-01", "2026-02-28")["credit"] == "700.00"
    assert load_document(conn, demo.company_id, twin).status == "draft"
    assert history(conn, demo.company_id, 7)[-1] == (
        "AI · Claude",
        "Проведение отменено",
        "дубль документа №4",
    )


def test_a_copy_of_the_file_is_made_before_the_first_edit(server, ledger, tmp_path):
    build_demo(ledger, "Alfa MMC")
    workspace = Workspace(tmp_path / "data")
    path = tmp_path / "data" / "Firma.gl"
    assert workspace.backups(path) == []

    first = call(server, "unpost_document", number=6, reason="проверка")
    copies = workspace.backups(path)
    assert len(copies) == 1 and "до правок AI" in copies[0].path.name
    assert first["backup"] == str(copies[0].path)
    # the copy is of the file before the edit: №6 is posted there
    copy = connect(copies[0].path)
    assert copy.execute("SELECT status FROM documents WHERE number = 6").fetchone()[0] == "posted"
    copy.close()

    second = call(server, "unpost_document", number=5, reason="проверка")
    assert "backup" not in second and len(workspace.backups(path)) == 1


def test_the_number_of_a_journal_line_is_changed_alone(server, conn, ledger, bank_firm):
    f = bank_firm
    answer = call(server, "set_e_qaime", number=3, old="MT001", new="mt 009", reason="опечатка")
    assert answer["changed_lines"] == 1
    after = answer["after"]["postings"][0]
    assert after["e_qaime"] == "MT009" and after["amount"] == "1180.00"
    assert after["credit"]["subconto"] == ["ALFA MMC", "Договор 1"]
    assert history(conn, f["cid"], 3)[-1] == ("AI · Claude", "Исправлен и проведён", "опечатка")

    assert (
        call(server, "set_e_qaime", number=3, old="MT001", new="MT010", reason="x")
        == "в документе №3 нет строки с e-qaimə MT001"
    )


# ---- the bank ---------------------------------------------------------------------------


@pytest.fixture
def paid_twice(ledger, bank_firm):
    f = bank_firm
    acc, v = f["acc"], f["v"]
    ledger.post_new(
        f["cid"],
        "2026-03-03",
        [
            PostingInput(
                acc["26"], acc["60.1"], "590", [v["rent"]], [v["alfa"], v["contract"]],
                invoice="MT002",
            )
        ],
    )  # fmt: skip
    payment = BankOperationInput(
        doc_date="2026-03-05",
        direction=OUT,
        account_id=acc["51"],
        subconto=(v["azn"],),
        kind=SUPPLIER,
        counterparty_id=v["alfa"],
        lines=(BankLine(acc["60.1"], 118000, (None, v["contract"]), "MT002"),),
        memo="Оплата ALFA",
    )
    ids = [ledger.bank.save_bank_operation(f["cid"], payment, post=True) for _ in range(2)]
    return {**f, "operations": ids}


def unpaid(server):
    rows = call(server, "e_qaime", date_from="2026-03-01", date_to="2026-03-31")["e_qaime"]
    return {r["number"]: r["unpaid_balance"] for r in rows}


def test_the_e_qaime_of_a_bank_payment_and_its_duplicate(server, conn, ledger, paid_twice):
    f = paid_twice
    assert closing(server, "51", "2026-03-01", "2026-03-31")["debit"] == "7640.00"
    assert unpaid(server) == {"MT001": "-1180.00", "MT002": "1770.00"}

    answer = call(
        server, "set_e_qaime", number=5, old="MT002", new="MT001", reason="оплата была по MT001"
    )
    assert answer["changed_lines"] == 1
    assert answer["before"]["postings"][0]["e_qaime"] == "MT002"
    assert answer["after"]["postings"][0]["e_qaime"] == "MT001"
    assert answer["after"]["status"] == "posted"
    # the operation itself says so too, not only its postings
    assert load_bank_operation(conn, f["cid"], f["operations"][0]).lines[0].invoice == "MT001"

    gone = call(server, "unpost_document", number=6, reason="дубль оплаты №5")
    assert gone["after"]["status"] == "draft"
    # the operation stays in the statement as a draft: a person deletes it
    assert load_bank_operation(conn, f["cid"], f["operations"][1]).status == "draft"
    assert closing(server, "51", "2026-03-01", "2026-03-31")["debit"] == "8820.00"
    assert unpaid(server) == {"MT001": "0.00", "MT002": "-590.00"}


def test_a_module_document_is_not_replaced_whole(server, paid_twice):
    line = {"debit": "60.1", "credit": "51", "amount": "1.00"}
    refused = call(
        server, "change_document", number=5, date="2026-03-05", memo="", postings=[line], reason="x"
    )
    assert refused == (
        "документ №5 сделан разделом программы (банк, склад…): целиком его меняет человек там"
    )
