"""«Проверено» of a bank operation: the import posts the lines it is sure of, a person
checking every line marks what they have seen (in the statement — Space); the form marks it
when it is posted there. Only a posted operation is checked: a draft waits anyway."""

from __future__ import annotations

from modern_gl.application.ledger.module import ModuleBase
from modern_gl.infrastructure.db import transaction


class BankCheckCommands(ModuleBase):
    def mark_checked(self, company_id: int, operation_ids: list[int], checked: bool) -> int:
        """The posted ones of the operations marked checked (or not); how many changed."""
        changed = 0
        with transaction(self.conn):
            for operation_id in operation_ids:
                done = self.conn.execute(
                    "UPDATE bank_operations SET is_checked = ? WHERE company_id = ? AND id = ? "
                    "AND is_checked <> ? AND document_id IN "
                    "(SELECT id FROM documents WHERE company_id = ? AND status = 'posted')",
                    (int(checked), company_id, operation_id, int(checked), company_id),
                ).rowcount
                if done:
                    changed += 1
                    action = "check" if checked else "uncheck"
                    self._audit(company_id, "bank_operation", operation_id, action, {})
        return changed
