"""Postings given by names, not ids (D84, D130): accounts by code, directory elements by
name, VÖEN or code, currencies by code; amounts as text ("261.13"), never a JSON float.
The assistant and the exchange file both write lines so; a file another program wrote is
read `exact` — no guessing by a part of a name."""

from __future__ import annotations

from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.i18n import tr

LINE_KEYS = {
    "debit",
    "debit_subconto",
    "credit",
    "credit_subconto",
    "amount",
    "memo",
    "e_qaime",
    "currency",
    "currency_amount",
}


def posting_lines(cat: Catalog, postings: object, exact: bool = False) -> list[PostingInput]:
    """The lines of a document; a problem — ValueError or LookupError naming the line."""
    if not isinstance(postings, list) or not postings:
        raise ValueError(tr("нет проводок"))
    return [_line(cat, i, p, exact) for i, p in enumerate(postings, start=1)]


def _line(cat: Catalog, i: int, p: object, exact: bool) -> PostingInput:
    if not isinstance(p, dict):
        raise ValueError(tr("строка {line}: ожидается объект с полями проводки", line=i))
    unknown = set(p) - LINE_KEYS
    if unknown:
        raise ValueError(tr("строка {line}: лишние поля {keys}", line=i, keys=sorted(unknown)))
    debit = cat.resolve_account(str(p.get("debit", "")), exact)
    credit = cat.resolve_account(str(p.get("credit", "")), exact)
    currency = cat.resolve_currency(p["currency"]).id if p.get("currency") else None
    return PostingInput(
        debit.id,
        credit.id,
        _amount(i, p.get("amount")),
        _subconto(cat, debit, p.get("debit_subconto") or [], exact),
        _subconto(cat, credit, p.get("credit_subconto") or [], exact),
        str(p.get("memo") or ""),
        currency,
        _amount(i, p["currency_amount"]) if p.get("currency_amount") is not None else None,
        str(p.get("e_qaime") or ""),
    )


def _amount(line: int, value: object) -> str:
    """An amount as text ("261.13"): a JSON number would arrive as a float."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(tr('строка {line}: сумма — строкой, например "261.13"', line=line))
    return str(value)


def _subconto(cat: Catalog, account: AccountInfo, names: object, exact: bool) -> list[int | None]:
    """The elements by name (or VÖEN) in the order of the account's subconto; a contract is
    looked for among its counterparty's."""
    if not isinstance(names, list):
        raise ValueError(tr('субконто — списком, например ["Bakı Elektrik"]'))
    kinds = [k for k in account.sc_kinds if k is not None]
    if len(names) > len(kinds):
        raise ValueError(
            tr(
                "у счёта {code} субконто: {kinds}",
                code=account.short,
                kinds=", ".join(cat.kinds[k] for k in kinds) or "—",
            )
        )
    values: list[int | None] = []
    for pos, name in enumerate(names):
        kind = account.sc_kinds[pos]
        if not name or kind is None:
            values.append(None)
            continue
        slot = cat.owner_slot(account, pos)
        owner = values[slot] if slot is not None and slot < len(values) else None
        found = cat.resolve_value(kind, str(name), owner, exact_only=exact)
        if found is None:
            raise LookupError(
                tr(
                    "«{name}» нет в справочнике «{kind}» — его добавляет человек в программе",
                    name=name,
                    kind=cat.kinds[kind],
                )
            )
        values.append(found)
    return values
