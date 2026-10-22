"""The bank accounts of the module as the list shows them (D78): grouped by kind —
current, currency, the ƏDV deposit, business cards — with the balance and how many
statements are not checked against the bank yet."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.bank.places import BankPlace, bank_places
from modern_gl.application.bank.statement import place_balance
from modern_gl.application.bank.statements import DIFF, OPEN, bank_statements
from modern_gl.infrastructure.db import Connection

CURRENT, CURRENCY, VAT_DEPOSIT, CARD = "current", "currency", "vat_deposit", "card"
# the groups of the list, in order (Russian name — a translation key)
ACCOUNT_KINDS = (
    (CURRENT, "Расчётные счета"),
    (CURRENCY, "Валютные счета"),
    (VAT_DEPOSIT, "Депозит ƏDV"),
    (CARD, "Бизнес-карты"),
)


@dataclass(frozen=True)
class BankAccount:
    place: BankPlace
    kind: str
    card_digits: str
    holder: str  # the employee who holds the card
    iban: str
    closed: bool
    balance: int
    last_statement: str | None  # the end of the latest statement
    unchecked: int  # statements the bank's balance is not entered for
    differences: int  # statements that do not agree with the bank

    @property
    def title(self) -> str:
        """The name, and a card's last digits: "ABB Visa ·· 4417"."""
        return f"{self.place.name} ·· {self.card_digits}" if self.card_digits else self.place.name


def default_kind(place: BankPlace) -> str:
    """The kind of an account nobody set: by its GL account and currency."""
    if place.account_type == "vat_deposit":
        return VAT_DEPOSIT
    return CURRENCY if place.currency else CURRENT


def bank_accounts(conn: Connection, company_id: int, day: str) -> list[BankAccount]:
    """Every bank account with its balance at the end of the day, in the list's order:
    by kind, then as the places go (GL account, name); closed ones as they are."""
    details = {
        (r["account_id"], r["value_id"]): r
        for r in conn.execute(
            "SELECT d.*, v.name AS holder FROM bank_account_details d "
            "LEFT JOIN subconto_values v ON v.id = d.holder_id WHERE d.company_id = ?",
            (company_id,),
        )
    }
    order = {kind: i for i, (kind, _) in enumerate(ACCOUNT_KINDS)}
    result = []
    for place in bank_places(conn, company_id):
        d = details.get(place.key)
        statements = bank_statements(conn, company_id, place)
        result.append(
            BankAccount(
                place,
                d["kind"] if d else default_kind(place),
                d["card_digits"] if d else "",
                (d["holder"] or "") if d else "",
                d["iban"] if d else "",
                bool(d["closed"]) if d else False,
                place_balance(conn, company_id, place, day),
                statements[-1].date_to if statements else None,
                sum(1 for s in statements if s.status == OPEN),
                sum(1 for s in statements if s.status == DIFF),
            )
        )
    result.sort(key=lambda a: order[a.kind])  # stable: the places' order within a kind
    return result
