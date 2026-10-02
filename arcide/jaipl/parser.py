"""jaipl parser: tokens -> AST.

Recursive descent, no dependencies, no lookahead beyond one token. Every
error carries a line and column so the editor can jump to it and the CLI
can print a caret.

The AST nodes are plain frozen dataclasses with a ``line`` attribute; the
interpreter walks them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lexer import JaiError, Token, tokenize


class ParseError(JaiError):
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"line {line}:{col}: {msg}")
        self.msg = msg
        self.line = line
        self.col = col


# ------------------------------------------------------------------ AST


@dataclass(frozen=True, slots=True)
class Node:
    line: int = 0


# expressions
@dataclass(frozen=True, slots=True)
class Literal(Node):
    value: object = None


@dataclass(frozen=True, slots=True)
class Var(Node):
    name: str = ""


@dataclass(frozen=True, slots=True)
class SelfRef(Node):
    pass


@dataclass(frozen=True, slots=True)
class ListLit(Node):
    items: tuple = ()


@dataclass(frozen=True, slots=True)
class MapLit(Node):
    pairs: tuple = ()


@dataclass(frozen=True, slots=True)
class Unary(Node):
    op: str = ""
    operand: object = None


@dataclass(frozen=True, slots=True)
class Binary(Node):
    op: str = ""
    left: object = None
    right: object = None


@dataclass(frozen=True, slots=True)
class Logical(Node):
    op: str = ""
    left: object = None
    right: object = None


@dataclass(frozen=True, slots=True)
class Assign(Node):
    target: object = None
    value: object = None


@dataclass(frozen=True, slots=True)
class Call(Node):
    func: object = None       # Var | Literal(str) for builtins
    args: tuple = ()


@dataclass(frozen=True, slots=True)
class MethodCall(Node):
    target: object = None
    name: str = ""
    args: tuple = ()


@dataclass(frozen=True, slots=True)
    # pylint: disable=too-few-public-methods
class Attribute(Node):
    target: object = None
    name: str = ""


@dataclass(frozen=True, slots=True)
class Index(Node):
    target: object = None
    key: object = None


@dataclass(frozen=True, slots=True)
class New(Node):
    class_name: str = ""
    args: tuple = ()


# statements
@dataclass(frozen=True, slots=True)
class Let(Node):
    name: str = ""
    value: object = None


@dataclass(frozen=True, slots=True)
class Param(Node):
    name: str = ""
    default: object = None


@dataclass(frozen=True, slots=True)
class FuncDecl(Node):
    name: str = ""
    params: tuple = ()
    body: object = None
    is_method: bool = False


@dataclass(frozen=True, slots=True)
class Return(Node):
    value: object = None


@dataclass(frozen=True, slots=True)
class If(Node):
    branches: tuple = ()      # ((cond, block), ...)
    orelse: object = None


@dataclass(frozen=True, slots=True)
class While(Node):
    cond: object = None
    body: object = None


@dataclass(frozen=True, slots=True)
class For(Node):
    var: str = ""
    start: object = None
    stop: object = None
    body: object = None


@dataclass(frozen=True, slots=True)
class Break(Node):
    pass


@dataclass(frozen=True, slots=True)
class Continue(Node):
    pass


@dataclass(frozen=True, slots=True)
class Import(Node):
    module: str = ""


@dataclass(frozen=True, slots=True)
class Block(Node):
    body: tuple = ()


@dataclass(frozen=True, slots=True)
class Field(Node):
    name: str = ""
    value: object = None


@dataclass(frozen=True, slots=True)
class ClassDecl(Node):
    name: str = ""
    parent: str | None = None
    fields: tuple = ()
    methods: tuple = ()


@dataclass(frozen=True, slots=True)
class Program(Node):
    body: tuple = ()
    comments: tuple = field(default=(), compare=False)

    def __iter__(self):
        # Lets callers walk a program's statements directly.
        return iter(self.body)

    def __len__(self) -> int:
        return len(self.body)


# Keywords that can start a statement. A statement also ends where the next
# one clearly begins, which keeps one-line function and class bodies readable
# without needing a semicolon after every line.
STATEMENT_KEYWORDS = (
    "let", "var", "func", "class", "if", "elif", "else", "while", "for",
    "return", "break", "continue", "new", "import",
)


# ------------------------------------------------------------------ parser


class Parser:
    def __init__(self, src: str):
        from .lexer import tokenize_with_comments

        self.toks, self.comments = tokenize_with_comments(src)
        self.i = 0
        self.src = src

    # -- token helpers -------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def peek(self, n: int = 1) -> Token:
        j = min(self.i + n, len(self.toks) - 1)
        return self.toks[j]

    def at(self, kind: str, value=None) -> bool:
        t = self.cur
        return t.kind == kind and (value is None or t.value == value)

    def at_op(self, *ops: str) -> bool:
        t = self.cur
        return t.kind == "op" and t.value in ops

    def at_kw(self, *kws: str) -> bool:
        t = self.cur
        return t.kind == "keyword" and t.value in kws

    def advance(self) -> Token:
        t = self.cur
        if t.kind != "eof":
            self.i += 1
        return t

    def accept_op(self, *ops: str):
        if self.at_op(*ops):
            return self.advance()
        return None

    def accept_kw(self, *kws: str):
        if self.at_kw(*kws):
            return self.advance()
        return None

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            t = self.cur
            raise ParseError(f"expected {op!r} but found {t}", t.line, t.col)
        return self.advance()

    def expect_kw(self, kw: str) -> Token:
        if not self.at_kw(kw):
            t = self.cur
            raise ParseError(f"expected {kw!r} but found {t}", t.line, t.col)
        return self.advance()

    def expect_ident(self) -> Token:
        if self.cur.kind != "ident":
            t = self.cur
            raise ParseError(f"expected a name but found {t}", t.line, t.col)
        return self.advance()

    def skip_newlines(self) -> None:
        while self.cur.kind == "newline" or self.at_op(";"):
            self.advance()

    def end_statement(self) -> None:
        if self.cur.kind == "newline" or self.at_op(";"):
            self.advance()
        elif not self.at("eof") and not self.at_op("}"):
            # A statement also ends where the next one clearly begins. This
            # only fires for keywords, which can never be an identifier, so
            # it cannot turn 'foo bar' into two statements by accident -- it
            # only lets a class body or a one-line function skip the
            # separators it does not need.
            if self.at_kw(*STATEMENT_KEYWORDS):
                return
            t = self.cur
            raise ParseError(f"unexpected {t} at end of statement", t.line, t.col)

    # -- program -------------------------------------------------------
    def parse(self) -> Program:
        body = []
        self.skip_newlines()
        while not self.at("eof"):
            body.append(self.statement())
            self.skip_newlines()
        return Program(line=1, body=tuple(body), comments=tuple(self.comments))

    # -- statements ----------------------------------------------------
    def statement(self):
        t = self.cur

        if self.at_kw("let", "var"):
            return self.let_stmt()
        if self.at_kw("func"):
            return self.func_decl()
        if self.at_kw("class"):
            return self.class_decl()
        if self.at_kw("return"):
            self.advance()
            if self.cur.kind == "newline" or self.at_op(";") or self.at("eof"):
                value = None
            else:
                value = self.expression()
            self.end_statement()
            return Return(line=t.line, value=value)
        if self.at_kw("if"):
            return self.if_stmt()
        if self.at_kw("while"):
            self.advance()
            cond = self.expression()
            body = self.block()
            self.end_statement()
            return While(line=t.line, cond=cond, body=body)
        if self.at_kw("for"):
            return self.for_stmt()
        if self.at_kw("break"):
            self.advance()
            self.end_statement()
            return Break(line=t.line)
        if self.at_kw("continue"):
            self.advance()
            self.end_statement()
            return Continue(line=t.line)
        if self.at_kw("import"):
            self.advance()
            name = self.cur
            if name.kind not in ("ident", "string"):
                raise ParseError(
                    f"expected a module name after import but found {name}",
                    name.line, name.col,
                )
            self.advance()
            while self.at_op("."):
                self.advance()
                self.expect_ident()
            self.end_statement()
            return Import(line=t.line, module=str(name.value))
        if self.at_op("{"):
            b = self.block()
            self.end_statement()
            return b

        expr = self.expression()
        self.end_statement()
        return expr

    def let_stmt(self):
        t = self.advance()  # let / var
        name = self.expect_ident()
        self.expect_op("=")
        value = self.expression()
        return Let(line=t.line, name=str(name.value), value=value)

    def decl_name(self) -> str:
        """Read a declared name.

        'new' is a keyword for instantiating, but it is also the name every
        jaipl class uses for its constructor, so it is accepted here.
        """
        if self.at_kw("new"):
            return str(self.advance().value)
        return str(self.expect_ident().value)

    def func_decl(self, is_method: bool = False):
        t = self.expect_kw("func")
        name = self.decl_name()
        params = self.param_list()
        body = self.block()
        return FuncDecl(
            line=t.line, name=name, params=params,
            body=body, is_method=is_method,
        )

    def param_list(self) -> tuple:
        self.expect_op("(")
        params = []
        if not self.at_op(")"):
            while True:
                pname = self.expect_ident()
                default = None
                if self.accept_op("="):
                    default = self.expression()
                params.append(
                    Param(line=pname.line, name=str(pname.value), default=default)
                )
                if not self.accept_op(","):
                    break
        self.expect_op(")")
        return tuple(params)

    def class_decl(self):
        t = self.expect_kw("class")
        name = self.expect_ident()
        parent = None
        if self.accept_kw("extends"):
            pname = self.expect_ident()
            parent = str(pname.value)
        self.expect_op("{")
        fields, methods = [], []
        self.skip_newlines()
        while not self.at_op("}"):
            self.skip_newlines()
            if self.at_op("}"):
                break
            if self.at_kw("let", "var"):
                ft = self.advance()
                fname = self.expect_ident()
                fvalue = None
                if self.accept_op("="):
                    fvalue = self.expression()
                fields.append(
                    Field(line=ft.line, name=str(fname.value), value=fvalue)
                )
                self.end_statement()
            elif self.at_kw("func"):
                methods.append(self.func_decl(is_method=True))
                self.skip_newlines()
            else:
                c = self.cur
                raise ParseError(
                    f"expected a field or method but found {c}", c.line, c.col
                )
        self.expect_op("}")
        return ClassDecl(
            line=t.line, name=str(name.value), parent=parent,
            fields=tuple(fields), methods=tuple(methods),
        )

    def if_stmt(self):
        t = self.cur
        branches = []
        self.expect_kw("if")
        cond = self.expression()
        body = self.block()
        branches.append((cond, body))
        orelse = None
        while True:
            save = self.i
            self.skip_newlines()
            if self.at_kw("elif"):
                self.advance()
                c2 = self.expression()
                b2 = self.block()
                branches.append((c2, b2))
                continue
            if self.at_kw("else"):
                self.advance()
                if self.at_kw("if"):
                    # `else if` is just another branch.
                    self.advance()
                    c2 = self.expression()
                    b2 = self.block()
                    branches.append((c2, b2))
                    continue
                orelse = self.block()
                break
            self.i = save
            break
        self.end_statement()
        return If(line=t.line, branches=tuple(branches), orelse=orelse)

    def for_stmt(self):
        t = self.expect_kw("for")
        var = self.expect_ident()
        self.expect_kw("in")
        start = self.expression()
        stop = None
        if self.accept_op(".."):
            stop = self.expression()
        body = self.block()
        self.end_statement()
        return For(
            line=t.line, var=str(var.value),
            start=start, stop=stop, body=body,
        )

    def block(self):
        t = self.expect_op("{")
        body = []
        self.skip_newlines()
        while not self.at_op("}"):
            if self.at("eof"):
                c = self.cur
                raise ParseError("unexpected end of file, expected '}'", c.line, c.col)
            body.append(self.statement())
            self.skip_newlines()
        self.expect_op("}")
        return Block(line=t.line, body=tuple(body))

    # -- expressions ---------------------------------------------------
    def expression(self):
        return self.assignment()

    def assignment(self):
        left = self.logical_or()
        if self.at_op("=", "+=", "-=", "*=", "/="):
            op = str(self.advance().value)
            right = self.assignment()
            if op == "=":
                return Assign(line=left.line, target=left, value=right)
            return Assign(
                line=left.line, target=left,
                value=Binary(line=left.line, op=op[0], left=left, right=right),
            )
        return left

    def logical_or(self):
        left = self.logical_and()
        while self.at_kw("or"):
            t = self.advance()
            right = self.logical_and()
            left = Logical(line=t.line, op="or", left=left, right=right)
        return left

    def logical_and(self):
        left = self.comparison()
        while self.at_kw("and"):
            t = self.advance()
            right = self.comparison()
            left = Logical(line=t.line, op="and", left=left, right=right)
        return left

    def comparison(self):
        left = self.additive()
        if self.at_op("==", "!=", "<", "<=", ">", ">="):
            op = str(self.advance().value)
            right = self.additive()
            return Binary(line=left.line, op=op, left=left, right=right)
        return left

    def additive(self):
        left = self.multiplicative()
        while self.at_op("+", "-"):
            op = str(self.advance().value)
            right = self.multiplicative()
            left = Binary(line=left.line, op=op, left=left, right=right)
        return left

    def multiplicative(self):
        left = self.power()
        while self.at_op("*", "/", "%"):
            op = str(self.advance().value)
            right = self.power()
            left = Binary(line=left.line, op=op, left=left, right=right)
        return left

    def power(self):
        # Binds tighter than * so 2 * 3 ** 2 is 18, and is right-associative
        # so 2 ** 3 ** 2 is 512.
        left = self.unary()
        if self.at_op("**"):
            t = self.advance()
            right = self.power()
            return Binary(line=t.line, op="**", left=left, right=right)
        return left

    def unary(self):
        if self.at_op("-", "!"):
            t = self.advance()
            operand = self.unary()
            return Unary(line=t.line, op=str(t.value), operand=operand)
        if self.at_kw("not"):
            t = self.advance()
            return Unary(line=t.line, op="!", operand=self.unary())
        return self.postfix()

    def postfix(self):
        expr = self.primary()
        while True:
            if self.at_op("("):
                args = self.arguments()
                if isinstance(expr, Var):
                    expr = Call(line=expr.line, func=expr, args=args)
                else:
                    expr = Call(line=expr.line, func=expr, args=args)
                continue
            if self.at_op("."):
                self.advance()
                name = self.expect_ident()
                if self.at_op("("):
                    args = self.arguments()
                    expr = MethodCall(
                        line=expr.line, target=expr, name=str(name.value), args=args
                    )
                else:
                    expr = Attribute(
                        line=expr.line, target=expr, name=str(name.value)
                    )
                continue
            if self.at_op("["):
                self.advance()
                key = self.expression()
                self.expect_op("]")
                expr = Index(line=expr.line, target=expr, key=key)
                continue
            break
        return expr

    def arguments(self) -> tuple:
        self.expect_op("(")
        args = []
        if not self.at_op(")"):
            while True:
                args.append(self.expression())
                if not self.accept_op(","):
                    break
                # A trailing comma before ')' is allowed, so calls and lists
                # can be wrapped one-item-per-line without fiddling.
                if self.at_op(")"):
                    break
        self.expect_op(")")
        return tuple(args)

    def primary(self):
        t = self.cur

        if t.kind in ("int", "float", "string"):
            self.advance()
            return Literal(line=t.line, value=t.value)

        if self.at_kw("true", "false", "null"):
            self.advance()
            val = {"true": True, "false": False, "null": None}[str(t.value)]
            return Literal(line=t.line, value=val)

        if self.at_kw("self"):
            self.advance()
            return SelfRef(line=t.line)

        if self.at_kw("new"):
            self.advance()
            cname = self.expect_ident()
            args = self.arguments() if self.at_op("(") else ()
            return New(line=t.line, class_name=str(cname.value), args=args)

        if t.kind == "ident":
            self.advance()
            return Var(line=t.line, name=str(t.value))

        if self.at_op("("):
            self.advance()
            e = self.expression()
            self.expect_op(")")
            return e

        if self.at_op("["):
            self.advance()
            items = []
            if not self.at_op("]"):
                while True:
                    items.append(self.expression())
                    if not self.accept_op(","):
                        break
                    if self.at_op("]"):
                        break
            self.expect_op("]")
            return ListLit(line=t.line, items=tuple(items))

        if self.at_op("{"):
            self.advance()
            pairs = []
            if not self.at_op("}"):
                while True:
                    k = self.cur
                    if k.kind in ("string", "ident"):
                        self.advance()
                        key = str(k.value)
                    else:
                        raise ParseError(
                            f"expected a map key but found {k}", k.line, k.col
                        )
                    self.expect_op(":")
                    pairs.append((key, self.expression()))
                    if not self.accept_op(","):
                        break
            self.expect_op("}")
            return MapLit(line=t.line, pairs=tuple(pairs))

        raise ParseError(f"unexpected {t}", t.line, t.col)


def parse(src: str) -> Program:
    return Parser(src).parse()


def parse_file(path) -> Program:
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    try:
        return parse(text)
    except JaiError as e:
        raise type(e)(e.msg, e.line, e.col) from None