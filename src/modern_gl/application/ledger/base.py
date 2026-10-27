"""State and lookups shared by every group of ledger use cases."""

from __future__ import annotations

from modern_gl.application.common import company_row, write_audit
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row


def clean_code(code: str | None) -> str | None:
    """Account codes are optional: blank means no code."""
    return (code or "").strip() or None


def account_label(account: Row) -> str:
    """How an account is named in messages: its code, or its name if it has none."""
    return account["code"] or account["name"]


class LedgerBase:
    """The connection, the author of changes (`actor`, written to `audit_events`) and the
    lookups every use case shares; a lookup raises NotFoundError, never writes."""

    def __init__(self, conn: Connection, actor: str = "local") -> None:
        self.conn = conn
        self.actor = actor

    def _company(self, company_id: int) -> Row:
        return company_row(self.conn, company_id)

    def _account(self, company_id: int, account: int | str) -> Row:
        """An account by id (int) or by code (str)."""
        by_id = isinstance(account, int)
        row = self.conn.execute(
            f"SELECT * FROM accounts WHERE company_id = ? AND {'id' if by_id else 'code'} = ?",
            (company_id, account),
        ).fetchone()
        if row is None:  # an id means nothing to the user
            raise NotFoundError(
                tr("счёт не найден") if by_id else tr("счёт {code} не найден", code=account)
            )
        return row

    def _currency(self, company_id: int, currency: int | str) -> Row:
        by_id = isinstance(currency, int)
        row = self.conn.execute(
            f"SELECT * FROM currencies WHERE company_id = ? AND {'id' if by_id else 'code'} = ?",
            (company_id, currency if by_id else currency.upper()),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                tr("валюта не найдена") if by_id else tr("валюта {code} не найдена", code=currency)
            )
        return row

    def _subconto_value(self, company_id: int, value_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM subconto_values WHERE company_id = ? AND id = ?", (company_id, value_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("элемент справочника не найден"))
        return row

    def _kind_id(self, company_id: int, code: str) -> int:
        """A kind of directory by its code (counterparty, item, warehouse…)."""
        row = self.conn.execute(
            "SELECT id FROM subconto_kinds WHERE company_id = ? AND code = ?", (company_id, code)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("вид субконто {code} не найден", code=code))
        return row["id"]

    def _audit(
        self, company_id: int | None, entity: str, entity_id: int, action: str, details: dict
    ) -> None:
        write_audit(self.conn, company_id, self.actor, entity, entity_id, action, details)
