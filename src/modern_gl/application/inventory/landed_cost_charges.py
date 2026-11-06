"""The expenses of a batch: typed, taken from a GL posting or from a purchase's service
line (D211), and what is checked before they are posted."""

from __future__ import annotations

from collections.abc import Sequence

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory.amounts import (
    blank,
    nonnegative_amount,
    positive_amount,
    typed_rate,
)
from modern_gl.application.inventory.model import LandedCostCharge
from modern_gl.application.inventory.stock import StockCommands
from modern_gl.domain.currency import to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, insert


def allocated_sql(company: str, document: str, line: str) -> str:
    """A subquery: how much of the GL posting `document`, `line` (SQL expressions) posted
    «Расходы по партии» documents took, all but the one of the next parameter (NULL — none
    left out). The picker and the check on posting count it alike."""
    return (
        "(SELECT COALESCE(SUM(c.amount), 0) FROM landed_cost_charges c "
        "JOIN inventory_documents i ON i.id = c.document_id AND i.status = 'posted' "
        f"WHERE c.company_id = {company} AND c.source_document_id = {document} "
        f"AND c.source_line_no = {line} AND c.document_id IS DISTINCT FROM ?)"
    )


def taken_of_line_sql(company: str, line: str) -> str:
    """A subquery: how much of the purchase's service line `line` posted batches took, all
    but the one of the next parameter (NULL — none left out)."""
    return (
        "(SELECT COALESCE(SUM(c.amount), 0) FROM landed_cost_charge_lines k "
        "JOIN landed_cost_charges c ON c.company_id = k.company_id AND c.id = k.charge_id "
        "JOIN inventory_documents i ON i.id = c.document_id AND i.status = 'posted' "
        f"WHERE k.company_id = {company} AND k.source_line_id = {line} "
        "AND c.document_id IS DISTINCT FROM ?)"
    )


class ChargeCommands(StockCommands):
    def _insert_charge(
        self, company_id: int, document_id: int, line_no: int, charge: LandedCostCharge
    ) -> None:
        amount = (
            0
            if charge.amount is None or blank(charge.amount)
            else positive_amount(charge.amount, line_no)
        )
        vat = (
            0
            if charge.vat_amount is None or blank(charge.vat_amount)
            else nonnegative_amount(charge.vat_amount)
        )
        currency_id = rate = currency_amount = None
        if charge.currency_id is not None:
            if charge.source_document_id is not None or charge.source_line_id is not None:
                raise ValidationError(tr("расход {n}: проводка-источник уже в манатах", n=line_no))
            if vat:
                raise ValidationError(
                    tr("расход {n}: в расходе в валюте НДС не указывается", n=line_no)
                )
            currency_id = self._currency(company_id, charge.currency_id)["id"]
            rate = typed_rate(charge.currency_rate)
            value = charge.currency_amount
            currency_amount = (
                0 if value is None or blank(value) else positive_amount(value, line_no)
            )
            amount = to_base(currency_amount, unit_rate(rate))
        if charge.cost_type_id is not None:
            self._cost_type(company_id, charge.cost_type_id)
        account_id, subconto = self._charge_side(company_id, charge, line_no, vat)
        charge_id = insert(
            self.conn,
            "INSERT INTO landed_cost_charges (company_id, document_id, line_no, cost_type_id, "
            "account_id, sc1, sc2, sc3, amount, vat_amount, source_document_id, "
            "source_line_no, memo, currency_id, currency_rate, currency_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                document_id,
                line_no,
                charge.cost_type_id,
                account_id,
                *subconto,
                amount,
                vat,
                charge.source_document_id,
                charge.source_line_no if charge.source_document_id is not None else None,
                charge.memo.strip(),
                currency_id,
                rate,
                currency_amount,
            ),
        )
        if charge.source_line_id is not None:
            self.conn.execute(
                "INSERT INTO landed_cost_charge_lines (company_id, charge_id, source_line_id) "
                "VALUES (?, ?, ?)",
                (company_id, charge_id, charge.source_line_id),
            )

    def _charge_side(
        self, company_id: int, charge: LandedCostCharge, line_no: int, vat: int
    ) -> tuple[int | None, Sequence[int | None]]:
        """The account and subconto an expense credits: as typed, or those of what it takes."""
        taken = charge.source_document_id is not None or charge.source_line_id is not None
        if taken and vat:
            raise ValidationError(tr("расход {n}: НДС уже учтён в документе-источнике", n=line_no))
        if charge.source_document_id is not None:
            if charge.source_line_no is None:
                raise ValidationError(tr("не указана строка проводки-источника"))
            posting = self._cost_source(
                company_id, charge.source_document_id, charge.source_line_no
            )
            return posting["debit_account_id"], (
                posting["dt_sc1"],
                posting["dt_sc2"],
                posting["dt_sc3"],
            )
        if charge.source_line_id is not None:
            line = self._charge_line(company_id, charge.source_line_id)
            return line["cost_account_id"], (line["cost_sc1"], line["cost_sc2"], line["cost_sc3"])
        if charge.account_id is not None:
            self._account(company_id, charge.account_id)
        return charge.account_id, pad_subconto(charge.subconto)

    def _cost_source(self, company_id: int, document_id: int, line_no: int) -> Row:
        """A GL posting an expense line takes: posted, in the common book, not one the
        warehouse made itself, with a positive amount."""
        row = self.conn.execute(
            """
            SELECT p.*, d.number, d.status, l.code AS layer,
                   EXISTS (SELECT 1 FROM document_owners o
                           WHERE o.company_id = d.company_id AND o.document_id = d.id
                             AND o.module = 'inventory' AND o.role = 'made') AS from_inventory
            FROM postings p
            JOIN documents d ON d.id = p.document_id
            JOIN layers l ON l.id = d.layer_id
            WHERE p.company_id = ? AND p.document_id = ? AND p.line_no = ?
            """,
            (company_id, document_id, line_no),
        ).fetchone()
        if row is None or row["status"] != "posted":
            raise ValidationError(tr("проводка-источник расхода не найдена или не проведена"))
        if row["from_inventory"]:
            raise ValidationError(tr("проводку складского документа нельзя взять как расход"))
        if row["layer"] != "common" or row["amount"] <= 0:
            raise ValidationError(
                tr("как расход можно взять только обычную проводку с положительной суммой")
            )
        return row

    def _charge_line(self, company_id: int, line_id: int) -> Row:
        """A purchase's service line an expense takes: a line of a purchase, with no item."""
        row = self.conn.execute(
            """
            SELECT l.*, d.number, d.gl_document_id, d.doc_type
            FROM inventory_lines l
            JOIN inventory_documents d ON d.company_id = l.company_id AND d.id = l.document_id
            WHERE l.company_id = ? AND l.id = ?
            """,
            (company_id, line_id),
        ).fetchone()
        if (
            row is None
            or row["doc_type"] != "receipt"
            or row["item_id"] is not None
            or row["cost_account_id"] is None
        ):
            raise ValidationError(tr("как расход можно взять только услугу из покупки"))
        return row

    def _require_line_left(self, company_id: int, doc: Row, charge: Row) -> None:
        """A service taken: of a posted purchase, still on the same account and with enough
        of it left. The batch may be earlier: the e-qaimə of a service comes after the goods;
        posted again from a day, such a purchase is out of the sequence for a moment, its GL
        document stays — only a purchase really not posted has none."""
        n = charge["line_no"]
        line = self._charge_line(company_id, charge["source_line_id"])
        if line["gl_document_id"] is None:
            raise ValidationError(
                tr("расход {n}: документ №{m} не проведён", n=n, m=line["number"])
            )
        if line["cost_account_id"] != charge["account_id"]:
            raise ValidationError(
                tr("расход {n}: в документе №{m} изменился счёт услуги", n=n, m=line["number"])
            )
        used = self.conn.execute(
            "SELECT " + taken_of_line_sql("?", "?"),
            (company_id, line["id"], doc["id"]),
        ).fetchone()[0]
        if used + charge["amount"] > line["amount"]:
            raise ValidationError(
                tr(
                    "расход {n}: услуга документа №{number} — {amount}, уже распределено "
                    "{used}, осталось {left}",
                    n=n,
                    number=line["number"],
                    amount=format_minor(line["amount"]),
                    used=format_minor(used),
                    left=format_minor(max(line["amount"] - used, 0)),
                )
            )

    def _charge_memo(self, company_id: int, doc: Row, charge: Row) -> str:
        if charge["memo"]:
            return charge["memo"]
        if charge["cost_type_id"] is not None:
            return self._cost_type(company_id, charge["cost_type_id"])["name"]
        if charge["source_line_id"] is not None:  # what the service says it is
            return self._charge_line(company_id, charge["source_line_id"])["memo"] or doc["memo"]
        if charge["source_document_id"] is not None:
            posting = self._cost_source(
                company_id, charge["source_document_id"], charge["source_line_no"]
            )
            return posting["memo"] or doc["memo"]
        return doc["memo"]

    def _require_charge_complete(self, company_id: int, doc: Row, charge: Row) -> None:
        n = charge["line_no"]
        if charge["amount"] <= 0:
            raise ValidationError(tr("расход {n}: не указана сумма", n=n))
        if charge["account_id"] is None:
            raise ValidationError(tr("расход {n}: не указан счёт", n=n))
        if charge["source_line_id"] is not None:
            self._require_line_left(company_id, doc, charge)
        if charge["source_document_id"] is None:
            return
        posting = self._cost_source(
            company_id, charge["source_document_id"], charge["source_line_no"]
        )
        used = self.conn.execute(
            "SELECT " + allocated_sql("?", "?", "?"),
            (company_id, charge["source_document_id"], charge["source_line_no"], doc["id"]),
        ).fetchone()[0]
        if used + charge["amount"] > posting["amount"]:
            raise ValidationError(
                tr(
                    "расход {n}: проводка документа №{number} — {amount}, уже распределено "
                    "{used}, осталось {left}",
                    n=n,
                    number=posting["number"],
                    amount=format_minor(posting["amount"]),
                    used=format_minor(used),
                    left=format_minor(max(posting["amount"] - used, 0)),
                )
            )
