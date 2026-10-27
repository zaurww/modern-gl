"""The exchange file of journal documents, version 1 (D130, docs/EXCHANGE.md): what
another program writes for the program to read. Only the shape is checked here — the
accounts and the directories are the company's (`importer`).

    {"format": "modern-gl/documents", "version": 1, "source": "etax-ext",
     "documents": [{"id": "S-2026-0001", "date": "2026-03-05", "memo": "…",
                    "postings": [{"debit": "62.1", "credit": "90.1", "amount": "118.00",
                                  "debit_subconto": ["Bakı Elektrik"]}]}]}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from modern_gl.application.ledger.inputs import DEFAULT_LAYERS
from modern_gl.i18n import tr

FORMAT = "modern-gl/documents"
VERSION = 1  # a newer file is refused: it may mean what this program does not know
LAYERS = tuple(code for code, _ in DEFAULT_LAYERS)

BATCH_KEYS = {"format", "version", "source", "documents"}
DOCUMENT_KEYS = {"id", "date", "memo", "layer", "postings", "reverses"}


class FormatError(ValueError):
    """The file is not an exchange file of a version this program reads, or a line of a
    document is not of the shape the format gives (`lines`)."""


@dataclass(frozen=True)
class ExchangeDocument:
    external_id: str  # the document's id in its program: a repeat finds it (D72)
    doc_date: str  # ISO
    memo: str
    layer: str
    postings: list  # lines as in `lines.posting_lines`, resolved against the company
    reverses: str = ""  # a red storno of the document of this id, instead of postings


@dataclass(frozen=True)
class ExchangeBatch:
    source: str  # the program that wrote the file
    documents: list[ExchangeDocument]


def parse_batch(data: object) -> ExchangeBatch:
    """The batch of a decoded JSON file; FormatError says what is wrong and where."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise FormatError(tr('это не файл документов Modern GL: нет "format": "{f}"', f=FORMAT))
    _no_unknown(data, BATCH_KEYS, tr("файл"))
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise FormatError(tr("версия формата — целое число, например 1"))
    if version > VERSION:
        raise FormatError(
            tr(
                "файл версии {v}, программа читает до {max} — обновите программу",
                v=version,
                max=VERSION,
            )
        )
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        raise FormatError(tr('не указан источник файла ("source")'))
    documents = data.get("documents")
    if not isinstance(documents, list):
        raise FormatError(tr('нет списка документов ("documents")'))
    return ExchangeBatch(source.strip(), [_document(i, d) for i, d in enumerate(documents, 1)])


def _document(n: int, d: object) -> ExchangeDocument:
    where = tr("документ {n}", n=n)
    if not isinstance(d, dict):
        raise FormatError(tr("{where}: ожидается объект", where=where))
    _no_unknown(d, DOCUMENT_KEYS, where)
    external_id = d.get("id")
    if not isinstance(external_id, str) or not external_id.strip():
        raise FormatError(tr('{where}: нет "id" — его номер в вашей программе', where=where))
    layer = d.get("layer", "common")
    if layer not in LAYERS:
        raise FormatError(
            tr("{where}: слой — один из {layers}", where=where, layers=", ".join(LAYERS))
        )
    memo = d.get("memo", "")
    if not isinstance(memo, str):
        raise FormatError(tr('{where}: "memo" — строка', where=where))
    reverses = d.get("reverses", "")
    if not isinstance(reverses, str) or (reverses and d.get("postings")):
        raise FormatError(tr('{where}: "reverses" — id документа, без своих проводок', where=where))
    return ExchangeDocument(
        external_id.strip(),
        _date(where, d.get("date")),
        memo,
        layer,
        d.get("postings") or [],
        reverses.strip(),
    )


def _date(where: str, value: object) -> str:
    try:
        if not isinstance(value, str) or len(value) != 10:  # not "20260305"
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise FormatError(
            tr('{where}: дата — "ГГГГ-ММ-ДД", например "2026-03-05"', where=where)
        ) from None


def _no_unknown(data: dict, known: set[str], where: str) -> None:
    unknown = set(data) - known
    if unknown:
        raise FormatError(tr("{where}: лишние поля {keys}", where=where, keys=sorted(unknown)))
