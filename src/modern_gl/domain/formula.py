"""Amount formulas of entry templates.

A formula uses S (the operation amount entered once), L1, L2… (amounts of the
template's lines), numbers (1180, 1.18, 1,18), + - * / and parentheses:
    S            the amount itself
    S*18/118     VAT inside an amount with 18% VAT
    S-L2         the amount without line 2
An empty formula means the amount is typed by hand.

Arithmetic is exact (fractions); only the final line amount is rounded to
kopecks, half away from zero.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import SCALE, round_half_away
from modern_gl.i18n import tr

MINOR = 10**SCALE  # kopecks in a manat

_TOKEN = re.compile(r"\s*(?:(\d+(?:[.,]\d+)?)|([SL])(\d*)|(.))")


def _tokens(text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for number, name, index, other in _TOKEN.findall(text.upper()):
        if number:
            result.append(("num", number.replace(",", ".")))
        elif name == "S" and not index:
            result.append(("var", "S"))
        elif name == "L" and index:
            result.append(("var", f"L{int(index)}"))
        elif other and other in "+-*/()":
            result.append((other, other))
        elif other.strip() or name:
            raise ValidationError(tr("непонятный символ «{c}» в формуле", c=other or name))
    return result


@dataclass(frozen=True)
class _Num:
    value: Fraction


@dataclass(frozen=True)
class _Var:
    name: str  # "S" or "L<n>"


@dataclass(frozen=True)
class _Neg:
    inner: _Node


@dataclass(frozen=True)
class _BinOp:
    op: str  # + - * /
    left: _Node
    right: _Node


type _Node = _Num | _Var | _Neg | _BinOp


class _Parser:
    """expr := term (('+'|'-') term)* ; term := factor (('*'|'/') factor)* ;
    factor := ('-'|'+') factor | number | S | Ln | '(' expr ')'"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = _tokens(text)
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self) -> _Node:
        if not self.tokens:
            raise ValidationError(tr("пустая формула"))
        node = self.expr()
        if self.peek() is not None:
            raise ValidationError(tr("ошибка в формуле «{f}»", f=self.text))
        return node

    def expr(self) -> _Node:
        node = self.term()
        while self.peek() in ("+", "-"):
            node = _BinOp(self.take()[0], node, self.term())
        return node

    def term(self) -> _Node:
        node = self.factor()
        while self.peek() in ("*", "/"):
            node = _BinOp(self.take()[0], node, self.factor())
        return node

    def factor(self) -> _Node:
        kind = self.peek()
        if kind in ("-", "+"):
            self.take()
            inner = self.factor()
            return _Neg(inner) if kind == "-" else inner
        if kind == "num":
            return _Num(Fraction(self.take()[1]))
        if kind == "var":
            return _Var(self.take()[1])
        if kind == "(":
            self.take()
            node = self.expr()
            if self.peek() != ")":
                raise ValidationError(tr("не закрыта скобка в формуле «{f}»", f=self.text))
            self.take()
            return node
        raise ValidationError(tr("ошибка в формуле «{f}»", f=self.text))


def parse(text: str) -> _Node:
    """The formula's tree; ValidationError (message for the user) on a syntax error."""
    return _Parser(text.strip()).parse()


def variables(node: _Node) -> set[str]:
    """The names a formula uses: "S" and "L<n>"."""
    match node:
        case _Var(name):
            return {name}
        case _Num():
            return set()
        case _Neg(inner):
            return variables(inner)
        case _BinOp(_, left, right):
            return variables(left) | variables(right)


def _evaluate(node: _Node, values: dict[str, Fraction]) -> Fraction:
    match node:
        case _Num(value):
            return value
        case _Var(name):
            return values[name]
        case _Neg(inner):
            return -_evaluate(inner, values)
        case _BinOp(op, left, right):
            return _apply(op, _evaluate(left, values), _evaluate(right, values))


def _apply(op: str, left: Fraction, right: Fraction) -> Fraction:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        raise ValidationError(tr("деление на ноль в формуле"))
    return left / right


def _round_minor(value: Fraction) -> int:
    """Major units (exact) -> kopecks, half away from zero."""
    return round_half_away(value * MINOR)


def check(formulas: Sequence[str]) -> None:
    """Validate a template's formulas: syntax, line references, no cycles."""
    compute(formulas, None)


def uses_amount(formulas: Sequence[str]) -> bool:
    """Whether any of the template's formulas uses S (the amount typed once)."""
    return any(f.strip() and "S" in variables(parse(f)) for f in formulas)


def compute(formulas: Sequence[str], amount: int | None) -> list[int | None]:
    """Line amounts in kopecks for the operation amount S (kopecks); None where the
    formula is empty (typed by hand). With amount=None only validates (S = 1)."""
    trees = {i + 1: parse(f) for i, f in enumerate(formulas) if f.strip()}
    s = Fraction(amount if amount is not None else MINOR, MINOR)
    done: dict[int, int] = {}

    def line(n: int, path: tuple[int, ...]) -> int:
        if n in done:
            return done[n]
        if n in path:
            raise ValidationError(tr("строка {n}: формула ссылается сама на себя", n=n))
        values = {"S": s}
        for name in variables(trees[n]):
            if name == "S":
                continue
            ref = int(name[1:])
            if ref not in trees:
                raise ValidationError(tr("строка {n}: в строке {ref} нет формулы", n=n, ref=ref))
            values[name] = Fraction(line(ref, (*path, n)), MINOR)
        done[n] = _round_minor(_evaluate(trees[n], values))
        return done[n]

    return [line(i + 1, ()) if i + 1 in trees else None for i in range(len(formulas))]


def evaluate(text: str) -> int:
    """An amount typed as arithmetic ("1180*18/118", "=1000+180") -> kopecks, rounded
    half away from zero. Only numbers and + - * / ( ) — no S or L here."""
    tree = parse(text.strip().lstrip("=").replace(" ", "").replace("\u00a0", ""))
    if variables(tree):
        raise ValidationError(tr("в сумме можно только числа и + − * / ( )"))
    return _round_minor(_evaluate(tree, {}))
