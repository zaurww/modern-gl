"""Shared from test_vat_deposit_import.py (moved here: other test modules use it too)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from modern_gl.application.bank import (
    BankPlace,
)
from modern_gl.application.bank.deposit_import import (
    parse_operation,
)
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.infrastructure.etaxes import EtaxesClient, Response

OWN_TIN = "1400000001"


def raw(
    moment: str,
    income: object,
    expense: object,
    *,
    tin: str = "1100000001",
    name: str = '"ALFA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ',
    kind: str = "SUB_TO_SUB",
    destination: str = "TAXPAYER",
    receipt: str = "2619000000000000",
    explanation: str = "ƏDV köçürməsi",
    invoices: list | None = None,
    status: str = "SUCCESS",
) -> dict:
    return {
        "id": f"id{moment}",
        "tin": tin,
        "name": name,
        "operationDate": moment,
        "operationType": kind,
        "paymentType": "INCOME" if income is not None else "EXPENSE",
        "account": "CURRENT" if kind == "CURRENT_TO_SUB" else "MAIN",
        "destination": destination,
        "income": income,
        "expense": expense,
        "receiptNumber": receipt,
        "explanation": explanation,
        "operationStatus": status,
        "documentKind": "INVOICE" if invoices else "ADVANCE",
        "invoices": invoices,
    }


BETA = "2222222222"


BETA_NAME = '"BETA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ'


PORTAL = [
    raw(
        "20261001101500",
        Decimal("594"),
        None,
        receipt="2619000000000001",
        invoices=[
            {"serialNumber": "MT260812000002", "vat": Decimal("54")},
            {"serialNumber": "MT260411000001", "vat": Decimal("540")},
        ],
        tin=BETA,
        name=BETA_NAME,
    ),
    raw(
        "20261002090000",
        None,
        Decimal("12.44"),
        receipt="2619000000000002",
        invoices=[{"serialNumber": "MT261011000003", "vat": Decimal("12.4369")}],
    ),
    raw(
        "20261002120000",
        None,
        Decimal("940"),
        tin="1602473621",
        name="MİLLİ GƏLİRLƏR BAŞ İDARƏSİ",
        kind="SUB_TO_BUDGET",
        destination="BUDGET",
        receipt="2619000000000003",
    ),
    raw(
        "20261003100000",
        Decimal("90"),
        None,
        kind="CURRENT_TO_SUB",
        destination="BANK",
        receipt="nb",
        explanation="29.09.26 TARIXLI MT260912\n395884 QAIMEYE ESASEN",
        tin=BETA,
        name=BETA_NAME,
    ),
    raw(
        "20261003110000",
        Decimal("200"),
        None,
        tin=OWN_TIN,
        name="ÖZÜMÜZ MMC",
        kind="CURRENT_TO_SUB",
        destination="BANK",
        receipt="nb",
    ),
    raw("20261003120000", Decimal("50"), None, receipt="2619000000000004", status="REJECTED"),
]


@pytest.fixture(name="deposit_firm")
def firm(ledger):
    cid = ledger.create_company("ООО Депозит")
    apply_chart_template(ledger, cid, "1c77", "ru")
    acc = {code: ledger.account_id(cid, code) for code in ("55", "60.1", "62.1", "68.2", "51")}
    ledger.set_account_type(cid, acc["55"], "vat_deposit")
    deposit = ledger.bank.add_bank_account(cid, "ƏDV depozit", acc["55"], "vat_deposit")
    place = BankPlace(acc["55"], deposit, "ƏDV depozit", "55", None, "", "vat_deposit")
    alfa = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "counterparty"), "Альфа")
    ledger.set_subconto_value_tax(cid, alfa, "1100000001")
    return {"cid": cid, "acc": acc, "place": place, "alfa": alfa}


def operations():
    return [parse_operation(r, OWN_TIN) for r in PORTAL]


class FakeDepositPortal:
    """Answers like new.e-taxes.gov.az: the balance, the operations in pages of 50."""

    def __init__(
        self, rows: list[dict], balance: str = "1000", read_at: str = "", token: str = "good"
    ) -> None:
        self.rows, self.balance, self.token, self.calls = rows, balance, token, []
        self.read_at = read_at or "2026-10-03T23:00:00.123456789"

    def __call__(self, method, url, headers, body):
        request = json.loads(body) if body else None
        self.calls.append((method, url, request))
        if headers["x-authorization"] != f"Bearer {self.token}":
            return Response(401, b"")
        if url.endswith("/accountInfo"):
            answer = {"mainAccount": float(self.balance), "informationOn": self.read_at}
            return Response(200, json.dumps(answer).encode())
        assert request is not None  # a page is asked for with its offset and size
        page = self.rows[request["offset"] : request["offset"] + request["maxCount"]]
        more = request["offset"] + request["maxCount"] < len(self.rows)
        return Response(200, json.dumps({"operations": page, "hasMore": more}).encode())


def as_json(rows: list[dict]) -> list[dict]:
    """The rows as the portal sends them: numbers, not Decimal."""
    return json.loads(json.dumps(rows, default=float))


@pytest.fixture
def deposit_session(ledger, deposit_firm, monkeypatch):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import portal_login
    from modern_gl.desktop.bank_page import deposit_fetch as fetch
    from modern_gl.desktop.session import Session
    from tests.helpers.eqaime import fake_token

    cid = deposit_firm["cid"]
    messages: list[str] = []
    s = Session(
        ledger.conn, ledger, cid, "ООО Депозит", Catalog(ledger.conn, cid), notify=messages.append
    )
    s.working_date = date(2026, 10, 5)
    ledger.set_company_tax_id(cid, OWN_TIN)  # the portal's firm (D113)
    token = fake_token(OWN_TIN)
    portal = FakeDepositPortal(as_json(PORTAL), token=token)
    monkeypatch.setattr(fetch, "EtaxesClient", lambda token: EtaxesClient(token, send=portal))
    portal_login.forget_token()
    return s, messages, token, portal
