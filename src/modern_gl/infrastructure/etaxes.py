"""The API of new.e-taxes.gov.az: the e-qaimə, as the user's etaxes-ext extension calls it
(its `lib/api.js`, `docs/api-reference.md`), and the ƏDV deposit account (D112, as the
portal's own page «ƏDV depozit hesabı» calls it).

Signing in is the portal's own (ASAN İmza in its page); this client only carries the JWT
the portal keeps in `localStorage['aztax-jwt']`. The token lives 10 minutes. Amounts come
as JSON numbers: they are read as Decimal, never float."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from modern_gl.domain.eqaime import TURNOVER
from modern_gl.i18n import language, tr

BASE_URL = "https://new.e-taxes.gov.az"
PORTAL_TOKEN_KEY = "aztax-jwt"  # noqa: S105 the key's name in the page's storage, not a token
INBOX = "/api/po/invoice/public/v2/invoice/find.inbox"  # received: purchases
OUTBOX = "/api/po/invoice/public/v2/invoice/find.outbox"  # sent: sales
DETAIL = "/api/po/invoice/public/v2/invoice/"
VAT_ACCOUNT = "/api/po/vatacc/public/v1/accountInfo"  # the ƏDV deposit account's balance
VAT_OPERATIONS = "/api/po/vatacc/public/v1/operation/find.outbox"  # its operations
PAGE_SIZE = 50
APPROVED = TURNOVER  # the API takes one status at a time


class PortalError(Exception):
    """The portal did not answer as expected; the message is for the user."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code  # the HTTP status, 0 if the portal was not reached


class TokenExpiredError(PortalError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


# (method, url, headers, body) -> response; replaced in tests
Send = Callable[[str, str, dict[str, str], bytes | None], Response]


def urllib_send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> Response:
    if not url.startswith("https://"):
        raise ValueError(f"the portal is reached only over https: {url}")
    # S310: the scheme is checked just above
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=90) as answer:  # noqa: S310
            return Response(answer.status, answer.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read())


def portal_date(day: date, time: str) -> str:
    """The date format of the request body: "DD-MM-YYYY HH:MM"."""
    return f"{day:%d-%m-%Y} {time}"


def _said(body: bytes) -> str:
    """What the portal says in an error: its message in the interface language
    ({"message": {"az": "Sorğu məlumatları yalnışdır…"}}), else the start of the body."""
    try:
        message = json.loads(body).get("message")
    except (ValueError, AttributeError):
        message = None
    if isinstance(message, dict):
        message = message.get(language()) or message.get("az") or next(iter(message.values()), "")
    if isinstance(message, str) and message:
        return message
    return body[:120].decode(errors="replace")


class EtaxesClient:
    def __init__(self, token: str, send: Send = urllib_send) -> None:
        self.token = token
        self.send = send

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        headers = {
            "x-authorization": f"Bearer {self.token}",  # not Authorization: the portal's way
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        data = None if body is None else json.dumps(body).encode()
        try:
            answer = self.send(method, f"{BASE_URL}{path}", headers, data)
        except OSError as exc:
            raise PortalError(tr("портал недоступен: {error}", error=exc)) from exc
        if answer.status == 401:
            raise TokenExpiredError(tr("вход на портал истёк — войдите ещё раз"))
        if answer.status >= 400:
            raise PortalError(
                tr("портал ответил {code}: {text}", code=answer.status, text=_said(answer.body)),
                answer.status,
            )
        return json.loads(answer.body, parse_float=Decimal)

    def invoices(
        self,
        outgoing: bool,
        date_from: date,
        date_to: date,
        statuses: tuple[str, ...] = APPROVED,
    ) -> Iterator[dict]:
        """The e-qaimə list rows of a period: received (purchases) or sent (sales)."""
        for status in statuses:
            offset = 0
            while True:
                data = self._call(
                    "POST",
                    OUTBOX if outgoing else INBOX,
                    {
                        "sortBy": "creationDate",
                        "sortAsc": True,
                        "statuses": [status],
                        "types": None,
                        "kinds": None,
                        "serialNumber": None,
                        "senderTin": None,
                        "receiverTin": None,
                        "senderName": None,
                        "productName": None,
                        "productCode": None,
                        "receiverName": None,
                        "creationDateFrom": portal_date(date_from, "00:00"),
                        "creationDateTo": portal_date(date_to, "23:59"),
                        "amountFrom": None,
                        "amountTo": None,
                        "offset": offset,
                        "maxCount": PAGE_SIZE,
                        "actionOwner": None,
                    },
                )
                page = data.get("invoices") or []  # not «content»: the portal's field
                yield from page
                if not data.get("hasMore") or not page:
                    break
                offset += PAGE_SIZE

    def detail(self, invoice_id: str, source_system: str) -> dict:
        """One e-qaimə with its lines (items)."""
        data = self._call("GET", f"{DETAIL}{invoice_id}?sourceSystem={source_system or 'avis'}")
        return data.get("invoice", data)

    def vat_deposit_balance(self) -> tuple[Decimal, str]:
        """The ƏDV deposit account's balance now, and when the portal read it
        ("2026-10-23T12:18:35.2…")."""
        data = self._call("GET", VAT_ACCOUNT)
        return Decimal(str(data.get("mainAccount") or 0)), str(data.get("informationOn") or "")

    def vat_deposit_operations(self, date_from: date, date_to: date) -> Iterator[dict]:
        """The operations of the ƏDV deposit account in a period, all statuses."""
        offset = 0
        while True:
            data = self._call(
                "POST",
                VAT_OPERATIONS,
                {
                    "creationDateFrom": date_from.isoformat(),
                    "creationDateTo": date_to.isoformat(),
                    "accounts": None,
                    "operationTypes": [],
                    "operationStatuses": [],
                    "receiptNumber": None,
                    "taxCodes": None,
                    "offset": offset,
                    "maxCount": PAGE_SIZE,
                    "counterpartyTin": None,
                    "sortAsc": True,
                    "sortBy": "DATE",
                    "paymentTypes": None,
                },
            )
            page = data.get("operations") or []
            yield from page
            if not data.get("hasMore") or not page:
                break
            offset += PAGE_SIZE
