"""Companies and their closed period."""

from __future__ import annotations

from datetime import date

from modern_gl.application.common import insert, now, with_reason
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.application.ledger.inputs import DEFAULT_LAYERS
from modern_gl.domain.company import COMPANY_MODES
from modern_gl.domain.currency import DEFAULT_CURRENCIES, currency_name
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.tax_id import resident_tax_id
from modern_gl.i18n import LANGUAGES, tr
from modern_gl.infrastructure.db import transaction


class CompanyCommands(LedgerBase):
    """Use cases of a company: create, rename, its VÖEN and closed period."""

    def create_company(self, name: str, base_currency: str = "AZN") -> int:
        """A new company with its books (layers) and default currencies; returns its id.
        One transaction, audited."""
        with transaction(self.conn):
            company_id = insert(
                self.conn,
                "INSERT INTO companies (name, base_currency, created_at) VALUES (?, ?, ?)",
                (name, base_currency, now()),
            )
            self.conn.executemany(
                "INSERT INTO layers (company_id, code, name) VALUES (?, ?, ?)",
                [(company_id, code, tr(title)) for code, title in DEFAULT_LAYERS],
            )
            self.conn.executemany(
                "INSERT INTO currencies (company_id, code, name) VALUES (?, ?, ?)",
                [(company_id, code, currency_name(code)) for code in DEFAULT_CURRENCIES],
            )
            self._audit(
                company_id,
                "company",
                company_id,
                "create",
                {"name": name, "base_currency": base_currency},
            )
        return company_id

    def rename_company(self, company_id: int, name: str) -> None:
        """A new name for the company (e.g. after «Save as»). Audited."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("Название компании не может быть пустым"))
        with transaction(self.conn):
            old = self._company(company_id)["name"]
            if old == name:
                return
            self.conn.execute("UPDATE companies SET name = ? WHERE id = ?", (name, company_id))
            self._audit(company_id, "company", company_id, "rename", {"from": old, "to": name})

    def set_company_tax_id(self, company_id: int, tax_id: str | None) -> None:
        """The company's own VÖEN (D113): 10 digits, or None — not known. Audited."""
        tax_id = resident_tax_id(tax_id)
        with transaction(self.conn):
            old = self._company(company_id)["tax_id"]
            if old == tax_id:
                return
            self.conn.execute("UPDATE companies SET tax_id = ? WHERE id = ?", (tax_id, company_id))
            self._audit(
                company_id, "company", company_id, "set_tax_id", {"from": old, "to": tax_id}
            )

    def set_parallel_books(self, company_id: int, on: bool) -> None:
        """Parallel books (IFRS, tax) on or off (D63): off hides the «Book» field of a
        document and the book switch of reports. Not while documents lie outside the
        common layer — they would vanish from sight. Audited."""
        with transaction(self.conn):
            old = bool(self._company(company_id)["parallel_books"])
            if old == on:
                return
            if not on:
                used = self.conn.execute(
                    "SELECT COUNT(*) FROM documents d JOIN layers l ON l.id = d.layer_id "
                    "WHERE d.company_id = ? AND l.code <> 'common'",
                    (company_id,),
                ).fetchone()[0]
                if used:
                    raise ValidationError(
                        tr(
                            "Нельзя выключить параллельные книги: в корректировках МСФО и "
                            "налога есть документы ({n})",
                            n=used,
                        )
                    )
            self.conn.execute(
                "UPDATE companies SET parallel_books = ? WHERE id = ?", (int(on), company_id)
            )
            self._audit(
                company_id, "company", company_id, "set_parallel_books", {"from": old, "to": on}
            )

    def set_company_mode(self, company_id: int, mode: str) -> None:
        """How the company is kept (D90): 'full', or 'stock' — only the warehouse, purchases
        and sales are shown; the postings are made all the same. Audited."""
        if mode not in COMPANY_MODES:
            raise ValidationError(tr("Неизвестный режим компании: {mode}", mode=mode))
        with transaction(self.conn):
            old = self._company(company_id)["mode"]
            if old == mode:
                return
            self.conn.execute("UPDATE companies SET mode = ? WHERE id = ?", (mode, company_id))
            self._audit(company_id, "company", company_id, "set_mode", {"from": old, "to": mode})

    def set_document_language(self, company_id: int, code: str) -> None:
        """The language the program writes its own texts into the company's documents in
        (D152): later documents only — what is written stays. Audited."""
        if code not in LANGUAGES:
            raise ValidationError(tr("неизвестный язык документов: {code}", code=code))
        with transaction(self.conn):
            old = self._company(company_id)["document_language"]
            if old == code:
                return
            self.conn.execute(
                "UPDATE companies SET document_language = ? WHERE id = ?", (code, company_id)
            )
            self._audit(
                company_id,
                "company",
                company_id,
                "set_document_language",
                {"from": old, "to": code},
            )

    def set_vat_payer_from(self, company_id: int, day: date | str | None) -> None:
        """Since when the company pays ƏDV (D145); None — all along. Before that day the
        ƏDV reports owe and credit nothing. Audited."""
        value = None if day is None else iso_date(day)
        with transaction(self.conn):
            old = self._company(company_id)["vat_payer_from"]
            if old == value:
                return
            self.conn.execute(
                "UPDATE companies SET vat_payer_from = ? WHERE id = ?", (value, company_id)
            )
            self._audit(
                company_id, "company", company_id, "set_vat_payer_from", {"from": old, "to": value}
            )

    def set_closed_through(
        self, company_id: int, through: date | str | None, reason: str = ""
    ) -> None:
        """Close the period up to `through` inclusive; None reopens everything. Audited,
        with why it was done (`reason`, asked when a closed period is opened again)."""
        value = None if through is None else iso_date(through)
        with transaction(self.conn):
            old = self._company(company_id)["closed_through"]
            self.conn.execute(
                "UPDATE companies SET closed_through = ? WHERE id = ?", (value, company_id)
            )
            self._audit(
                company_id,
                "company",
                company_id,
                "set_closed_through",
                with_reason({"from": old, "to": value}, reason),
            )
