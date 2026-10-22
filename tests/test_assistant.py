"""The assistant server (D83): the books for an AI over MCP, read-only.

Figures — the golden example of conftest (hand-calculated there): February 2026,
531 opening Ct 200, turnover Ct 500, closing Ct 700; total closing 10 700 / 10 700.
"""

import io
import json

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.assistant.companies import Companies
from modern_gl.assistant.protocol import Server
from modern_gl.assistant.server import build_tools
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import Workspace
from tests.conftest import build_demo


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
    yield Server("modern-gl", "test", build_tools(companies))
    companies.close()


def call(server, tool, **arguments):
    answer = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    )
    result = answer["result"]
    if result.get("isError"):
        return result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


def test_handshake_and_tool_list(server):
    init = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"trial_balance", "account_card", "document", "e_qaime"} <= names
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_broken_requests_are_json_rpc_errors(server):
    assert server.handle_line("{not json")["error"]["code"] == -32700
    assert server.handle({"jsonrpc": "2.0", "id": 3, "method": "x"})["error"]["code"] == -32601
    unknown = {"name": "trial_balance", "arguments": {"date_from": "2026-02-01", "x": 1}}
    answer = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": unknown})
    assert answer["error"]["code"] == -32602


def test_trial_balance(server):
    osv = call(server, "trial_balance", date_from="2026-02-01", date_to="2026-02-28")
    rows = {r["code"]: r for r in osv["rows"]}
    assert rows["531"]["opening"] == {"debit": "0.00", "credit": "200.00"}
    assert rows["531"]["turnover"] == {"debit": "0.00", "credit": "500.00"}
    assert rows["531"]["closing"] == {"debit": "0.00", "credit": "700.00"}
    assert rows["22"]["group"] and rows["221"]["closing"]["debit"] == "7000.00"
    assert osv["total"]["closing"] == {"debit": "10700.00", "credit": "10700.00"}


def test_account_card_and_analysis(server):
    card = call(server, "account_card", account="531", date_from="2026-01-01", date_to="2026-02-28")
    assert card["opening_balance"] == "0.00"
    assert [(c["document"], c["balance"]) for c in card["lines"]] == [
        (2, "-1200.00"),
        (3, "-200.00"),
        (4, "-700.00"),
    ]
    assert card["closing_balance"] == "-700.00"
    analysis = call(
        server, "account_analysis", account="531", date_from="2026-01-01", date_to="2026-02-28"
    )
    by_corr = {r["code"]: r for r in analysis["by_corr_account"]}
    assert by_corr["201"] == {
        "code": "201",
        "name": "Материалы",
        "debit": "0.00",
        "credit": "1700.00",
    }
    assert by_corr["221"]["debit"] == "1000.00"


def test_subconto_balance(server):
    rows = call(
        server, "subconto_balance", account="531", date_from="2026-02-01", date_to="2026-02-28"
    )
    by_name = {r["name"]: r for r in rows["rows"]}
    assert by_name["Поставщик A"]["closing"] == {"debit": "0.00", "credit": "200.00"}
    assert by_name["Поставщик B"]["turnover"] == {"debit": "0.00", "credit": "500.00"}


def test_documents_and_one_document(server):
    february = call(server, "documents", date_from="2026-02-01", date_to="2026-02-28")
    assert [d["number"] for d in february["documents"]] == [4, 5, 6]
    doc = call(server, "document", number=2)
    assert doc["date"] == "2026-01-10"
    [posting] = doc["postings"]
    assert posting["debit"] == {"account": "201  Материалы", "subconto": []}
    assert posting["credit"] == {"account": "531  Поставщики", "subconto": ["Поставщик A"]}
    assert posting["amount"] == "1200.00"
    assert call(server, "document", number=99) == "документ №99 не найден"


def test_directory(server):
    found = call(server, "directory", name="контрагенты", search="b")
    assert found["elements"] == [{"name": "Поставщик B"}]


def test_company_by_name(server, folder):
    assert call(server, "companies") == {"companies": ["Alfa MMC"]}
    assert call(server, "chart_of_accounts", company="alfa")["accounts"][0]["code"] == "201"
    conn = connect(folder / "Beta.gl")
    Ledger(conn).create_company("Beta")
    conn.close()
    assert "укажите компанию" in call(server, "chart_of_accounts")
    assert "не найдена" in call(server, "chart_of_accounts", company="Gamma")


def test_reads_without_writing_and_follows_the_file(server, folder):
    path = folder / "Alfa.gl"
    call(server, "companies")  # listing reads the names (and leaves an empty -wal, -shm)
    before, names = path.read_bytes(), sorted(p.name for p in folder.iterdir())
    call(server, "trial_balance", date_from="2026-02-01", date_to="2026-02-28")
    assert path.read_bytes() == before
    assert sorted(p.name for p in folder.iterdir()) == names

    conn = connect(path)  # the user goes on working in the program
    ledger = Ledger(conn)
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    accounts = dict(conn.execute("SELECT code, id FROM accounts WHERE company_id = ?", (cid,)))
    ledger.post_new(cid, "2026-02-25", [PostingInput(accounts["721"], accounts["221"], "50.00")])
    osv = call(server, "trial_balance", date_from="2026-02-01", date_to="2026-02-28")
    conn.close()
    assert {r["code"]: r for r in osv["rows"]}["721"]["turnover"]["debit"] == "350.00"


def test_serves_lines_over_stdio(server):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    stdin = io.BytesIO(b"".join(json.dumps(r).encode() + b"\n" for r in requests))
    stdout = io.BytesIO()
    server.serve(stdin, stdout)
    answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [a["id"] for a in answers] == [1, 2]
    assert answers[1]["result"] == {}


def test_chart_says_current_or_long_term(server, folder):
    """The type gives the term of an asset or liability (D89); other accounts have none."""
    conn = connect(folder / "Alfa.gl")
    ledger = Ledger(conn)
    [cid] = [c.id for c in ledger.companies.list()] if hasattr(ledger, "companies") else [1]
    ledger.add_account(cid, "101", "Основные средства", account_type="fixed_asset")
    ledger.add_account(cid, "102", "Касса", account_type="cash")
    conn.close()
    terms = {
        a["code"]: a["term"] for a in call(server, "chart_of_accounts", company="alfa")["accounts"]
    }
    assert (terms["101"], terms["102"], terms["201"]) == ("long_term", "current", "")
