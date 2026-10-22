"""Currency revaluation: exchange differences of currency balances on a day."""

from __future__ import annotations

from datetime import date

from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger.base import account_label
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.currency import to_base
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction


class RevaluationCommands(DocumentCommands):
    def revalue(
        self,
        company_id: int,
        day: date | str,
        gain_account: int | str,
        loss_account: int | str | None = None,
        memo: str | None = None,
    ) -> int | None:
        """Переоценка валютных остатков on `day` (common layer).

        Every balance of a currency account — per subconto values and currency — is
        brought to its currency balance at the rate of the day. A gain is credited to
        `gain_account`, a loss debited to `loss_account` (the same account by default).
        Returns the posted document, or None when everything is already at the rate.
        """
        day = iso_date(day)
        with transaction(self.conn):
            gain = self._account(company_id, gain_account)
            loss = self._account(company_id, loss_account or gain_account)
            for acc in (gain, loss):
                if acc["currency"]:
                    raise ValidationError(
                        tr(
                            "счёт {code}: курсовые разницы относят на счёт без валютного учёта",
                            code=account_label(acc),
                        )
                    )
            postings = []
            for b in self._currency_balances(company_id, day):
                rate = rate_on(self.conn, company_id, b["currency_id"], day)
                if rate is None:
                    raise ValidationError(
                        tr("нет курса {code} на {date}", code=b["code"], date=day)
                    )
                diff = to_base(b["currency_balance"], rate.per_unit) - b["balance"]
                if diff == 0:
                    continue
                sc = (b["sc1"], b["sc2"], b["sc3"])
                if diff > 0:
                    dt, ct, dt_sc, ct_sc = b["account_id"], gain["id"], sc, ()
                else:
                    dt, ct, dt_sc, ct_sc = loss["id"], b["account_id"], (), sc
                postings.append(
                    PostingInput(
                        dt,
                        ct,
                        from_minor(abs(diff)),
                        dt_sc,
                        ct_sc,
                        tr("Курсовая разница {code}", code=b["code"]),
                        currency_id=b["currency_id"],
                        currency_amount=0,
                    )
                )
            if not postings:
                return None
            shown = ".".join(reversed(day.split("-")))
            text = memo or tr("Переоценка валютных остатков на {date}", date=shown)
            return self.post_new(company_id, day, postings, text)

    def _currency_balances(self, company_id: int, day: str) -> list[Row]:
        """Balances of currency accounts on `day` (common layer), in manat and in currency,
        per account, subconto values and currency."""
        return self.conn.execute(
            """
            WITH docs AS (
                SELECT d.id FROM documents d JOIN layers l ON l.id = d.layer_id
                WHERE d.company_id = :company_id AND d.status = 'posted'
                  AND d.doc_date <= :day AND l.code = 'common'
            ),
            moves AS (
                SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc1, p.dt_sc2 AS sc2,
                       p.dt_sc3 AS sc3, p.currency_id, p.amount, p.currency_amount
                FROM postings p JOIN docs ON docs.id = p.document_id
                JOIN accounts a ON a.id = p.debit_account_id
                WHERE a.currency <> 0 AND p.currency_id IS NOT NULL
                UNION ALL
                SELECT p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3, p.currency_id,
                       -p.amount, -p.currency_amount
                FROM postings p JOIN docs ON docs.id = p.document_id
                JOIN accounts a ON a.id = p.credit_account_id
                WHERE a.currency <> 0 AND p.currency_id IS NOT NULL
            )
            SELECT m.account_id, m.sc1, m.sc2, m.sc3, m.currency_id, c.code,
                   SUM(m.amount) AS balance, SUM(m.currency_amount) AS currency_balance
            FROM moves m JOIN currencies c ON c.id = m.currency_id
            GROUP BY m.account_id, m.sc1, m.sc2, m.sc3, m.currency_id
            ORDER BY m.account_id, c.code, m.sc1, m.sc2, m.sc3
            """,
            {"company_id": company_id, "day": day},
        ).fetchall()
