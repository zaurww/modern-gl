"""The e-qaimə API of new.e-taxes.gov.az, as the user's etaxes-ext extension calls it
(its `lib/api.js`, `docs/api-reference.md`).

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

from modern_gl.i18n import tr

BASE_URL = "https://new.e-taxes.gov.az"
PORTAL_TOKEN_KEY = "aztax-jwt"  # where the portal page keeps the token
INBOX = "/api/po/invoice/public/v2/invoice/find.inbox"  # received: purchases
OUTBOX = "/api/po/invoice/public/v2/invoice/find.outbox"  # sent: sales
DETAIL = "/api/po/invoice/public/v2/invoice/"
PAGE_SIZE = 50
# statuses that count in turnover (etaxes-ext DOVRIYYE_STATUSES); the API takes one at a time
APPROVED = ("approved", "approvedBySystem", "cancelationRefused", "correctionRefused")


class PortalError(Exception):
    """The portal did not answer as expected; the message is for the user."""


class TokenExpired(PortalError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


# (method, url, headers, body) -> response; replaced in tests
Send = Callable[[str, str, dict[str, str], bytes | None], Response]


def urllib_send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> Response:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as answer:
            return Response(answer.status, answer.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read())


def portal_date(day: date, time: str) -> str:
    """The date format of the request body: "DD-MM-YYYY HH:MM"."""
    return f"{day:%d-%m-%Y} {time}"


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
            raise TokenExpired(tr("вход на портал истёк — войдите ещё раз"))
        if answer.status >= 400:
            text = answer.body[:120].decode(errors="replace")
            raise PortalError(tr("портал ответил {code}: {text}", code=answer.status, text=text))
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
