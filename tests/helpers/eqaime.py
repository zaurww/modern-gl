"""Shared from test_eqaime_import.py (moved here: other test modules use it too)."""

from __future__ import annotations

import json

from modern_gl.infrastructure.etaxes import (
    Response,
)

SUPPLIER_TIN = "1700000001"


def received(number: str = "MT2603000111", tin: str = SUPPLIER_TIN) -> tuple[dict, dict]:
    """A supplier's e-qaimə: 10 printers 120.00 (VAT base 120.00) and a repair 50.00
    (code 99…: a service, VAT base 50.00): VAT 21.60 + 9.00."""
    row = {
        "id": "a1",
        "sourceSystem": "avis",
        "serialNumber": number,
        "status": "approved",
        "kind": "defaultInvoice",
        "createdAt": "2026-03-05T15:32:56.394",
        "sender": {"tin": tin, "name": "Təchizatçı MMC"},
    }
    detail = {
        **row,
        "items": [
            {
                "productName": "Printer",
                "productGroup": {"code": "8443321000"},
                "unit": "ədəd",
                "quantity": 10,
                "pricePerUnit": 12,
                "cost": 120.0,
                "vat18": 120.0,
            },
            {
                "productName": "Printerin təmiri",
                "productGroup": {"code": "9995110000"},
                "unit": "xidmət",
                "quantity": 1,
                "cost": 50,
                "vat18": 50,
            },
        ],
    }
    return row, detail


class FakePortal:
    """Answers like new.e-taxes.gov.az: pages of 50, one status per request."""

    def __init__(self, rows: dict[str, list[dict]], details: dict[str, dict]) -> None:
        self.rows, self.details, self.calls = rows, details, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        if headers["x-authorization"] != "Bearer good":
            return Response(401, b"")
        if method == "POST":
            request = json.loads(body)
            rows = self.rows.get(request["statuses"][0], [])
            page = rows[request["offset"] : request["offset"] + request["maxCount"]]
            more = request["offset"] + request["maxCount"] < len(rows)
            return Response(200, json.dumps({"invoices": page, "hasMore": more}).encode())
        invoice_id = url.rsplit("/", 1)[1].split("?")[0]
        if invoice_id not in self.details:
            return Response(500, b"INTERNAL_SERVICE_EXCEPTION")
        return Response(200, json.dumps({"invoice": self.details[invoice_id]}).encode())


def fake_token(voen: str = "1402375141", name: str = "ДЕМО MMC", lifetime: int = 600) -> str:
    import base64
    import time

    payload = {"voen": voen, "organizationName": name, "exp": int(time.time()) + lifetime}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"head.{body}.sign"
