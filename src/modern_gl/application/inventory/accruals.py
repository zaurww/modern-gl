"""Expenses of earlier months: a receipt's accrual documents, one per month (D65)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from modern_gl.application.common import require_open
from modern_gl.application.inventory.base import InventoryBase
from modern_gl.application.inventory.model import ACCRUED_CODE
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import ACCRUED_EXPENSES
from modern_gl.domain.dates import month_name
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import Row, insert


class AccrualCommands(InventoryBase):
    def _accrue(
        self,
        company_id: int,
        doc: Row,
        lines: Sequence[Row],
        postings: list[PostingInput],
    ) -> dict[str, list[PostingInput]]:
        """The lines of a receipt whose expense belongs to an earlier month (D65): each is
        accrued on the last day of its month (Dr expense / Cr accrued expenses, the supplier
        as subconto) and the receipt closes the accrual (Dr accrued expenses / Cr supplier)
        instead of debiting the expense. Rewrites `postings` in place; returns the accrual
        postings by month. Goods are never accrued: stock comes on the receipt's date."""
        first_of_month = doc["doc_date"][:7] + "-01"
        account_id: int | None = None
        by_month: dict[str, list[PostingInput]] = {}
        for i, line in enumerate(lines):
            expense_date = line["expense_date"]
            if expense_date is None:
                continue
            if expense_date >= first_of_month:
                raise ValidationError(
                    tr(
                        "строка {line}: расход за {month} должен быть раньше месяца документа",
                        line=line["line_no"],
                        month=month_name(expense_date[:7]),
                    )
                )
            if account_id is None:
                account_id = self._accrual_account(company_id)
            p = postings[i]
            accrued_sc = self._by_kind(company_id, account_id, p.credit_subconto)
            by_month.setdefault(expense_date, []).append(
                PostingInput(
                    p.debit_account_id,
                    account_id,
                    p.amount,
                    p.debit_subconto,
                    accrued_sc,
                    p.memo,
                )
            )
            postings[i] = replace(p, debit_account_id=account_id, debit_subconto=accrued_sc)
        return dict(sorted(by_month.items()))

    def _accrual_account(self, company_id: int) -> int:
        """The accrued expenses account (76H): the role's, the only account of its type,
        or a new 76H with the counterparty directory when the chart has none."""
        account_id = self.ledger.account_role(company_id, ACCRUED_EXPENSES)
        if account_id is not None:
            return account_id
        if (
            self.conn.execute(
                "SELECT 1 FROM accounts WHERE company_id = ? AND account_type = ?",
                (company_id, ACCRUED_EXPENSES),
            ).fetchone()
            or self.conn.execute(
                "SELECT 1 FROM accounts WHERE company_id = ? AND code = ?",
                (company_id, ACCRUED_CODE),
            ).fetchone()
        ):
            raise ValidationError(
                tr(
                    "не определён счёт начисленных расходов: оставьте один активный счёт "
                    "типа «Начисленные расходы» (например, {code})",
                    code=ACCRUED_CODE,
                )
            )
        kinds = self.conn.execute(
            "SELECT id FROM subconto_kinds WHERE company_id = ? AND code = 'counterparty'",
            (company_id,),
        ).fetchall()
        return self.ledger.add_account(
            company_id,
            ACCRUED_CODE,
            tr("Начисленные расходы"),
            subconto=[row["id"] for row in kinds],
            account_type=ACCRUED_EXPENSES,
        )

    def _finish_accruals(
        self, company_id: int, doc: Row, by_month: dict[str, list[PostingInput]]
    ) -> None:
        """Post, rewrite or remove the receipt's accrual documents so that there is one per
        month of `by_month` (D65). A recalculation that changes nothing leaves an accrual in
        a closed period alone; a month no line belongs to any more loses its document."""
        existing = {
            row["expense_date"]: row
            for row in self.conn.execute(
                "SELECT * FROM inventory_accruals WHERE company_id = ? AND document_id = ?",
                (company_id, doc["id"]),
            )
        }
        for expense_date, row in existing.items():
            if expense_date not in by_month:
                self._drop_accrual(company_id, row)
        memo = trd("Начисление расхода по поступлению №{n}", n=doc["number"])
        for expense_date, postings in by_month.items():
            if expense_date in existing:
                gl_id = existing[expense_date]["gl_document_id"]
                self.ledger.rewrite_linked(company_id, gl_id, expense_date, postings, memo)
                continue
            require_open(
                self._company(company_id),
                expense_date,
                lambda closed, month=expense_date: tr(
                    "расход за {month} не отнести: период закрыт по {closed}. Выберите в "
                    "«Расход за» месяц документа",
                    month=month_name(month[:7]),
                    closed=closed,
                ),
            )
            gl_id = self.ledger.post_new(company_id, expense_date, postings, memo)
            insert(
                self.conn,
                "INSERT INTO inventory_accruals (company_id, document_id, expense_date, "
                "gl_document_id) VALUES (?, ?, ?, ?)",
                (company_id, doc["id"], expense_date, gl_id),
            )

    def _drop_accruals(self, company_id: int, document_id: int) -> None:
        """Remove every accrual document of a receipt (unposting, deletion)."""
        for row in self.conn.execute(
            "SELECT * FROM inventory_accruals WHERE company_id = ? AND document_id = ?",
            (company_id, document_id),
        ).fetchall():
            self._drop_accrual(company_id, row)

    def _drop_accrual(self, company_id: int, row: Row) -> None:
        self.ledger.require_changeable(company_id, row["gl_document_id"])
        self.conn.execute("DELETE FROM inventory_accruals WHERE id = ?", (row["id"],))
        self.ledger.delete_document(company_id, row["gl_document_id"])
