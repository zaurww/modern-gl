"""Entry templates: a reusable set of postings with amount formulas."""

from __future__ import annotations

from collections.abc import Sequence

from modern_gl.application.common import insert, pad_subconto
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.application.ledger.inputs import TemplateLine
from modern_gl.domain import formula as formulas
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class TemplateCommands(LedgerBase):
    """Use cases of entry templates: postings with amount formulas, saved for reuse."""

    def save_template(
        self,
        company_id: int,
        name: str,
        lines: Sequence[TemplateLine],
        memo: str = "",
        template_id: int | None = None,
    ) -> int:
        """Create an entry template, or replace one (name, memo and all lines). Audited."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название шаблона не может быть пустым"))
        lines = [ln for ln in lines if ln.debit_account_id or ln.credit_account_id or ln.formula]
        if not lines:
            raise ValidationError(tr("в шаблоне нет строк"))
        formulas.check([ln.formula for ln in lines])
        with transaction(self.conn):
            if template_id is None:
                template_id = insert(
                    self.conn,
                    "INSERT INTO entry_templates (company_id, name, memo) VALUES (?, ?, ?)",
                    (company_id, name, memo.strip()),
                )
                action = "create"
            else:
                found = self.conn.execute(
                    "UPDATE entry_templates SET name = ?, memo = ? WHERE company_id = ? AND id = ?",
                    (name, memo.strip(), company_id, template_id),
                ).rowcount
                if not found:
                    raise NotFoundError(tr("шаблон не найден"))
                self.conn.execute(
                    "DELETE FROM entry_template_lines WHERE template_id = ?", (template_id,)
                )
                action = "update"
            for line_no, ln in enumerate(lines, start=1):
                self.conn.execute(
                    "INSERT INTO entry_template_lines (company_id, template_id, line_no, "
                    "debit_account_id, credit_account_id, dt_sc1, dt_sc2, dt_sc3, "
                    "ct_sc1, ct_sc2, ct_sc3, formula, memo) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        company_id,
                        template_id,
                        line_no,
                        ln.debit_account_id,
                        ln.credit_account_id,
                        *pad_subconto(ln.debit_subconto, line_no),
                        *pad_subconto(ln.credit_subconto, line_no),
                        ln.formula.strip(),
                        ln.memo.strip(),
                    ),
                )
            self._audit(
                company_id,
                "entry_template",
                template_id,
                action,
                {"name": name, "lines": [ln.formula for ln in lines]},
            )
        return template_id

    def delete_template(self, company_id: int, template_id: int) -> None:
        """Delete a template (documents made from it stay); NotFoundError if it is not there."""
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT name FROM entry_templates WHERE company_id = ? AND id = ?",
                (company_id, template_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(tr("шаблон не найден"))
            self.conn.execute("DELETE FROM entry_templates WHERE id = ?", (template_id,))
            self._audit(company_id, "entry_template", template_id, "delete", {"name": row[0]})
