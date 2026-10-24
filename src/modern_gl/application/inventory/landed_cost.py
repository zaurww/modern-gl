"""«Расходы по партии»: a batch's expenses allocated over its receipt lines,
split between the stock on hand and what was already issued."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory.amounts import (
    allocate_charges,
    allocate_minor,
    blank,
    money,
    nonnegative_amount,
    positive_amount,
    split_charges,
    typed_rate,
)
from modern_gl.application.inventory.model import (
    ALLOCATION_METHODS,
    LandedCostCharge,
    LandedCostTarget,
)
from modern_gl.application.inventory.stock import StockCommands
from modern_gl.application.ledger import PostingInput
from modern_gl.application.ledger.documents import explain_owner
from modern_gl.domain.currency import to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor, round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction

explain_owner(
    "landed_cost",
    lambda _role, n, m: tr(
        "документ №{n} взят как расход партии в складском документе №{m}: "
        "сначала уберите его оттуда",
        n=n,
        m=m,
    ),
)


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


@dataclass(frozen=True)
class _Credit:
    """A credit piece of landed cost postings: a charge's share of one receipt line."""

    account_id: int
    subconto: Sequence[int | None]
    amount: int
    memo: str
    currency_id: int | None = None
    currency_amount: int = 0


def _pair(
    debits: Sequence[tuple[int, Sequence[int | None], int]], credits: Sequence[_Credit]
) -> list[PostingInput]:
    """Postings from debit pieces (account, subconto, amount) and credit pieces of the same
    total, matched in order. A credit piece in a currency split over several postings
    shares its currency amount in proportion to the manat amounts."""
    pieces: list[tuple[int, int, int]] = []  # debit index, credit index, amount
    d_left = [amount for _, _, amount in debits]
    c_left = [credit.amount for credit in credits]
    i = j = 0
    while i < len(debits) and j < len(credits):
        amount = min(d_left[i], c_left[j])
        if amount:
            pieces.append((i, j, amount))
        d_left[i] -= amount
        c_left[j] -= amount
        i += d_left[i] == 0
        j += c_left[j] == 0
    in_currency: dict[int, int] = {}
    for j, credit in enumerate(credits):
        mine = [(k, piece[2]) for k, piece in enumerate(pieces) if piece[1] == j]
        if credit.currency_id is not None and credit.currency_amount > 0 and mine:
            in_currency.update(allocate_minor(credit.currency_amount, mine))
    return [
        PostingInput(
            debits[i][0],
            credits[j].account_id,
            money(amount),
            tuple(debits[i][1]),
            tuple(credits[j].subconto),
            credits[j].memo,
            credits[j].currency_id,
            None if credits[j].currency_id is None else money(in_currency.get(k, 0)),
        )
        for k, (i, j, amount) in enumerate(pieces)
    ]


class LandedCostCommands(StockCommands):
    def create_landed_cost_draft(
        self,
        company_id: int,
        doc_date: date | str,
        targets: Sequence[LandedCostTarget],
        charges: Sequence[LandedCostCharge],
        method: str = "value",
        memo: str = "",
        *,
        cost_type_id: int | None = None,
    ) -> int:
        """Save a «Расходы по партии» document: the receipt lines of a batch, its expenses
        and how they are allocated (by value, by quantity or by hand). A draft may be
        unfinished; posting checks everything."""
        with transaction(self.conn):
            if cost_type_id is not None:
                self._cost_type(company_id, cost_type_id)
            document_id = self._insert_document(
                company_id, doc_date, "landed_cost", memo, cost_type_id=cost_type_id
            )
            self._write_landed_cost_draft(company_id, document_id, targets, charges, method)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "landed_cost"},
            )
        return document_id

    def update_landed_cost_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        targets: Sequence[LandedCostTarget],
        charges: Sequence[LandedCostCharge],
        method: str = "value",
        memo: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "landed_cost":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._release_lines(company_id, document_id, targets)
            self._write_landed_cost_draft(company_id, document_id, targets, charges, method)
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def _write_landed_cost_draft(
        self,
        company_id: int,
        document_id: int,
        targets: Sequence[LandedCostTarget],
        charges: Sequence[LandedCostCharge],
        method: str,
    ) -> None:
        if method not in ALLOCATION_METHODS:
            raise ValidationError(tr("неизвестный способ распределения"))
        if not targets:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        self.conn.execute(
            "UPDATE inventory_documents SET allocation_method = ? WHERE id = ?",
            (method, document_id),
        )
        seen: set[int] = set()
        for line_no, target in enumerate(targets, 1):
            receipt = self._receipt_line(company_id, target.receipt_line_id)
            if receipt["id"] in seen:
                raise ValidationError(tr("строка поступления выбрана дважды"))
            seen.add(receipt["id"])
            amount = (
                0
                if target.amount is None or blank(target.amount)
                else nonnegative_amount(target.amount)
            )
            self._insert_line(
                document_id,
                company_id,
                line_no,
                receipt["item_id"],
                receipt["warehouse_id"],
                None,
                0,
                amount,
                0,
                0,
                None,
                (),
                receipt["id"],
                "",
                line_id=target.line_id,
            )
        self.conn.execute("DELETE FROM landed_cost_charges WHERE document_id = ?", (document_id,))
        for line_no, charge in enumerate(charges, 1):
            self._insert_charge(company_id, document_id, line_no, charge)

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
            if charge.source_document_id is not None:
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
        if charge.source_document_id is not None:
            if charge.source_line_no is None:
                raise ValidationError(tr("не указана строка проводки-источника"))
            if vat:
                raise ValidationError(
                    tr("расход {n}: НДС уже учтён в документе-источнике", n=line_no)
                )
            posting = self._cost_source(
                company_id, charge.source_document_id, charge.source_line_no
            )
            account_id = posting["debit_account_id"]
            subconto = (posting["dt_sc1"], posting["dt_sc2"], posting["dt_sc3"])
        else:
            account_id = charge.account_id
            if account_id is not None:
                self._account(company_id, account_id)
            subconto = pad_subconto(charge.subconto)
        self.conn.execute(
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

    def _apply_landed_cost(
        self, company_id: int, doc: Row, lines: Sequence[Row]
    ) -> list[PostingInput]:
        """Allocate the charges over the batch, then split each receipt line's share between
        the stock still on hand and the expense accounts of what was already issued."""
        charges = self._charges(doc["id"])
        if not charges:
            raise ValidationError(tr("в документе нет расходов"))
        for charge in charges:
            self._require_charge_complete(company_id, doc, charge)
        total = sum(charge["amount"] for charge in charges)
        receipts = {
            line["id"]: self._landed_cost_source(company_id, line["source_receipt_line_id"])
            for line in lines
        }
        targets = self._landed_cost_targets(doc, lines, receipts, total)
        shares = split_charges([(c["id"], c["amount"]) for c in charges], targets)
        for (charge_id, line_id), share in shares.items():
            self.conn.execute(
                "INSERT INTO landed_cost_shares "
                "(company_id, document_id, charge_id, line_id, amount) VALUES (?, ?, ?, ?, ?)",
                (company_id, doc["id"], charge_id, line_id, share),
            )
        in_currency: dict[tuple[int, int], int] = {}  # a charge's currency amount by line
        for charge in charges:
            mine = [(line_id, v) for (c, line_id), v in shares.items() if c == charge["id"]]
            if charge["currency_id"] is not None and charge["currency_amount"] and mine:
                for line_id, value in allocate_minor(charge["currency_amount"], mine).items():
                    in_currency[(charge["id"], line_id)] = value
        postings: list[PostingInput] = []
        for line in lines:
            allocated = targets[line["id"]]
            debits, inventory_amount, expense_amount = (
                self._landed_cost_debits(company_id, doc, line, receipts[line["id"]], allocated)
                if allocated
                else ([], 0, 0)
            )
            credits = [
                _Credit(
                    charge["account_id"],
                    (charge["sc1"], charge["sc2"], charge["sc3"]),
                    shares[(charge["id"], line["id"])],
                    self._charge_memo(company_id, doc, charge),
                    charge["currency_id"],
                    in_currency.get((charge["id"], line["id"]), 0),
                )
                for charge in charges
                if (charge["id"], line["id"]) in shares
            ]
            postings += _pair(debits, credits)
            self.conn.execute(
                "UPDATE inventory_lines SET amount = ?, inventory_amount = ?, "
                "expense_amount = ? WHERE id = ?",
                (allocated, inventory_amount, expense_amount, line["id"]),
            )
        return postings + self._vat_postings(
            company_id,
            ("", ""),
            [
                (charge["account_id"], (charge["sc1"], charge["sc2"], charge["sc3"]), vat)
                for charge in charges
                if (vat := charge["vat_amount"])
            ],
        )

    def _landed_cost_targets(
        self,
        doc: Row,
        lines: Sequence[Row],
        receipts: Mapping[int, Row],
        total: int,
    ) -> dict[int, int]:
        """Line id -> its share of all the charges."""
        if not lines:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        method = doc["allocation_method"] or "value"
        if method == "manual":
            allocated = sum(line["amount"] for line in lines)
            if allocated != total:
                raise ValidationError(
                    tr(
                        "распределено {allocated}, а расходов {total}",
                        allocated=format_minor(allocated),
                        total=format_minor(total),
                    )
                )
            return {line["id"]: line["amount"] for line in lines}
        return allocate_charges(
            method,
            total,
            [
                (line["id"], receipts[line["id"]]["amount"], receipts[line["id"]]["quantity"])
                for line in lines
            ],
        )

    def _landed_cost_debits(
        self,
        company_id: int,
        doc: Row,
        line: Row,
        receipt: Row,
        allocated: int,
    ) -> tuple[list[tuple[int, Sequence[int | None], int]], int, int]:
        """Where a receipt line's share goes: (debit pieces, to stock, to expense)."""
        consumptions = self._receipt_consumptions(company_id, receipt["id"])
        consumed_quantity = sum(row["quantity"] for row in consumptions)
        remaining_quantity = receipt["quantity"] - consumed_quantity
        inventory_amount = round_ratio(allocated * remaining_quantity, receipt["quantity"])
        expense_amount = allocated - inventory_amount
        debits: list[tuple[int, Sequence[int | None], int]] = []
        if inventory_amount:
            stock = self._landed_cost_to_stock(
                company_id,
                doc["id"],
                line["id"],
                doc["doc_date"],
                self._item(company_id, receipt["item_id"]),
                inventory_amount,
            )
            if stock is None:  # nothing left in stock: all of it is expense
                expense_amount += inventory_amount
                inventory_amount = 0
            else:
                debits += stock
        if expense_amount:
            debits += self._landed_cost_to_expense(
                company_id, doc["id"], line["id"], consumptions, expense_amount
            )
        return debits, inventory_amount, expense_amount

    def _landed_cost_to_stock(
        self,
        company_id: int,
        inv_id: int,
        line_id: int,
        doc_date: date | str,
        item: Row,
        amount: int,
    ) -> list[tuple[int, Sequence[int | None], int]] | None:
        """Add `amount` to the item's stock value in each warehouse in proportion to its
        quantity there. None when no warehouse has the item any more."""
        balances = self._item_warehouse_quantities(company_id, item["id"])
        if not balances:
            return None
        postings = []
        for warehouse_id, share in allocate_minor(amount, balances).items():
            if not share:
                continue
            warehouse = self._warehouse(company_id, warehouse_id)
            self._insert_movement(
                company_id,
                inv_id,
                line_id,
                doc_date,
                item["id"],
                warehouse_id,
                "landed_cost",
                0,
                share,
            )
            postings.append(
                (
                    item["inventory_account_id"],
                    self._inventory_subconto(company_id, item, warehouse),
                    share,
                )
            )
        return postings

    def _landed_cost_to_expense(
        self,
        company_id: int,
        inv_id: int,
        line_id: int,
        consumptions: list[Row],
        amount: int,
    ) -> list[tuple[int, Sequence[int | None], int]]:
        """Charge `amount` to the expense accounts of the issues that consumed the receipt,
        in proportion to the quantity each took."""
        if not consumptions:
            raise ValidationError(tr("не найдены списания для распределения расхода"))
        by_issue = allocate_minor(
            amount, [(row["issue_line_id"], row["quantity"]) for row in consumptions]
        )
        issues = {row["issue_line_id"]: row for row in consumptions}
        postings = []
        for issue_line_id, share in by_issue.items():
            if not share:
                continue
            issue = issues[issue_line_id]
            self.conn.execute(
                "INSERT INTO landed_cost_expense_allocations "
                "(company_id, document_id, landed_cost_line_id, issue_line_id, amount) "
                "VALUES (?, ?, ?, ?, ?)",
                (company_id, inv_id, line_id, issue_line_id, share),
            )
            subconto: Sequence[int | None] = (
                issue["offset_sc1"],
                issue["offset_sc2"],
                issue["offset_sc3"],
            )
            if issue["doc_type"] == "sale":  # the cost of sales, as the sale posted it
                sold = self.conn.execute(
                    "SELECT * FROM inventory_lines WHERE id = ?", (issue_line_id,)
                ).fetchone()
                subconto = self._by_kind(
                    company_id, issue["offset_account_id"], self._sale_values(company_id, sold)
                )
            postings.append((issue["offset_account_id"], subconto, share))
        return postings

    def _landed_cost_source(self, company_id: int, line_id: int) -> Row:
        row = self.conn.execute(
            """
            SELECT l.*, d.number, d.status FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE l.company_id = ? AND l.id = ?
            """,
            (company_id, line_id),
        ).fetchone()
        if row is None or row["status"] != "posted":
            raise ValidationError(
                tr(
                    "расходы распределены на поступление №{n}, которое не проведено",
                    n=row["number"] if row else "?",
                )
            )
        return row

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

    def _charge_memo(self, company_id: int, doc: Row, charge: Row) -> str:
        if charge["memo"]:
            return charge["memo"]
        if charge["cost_type_id"] is not None:
            return self._cost_type(company_id, charge["cost_type_id"])["name"]
        return doc["memo"]

    def _require_charge_complete(self, company_id: int, doc: Row, charge: Row) -> None:
        n = charge["line_no"]
        if charge["amount"] <= 0:
            raise ValidationError(tr("расход {n}: не указана сумма", n=n))
        if charge["account_id"] is None:
            raise ValidationError(tr("расход {n}: не указан счёт", n=n))
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
