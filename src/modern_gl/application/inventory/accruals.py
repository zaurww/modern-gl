"""Expenses and incomes of earlier months: a receipt's or a sale's accrual documents, one
per month (D65). A purchased service is accrued Dr expense / Cr accrued expenses (76H) and
the receipt closes it Dr 76H / Cr supplier; a sold service Dr accrued income (76G) / Cr
revenue, and the sale closes it Dr customer / Cr 76G. VAT stays on the e-qaimə's date."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from modern_gl.application.common import require_open
from modern_gl.application.inventory.amounts import money
from modern_gl.application.inventory.base import InventoryBase
from modern_gl.application.inventory.model import ACCRUED_CODE, ACCRUED_INCOME_CODE
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import ACCRUED_EXPENSES, ACCRUED_INCOME
from modern_gl.domain.dates import month_end, month_name
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import N_, tr, trd
from modern_gl.infrastructure.db import Row, insert

# what the accrual of each document type is: the role and type of its account, the account
# made when the chart has none, the memo of the accrual document, the errors
ACCRUALS = {
    "receipt": {
        "role": ACCRUED_EXPENSES,
        "code": ACCRUED_CODE,
        "name": N_("Начисленные расходы"),
        "memo": N_("Начисление расхода по поступлению №{n}"),
        "no_account": N_(
            "не определён счёт начисленных расходов: оставьте один активный счёт "
            "типа «Начисленные расходы» (например, {code})"
        ),
        "later": N_("строка {line}: расход за {month} должен быть раньше месяца документа"),
        "closed": N_(
            "расход за {month} не отнести: период закрыт по {closed}. Выберите в "
            "«Расход за» месяц документа"
        ),
    },
    "sale": {
        "role": ACCRUED_INCOME,
        "code": ACCRUED_INCOME_CODE,
        "name": N_("Начисленные доходы"),
        "memo": N_("Начисление дохода по продаже №{n}"),
        "no_account": N_(
            "не определён счёт начисленных доходов: оставьте один активный счёт "
            "типа «Начисленные доходы» (например, {code})"
        ),
        "later": N_("строка {line}: доход за {month} должен быть раньше месяца документа"),
        "closed": N_(
            "доход за {month} не отнести: период закрыт по {closed}. Выберите в "
            "«Доход за» месяц документа"
        ),
    },
}


def line_expense_date(
    doc_type: str, item_id: int | None, expense_date: date | str | None, line_no: int
) -> str | None:
    """The month a purchased (sold) service belongs to (D65), as its last day. Goods come
    to (leave) stock on the document's date and have none."""
    if expense_date is None or expense_date == "":
        return None
    if item_id is None and doc_type == "sale":
        return month_end(expense_date)
    if item_id is None and doc_type == "receipt":
        return month_end(expense_date)
    if doc_type == "sale":
        raise ValidationError(
            tr(
                "строка {line}: месяц дохода указывается для услуг в продаже, не для товара",
                line=line_no,
            )
        )
    raise ValidationError(
        tr(
            "строка {line}: месяц расхода указывается для услуг и расходов в покупке, "
            "не для товара",
            line=line_no,
        )
    )


class AccrualCommands(InventoryBase):
    def _accrue(
        self,
        company_id: int,
        doc: Row,
        lines: Sequence[Row],
        postings: list[PostingInput],
    ) -> dict[str, list[PostingInput]]:
        """The lines of a receipt (sale) whose expense (income) belongs to an earlier month
        (D65): each is accrued on the last day of its month and the document closes the
        accrual instead of posting the expense (revenue) itself. `postings[i]` is the
        posting of `lines[i]`; rewritten in place, more may follow. Returns the accrual
        postings by month. Goods are never accrued: stock moves on the document's date."""
        words = ACCRUALS[doc["doc_type"]]
        first_of_month = doc["doc_date"][:7] + "-01"
        account_id: int | None = None
        by_month: dict[str, list[PostingInput]] = {}
        for i, line in enumerate(lines):
            expense_date = line["expense_date"]
            if expense_date is None:
                continue
            if expense_date >= first_of_month:
                raise ValidationError(
                    tr(words["later"], line=line["line_no"], month=month_name(expense_date[:7]))
                )
            if account_id is None:
                account_id = self._accrual_account(company_id, doc["doc_type"])
            if doc["doc_type"] == "sale":
                accrual = self._accrue_sale(company_id, account_id, line, postings, i)
            else:
                accrual = self._accrue_receipt(company_id, account_id, postings, i)
            by_month.setdefault(expense_date, []).append(accrual)
        return dict(sorted(by_month.items()))

    def _accrue_receipt(
        self, company_id: int, account_id: int, postings: list[PostingInput], i: int
    ) -> PostingInput:
        """Dr expense / Cr 76H [supplier] in the month; the receipt: Dr 76H / Cr supplier."""
        p = postings[i]
        accrued_sc = self._by_kind(company_id, account_id, p.credit_subconto)
        postings[i] = replace(p, debit_account_id=account_id, debit_subconto=accrued_sc)
        return PostingInput(
            p.debit_account_id, account_id, p.amount, p.debit_subconto, accrued_sc, p.memo
        )

    def _accrue_sale(
        self, company_id: int, account_id: int, line: Row, postings: list[PostingInput], i: int
    ) -> PostingInput:
        """Dr 76G [customer] / Cr revenue in the month, the amount without VAT; the sale:
        Dr customer / Cr 76G. Revenue charged with the VAT (Dt 62 / Kt 46 with VAT, D61):
        the VAT's part stays Dr customer / Cr revenue on the sale's date, so the VAT
        charge (Dt 46 / Kt 68.2) nets off in the same month."""
        p = postings[i]
        accrued_sc = self._by_kind(company_id, account_id, p.debit_subconto)
        amount = money(line["amount"])
        postings[i] = replace(
            p, credit_account_id=account_id, credit_subconto=accrued_sc, amount=amount
        )
        vat_part = money(line["amount"] + line["vat_amount"]) - amount
        if vat_part and p.amount != amount:  # the VAT's part of the revenue posting
            postings.append(replace(p, amount=vat_part))
        return PostingInput(
            account_id, p.credit_account_id, amount, accrued_sc, p.credit_subconto, p.memo
        )

    def _accrual_account(self, company_id: int, doc_type: str) -> int:
        """The accrued expenses (income) account: the role's, the only account of its type,
        or a new one with the counterparty directory when the chart has none."""
        words = ACCRUALS[doc_type]
        account_id = self.ledger.account_role(company_id, words["role"])
        if account_id is not None:
            return account_id
        if (
            self.conn.execute(
                "SELECT 1 FROM accounts WHERE company_id = ? AND account_type = ?",
                (company_id, words["role"]),
            ).fetchone()
            or self.conn.execute(
                "SELECT 1 FROM accounts WHERE company_id = ? AND code = ?",
                (company_id, words["code"]),
            ).fetchone()
        ):
            raise ValidationError(tr(words["no_account"], code=words["code"]))
        kinds = self.conn.execute(
            "SELECT id FROM subconto_kinds WHERE company_id = ? AND code = 'counterparty'",
            (company_id,),
        ).fetchall()
        return self.ledger.add_account(
            company_id,
            words["code"],
            tr(words["name"]),
            subconto=[row["id"] for row in kinds],
            account_type=words["role"],
        )

    def _finish_accruals(
        self, company_id: int, doc: Row, by_month: dict[str, list[PostingInput]]
    ) -> None:
        """Post, rewrite or remove the document's accrual documents so that there is one
        per month of `by_month` (D65). A recalculation that changes nothing leaves an
        accrual in a closed period alone; a month no line belongs to any more loses its
        document."""
        words = ACCRUALS[doc["doc_type"]]
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
        memo = trd(words["memo"], n=doc["number"])
        for expense_date, postings in by_month.items():
            if expense_date in existing:
                gl_id = existing[expense_date]["gl_document_id"]
                self.ledger.rewrite_linked(company_id, gl_id, expense_date, postings, memo)
                continue
            require_open(
                self._company(company_id),
                expense_date,
                lambda closed, month=expense_date: tr(
                    words["closed"], month=month_name(month[:7]), closed=closed
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
        """Remove every accrual document of a receipt or sale (unposting, deletion)."""
        for row in self.conn.execute(
            "SELECT * FROM inventory_accruals WHERE company_id = ? AND document_id = ?",
            (company_id, document_id),
        ).fetchall():
            self._drop_accrual(company_id, row)

    def _drop_accrual(self, company_id: int, row: Row) -> None:
        self.ledger.require_changeable(company_id, row["gl_document_id"])
        self.conn.execute(
            "DELETE FROM inventory_accruals WHERE company_id = ? AND id = ?",
            (
                company_id,
                row["id"],
            ),
        )
        self.ledger.delete_document(company_id, row["gl_document_id"])
