"""The accounts a sale of goods posts to, chosen for the stock account of the goods
(D-new-stock-sale-accounts): the warehouse's own table over the company's account roles.
«Товары» (41) may have another revenue and cost of sales than «Материалы» (10); a stock
account without accounts of its own takes the company's (the roles of D34)."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from modern_gl.application.inventory.model import SALE_ACCOUNT_ROLES, SALE_RETURN
from modern_gl.application.inventory.rebuild import RebuildCommands
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class SaleAccountCommands(RebuildCommands):
    def set_sale_accounts(
        self, company_id: int, accounts: Mapping[tuple[int, str], int | None]
    ) -> None:
        """The settings saved: (stock account, role) -> the account a sale of its goods
        posts to; None — the company's own again. The sales of these goods are posted
        again on the new accounts (what is in the closed period stays, D5) — all of it or,
        if a sale does not post on the new account, nothing."""
        with transaction(self.conn):
            changed = [
                stock_account_id
                for (stock_account_id, role), account_id in accounts.items()
                if self._set_sale_account(company_id, stock_account_id, role, account_id)
            ]
            if changed:
                self._repost_sales(company_id, changed)

    def _set_sale_account(
        self, company_id: int, stock_account_id: int, role: str, account_id: int | None
    ) -> bool:
        """Write one cell of the table; False when it says the same already."""
        if role not in SALE_ACCOUNT_ROLES:
            raise ValidationError(tr("неизвестная роль счёта: {role}", role=role))
        self._validate_inventory_account(company_id, stock_account_id)
        before = self._own_sale_account(company_id, stock_account_id, role)
        if before == account_id:
            return False
        if account_id is None:
            self.conn.execute(
                "DELETE FROM inventory_sale_accounts "
                "WHERE company_id = ? AND stock_account_id = ? AND role = ?",
                (company_id, stock_account_id, role),
            )
        else:
            self._require_sale_account(company_id, account_id)
            self.conn.execute(
                "INSERT INTO inventory_sale_accounts "
                "(company_id, stock_account_id, role, account_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (company_id, stock_account_id, role) "
                "DO UPDATE SET account_id = excluded.account_id",
                (company_id, stock_account_id, role, account_id),
            )
        self._audit(
            company_id,
            "inventory_sale_account",
            stock_account_id,
            "set" if account_id is not None else "clear",
            {"role": role, "before": before, "after": account_id},
        )
        return True

    def _require_sale_account(self, company_id: int, account_id: int) -> None:
        account = self._account(company_id, account_id)
        label = account["code"] or account["name"]
        if account["is_group"] or not account["active"]:
            raise ValidationError(tr("счёт {code}: нужен активный счёт проводок", code=label))
        if {"item", "warehouse"} <= set(self._account_kind_codes(company_id, account)):
            raise ValidationError(
                tr(
                    "счёт {code} — счёт запасов: выручка и себестоимость на него не идут",
                    code=label,
                )
            )

    def _repost_sales(self, company_id: int, stock_account_ids: Collection[int]) -> None:
        """The warehouse's documents again from the first sale (or return of a sale) of
        the goods on these stock accounts that is not in the closed period."""
        closed = self._company(company_id)["closed_through"] or ""
        days = [
            self.conn.execute(
                "SELECT MIN(d.doc_date) AS day FROM inventory_lines l "
                "JOIN inventory_documents d ON d.company_id = l.company_id "
                "AND d.id = l.document_id "
                "JOIN inventory_items i ON i.company_id = l.company_id AND i.id = l.item_id "
                "WHERE l.company_id = ? AND i.inventory_account_id = ? "
                "AND d.status = 'posted' AND d.doc_type IN ('sale', ?) AND d.doc_date > ?",
                (company_id, stock_account_id, SALE_RETURN, closed),
            ).fetchone()["day"]
            for stock_account_id in stock_account_ids
        ]
        first = min((day for day in days if day is not None), default=None)
        if first is not None:
            self.rebuild_postings(company_id, first)
