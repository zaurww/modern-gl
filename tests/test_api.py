"""The developers' API and its command line (D130, docs/API.md) over a company file of the
golden example (conftest, hand-calculated there): February 2026 — 531 opening Ct 200,
turnover Ct 500, closing Ct 700; total closing 10 700 / 10 700.

The answers are the contract of API_VERSION 1: a change that breaks a test here breaks
someone's script."""

from __future__ import annotations

import json

import pytest

from modern_gl.api import API_VERSION, ReadOnlyError, open_company
from modern_gl.api.cli import main
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import load_document
from modern_gl.infrastructure.db import connect
from tests.conftest import build_demo

MARCH = {
    "format": "modern-gl/documents",
    "version": 1,
    "source": "test-shop",
    "documents": [
        {
            "id": "S-1",
            "date": "2026-03-02",
            "postings": [
                {
                    "debit": "201",
                    "credit": "531",
                    "amount": "150.00",
                    "credit_subconto": ["Поставщик A"],
                }
            ],
        }
    ],
}


@pytest.fixture
def company_file(tmp_path):
    path = tmp_path / "Alfa.gl"
    conn = connect(path)
    build_demo(Ledger(conn), "Alfa MMC")
    conn.close()
    return path


def test_the_version_is_one():
    assert API_VERSION == 1


def test_reading_is_plain_data(company_file):
    with open_company(company_file) as company:
        assert company.name == "Alfa MMC" and company.read_only
        osv = company.trial_balance("2026-02-01", "2026-02-28")
        chart = company.chart_of_accounts()
    row = next(r for r in osv["rows"] if r["code"] == "531")
    assert row["opening"] == {"debit": "0.00", "credit": "200.00"}
    assert row["closing"] == {"debit": "0.00", "credit": "700.00"}
    assert osv["total"]["closing"] == {"debit": "10700.00", "credit": "10700.00"}
    assert "531" in {a["code"] for a in chart["accounts"]}


def test_a_snapshot_does_not_write(company_file):
    with open_company(company_file) as company, pytest.raises(ReadOnlyError):
        company.import_documents(MARCH)


def test_import_writes_drafts_by_the_api_and_a_repeat_finds_them(company_file):
    with open_company(company_file, write=True, actor="test-shop") as company:
        first = company.import_documents(MARCH)
        again = company.import_documents(MARCH)
    assert first == {
        "ok": True,
        "new": ["S-1"],
        "created": [{"id": "S-1", "number": 7}],
        "existing": [],
        "errors": [],
    }
    assert again["created"] == [] and again["existing"] == [{"id": "S-1", "number": 7}]
    conn = connect(company_file)
    doc = conn.execute("SELECT id, status FROM documents WHERE number = 7").fetchone()
    assert doc["status"] == "draft"
    actor = conn.execute(
        "SELECT actor FROM audit_events WHERE entity_id = ? AND action = 'create_draft'",
        (doc["id"],),
    ).fetchone()["actor"]
    assert actor == "API · test-shop"  # the document's author (D82)
    assert load_document(conn, 1, doc["id"]).postings[0].amount == 15_000
    conn.close()


def run(capsys, *argv) -> tuple[int, dict]:
    code = main(["--lang", "ru", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_the_command_line_exports_and_imports(company_file, tmp_path, capsys):
    code, osv = run(
        capsys, "trial-balance", str(company_file), "--from", "2026-02-01", "--to", "2026-02-28"
    )
    assert code == 0 and osv["total"]["closing"]["debit"] == "10700.00"
    code, data = run(
        capsys, "export", str(company_file), "--from", "2026-01-01", "--to", "2026-01-31"
    )
    assert code == 0 and [d["id"] for d in data["documents"]] == ["1", "2", "3"]
    march = tmp_path / "march.json"
    march.write_text(json.dumps(MARCH), encoding="utf-8")
    code, check = run(capsys, "import", str(company_file), str(march), "--check")
    assert code == 0 and check["new"] == ["S-1"] and check["created"] == []
    code, done = run(capsys, "import", str(company_file), str(march), "--post")
    assert code == 0 and done["created"] == [{"id": "S-1", "number": 7}]


def test_the_command_line_says_what_is_wrong(company_file, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**MARCH, "version": 9}), encoding="utf-8")
    code, answer = run(capsys, "import", str(company_file), str(bad))
    assert code == 1 and "версии 9" in answer["error"]
    wrong = {**MARCH, "documents": [{**MARCH["documents"][0], "date": "2026-03-02"}]}
    wrong["documents"][0]["postings"] = [{**MARCH["documents"][0]["postings"][0], "debit": "9"}]
    bad.write_text(json.dumps(wrong), encoding="utf-8")
    code, answer = run(capsys, "import", str(company_file), str(bad))
    assert code == 1 and answer["errors"] == [{"id": "S-1", "message": "счёт «9» не найден"}]
