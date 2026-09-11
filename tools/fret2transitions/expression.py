"""A small, safe parser for the Boolean subset used in FSM guards."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Mapping

from .errors import ExpressionSyntaxError


class Expr:
    """Base class for parsed expressions."""

    def identifiers(self) -> set[str]:
        raise NotImplementedError

    def to_python(self, input_name: str = "inputs") -> str:
        raise NotImplementedError

    def evaluate(self, values: Mapping[str, object]) -> object:
        raise NotImplementedError


@dataclass(frozen=True)
class Literal(Expr):
    value: object

    def identifiers(self) -> set[str]:
        return set()

    def to_python(self, input_name: str = "inputs") -> str:
        return repr(self.value)

    def evaluate(self, values: Mapping[str, object]) -> object:
        return self.value


@dataclass(frozen=True)
class Variable(Expr):
    name: str

    def identifiers(self) -> set[str]:
        return {self.name}

    def to_python(self, input_name: str = "inputs") -> str:
        return f"{input_name}[{self.name!r}]"

    def evaluate(self, values: Mapping[str, object]) -> object:
        return values[self.name]


@dataclass(frozen=True)
class Not(Expr):
    operand: Expr

    def identifiers(self) -> set[str]:
        return self.operand.identifiers()

    def to_python(self, input_name: str = "inputs") -> str:
        return f"(not {self.operand.to_python(input_name)})"

    def evaluate(self, values: Mapping[str, object]) -> object:
        return not bool(self.operand.evaluate(values))


@dataclass(frozen=True)
class Binary(Expr):
    operator: str
    left: Expr
    right: Expr

    def identifiers(self) -> set[str]:
        return self.left.identifiers() | self.right.identifiers()

    def to_python(self, input_name: str = "inputs") -> str:
        operator = "and" if self.operator == "and" else "or"
        left = self.left.to_python(input_name)
        right = self.right.to_python(input_name)
        return f"({left} {operator} {right})"

    def evaluate(self, values: Mapping[str, object]) -> object:
        if self.operator == "and":
            return bool(self.left.evaluate(values)) and bool(self.right.evaluate(values))
        return bool(self.left.evaluate(values)) or bool(self.right.evaluate(values))


@dataclass(frozen=True)
class Comparison(Expr):
    operator: str
    left: Expr
    right: Expr

    def identifiers(self) -> set[str]:
        return self.left.identifiers() | self.right.identifiers()

    def to_python(self, input_name: str = "inputs") -> str:
        operator = "==" if self.operator == "=" else self.operator
        left = self.left.to_python(input_name)
        right = self.right.to_python(input_name)
        return f"({left} {operator} {right})"

    def evaluate(self, values: Mapping[str, object]) -> object:
        left = self.left.evaluate(values)
        right = self.right.evaluate(values)
        if self.operator == "=":
            return left == right
        if self.operator == "!=":
            return left != right
        if self.operator == "<":
            return left < right
        if self.operator == "<=":
            return left <= right
        if self.operator == ">":
            return left > right
        if self.operator == ">=":
            return left >= right
        raise AssertionError(f"unknown comparison operator: {self.operator}")


_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<LE><=)
  | (?P<GE>>=)
  | (?P<NE>!=)
  | (?P<EQ>==|=)
  | (?P<AND>&|\band\b)
  | (?P<OR>\||\bor\b)
  | (?P<NOT>!|\bnot\b)
  | (?P<LT><)
  | (?P<GT>>)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<BOOL>\btrue\b|\bfalse\b)
  | (?P<NUMBER>-?(?:\d+\.\d+|\d+))
  | (?P<STRING>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_.]*)
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if not match:
            fragment = text[position : position + 20]
            raise ExpressionSyntaxError(
                f"unsupported token at column {position + 1}: {fragment!r}"
            )
        kind = match.lastgroup
        if kind != "WS":
            assert kind is not None
            tokens.append(Token(kind, match.group(), position))
        position = match.end()
    tokens.append(Token("EOF", "", position))
    return tokens


class ExpressionParser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = tokenize(text)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def accept(self, *kinds: str) -> Token | None:
        if self.current.kind in kinds:
            token = self.current
            self.index += 1
            return token
        return None

    def expect(self, kind: str) -> Token:
        token = self.accept(kind)
        if token is None:
            raise ExpressionSyntaxError(
                f"expected {kind} at column {self.current.position + 1} in {self.text!r}"
            )
        return token

    def parse(self) -> Expr:
        expression = self.parse_or()
        self.expect("EOF")
        return expression

    def parse_or(self) -> Expr:
        expression = self.parse_and()
        while self.accept("OR"):
            expression = Binary("or", expression, self.parse_and())
        return expression

    def parse_and(self) -> Expr:
        expression = self.parse_not()
        while self.accept("AND"):
            expression = Binary("and", expression, self.parse_not())
        return expression

    def parse_not(self) -> Expr:
        if self.accept("NOT"):
            return Not(self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Expr:
        expression = self.parse_primary()
        operator = self.accept("EQ", "NE", "LT", "LE", "GT", "GE")
        if operator:
            normalized = "=" if operator.kind == "EQ" else operator.value
            expression = Comparison(normalized, expression, self.parse_primary())
        return expression

    def parse_primary(self) -> Expr:
        if self.accept("LPAREN"):
            expression = self.parse_or()
            self.expect("RPAREN")
            return expression
        token = self.accept("BOOL", "NUMBER", "STRING", "IDENT")
        if token is None:
            raise ExpressionSyntaxError(
                f"expected a value at column {self.current.position + 1} in {self.text!r}"
            )
        if token.kind == "BOOL":
            return Literal(token.value.lower() == "true")
        if token.kind == "NUMBER":
            return Literal(float(token.value) if "." in token.value else int(token.value))
        if token.kind == "STRING":
            # FRET state-machine names normally use identifiers. Quoted values are
            # accepted here so the converter does not need Python eval().
            return Literal(ast.literal_eval(token.value))
        return Variable(token.value)


def parse_expression(text: str) -> Expr:
    return ExpressionParser(text.strip()).parse()


def flatten(expression: Expr, operator: str) -> list[Expr]:
    if isinstance(expression, Binary) and expression.operator == operator:
        return flatten(expression.left, operator) + flatten(expression.right, operator)
    return [expression]


def join(operator: str, expressions: list[Expr]) -> Expr:
    if not expressions:
        return Literal(True if operator == "and" else False)
    result = expressions[0]
    for expression in expressions[1:]:
        result = Binary(operator, result, expression)
    return result


def canonical(expression: Expr) -> str:
    """Return a stable form used for structural Boolean equivalence checks."""

    if isinstance(expression, Literal):
        return repr(expression.value)
    if isinstance(expression, Variable):
        return f"var:{expression.name}"
    if isinstance(expression, Not):
        return f"not({canonical(expression.operand)})"
    if isinstance(expression, Comparison):
        return f"cmp:{canonical(expression.left)}{expression.operator}{canonical(expression.right)}"
    if isinstance(expression, Binary):
        parts = sorted({canonical(part) for part in flatten(expression, expression.operator)})
        return f"{expression.operator}({','.join(parts)})"
    raise TypeError(f"unsupported expression: {type(expression).__name__}")


def state_value(expression: Expr) -> str:
    if isinstance(expression, Variable):
        return expression.name
    if isinstance(expression, Literal):
        if isinstance(expression.value, bool):
            return str(expression.value).lower()
        return str(expression.value)
    raise ExpressionSyntaxError("a state value must be an identifier or literal")


def assignment(expression: Expr) -> tuple[str, str]:
    """Extract ``state_variable = state_value`` from an expression."""

    if not isinstance(expression, Comparison) or expression.operator != "=":
        raise ExpressionSyntaxError("expected a state equality")
    if isinstance(expression.left, Variable):
        return expression.left.name, state_value(expression.right)
    if isinstance(expression.right, Variable):
        return expression.right.name, state_value(expression.left)
    raise ExpressionSyntaxError("a state equality must contain a variable")


def extract_source(expression: Expr, state_variable: str) -> tuple[str, Expr]:
    """Remove a top-level state equality from a conjunction and return its value."""

    terms = flatten(expression, "and")
    source: str | None = None
    remaining: list[Expr] = []
    for term in terms:
        try:
            variable, value = assignment(term)
        except ExpressionSyntaxError:
            remaining.append(term)
            continue
        if variable == state_variable and source is None:
            source = value
        else:
            remaining.append(term)
    if source is None:
        raise ExpressionSyntaxError(
            f"condition does not contain a top-level equality for {state_variable!r}"
        )
    return source, join("and", remaining)
