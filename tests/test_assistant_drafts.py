"""Drafts from the assistant (D84): only drafts, through Ledger, marked as the AI's.

Golden example of conftest: documents 1–6, 531 closes February at Ct 700 (A 200, B 500).
"""

import json

import pytest

from modern_gl.application.authorship import document_authors
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import document_by_number, load_document
from modern_gl.application.workspace import Workspace
from modern_gl.assistant.companies import Companies
from modern_gl.assistant.drafts import Drafts
from modern_gl.assistant.protocol import Server, Session
from modern_gl.assistant.server import build_tools
from modern_gl.infrastructure.db import connect
from tests.conftest import build_demo

PAY_B = {"debit": "531", "debit_subconto": ["Поставщик B"], "credit": "221", "amount": "500.00"}


@pytest.fixture
def folder(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = connect(data / "Alfa.gl")
    build_demo(Ledger(conn), "Alfa MMC")
    conn.close()
    return data


@pytest.fixture
def server(folder):
    companies = Companies(Workspace(folder))
    session = Session()
    drafts = Drafts(companies, lambda: session.client)
    server = Server("modern-gl", "test", build_tools(companies, drafts), session=session)
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


def in_file(folder, number):
    conn = connect(folder / "Alfa.gl")
    try:
        cid = conn.execute("SELECT id FROM companies").fetchone()[0]
        doc_id = document_by_number(conn, cid, number)
        return load_document(conn, cid, doc_id), document_authors(conn, cid, doc_id)
    finally:
        conn.close()


def test_without_the_flag_there_is_nothing_that_writes(folder):
    companies = Companies(Workspace(folder))
    answer = Server("modern-gl", "test", build_tools(companies)).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert answer is not None
    tools = answer["result"]["tools"]
    companies.close()
    assert not {t["name"] for t in tools} & {"create_draft", "update_draft", "delete_draft"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_a_draft_is_made_never_posted_and_the_ai_is_its_author(server, folder):
    draft = call(server, "create_draft", date="2026-02-25", memo="Оплата B", postings=[PAY_B])
    assert draft["number"] == 7 and draft["status"] == "draft"
    assert draft["would_post"] is True
    assert draft["postings"][0]["debit"] == {
        "account": "531  Поставщики",
        "subconto": ["Поставщик B"],
    }

    doc, authors = in_file(folder, 7)
    assert doc.status == "draft" and doc.postings[0].amount == 50000
    assert authors is not None
    assert authors.entered_by == "AI · Claude" and authors.posted_by is None
    # a draft is not in the books: 531 still closes February at Ct 700
    osv = call(server, "trial_balance", date_from="2026-02-01", date_to="2026-02-28")
    assert {r["code"]: r for r in osv["rows"]}["531"]["closing"]["credit"] == "700.00"


def test_what_would_stop_posting_is_said(server):
    no_supplier = {"debit": "531", "credit": "221", "amount": "500.00"}
    draft = call(server, "create_draft", date="2026-02-25", memo="?", postings=[no_supplier])
    assert draft["would_post"] is False
    assert draft["problem"] == "строка 1, Дт 531: не заполнено «Контрагенты»"


def test_names_must_exist_and_amounts_are_text(server):
    missing = {**PAY_B, "debit_subconto": ["Поставщик C"]}
    text = call(server, "create_draft", date="2026-02-25", memo="x", postings=[missing])
    assert (
        text == "«Поставщик C» нет в справочнике «Контрагенты» — его добавляет человек в программе"
    )
    as_number = {**PAY_B, "amount": 500.5}
    assert "сумма — строкой" in call(
        server, "create_draft", date="2026-02-25", memo="x", postings=[as_number]
    )
    assert "не найден" in call(
        server, "create_draft", date="2026-02-25", memo="x", postings=[{**PAY_B, "credit": "999"}]
    )


def test_only_its_own_drafts_are_changed(server, folder):
    call(server, "create_draft", date="2026-02-25", memo="Оплата", postings=[PAY_B])
    fixed = {**PAY_B, "amount": "450.00"}
    changed = call(
        server, "update_draft", number=7, date="2026-02-26", memo="Оплата B", postings=[fixed]
    )
    assert (changed["date"], changed["postings"][0]["amount"]) == ("2026-02-26", "450.00")

    refused = call(server, "update_draft", number=2, date="2026-01-10", memo="x", postings=[PAY_B])
    assert refused == "документ №2 ввёл не помощник — его меняет человек"
    assert (
        call(server, "delete_draft", number=3)
        == "документ №3 ввёл не помощник — его меняет человек"
    )

    assert call(server, "delete_draft", number=7) == {"deleted": 7}
    assert call(server, "document", number=7) == "документ №7 не найден"


def test_a_draft_the_user_posted_is_theirs_now(server, folder):
    call(server, "create_draft", date="2026-02-25", memo="Оплата", postings=[PAY_B])
    conn = connect(folder / "Alfa.gl")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    Ledger(conn, actor="Zaur").post(cid, document_by_number(conn, cid, 7))
    conn.close()
    assert "уже проведён" in call(server, "delete_draft", number=7)


def test_works_while_the_program_has_the_file_open(server, folder):
    program = connect(folder / "Alfa.gl")  # the program keeps its connection
    cid = program.execute("SELECT id FROM companies").fetchone()[0]
    draft = call(server, "create_draft", date="2026-02-25", memo="Оплата", postings=[PAY_B])
    assert (
        load_document(program, cid, document_by_number(program, cid, draft["number"])).memo
        == "Оплата"
    )
    program.close()
