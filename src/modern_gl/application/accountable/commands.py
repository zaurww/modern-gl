"""The writes of advance reports (D218): save (and post), unpost, delete,
rebuild. Each line posts Dt its account / Kt the accountable account with the employee:
the money he was given is spent on it. A draft keeps only what was entered."""

from __future__ import annotations

from datetime import date

from modern_gl.application.accountable.model import (
    AdvanceReport,
    AdvanceReportInput,
    load_advance_report,
    load_advance_reports,
)
from modern_gl.application.accountable.people import AccountableAccount, accountable_account
from modern_gl.application.common import pad_subconto
from modern_gl.application.ledger.documents import explain_owner
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.ledger.module import ModuleBase
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import transaction

explain_owner(
    "accountable",
    lambda _role, _n, _m: tr(
        "проводки созданы авансовым отчётом; исправьте его в разделе «Подотчётные лица»"
    ),
)


class AdvanceReportCommands(ModuleBase):
    def save_advance_report(
        self,
        company_id: int,
        data: AdvanceReportInput,
        report_id: int | None = None,
        *,
        post: bool,
    ) -> int:
        """Create or change an advance report; `post` builds and posts its GL document.
        A posted report is changed in place (D32): it keeps its number."""
        memo = data.memo or self.default_memo(company_id, data.employee_id)
        with transaction(self.conn):
            account = accountable_account(self.conn, company_id)
            if report_id is None:
                doc_id = self.documents.new(company_id, data.doc_date, memo)
                saved: int = self.conn.execute(
                    "INSERT INTO advance_reports (company_id, document_id) VALUES (?, ?) "
                    "RETURNING id",
                    (company_id, doc_id),
                ).fetchone()[0]
                action = "create"
            else:
                saved = report_id
                old = load_advance_report(self.conn, company_id, saved)
                doc = self.documents.get(company_id, old.document_id)
                if doc["status"] == "posted":
                    if not post:
                        raise ValidationError(
                            tr(
                                "документ №{n} проведён: чтобы сохранить его черновиком, "
                                "сначала отмените проведение",
                                n=doc["number"],
                            )
                        )
                    self.documents.require_changeable(company_id, doc)
                action = "update"
            self._store(company_id, saved, data, account)
            report = load_advance_report(self.conn, company_id, saved)
            if post:
                postings = self._postings(company_id, data, account, memo)
                self.documents.write(company_id, report.document_id, data.doc_date, postings, memo)
                action = "post"
            else:
                self.documents.set_header(company_id, report.document_id, data.doc_date, memo)
            self._audit(company_id, "advance_report", saved, action, {})
        return saved

    def unpost_advance_report(self, company_id: int, report_id: int) -> None:
        """Back to a draft: its postings go (the audit trail keeps them)."""
        with transaction(self.conn):
            report = load_advance_report(self.conn, company_id, report_id)
            self.documents.unpost(company_id, self.documents.get(company_id, report.document_id))
            self._audit(company_id, "advance_report", report_id, "unpost", {})

    def delete_advance_report(self, company_id: int, report_id: int) -> None:
        """The report and its GL document away (a posted one — in an open period)."""
        with transaction(self.conn):
            report = load_advance_report(self.conn, company_id, report_id)
            doc = self.documents.get(company_id, report.document_id)
            if doc["status"] == "posted":
                self.documents.require_changeable(company_id, doc)
            self.conn.execute(
                "DELETE FROM advance_reports WHERE company_id = ? AND id = ?",
                (company_id, report_id),
            )
            self.documents.remove(company_id, doc)
            self._audit(company_id, "advance_report", report_id, "delete", {})

    def rebuild_postings(self, company_id: int, since: date | str) -> list[int]:
        """The GL documents of posted reports from `since` on, built again (D101)."""
        return self.documents.rebuild_each(
            company_id,
            since,
            "advance_reports",
            lambda ids: load_advance_reports(self.conn, company_id, ids),
            lambda report: self._rebuild(company_id, report),
            lambda n, day, error: tr(
                "авансовый отчёт №{n} от {date}: {error}", n=n, date=day, error=error
            ),
        )

    def default_memo(self, company_id: int, employee_id: int | None) -> str:
        """«Авансовый отчёт: Məmmədov R.» — in the language of documents."""
        if employee_id is None:
            return trd("Авансовый отчёт")
        name = self.conn.execute(
            "SELECT name FROM subconto_values WHERE company_id = ? AND id = ?",
            (company_id, employee_id),
        ).fetchone()
        return trd("Авансовый отчёт: {name}", name=name[0] if name else "")

    # ---- internals --------------------------------------------------------------------

    def _rebuild(self, company_id: int, report: AdvanceReport) -> list[int]:
        account = accountable_account(self.conn, company_id)
        postings = self._postings(company_id, report, account, report.memo)
        changed = self.documents.rebuild(
            company_id, report.document_id, report.doc_date, postings, report.memo
        )
        return [report.document_id] if changed else []

    def _store(
        self,
        company_id: int,
        report_id: int,
        data: AdvanceReportInput,
        account: AccountableAccount | None,
    ) -> None:
        self.conn.execute(
            "UPDATE advance_reports SET account_id = ?, employee_id = ? "
            "WHERE company_id = ? AND id = ?",
            (account.id if account else None, data.employee_id, company_id, report_id),
        )
        self.conn.execute(
            "DELETE FROM advance_report_lines WHERE company_id = ? AND report_id = ?",
            (company_id, report_id),
        )
        for line_no, line in enumerate(data.lines, start=1):
            sc = pad_subconto(line.subconto, line_no)
            self.conn.execute(
                "INSERT INTO advance_report_lines (company_id, report_id, line_no, account_id, "
                "sc1, sc2, sc3, amount, memo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (company_id, report_id, line_no, line.account_id, *sc, line.amount, line.memo),
            )

    def _postings(
        self,
        company_id: int,
        data: AdvanceReportInput,
        account: AccountableAccount | None,
        memo: str,
    ) -> list[PostingInput]:
        if account is None:
            raise ValidationError(
                tr("нет счёта подотчётных лиц: нужен счёт со справочником «Сотрудники»")
            )
        if data.employee_id is None:
            raise ValidationError(tr("не указан сотрудник"))
        lines = [line for line in data.lines if line.account_id is not None or line.amount]
        if not lines:
            raise ValidationError(tr("в отчёте нет строк"))
        employee: list[int | None] = [None, None, None]
        employee[account.position - 1] = data.employee_id
        postings = []
        for line_no, line in enumerate(lines, start=1):
            if line.account_id is None:
                raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
            if not line.amount:
                raise ValidationError(tr("строка {line}: нулевая сумма", line=line_no))
            if line.account_id == account.id:
                raise ValidationError(
                    tr("строка {line}: расход не может идти на счёт подотчётных лиц", line=line_no)
                )
            postings.append(
                PostingInput(
                    line.account_id,
                    account.id,
                    from_minor(line.amount),
                    pad_subconto(line.subconto, line_no),
                    tuple(employee),
                    line.memo or memo,
                )
            )
        return postings
