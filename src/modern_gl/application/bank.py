"""Bank operations (D46): what was entered, the bank accounts of the company, and the
statement of one of them. Amounts are minor units of the operation's currency (None =
manat); the statement is read from postings, so every document on the account is in it."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.common import pad_subconto
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import sort_key, tr

IN, OUT = "in", "out"  # mədaxil: money comes to the bank account; məxaric: it leaves
SUPPLIER, CUSTOMER, TAX, SALARY, FEE, TRANSFER, OTHER = (
    "supplier",
    "customer",
    "tax",
    "salary",
    "fee",
    "transfer",
    "other",
)
# what an operation is (Russian name — a translation key); the order of the form's list
KINDS = (
    (SUPPLIER, "Поставщик"),
    (CUSTOMER, "Покупатель"),
    (TAX, "Налоги"),
    (SALARY, "Зарплата"),
    (FEE, "Комиссия банка"),
    (TRANSFER, "Перевод между своими счетами"),
    (OTHER, "Прочее"),
)
KIND_NAMES = dict(KINDS)
# A line's account when nothing was paid to the counterparty before: the first account
# of the type (60, 62, 68.1, 70; another bank account for a transfer). A bank fee goes to
# the account of the settings (role bank_fee).
KIND_TYPES = {
    SUPPLIER: "payable",
    CUSTOMER: "receivable",
    TAX: "tax_payable",
    SALARY: "payroll",
    TRANSFER: "bank",
}
# Bank accounts of the module: money on current accounts, and the ƏDV deposit account
BANK_TYPES = ("bank", "vat_deposit")
# The ƏDV deposit account pays and receives only ƏDV (D41): to a supplier's deposit
# account, from a customer, to the budget, or between deposit accounts.
VAT_DEPOSIT_KINDS = (SUPPLIER, CUSTOMER, TAX, TRANSFER)


@dataclass(frozen=True)
class BankLine:
    """Where the money goes (məxaric) or comes from (mədaxil): an account, its subconto
    (a contract, a tax, an employee…) and the e-qaimə the payment closes."""

    account_id: int | None  # None only in a draft
    amount: int  # minor units of the operation's currency; 0 only in a draft
    subconto: Sequence[int | None] = ()
    invoice: str = ""


@dataclass(frozen=True)
class BankOperationInput:
    doc_date: str
    direction: str  # IN or OUT
    account_id: int | None  # the bank account's GL account; None only in a draft
    lines: Sequence[BankLine] = ()
    kind: str = OTHER
    subconto: Sequence[int | None] = ()  # of the bank account (Kapital Bank AZN)
    currency_id: int | None = None  # None: manat
    counterparty_id: int | None = None  # fills the counterparty of every line
    memo: str = ""  # the purpose of payment
    reference: str = ""  # reference of the bank statement line

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines)


@dataclass(frozen=True)
class BankOperation(BankOperationInput):
    id: int = 0
    document_id: int = 0
    number: int = 0
    status: str = "draft"


def load_bank_operation(
    conn: sqlite3.Connection, company_id: int, operation_id: int
) -> BankOperation:
    r = conn.execute(
        "SELECT o.*, d.number, d.doc_date, d.memo, d.status FROM bank_operations o "
        "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
        "WHERE o.company_id = ? AND o.id = ?",
        (company_id, operation_id),
    ).fetchone()
    if r is None:
        raise NotFoundError(tr("документ {id} не найден", id=operation_id))
    lines = tuple(
        BankLine(x["account_id"], x["amount"], (x["sc1"], x["sc2"], x["sc3"]), x["invoice"])
        for x in conn.execute(
            "SELECT * FROM bank_operation_lines WHERE company_id = ? AND operation_id = ? "
            "ORDER BY line_no",
            (company_id, operation_id),
        )
    )
    return BankOperation(
        doc_date=r["doc_date"],
        direction=r["direction"],
        account_id=r["account_id"],
        lines=lines,
        kind=r["kind"],
        subconto=(r["sc1"], r["sc2"], r["sc3"]),
        currency_id=r["currency_id"],
        counterparty_id=r["counterparty_id"],
        memo=r["memo"],
        reference=r["reference"],
        id=r["id"],
        document_id=r["document_id"],
        number=r["number"],
        status=r["status"],
    )


def bank_operation_of_document(
    conn: sqlite3.Connection, company_id: int, document_id: int
) -> int | None:
    """The bank operation whose postings these are."""
    row = conn.execute(
        "SELECT id FROM bank_operations WHERE company_id = ? AND document_id = ?",
        (company_id, document_id),
    ).fetchone()
    return row[0] if row else None


def find_bank_operation(conn: sqlite3.Connection, company_id: int, reference: str) -> int | None:
    """An operation already entered for a bank statement line (future statement import)."""
    reference = reference.strip()
    if not reference:
        return None
    row = conn.execute(
        "SELECT id FROM bank_operations WHERE company_id = ? AND reference = ? ORDER BY id LIMIT 1",
        (company_id, reference),
    ).fetchone()
    return row[0] if row else None


def last_lines(
    conn: sqlite3.Connection, company_id: int, direction: str, counterparty_id: int
) -> list[BankLine]:
    """What the money of this counterparty went to (came from) last time: the accounts and
    subconto of its latest operation of the same direction, without amounts and e-qaimə.
    Payments made through the journal count too: the latest posting between a bank
    account and an account with this counterparty."""
    row = conn.execute(
        "SELECT o.id FROM bank_operations o JOIN documents d ON d.id = o.document_id "
        "WHERE o.company_id = ? AND o.direction = ? AND o.counterparty_id = ? "
        "ORDER BY d.doc_date DESC, d.number DESC LIMIT 1",
        (company_id, direction, counterparty_id),
    ).fetchone()
    if row is not None:
        return [
            BankLine(r["account_id"], 0, (r["sc1"], r["sc2"], r["sc3"]))
            for r in conn.execute(
                "SELECT account_id, sc1, sc2, sc3 FROM bank_operation_lines "
                "WHERE operation_id = ? AND account_id IS NOT NULL ORDER BY line_no",
                (row[0],),
            )
        ]
    # out: the bank account is credited, the counterparty's account debited
    bank_col, other_col, other = (
        ("credit_account_id", "debit_account_id", "dt")
        if direction == OUT
        else ("debit_account_id", "credit_account_id", "ct")
    )
    found = conn.execute(
        f"""
        SELECT p.{other_col} AS account_id, p.{other}_sc1 AS sc1, p.{other}_sc2 AS sc2,
               p.{other}_sc3 AS sc3
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN accounts b ON b.id = p.{bank_col}
        WHERE p.company_id = :c AND b.account_type IN ('bank', 'vat_deposit')
          AND :v IN (p.{other}_sc1, p.{other}_sc2, p.{other}_sc3)
        ORDER BY d.doc_date DESC, d.number DESC, p.line_no LIMIT 1
        """,
        {"c": company_id, "v": counterparty_id},
    ).fetchone()
    if found is None:
        return []
    return [BankLine(found["account_id"], 0, (found["sc1"], found["sc2"], found["sc3"]))]


# ---- bank accounts and their statements -------------------------------------------------


@dataclass(frozen=True)
class BankPlace:
    """A bank account of the company: a GL account (51) and an element of its bank account
    directory (Kapital Bank AZN), or the GL account alone when it has no directory."""

    account_id: int
    value_id: int | None
    name: str
    account_code: str
    currency_id: int | None  # the element's currency; None: manat (or not fixed)
    currency: str  # its code, "" for manat
    account_type: str | None

    @property
    def key(self) -> tuple[int, int | None]:
        return self.account_id, self.value_id

    @property
    def subconto(self) -> tuple[int | None, int | None, int | None]:
        return pad_subconto(() if self.value_id is None else (self.value_id,))


def bank_places(conn: sqlite3.Connection, company_id: int) -> list[BankPlace]:
    """Bank accounts: each element of the bank account directory under the GL accounts it
    was used on; an element never used is under the first account that fits its currency
    (a USD account under 52, not 51). A GL account without the directory is one place."""
    accounts = conn.execute(
        """
        SELECT a.id, COALESCE(a.code, a.name) AS code, a.name, a.currency, a.account_type,
               CASE WHEN k1.code = 'bank_account' THEN 1
                    WHEN k2.code = 'bank_account' THEN 2
                    WHEN k3.code = 'bank_account' THEN 3 END AS position
        FROM accounts a
        LEFT JOIN subconto_kinds k1 ON k1.id = a.sc1_kind_id
        LEFT JOIN subconto_kinds k2 ON k2.id = a.sc2_kind_id
        LEFT JOIN subconto_kinds k3 ON k3.id = a.sc3_kind_id
        WHERE a.company_id = ? AND a.is_group = 0 AND a.active = 1
          AND (a.account_type IN ('bank', 'vat_deposit')
               OR (a.account_type IS NULL AND 'bank_account' IN (k1.code, k2.code, k3.code)))
        ORDER BY a.code IS NULL, a.code, a.name
        """,
        (company_id,),
    ).fetchall()
    values = conn.execute(
        "SELECT v.id, v.name, v.currency_id, c.code AS currency FROM subconto_values v "
        "JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'bank_account' "
        "LEFT JOIN currencies c ON c.id = v.currency_id "
        "WHERE v.company_id = ? AND v.active = 1",
        (company_id,),
    ).fetchall()
    used = {
        (r[0], r[1])
        for r in conn.execute(
            """
            SELECT debit_account_id, value FROM (
                SELECT debit_account_id, dt_sc1 AS value FROM postings WHERE company_id = :c
                UNION SELECT debit_account_id, dt_sc2 FROM postings WHERE company_id = :c
                UNION SELECT debit_account_id, dt_sc3 FROM postings WHERE company_id = :c
                UNION SELECT credit_account_id, ct_sc1 FROM postings WHERE company_id = :c
                UNION SELECT credit_account_id, ct_sc2 FROM postings WHERE company_id = :c
                UNION SELECT credit_account_id, ct_sc3 FROM postings WHERE company_id = :c
                UNION SELECT account_id, sc1 FROM bank_operations WHERE company_id = :c
                UNION SELECT account_id, sc2 FROM bank_operations WHERE company_id = :c
                UNION SELECT account_id, sc3 FROM bank_operations WHERE company_id = :c
            ) WHERE value IS NOT NULL
            """,
            {"c": company_id},
        )
    }

    def fits(account: sqlite3.Row, value: sqlite3.Row) -> bool:
        if account["currency"] == 0:  # manat only
            return value["currency_id"] is None
        if account["currency"] == 1:  # currency only
            return value["currency_id"] is not None
        return True

    with_directory = [a for a in accounts if a["position"] is not None]
    places: list[BankPlace] = []
    for account in accounts:
        if account["position"] is None:
            places.append(
                BankPlace(
                    account["id"],
                    None,
                    account["name"],
                    account["code"],
                    None,
                    "",
                    account["account_type"],
                )
            )
            continue
        for value in values:
            here = (account["id"], value["id"]) in used
            if not here:
                anywhere = any((a["id"], value["id"]) in used for a in with_directory)
                first = next((a for a in with_directory if fits(a, value)), None)
                here = not anywhere and first is not None and first["id"] == account["id"]
            if here:
                places.append(
                    BankPlace(
                        account["id"],
                        value["id"],
                        value["name"],
                        account["code"],
                        value["currency_id"],
                        value["currency"] or "",
                        account["account_type"],
                    )
                )
    order = {a["id"]: i for i, a in enumerate(accounts)}
    places.sort(key=lambda p: (order[p.account_id], sort_key(p.name)))
    return places


@dataclass
class StatementLine:
    document_id: int
    number: int
    doc_date: str
    memo: str
    status: str  # a draft bank operation is listed, but it does not move the balance
    money_in: int
    money_out: int
    balance: int | None  # after this line; None for a draft
    counterparty: str  # names on the other side, «, »-separated
    corr: str  # codes of the other side's accounts
    kind: str = ""  # a bank operation's kind, "conversion", or "" (journal, warehouse…)
    direction: str = ""  # of a bank operation


@dataclass
class Statement:
    opening: int
    lines: list[StatementLine] = field(default_factory=list)
    currency: str = ""  # "" manat

    @property
    def closing(self) -> int:
        posted = [line.balance for line in self.lines if line.balance is not None]
        return posted[-1] if posted else self.opening

    @property
    def total_in(self) -> int:
        return sum(line.money_in for line in self.lines if line.status == "posted")

    @property
    def total_out(self) -> int:
        return sum(line.money_out for line in self.lines if line.status == "posted")


def statement(
    conn: sqlite3.Connection,
    company_id: int,
    place: BankPlace,
    date_from: str,
    date_to: str,
) -> Statement:
    """Every document that moved the bank account in the period (one row per document),
    with the running balance, in the account's currency; draft bank operations too."""
    params = {
        "c": company_id,
        "a": place.account_id,
        "v": place.value_id,
        "from": iso_date(date_from),
        "to": iso_date(date_to),
    }
    amount = "COALESCE(p.currency_amount, 0)" if place.currency_id is not None else "p.amount"
    sides = []
    for own, other, sign in (("dt", "ct", 1), ("ct", "dt", -1)):
        own_col = "debit_account_id" if own == "dt" else "credit_account_id"
        other_col = "credit_account_id" if own == "dt" else "debit_account_id"
        sides.append(
            f"""
            SELECT p.document_id, {sign} * {amount} AS net, p.{other_col} AS corr_id,
                   p.{other}_sc1 AS o1, p.{other}_sc2 AS o2, p.{other}_sc3 AS o3
            FROM postings p
            WHERE p.company_id = :c AND p.{own_col} = :a
              AND (:v IS NULL OR :v IN (p.{own}_sc1, p.{own}_sc2, p.{own}_sc3))
            """
        )
    moves = " UNION ALL ".join(sides)
    rows = conn.execute(
        f"""
        WITH moves AS ({moves}),
        docs AS (
            SELECT d.id, d.number, d.doc_date, d.memo,
                   SUM(CASE WHEN m.net > 0 THEN m.net ELSE 0 END) AS money_in,
                   SUM(CASE WHEN m.net < 0 THEN -m.net ELSE 0 END) AS money_out
            FROM moves m
            JOIN documents d ON d.id = m.document_id AND d.status = 'posted'
            JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
            WHERE d.doc_date <= :to
            GROUP BY d.id
        )
        SELECT docs.*,
               (SELECT GROUP_CONCAT(name, ', ') FROM (
                    SELECT DISTINCT v.name FROM moves m
                    JOIN subconto_values v ON v.id IN (m.o1, m.o2, m.o3)
                    JOIN subconto_kinds k ON k.id = v.kind_id
                     AND k.code IN ('counterparty', 'employee', 'bank_account')
                    WHERE m.document_id = docs.id)) AS counterparty,
               (SELECT GROUP_CONCAT(code, ', ') FROM (
                    SELECT DISTINCT COALESCE(a.code, a.name) AS code FROM moves m
                    JOIN accounts a ON a.id = m.corr_id
                    WHERE m.document_id = docs.id)) AS corr,
               o.kind, o.direction,
               (SELECT 1 FROM currency_conversions x
                WHERE x.document_id = docs.id OR x.credit_document_id = docs.id) AS conversion
        FROM docs
        LEFT JOIN bank_operations o ON o.document_id = docs.id
        ORDER BY docs.doc_date, docs.number
        """,
        params,
    ).fetchall()
    result = Statement(opening=0, currency=place.currency)
    balance = 0
    for r in rows:
        balance += r["money_in"] - r["money_out"]
        if r["doc_date"] < params["from"]:
            result.opening = balance
            continue
        kind = r["kind"] or ("conversion" if r["conversion"] else "")
        result.lines.append(
            StatementLine(
                r["id"],
                r["number"],
                r["doc_date"],
                r["memo"],
                "posted",
                r["money_in"],
                r["money_out"],
                balance,
                r["counterparty"] or "",
                r["corr"] or "",
                kind,
                r["direction"] or "",
            )
        )
    for d in _drafts(conn, place, params):
        result.lines.append(d)
    result.lines.sort(key=lambda line: (line.doc_date, line.number))
    return result


def _drafts(conn: sqlite3.Connection, place: BankPlace, params: dict) -> list[StatementLine]:
    rows = conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, d.memo, o.kind, o.direction,
               COALESCE(SUM(x.amount), 0) AS total, v.name AS counterparty,
               (SELECT GROUP_CONCAT(code, ', ') FROM (
                    SELECT DISTINCT COALESCE(a.code, a.name) AS code
                    FROM bank_operation_lines y JOIN accounts a ON a.id = y.account_id
                    WHERE y.operation_id = o.id)) AS corr
        FROM bank_operations o
        JOIN documents d ON d.id = o.document_id AND d.status = 'draft'
        LEFT JOIN bank_operation_lines x ON x.operation_id = o.id
        LEFT JOIN subconto_values v ON v.id = o.counterparty_id
        WHERE o.company_id = :c AND o.account_id = :a
          AND (:v IS NULL OR :v IN (o.sc1, o.sc2, o.sc3))
          AND d.doc_date BETWEEN :from AND :to
        GROUP BY o.id
        """,
        params,
    ).fetchall()
    return [
        StatementLine(
            r["id"],
            r["number"],
            r["doc_date"],
            r["memo"],
            "draft",
            r["total"] if r["direction"] == IN else 0,
            r["total"] if r["direction"] == OUT else 0,
            None,
            r["counterparty"] or "",
            r["corr"] or "",
            r["kind"],
            r["direction"],
        )
        for r in rows
    ]


def place_balance(conn: sqlite3.Connection, company_id: int, place: BankPlace, day: str) -> int:
    """The balance of a bank account at the end of the day, in its currency."""
    amount = "COALESCE(p.currency_amount, 0)" if place.currency_id is not None else "p.amount"
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE
            WHEN p.debit_account_id = :a
                 AND (:v IS NULL OR :v IN (p.dt_sc1, p.dt_sc2, p.dt_sc3)) THEN {amount}
            ELSE 0 END), 0)
             - COALESCE(SUM(CASE
            WHEN p.credit_account_id = :a
                 AND (:v IS NULL OR :v IN (p.ct_sc1, p.ct_sc2, p.ct_sc3)) THEN {amount}
            ELSE 0 END), 0)
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
        WHERE p.company_id = :c AND d.doc_date <= :day
          AND (p.debit_account_id = :a OR p.credit_account_id = :a)
        """,
        {"c": company_id, "a": place.account_id, "v": place.value_id, "day": iso_date(day)},
    ).fetchone()
    return row[0]


def default_memo(direction: str, kind: str, counterparty: str = "") -> str:
    """The purpose of payment when none is typed: what it is, and to whom."""
    out, name = direction == OUT, counterparty
    if kind == SUPPLIER:
        text = (
            tr("Оплата поставщику {name}", name=name)
            if out
            else tr("Возврат от поставщика {name}", name=name)
        )
    elif kind == CUSTOMER:
        text = (
            tr("Возврат покупателю {name}", name=name)
            if out
            else tr("Оплата от покупателя {name}", name=name)
        )
    elif kind == TAX:
        text = tr("Уплата налогов") if out else tr("Возврат налогов")
    elif kind == SALARY:
        text = tr("Выплата зарплаты") if out else tr("Возврат зарплаты")
    elif kind == FEE:
        text = tr("Комиссия банка") if out else tr("Возврат комиссии банка")
    elif kind == TRANSFER:
        text = tr("Перевод между своими счетами")
    elif name:
        text = tr("Платёж {name}", name=name) if out else tr("Поступление от {name}", name=name)
    else:
        text = tr("Прочий расход") if out else tr("Прочий приход")
    return text.strip()
