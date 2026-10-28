"""A conversion between the company's accounts from bank statement files (D37): the money
leaves one account and comes to the other — a line in each account's file, the same
reference in both; the bank's fee of it is a line of the same operation. Both files
loaded — one conversion, posted; one of them — a draft with that side, finished when the
other file comes. The order of the files does not matter: a side loaded before its
account's IBAN was known is a draft (a transfer, a fee) — the next load replaces such
drafts by the conversion; a side posted by hand keeps the conversion out, and says so.

The bank module makes a conversion of the conversion module here: the one place the bank
writes another module's document."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from modern_gl.application.bank.file_import import CONVERSION, FileOperation
from modern_gl.application.bank.import_commands import BankImportCommands
from modern_gl.application.bank.imported import DRAFT, KNOWN, POSTED, ImportRow
from modern_gl.application.bank.operations import FEE, IN, OUT
from modern_gl.application.common import pad_subconto
from modern_gl.application.conversion.calc import (
    ConversionFee,
    ConversionInput,
    ConversionSide,
    load_conversion,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class FileConversionCommands(BankImportCommands):
    def _redo_conversion_drafts(
        self, company_id: int, ops: Sequence[FileOperation]
    ) -> dict[str, int]:
        """The drafts of bank operations with a conversion's references (its sides, its
        fees) deleted: the conversion takes their place. -> the references of a side
        posted as a bank operation (the conversion is not made): its number."""
        sides = {op.reference for op in ops if op.kind == CONVERSION}
        fees = {f.reference for op in ops if op.kind == CONVERSION for f in op.fees}
        if not sides:
            return {}
        marks = ", ".join("?" * len(sides | fees))
        rows = self.conn.execute(
            "SELECT o.id, o.reference, d.status, d.number FROM bank_operations o "
            "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
            f"WHERE o.company_id = ? AND o.reference IN ({marks})",
            (company_id, *sorted(sides | fees)),
        ).fetchall()
        posted = {}
        for r in rows:
            if r["status"] == "draft":
                self.delete_bank_operation(company_id, r["id"])
            elif r["reference"] in sides:
                posted[r["reference"]] = r["number"]
        return posted

    def _file_conversion(
        self,
        company_id: int,
        op: FileOperation,
        ops: Sequence[FileOperation],
        known: bool,
        post: bool,
        taken: Collection[str] = (),
    ) -> list[ImportRow]:
        """The conversion of the line `op` (and of the other account's line among `ops`):
        a new one, or the one of an earlier file finished with this side; a fee `taken`
        (posted as a bank operation) stays out. -> the rows of both lines and their
        fees."""
        other = next(
            (
                x
                for x in ops
                if x is not op and x.kind == CONVERSION and x.reference == op.reference
            ),
            None,
        )
        mine = [x for x in (op, other) if x is not None]
        existing = self._conversion_of(company_id, op.reference) if known else None
        fees: list[ConversionFee] = []
        sides: dict[str, ConversionSide | None] = {OUT: None, IN: None}
        days: dict[str, str | None] = {OUT: None, IN: None}
        memo = op.memo
        if existing is not None:
            before = load_conversion(self.conn, company_id, existing)
            has = {OUT: before.source is not None, IN: before.target is not None}
            if before.status == "draft":  # made again of the files' sides and fees: the
                loaded = {x.direction for x in mine}  # rates may be there now
                has = {side: has[side] and side not in loaded for side in has}
            mine = [x for x in mine if not has[x.direction]]
            if not mine:
                return [ImportRow(op, KNOWN)]
            sides = {
                OUT: before.source if has[OUT] else None,
                IN: before.target if has[IN] else None,
            }
            days = {
                OUT: before.doc_date if sides[OUT] else None,
                IN: (before.target_date or before.doc_date) if sides[IN] else None,
            }
            fees = [f for f in before.fees if _of_side(f, sides)]
            memo = before.memo
        for x in mine:
            days[x.direction] = x.day
            sides[x.direction] = ConversionSide(
                x.place.account_id, x.amount, x.place.subconto, x.place.currency_id, x.reference
            )
            fees += [
                ConversionFee(x.place.account_id, -f.amount, x.place.subconto, x.place.currency_id)
                for f in x.fees
                if f.reference not in taken
            ]
        data = ConversionInput(
            doc_date=days[OUT] or days[IN] or op.day,  # the debit's day is the conversion's
            source=sides[OUT],
            target=sides[IN],
            target_date=days[IN] if days[OUT] and days[IN] and days[IN] != days[OUT] else None,
            fees=tuple(fees),
            memo=memo,
        )
        state, why, document = self._save_file_conversion(company_id, data, existing, post)
        return [row for x in mine for row in _rows(x, state, why, document)]

    def _held_conversion(
        self, op: FileOperation, ops: Sequence[FileOperation], number: int
    ) -> list[ImportRow]:
        """A conversion one side of which is posted as bank operation `number` (a transfer
        posted by hand): nothing written, both lines say what to do."""
        why = tr(
            "конвертация: сторона уже проведена операцией №{n} — отмените её проведение "
            "и загрузите файлы ещё раз",
            n=number,
        )
        mine = [x for x in ops if x.kind == CONVERSION and x.reference == op.reference]
        rows = []
        for x in mine:
            rows.append(ImportRow(x, KNOWN, (), why))
            rows += [ImportRow(FileOperation(f, x.place, FEE), KNOWN, (), why) for f in x.fees]
        return rows

    def _save_file_conversion(
        self, company_id: int, data: ConversionInput, existing: int | None, post: bool
    ) -> tuple[str, str, int]:
        """Saved: posted when both sides are known and `post`, else a draft (and why)."""
        conversions = self.ledger.conversion
        why = ""
        if data.source is None or data.target is None:
            why = tr("вторая сторона — в выписке другого счёта")
        elif post:
            try:
                with transaction(self.conn):  # a savepoint: what did not post is undone
                    saved = conversions.save_conversion(company_id, data, existing, post=True)
                return POSTED, "", self._conversion_document(company_id, saved)
            except LedgerError as e:
                why = str(e)
        saved = conversions.save_conversion(company_id, data, existing, post=False)
        return (
            DRAFT,
            why or tr("загружено черновиком"),
            self._conversion_document(company_id, saved),
        )

    def _conversion_of(self, company_id: int, reference: str) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM currency_conversions WHERE company_id = ? "
            "AND (from_reference = ? OR to_reference = ?) ORDER BY id LIMIT 1",
            (company_id, reference, reference),
        ).fetchone()
        return row["id"] if row else None

    def _conversion_document(self, company_id: int, conversion_id: int) -> int:
        return self.conn.execute(
            "SELECT document_id FROM currency_conversions WHERE company_id = ? AND id = ?",
            (company_id, conversion_id),
        ).fetchone()["document_id"]


def _of_side(fee: ConversionFee, sides: dict[str, ConversionSide | None]) -> bool:
    """The fee was taken on a side kept (not loaded again): the side's account."""
    return any(
        side is not None
        and (side.account_id, pad_subconto(side.subconto))
        == (fee.account_id, pad_subconto(fee.subconto))
        for side in sides.values()
    )


def _rows(op: FileOperation, state: str, why: str, document: int) -> list[ImportRow]:
    """The line's row, and a row for each fee of it."""
    other = op.target.name if op.target else ""
    rows = [
        ImportRow(
            op, state, ((tr("конвертация: {name}", name=other), "", op.amount),), why, document
        )
    ]
    for fee in op.fees:
        part = FileOperation(fee, op.place, FEE)
        rows.append(
            ImportRow(part, state, ((tr("комиссия конвертации"), "", part.amount),), why, document)
        )
    return rows
