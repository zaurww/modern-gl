"""Expenses of an earlier month: a receipt's accrual document (D65)."""

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
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row


class AccrualCommands(InventoryBase):
    def _accrue(
        self,
        company_id: int,
        doc: Row,
        lines: Sequence[Row],
        postings: list[PostingInput],
    ) -> list[PostingInput]:
        """A receipt whose expense belongs to an earlier month (D65). Each line without an
        item is accrued on the last day of that month (Dr expense / Cr accrued expenses,
        the supplier as subconto); the receipt closes the accrual (Dr accrued expenses /
        Cr supplier) instead of debiting the expense. Rewrites `postings` in place and
        returns the accrual's postings. Goods are not accrued: stock comes on its date."""
        expense_date = doc["expense_date"]
        if expense_date >= doc["doc_date"][:7] + "-01":
            raise ValidationError(
                tr(
                    "расход за {month} должен быть раньше месяца документа",
                    month=month_name(expense_date[:7]),
                )
            )
        expense_lines = [i for i, line in enumerate(lines) if line["item_id"] is None]
        if not expense_lines:
            raise ValidationError(
                tr(
                    "месяц расхода указывается для услуг и расходов: в документе нет строк "
                    "без товара"
                )
            )
        account_id = self._accrual_account(company_id)
        accrual = []
        for i in expense_lines:
            p = postings[i]
            accrued_sc = self._by_kind(company_id, account_id, p.credit_subconto)
            accrual.append(
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
        return accrual

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

    def _finish_accrual(
        self, company_id: int, document_id: int, postings: Sequence[PostingInput]
    ) -> None:
        """Post, rewrite or remove the receipt's accrual document (D65). A recalculation
        that changes nothing leaves an accrual in a closed period alone."""
        doc = self._document(company_id, document_id)
        accrual_id = doc["accrual_document_id"]
        if not postings:
            if accrual_id is not None:
                self._drop_accrual(company_id, doc)
            return
        memo = tr("Начисление расхода по поступлению №{n}", n=doc["number"])
        if accrual_id is not None:
            self.ledger.rewrite_linked(company_id, accrual_id, doc["expense_date"], postings, memo)
            return
        require_open(
            self._company(company_id),
            doc["expense_date"],
            lambda closed: tr(
                "расход за {month} не отнести: период закрыт по {closed}. Выберите в "
                "«Расход за» месяц документа",
                month=month_name(doc["expense_date"][:7]),
                closed=closed,
            ),
        )
        accrual_id = self.ledger.post_new(company_id, doc["expense_date"], postings, memo)
        self.conn.execute(
            "UPDATE inventory_documents SET accrual_document_id = ? WHERE id = ?",
            (accrual_id, document_id),
        )

    def _drop_accrual(self, company_id: int, doc: Row) -> None:
        accrual_id = doc["accrual_document_id"]
        self.conn.execute(
            "UPDATE inventory_documents SET accrual_document_id = NULL WHERE id = ?", (doc["id"],)
        )
        self.ledger.delete_document(company_id, accrual_id)
