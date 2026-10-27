"""The warehouse in «Проверка книги» (D-new): the stock agrees with its accounts — what
SAP reconciles as stock against the GL (MB5L). The value of the goods by their account
(the movements' amounts) is the balance of that account in the common layer, where the
warehouse posts. A posting made to 41 by hand in the journal, past the warehouse, shows
here."""

from __future__ import annotations

from modern_gl.application.ledger import Ledger
from modern_gl.application.ledger.base import account_label
from modern_gl.application.verification import CheckResult, Finding
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


def stock_against_accounts(ledger: Ledger, company_id: int) -> CheckResult:
    """Each account the goods are kept on: the warehouse's value and the account's balance."""
    rows = ledger.conn.execute(
        "WITH stock AS ("
        "  SELECT i.inventory_account_id AS account_id, SUM(m.amount) AS amount "
        "  FROM stock_movements m JOIN inventory_items i "
        "  ON i.company_id = m.company_id AND i.id = m.item_id "
        "  WHERE m.company_id = ? GROUP BY i.inventory_account_id"
        "), books AS ("
        "  SELECT s.account_id, COALESCE(SUM(CASE WHEN p.debit_account_id = s.account_id "
        "    THEN p.amount ELSE -p.amount END), 0) AS amount "
        "  FROM stock s JOIN postings p ON p.company_id = ? "
        "  AND s.account_id IN (p.debit_account_id, p.credit_account_id) "
        "  JOIN documents d ON d.company_id = p.company_id AND d.id = p.document_id "
        "  JOIN layers l ON l.company_id = d.company_id AND l.id = d.layer_id "
        "  WHERE d.status = 'posted' AND l.code = 'common' "
        "  AND p.debit_account_id <> p.credit_account_id "
        "  GROUP BY s.account_id"
        ") "
        "SELECT a.*, s.amount AS stock, COALESCE(b.amount, 0) AS books FROM stock s "
        "JOIN accounts a ON a.company_id = ? AND a.id = s.account_id "
        "LEFT JOIN books b ON b.account_id = s.account_id "
        "WHERE s.amount <> COALESCE(b.amount, 0) ORDER BY a.code",
        (company_id, company_id, company_id),
    ).fetchall()
    return CheckResult(
        tr("Склад сходится со счетами запасов"),
        tuple(
            Finding(
                tr(
                    "счёт {account}: на складе {stock}, по книге {books}, разница {diff}",
                    account=account_label(row),
                    stock=format_minor(row["stock"]),
                    books=format_minor(row["books"]),
                    diff=format_minor(row["stock"] - row["books"]),
                )
            )
            for row in rows
        ),
    )
