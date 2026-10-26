"""The ƏDV deposit account from the tax portal (D112): its operations read into the bank
module's statements — what each one is, which of them the books already have, the
balance at the end of each day.

The portal's operation (POST vatacc/…/operation/find.outbox) is money in or out of the
deposit account: from or to another taxpayer's deposit account (SUB_TO_SUB), from a bank
current account (CURRENT_TO_SUB — a customer pays the ƏDV from its bank; the receipt
number is then "nb"), to the budget (SUB_TO_BUDGET). The e-qaimə it pays are listed with
their ƏDV; an advance names none (the purpose may: "ƏDV köçürməsi-MT2604 11863435")."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from modern_gl.application.bank.imported import ImportedOperation
from modern_gl.application.bank.operations import (
    CUSTOMER,
    IN,
    OUT,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    last_lines,
)
from modern_gl.application.bank.places import BankPlace
from modern_gl.application.bank.statement import StatementLine, statement
from modern_gl.domain.dates import next_day
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import portal_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.infrastructure.etaxes import EtaxesClient

DONE = "SUCCESS"  # «Əməliyyat icra olundu»; another status did not move the money
TAXPAYER, BANK = "TAXPAYER", "BANK"  # where the money came from or went: anything else
# (BUDGET, the customs) is a tax
# an e-qaimə number in a purpose of payment — MT, or AA of an advance e-qaimə (the bank
# breaks the purpose into lines of 35 characters anywhere, a person types a space after
# the month: read without spaces)
INVOICE_IN_TEXT = re.compile(r"(?:MT|AA)\d{12}", re.IGNORECASE)


@dataclass(frozen=True)
class DepositOperation:
    """One operation of the portal, in minor units."""

    portal_id: str
    receipt: str  # the 16-digit number of the document, or "nb"
    day: str  # ISO date
    moment: str  # "20261022131737": the order within a day
    direction: str  # IN or OUT
    amount: int
    tin: str  # the other side's VÖEN
    name: str  # its name on the portal
    kind: str  # SUPPLIER, CUSTOMER, TAX or TRANSFER
    memo: str
    invoices: tuple[tuple[str, int | None], ...] = ()  # (e-qaimə, its ƏDV; None — unknown)
    done: bool = True

    @property
    def reference(self) -> str:
        """What the operation is known by in the books: the receipt number, else the
        portal's id (a payment from a bank has no receipt number)."""
        return self.receipt if self.receipt.isdigit() else self.portal_id

    @property
    def net(self) -> int:
        return self.amount if self.direction == IN else -self.amount


def parse_operation(raw: dict, own_tin: str = "") -> DepositOperation:
    """An operation as the portal gives it."""
    direction = IN if raw.get("paymentType") == "INCOME" else OUT
    amount = raw.get("income") if direction == IN else raw.get("expense")
    tin = str(raw.get("tin") or "")
    destination = str(raw.get("destination") or "")
    if own_tin and tin == own_tin:
        kind = TRANSFER  # the company's own bank account tops the deposit up
    elif destination in (TAXPAYER, BANK):
        kind = CUSTOMER if direction == IN else SUPPLIER
    else:
        kind = TAX
    memo = " ".join(str(raw.get("explanation") or "").replace("\n", "").split())
    listed = tuple(
        (normalize_invoice(str(i.get("serialNumber"))) or "", portal_minor(i.get("vat")))
        for i in raw.get("invoices") or ()
        if i.get("serialNumber")
    )
    invoices: tuple[tuple[str, int | None], ...] = listed or tuple(
        (number, None) for number in invoices_in(str(raw.get("explanation") or ""))
    )
    moment = str(raw.get("operationDate") or "")
    return DepositOperation(
        portal_id=str(raw.get("id") or ""),
        receipt=str(raw.get("receiptNumber") or ""),
        day=f"{moment[:4]}-{moment[4:6]}-{moment[6:8]}",
        moment=moment,
        direction=direction,
        amount=portal_minor(amount),
        tin=tin,
        name=" ".join(str(raw.get("name") or "").split()),
        kind=kind,
        memo=memo,
        invoices=tuple(sorted(invoices)),  # the oldest first: the number grows with time
        done=raw.get("operationStatus") == DONE,
    )


@dataclass(frozen=True)
class DepositFetched:
    """What the portal gave: the operations from the period's first day up to now (the
    balance of a day is counted back from the balance now), the balance now."""

    operations: list[DepositOperation]
    balance: int
    date_from: str
    date_to: str  # the period loaded: the operations after it only count the balance


def fetch_deposit(
    client: EtaxesClient,
    date_from: date,
    today: date,
    own_tin: str,
    progress: Callable[[str], None],
    date_to: date | None = None,
) -> DepositFetched:
    """The operations of the period `date_from`–`date_to` (else up to today). The balance
    first, then the operations up to today: one that comes in meanwhile is left for the
    next time, so the balance of each day stays right."""
    progress(tr("Остаток ƏDV depozit на портале…"))
    balance, read_at = client.vat_deposit_balance()
    cutoff = "".join(ch for ch in read_at if ch.isdigit())[:14]
    operations = []
    for n, raw in enumerate(client.vat_deposit_operations(date_from, today), 1):
        progress(tr("Загружено операций: {n}", n=n))
        op = parse_operation(raw, own_tin)
        if not cutoff or op.moment <= cutoff:
            operations.append(op)
    last = min(date_to or today, today)
    return DepositFetched(
        operations, portal_minor(balance), date_from.isoformat(), last.isoformat()
    )


@dataclass(frozen=True)
class PortalLoad:
    """A period loaded from the portal into a bank account (D115)."""

    date_from: str
    date_to: str
    loaded_at: str
    operations: int

    @property
    def closed_to(self) -> str:
        """The last day of the period that had ended when it was loaded: a day loaded on
        that day may get an operation later — it is loaded again."""
        moment = datetime.fromisoformat(self.loaded_at)
        if moment.tzinfo is not None:
            moment = moment.astimezone()  # the portal's day is the user's day
        return min(self.date_to, (moment.date() - timedelta(days=1)).isoformat())


def portal_loads(conn: Connection, company_id: int, place: BankPlace) -> list[PortalLoad]:
    """The periods loaded into the account, the earliest first."""
    return [
        PortalLoad(r["date_from"], r["date_to"], r["loaded_at"], r["operations"])
        for r in conn.execute(
            "SELECT date_from, date_to, loaded_at, operations FROM bank_portal_loads "
            "WHERE company_id = ? AND account_id = ? AND COALESCE(value_id, 0) = ? "
            "ORDER BY date_from, date_to",
            (company_id, place.account_id, place.value_id or 0),
        )
    ]


def loaded_spans(loads: Sequence[PortalLoad]) -> list[tuple[str, str]]:
    """The loaded periods joined: overlapping ones and ones that go on the next day; a day
    loaded before it ended is not counted (`PortalLoad.closed_to`)."""
    spans: list[tuple[str, str]] = []
    closed = [(x.date_from, x.closed_to) for x in loads if x.date_from <= x.closed_to]
    for first, last in sorted(closed):
        if spans and first <= next_day(spans[-1][1]):
            spans[-1] = (spans[-1][0], max(spans[-1][1], last))
        else:
            spans.append((first, last))
    return spans


def loaded_already(loads: Sequence[PortalLoad], date_from: str, date_to: str) -> bool:
    """Every day of the period was loaded before."""
    return any(a <= date_from and date_to <= b for a, b in loaded_spans(loads))


def next_to_load(loads: Sequence[PortalLoad]) -> str | None:
    """The day to load from: after the last loaded one (a day loaded before it ended — that
    day again); nothing loaded — None."""
    spans = loaded_spans(loads)
    if spans:
        return next_day(spans[-1][1])
    return min((x.date_from for x in loads), default=None)


def unfinished_days(loads: Sequence[PortalLoad]) -> list[str]:
    """The days loaded before they ended that no later load covers: to load again."""
    spans = loaded_spans(loads)
    days = {x.date_to for x in loads if x.closed_to < x.date_to}
    return sorted(d for d in days if not any(a <= d <= b for a, b in spans))


def invoices_in(text: str) -> list[str]:
    """The e-qaimə numbers named in a purpose of payment, each once."""
    found: list[str] = []
    for match in INVOICE_IN_TEXT.findall("".join(text.split())):
        number = normalize_invoice(match) or ""
        if number not in found:
            found.append(number)
    return found


def day_closings(operations: Sequence[DepositOperation], balance: int) -> dict[str, int]:
    """The balance at the end of every day with operations, counted back from the balance
    now: the portal gives no balance per day."""
    closings: dict[str, int] = {}
    later = 0  # what moved the account after the day
    for day in sorted({op.day for op in operations if op.done}, reverse=True):
        closings[day] = balance - later
        later += sum(op.net for op in operations if op.done and op.day == day)
    return closings


@dataclass
class DepositPlan:
    """What the import does with the portal's operations of a period."""

    new: list[DepositOperation] = field(default_factory=list)
    known: list[DepositOperation] = field(default_factory=list)  # in the books already
    # an operation entered by hand (the ƏDV part of a payment, D69) gets its reference
    linked: list[tuple[DepositOperation, int]] = field(default_factory=list)


def plan_deposit_import(
    conn: Connection,
    company_id: int,
    place: BankPlace,
    operations: Sequence[DepositOperation],
) -> DepositPlan:
    """Which operations the books have: by the reference, else a line of the statement
    on the same day with the same amount and direction (entered by hand; a transfer from
    the company's bank account, typed on that account's statement)."""
    plan = DepositPlan()
    done = sorted((op for op in operations if op.done), key=lambda op: op.moment)
    if not done:
        return plan
    references = deposit_references(conn, company_id, place)
    lines = statement(conn, company_id, place, done[0].day, done[-1].day).lines
    free = [line for line in lines if references.get(line.document_id, "") == ""]
    for op in done:
        if op.reference in references.values():
            plan.known.append(op)
            continue
        line = same_line(free, op)
        if line is None:
            plan.new.append(op)
            continue
        free.remove(line)
        operation_id = _operation_of(conn, company_id, line.document_id)
        if operation_id is None:
            plan.known.append(op)  # a journal entry, a transfer: nothing to mark
        else:
            plan.linked.append((op, operation_id))
    return plan


def same_line(lines: list[StatementLine], op: DepositOperation) -> StatementLine | None:
    money = (lambda line: line.money_in) if op.direction == IN else (lambda line: line.money_out)
    return next((x for x in lines if x.doc_date == op.day and money(x) == op.amount), None)


def deposit_references(conn: Connection, company_id: int, place: BankPlace) -> dict[int, str]:
    """document -> reference of the bank operations on the deposit account."""
    return {
        r["document_id"]: r["reference"]
        for r in conn.execute(
            "SELECT document_id, reference FROM bank_operations "
            "WHERE company_id = ? AND account_id = ? AND (? IS NULL OR ? IN (sc1, sc2, sc3))",
            (company_id, place.account_id, place.value_id, place.value_id),
        )
    }


def _operation_of(conn: Connection, company_id: int, document_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM bank_operations WHERE company_id = ? AND document_id = ?",
        (company_id, document_id),
    ).fetchone()
    return row["id"] if row else None


def previous_lines(
    conn: Connection,
    company_id: int,
    place: BankPlace,
    op: ImportedOperation,
    counterparty_id: int | None,
) -> list[BankLine]:
    """What this kind of money went to (came from) last time: the counterparty's last
    operation; without one — the last of the kind on the account (a tax from the deposit
    account: 68.2 ƏDV; salary to the cards)."""
    if counterparty_id is not None:
        return last_lines(conn, company_id, op.direction, counterparty_id)
    row = conn.execute(
        "SELECT l.account_id, l.sc1, l.sc2, l.sc3 FROM bank_operations o "
        "JOIN documents d ON d.id = o.document_id "
        "JOIN bank_operation_lines l ON l.operation_id = o.id AND l.account_id IS NOT NULL "
        "WHERE o.company_id = ? AND o.kind = ? AND o.direction = ? AND o.account_id = ? "
        "ORDER BY d.doc_date DESC, d.number DESC, l.line_no LIMIT 1",
        (company_id, op.kind, op.direction, place.account_id),
    ).fetchone()
    if row is None:
        return []
    return [BankLine(row["account_id"], 0, (row["sc1"], row["sc2"], row["sc3"]))]
