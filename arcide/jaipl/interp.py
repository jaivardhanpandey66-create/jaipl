"""jaipl runtime: a tree-walking interpreter.

Pure Python, no dependencies.

Values are plain Python objects where that is natural (``int``, ``float``,
``str``, ``list``, ``dict``, ``bool``, ``None``) and small classes where it
is not. User classes get real inheritance and virtual dispatch: a method
looked up on an instance always resolves against the instance's own class
first, so overriding works without any extra machinery.

Control flow uses exceptions, which keeps the evaluator free of flag
plumbing: ``return``, ``break`` and ``continue`` all unwind naturally.
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .lexer import JaiError
from .parser import (
    Assign, Attribute, Binary, Block, Break, Call, ClassDecl, Continue,
    Field as FieldDecl, For, FuncDecl, If, Import, Index, Let, ListLit,
    Literal, Logical, MapLit, MethodCall, New, Program, Return, SelfRef,
    Unary, Var, While,
)


class RuntimeError_(JaiError):
    """A jaipl-level error (as opposed to a lexer/parser error)."""

    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.msg = msg
        self.line = line


def _default_step_limit() -> int:
    """How many statements run before an infinite loop is called out.

    Overridable with JAIPL_MAX_STEPS, and 0 disables the check entirely for
    genuinely long-running programs.
    """
    raw = os.environ.get("JAIPL_MAX_STEPS", "")
    if raw.strip():
        try:
            return int(raw)
        except ValueError:
            pass
    return 20_000_000


# control-flow signals
class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class ExitSignal(Exception):
    def __init__(self, code: int = 0):
        self.code = code


# ------------------------------------------------------------------ values


class Instance:
    """A user object. ``vars`` starts as a copy of the class's fields."""

    __slots__ = ("cls", "vars")

    def __init__(self, cls: "UserClass", vars_: dict):
        self.cls = cls
        self.vars = vars_

    @property
    def type_name(self) -> str:
        return self.cls.name

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self.vars.items())
        return f"{self.cls.name}({inner})"


class UserClass:
    __slots__ = ("name", "parent", "fields", "methods", "env")

    def __init__(self, name: str, parent: "UserClass | None"):
        self.name = name
        self.parent = parent
        self.fields: list[FieldDecl] = []
        self.methods: dict[str, FuncDecl] = {}
        self.env = None

    def find_method(self, name: str) -> FuncDecl | None:
        c: UserClass | None = self
        while c is not None:
            if name in c.methods:
                return c.methods[name]
            c = c.parent
        return None

    def all_fields(self) -> list[FieldDecl]:
        """Base-class fields first, so a subclass can shadow defaults."""
        chain = []
        c: UserClass | None = self
        while c is not None:
            chain.append(c)
            c = c.parent
        out = []
        for c in reversed(chain):
            out.extend(c.fields)
        return out

    def ancestors(self) -> list[str]:
        names = []
        c = self.parent
        while c is not None:
            names.append(c.name)
            c = c.parent
        return names


class Function:
    __slots__ = ("decl", "env", "name", "is_method")

    def __init__(self, decl: FuncDecl, env: "Env", name: str = ""):
        self.decl = decl
        self.env = env
        self.name = name or decl.name
        self.is_method = decl.is_method


class NativeFn:
    __slots__ = ("name", "fn", "wants_interp")

    def __init__(self, name: str, fn, wants_interp=False):
        self.name = name
        self.fn = fn
        self.wants_interp = wants_interp


class BoundMethod:
    __slots__ = ("instance", "func")

    def __init__(self, instance: Instance, func: Function):
        self.instance = instance
        self.func = func


# ------------------------------------------------------------------ env


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent: "Env | None" = None):
        self.vars: dict[str, object] = {}
        self.parent = parent

    def get(self, name: str):
        e: Env | None = self
        while e is not None:
            if name in e.vars:
                return e.vars[name]
            e = e.parent
        raise KeyError(name)

    def has(self, name: str) -> bool:
        e: Env | None = self
        while e is not None:
            if name in e.vars:
                return True
            e = e.parent
        return False

    def set(self, name: str, value) -> None:
        e: Env | None = self
        while e is not None:
            if name in e.vars:
                e.vars[name] = value
                return
            e = e.parent
        raise KeyError(name)

    def assign_new(self, name: str, value) -> None:
        self.vars[name] = value

    def define(self, name: str, value) -> None:
        self.vars[name] = value


# ------------------------------------------------------------------ output


@dataclass
class Output:
    """Where print() goes. Swap this to capture output in tests."""

    write: object = print
    lines: list = field(default_factory=list)


# ------------------------------------------------------------------ interp


class Interpreter:
    # Each jaipl call frame costs several Python frames, so Python's own
    # limit has to sit well above this one or a legitimate deep recursion
    # dies as a RecursionError instead of the clear message below.
    MAX_DEPTH = 300

    def __init__(self, out: Output | None = None, max_steps: int = 0):
        self.globals = Env()
        self.out = out or Output()
        self.classes: dict[str, UserClass] = {}
        self.depth = 0
        self.steps = 0
        # 0 means "use the default", which is a high ceiling rather than no
        # ceiling: an accidental 'while true {}' should stop with a message
        # instead of hanging the editor forever.
        self.max_steps = max_steps or _default_step_limit()
        self.exited: int | None = None
        sys.setrecursionlimit(max(sys.getrecursionlimit(), self.MAX_DEPTH * 30))
        self._install_builtins()

    # -- builtins -----------------------------------------------------
    def _install_builtins(self) -> None:
        g = self.globals

        def _print(*args):
            parts = [self.to_display(a) for a in args]
            line = " ".join(parts)
            self.out.lines.append(line)
            self.out.write(line)

        def _len(v):
            if isinstance(v, (list, str, dict)):
                return len(v)
            raise RuntimeError_(
                f"len() needs a list, map or string, not {type(v).__name__}"
            )

        def _str(v):
            return self.to_display(v)

        def _int(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                raise RuntimeError_(f"cannot convert {v!r} to int") from None

        def _float(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                raise RuntimeError_(f"cannot convert {v!r} to float") from None

        def _input(prompt=""):
            if prompt:
                self.out.write(str(prompt))
            try:
                return input()
            except EOFError:
                return ""

        def _push(lst, value):
            if not isinstance(lst, list):
                raise RuntimeError_("push() needs a list")
            lst.append(value)
            return None

        def _pop(lst):
            if not isinstance(lst, list) or not lst:
                raise RuntimeError_("pop() needs a non-empty list")
            return lst.pop()

        def _range(*a):
            try:
                return list(range(*[int(x) for x in a]))
            except (TypeError, ValueError):
                raise RuntimeError_(f"bad range arguments {a!r}") from None

        def _type(v):
            return self.type_name(v)

        def _has(container, key):
            if isinstance(container, dict):
                return str(key) in container
            if isinstance(container, list):
                return 0 <= int(key) < len(container)
            if isinstance(container, str):
                return 0 <= int(key) < len(container)
            if isinstance(container, Instance):
                return key in container.vars
            return False

        def _keys(v):
            if isinstance(v, dict):
                return list(v.keys())
            if isinstance(v, Instance):
                return list(v.vars.keys())
            raise RuntimeError_("keys() needs a map or object")

        def _values(v):
            if isinstance(v, dict):
                return list(v.values())
            if isinstance(v, Instance):
                return list(v.vars.values())
            raise RuntimeError_("values() needs a map or object")

        def _sqrt(v):
            return math.sqrt(float(v))

        def _exit(code=0):
            raise ExitSignal(int(code))

        def _clock():
            return time.monotonic()

        for name, fn in [
            ("print", _print), ("len", _len), ("str", _str), ("int", _int),
            ("float", _float), ("input", _input), ("push", _push),
            ("pop", _pop), ("range", _range), ("type", _type), ("has", _has),
            ("keys", _keys), ("values", _values), ("sqrt", _sqrt),
            ("exit", _exit), ("clock", _clock),
        ]:
            g.define(name, NativeFn(name, fn))

    # -- helpers ------------------------------------------------------
    def type_name(self, v) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, int):
            return "int"
        if isinstance(v, float):
            return "float"
        if isinstance(v, str):
            return "str"
        if isinstance(v, list):
            return "list"
        if isinstance(v, dict):
            return "map"
        if isinstance(v, Instance):
            return v.cls.name
        if isinstance(v, (Function, BoundMethod, NativeFn)):
            return "func"
        return type(v).__name__

    def to_display(self, v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        if isinstance(v, float):
            if v == int(v) and abs(v) < 1e16:
                return f"{v:.1f}"
            return str(v)
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return "[" + ", ".join(self.to_display(x) for x in v) + "]"
        if isinstance(v, dict):
            body = ", ".join(
                f"{k}: {self.to_display(x)}" for k, x in v.items()
            )
            return "{" + body + "}"
        return str(v)

    def truthy(self, v) -> bool:
        if isinstance(v, Instance):
            return True
        return bool(v)

    # -- entry --------------------------------------------------------
    def run(self, program: Program) -> None:
        env = self.globals
        try:
            self.hoist(program, env)
            for stmt in program.body:
                self.exec_stmt(stmt, env)
        except ExitSignal as e:
            self.exited = e.code

    def hoist(self, program: Program, env: Env) -> None:
        """Define classes and functions before any statement runs.

        Without this, a class defined at the bottom of the file would not
        exist for a ``new`` near the top, which is needlessly surprising.
        """
        for stmt in program.body:
            if isinstance(stmt, ClassDecl):
                self.declare_class(stmt, env)
        for stmt in program.body:
            if isinstance(stmt, FuncDecl) and not stmt.is_method:
                env.define(stmt.name, Function(stmt, env))

    def declare_class(self, node: ClassDecl, env: Env) -> UserClass:
        parent = None
        if node.parent:
            parent = env.get(node.parent)
            if not isinstance(parent, UserClass):
                raise RuntimeError_(
                    f"class {node.name} extends {node.parent}, "
                    f"which is not a class",
                    node.line,
                )
        cls = UserClass(node.name, parent)
        cls.env = env
        cls.fields = list(node.fields)
        for m in node.methods:
            cls.methods[m.name] = m
        self.classes[node.name] = cls
        env.define(node.name, cls)
        return cls

    # -- statements ---------------------------------------------------
    def exec_stmt(self, node, env: Env):
        self.steps += 1
        if self.max_steps and self.steps > self.max_steps:
            raise RuntimeError_(
                f"stopped after {self.max_steps:,} steps "
                f"(infinite loop?)"
            )

        t = type(node)

        if t is Let:
            env.assign_new(node.name, self.eval(node.value, env))
            return None

        if t is Block:
            inner = Env(env)
            for s in node.body:
                self.exec_stmt(s, inner)
            return None

        if t is FuncDecl:
            env.define(node.name, Function(node, env))
            return None

        if t is ClassDecl:
            self.declare_class(node, env)
            return None

        if t is Return:
            raise ReturnSignal(
                self.eval(node.value, env) if node.value is not None else None
            )

        if t is If:
            for cond, body in node.branches:
                if self.truthy(self.eval(cond, env)):
                    self.exec_stmt(body, Env(env))
                    return None
            if node.orelse is not None:
                self.exec_stmt(node.orelse, Env(env))
            return None

        if t is While:
            while self.truthy(self.eval(node.cond, env)):
                try:
                    self.exec_stmt(node.body, Env(env))
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
            return None

        if t is For:
            if node.stop is None:
                items = self.eval(node.start, env)
                if not isinstance(items, list):
                    raise RuntimeError_(
                        "'for x in ...' needs a list or a range "
                        "like 0..10",
                        node.line,
                    )
            else:
                start = self.eval(node.start, env)
                stop = self.eval(node.stop, env)
                self._check_number(start, stop, "..", node.line)
                items = range(int(start), int(stop))
            for item in items:
                inner = Env(env)
                inner.define(node.var, item)
                try:
                    self.exec_stmt(node.body, inner)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
            return None

        if t is Break:
            raise BreakSignal()

        if t is Continue:
            raise ContinueSignal()

        if t is Import:
            self.do_import(node, env)
            return None

        # expression used as a statement
        self.eval(node, env)
        return None

    def do_import(self, node: Import, env: Env) -> None:
        """``import gpp`` binds a module.

        Modules are resolved lazily, so importing 'gpp' only pays for the
        compiler lookup when the program actually calls into it.
        """
        name = node.module
        if name in ("math", "core", "std"):
            return
        if name == "gpp":
            from . import bridge

            env.define("gpp", bridge.make_module())
            return
        raise RuntimeError_(
            f"unknown module {name!r}. Available modules: gpp", node.line
        )

    # -- expressions --------------------------------------------------
    def eval(self, node, env: Env):
        t = type(node)

        if t is Literal:
            return node.value

        if t is Var:
            try:
                return env.get(node.name)
            except KeyError:
                if node.name in self.classes:
                    return self.classes[node.name]
                raise RuntimeError_(
                    f"unknown name {node.name!r}", node.line
                ) from None

        if t is SelfRef:
            if not env.has("self"):
                raise RuntimeError_("'self' used outside a method", node.line)
            return env.get("self")

        if t is ListLit:
            return [self.eval(x, env) for x in node.items]

        if t is MapLit:
            return {k: self.eval(v, env) for k, v in node.pairs}

        if t is Binary:
            return self.binary(node, env)

        if t is Logical:
            left = self.eval(node.left, env)
            if node.op == "and":
                return self.eval(node.right, env) if self.truthy(left) else left
            return left if self.truthy(left) else self.eval(node.right, env)

        if t is Unary:
            v = self.eval(node.operand, env)
            if node.op == "-":
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise RuntimeError_(f"cannot negate {self.type_name(v)}", node.line)
                return -v
            return not self.truthy(v)

        if t is Assign:
            return self.assign(node, env)

        if t is Index:
            return self.eval(node.target, env)[
                self.index_key(self.eval(node.key, env), node.line)
            ]

        if t is Attribute:
            return self.get_attr(self.eval(node.target, env), node.name, node.line)

        if t is New:
            return self.construct(node, env)

        if t is MethodCall:
            return self.call_method(node, env)

        if t is Call:
            return self.call(node, env)

        raise RuntimeError_(f"cannot evaluate {t.__name__}", getattr(node, "line", 0))

    def index_key(self, key, line: int):
        if isinstance(key, bool):
            return int(key)
        if isinstance(key, int):
            return key
        return str(key)

    def get_attr(self, target, name: str, line: int):
        if isinstance(target, Instance):
            if name in target.vars:
                return target.vars[name]
            meth = target.cls.find_method(name)
            if meth is not None:
                return BoundMethod(target, Function(meth, target.cls.env, name))
            raise RuntimeError_(
                f"{target.cls.name} has no field or method {name!r}", line
            )
        if isinstance(target, dict):
            if name in target:
                return target[name]
            raise RuntimeError_(f"map has no key {name!r}", line)
        raise RuntimeError_(
            f"cannot read {name!r} from {self.type_name(target)}", line
        )

    def assign(self, node: Assign, env: Env):
        value = self.eval(node.value, env)
        target = node.target
        tt = type(target)

        if tt is Var:
            try:
                env.set(target.name, value)
            except KeyError:
                # Assigning to something never declared is a normal thing to
                # do at the top level, so make the variable instead of
                # failing.
                env.assign_new(target.name, value)
            return value

        if tt is Index:
            container = self.eval(target.target, env)
            key = self.index_key(self.eval(target.key, env), node.line)
            if isinstance(container, list):
                if not isinstance(key, int):
                    raise RuntimeError_("list index must be an int", node.line)
                while len(container) <= key:
                    container.append(None)
                container[key] = value
            elif isinstance(container, dict):
                container[str(key)] = value
            else:
                raise RuntimeError_(
                    f"cannot assign into {self.type_name(container)}", node.line
                )
            return value

        if tt is Attribute:
            obj = self.eval(target.target, env)
            if isinstance(obj, Instance):
                obj.vars[target.name] = value
                return value
            raise RuntimeError_(
                f"cannot set {target.name!r} on {self.type_name(obj)}", node.line
            )

        raise RuntimeError_("cannot assign to this expression", node.line)

    def binary(self, node: Binary, env: Env):
        op = node.op
        if op == "&&":
            return self.truthy(self.eval(node.left, env)) and self.truthy(
                self.eval(node.right, env)
            )
        if op == "||":
            return self.truthy(self.eval(node.left, env)) or self.truthy(
                self.eval(node.right, env)
            )
        if op == "..":
            a = self.eval(node.left, env)
            b = self.eval(node.right, env)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return list(range(int(a), int(b)))
            raise RuntimeError_(
                "'..' needs two numbers (use a list to loop instead)", node.line
            )

        a = self.eval(node.left, env)
        b = self.eval(node.right, env)

        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
                    raise RuntimeError_("cannot use + on a list or map", node.line)
                return self.to_display(a) + self.to_display(b)
            if isinstance(a, list) and isinstance(b, list):
                return a + b
            self._check_number(a, b, op, node.line)
            return a + b
        if op == "-":
            self._check_number(a, b, op, node.line)
            return a - b
        if op == "*":
            if isinstance(a, str) and isinstance(b, int):
                return a * b
            if isinstance(a, int) and isinstance(b, str):
                return b * a
            if isinstance(a, list) and isinstance(b, int):
                return a * b
            self._check_number(a, b, op, node.line)
            return a * b
        if op == "/":
            self._check_number(a, b, op, node.line)
            if b == 0:
                raise RuntimeError_("division by zero", node.line)
            return a / b
        if op == "%":
            self._check_number(a, b, op, node.line)
            if b == 0:
                raise RuntimeError_("modulo by zero", node.line)
            return a % b
        if op == "**":
            self._check_number(a, b, op, node.line)
            return a ** b
        if op == "==":
            return self.loose_eq(a, b)
        if op == "!=":
            return not self.loose_eq(a, b)
        if op in ("<", "<=", ">", ">="):
            self._check_number(a, b, op, node.line)
            return {
                "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b,
            }[op]
        raise RuntimeError_(f"unknown operator {op!r}", node.line)

    def loose_eq(self, a, b) -> bool:
        if isinstance(a, Instance) or isinstance(b, Instance):
            return a is b
        if isinstance(a, bool) or isinstance(b, bool):
            return bool(a) == bool(b) and isinstance(a, bool) == isinstance(b, bool)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        if type(a) is not type(b):
            return a == b
        return a == b

    def _check_number(self, a, b, op: str, line: int) -> None:
        ok = (int, float)
        for v in (a, b):
            if isinstance(v, bool) or not isinstance(v, ok):
                raise RuntimeError_(
                    f"cannot use {op!r} with {self.type_name(v)}", line
                )

    # -- calls --------------------------------------------------------
    def construct(self, node: New, env: Env):
        try:
            cls = env.get(node.class_name)
        except KeyError:
            raise RuntimeError_(
                f"unknown class {node.class_name!r}", node.line
            ) from None
        if not isinstance(cls, UserClass):
            raise RuntimeError_(f"{node.class_name} is not a class", node.line)

        obj = Instance(cls, {})
        inner = Env(cls.env)
        inner.define("self", obj)

        # Base fields first so a subclass field with the same name wins.
        for f in cls.all_fields():
            value = self.eval(f.value, inner) if f.value is not None else None
            obj.vars[f.name] = value

        ctor = cls.find_method("new")
        if ctor is not None:
            # The receiver plus whatever the caller passed: 'new' is an
            # ordinary method with an implicit self.
            args = [obj] + [self.eval(a, env) for a in node.args]
            self.invoke(Function(ctor, cls.env, "new"), args, node.line)
        elif node.args:
            raise RuntimeError_(
                f"class {cls.name} has no 'new' method "
                f"but {len(node.args)} argument(s) were given",
                node.line,
            )
        return obj

    def call_method(self, node: MethodCall, env: Env):
        target = self.eval(node.target, env)
        if isinstance(target, Instance):
            meth = target.cls.find_method(node.name)
            if meth is None:
                raise RuntimeError_(
                    f"{target.cls.name} has no method {node.name!r}", node.line
                )
            args = [self.eval(a, env) for a in node.args]
            return self.invoke(
                Function(meth, target.cls.env, node.name),
                [target] + args, node.line, node.args,
            )
        # builtin-ish method: list/map operations that are handy
        if isinstance(target, list):
            return self.list_method(target, node.name, node, env)
        if isinstance(target, dict):
            # A module is just a dict of callables, so a name that holds a
            # function is called rather than treated as a map shortcut.
            member = target.get(node.name)
            if isinstance(member, (NativeFn, Function, BoundMethod)):
                args = [self.eval(a, env) for a in node.args]
                return self.invoke(member, args, node.line)
            if node.name == "keys":
                return list(target.keys())
            if node.name == "values":
                return list(target.values())
            if node.name == "has":
                return self.truthy(self.eval(node.args[0], env)) in target
        if isinstance(target, str):
            if node.name == "upper":
                return target.upper()
            if node.name == "lower":
                return target.lower()
            if node.name == "split":
                sep = (
                    self.to_display(self.eval(node.args[0], env))
                    if node.args else " "
                )
                return target.split(sep)
        raise RuntimeError_(
            f"{self.type_name(target)} has no method {node.name!r}", node.line
        )

    def list_method(self, lst: list, name: str, node: MethodCall, env: Env):
        if name == "push":
            lst.append(self.eval(node.args[0], env))
            return None
        if name == "pop":
            if not lst:
                raise RuntimeError_("pop() on an empty list", node.line)
            return lst.pop()
        if name == "len":
            return len(lst)
        if name == "contains":
            return self.eval(node.args[0], env) in lst
        if name == "join":
            sep = (
                self.to_display(self.eval(node.args[0], env))
                if node.args else ""
            )
            return sep.join(self.to_display(x) for x in lst)
        if name == "reverse":
            lst.reverse()
            return None
        if name == "sort":
            try:
                lst.sort()
            except TypeError:
                raise RuntimeError_(
                    "sort() needs a list of numbers or strings", node.line
                ) from None
            return None
        raise RuntimeError_(f"list has no method {name!r}", node.line)

    def call(self, node: Call, env: Env):
        fn = node.func
        named = isinstance(fn, Var)
        name = fn.name if named else None

        if named:
            try:
                callee = env.get(name)
            except KeyError:
                if name in self.classes:
                    raise RuntimeError_(
                        f"{name} is a class; call 'new {name}(...)' "
                        f"to make an object",
                        node.line,
                    ) from None
                raise RuntimeError_(f"unknown name {name!r}", node.line) from None
        else:
            callee = self.eval(fn, env)

        if isinstance(callee, UserClass):
            raise RuntimeError_(
                f"{name or 'that'} is a class; call 'new {name}(...)' "
                f"to make an object",
                node.line,
            )

        args = [self.eval(a, env) for a in node.args]
        return self.invoke(callee, args, node.line, node.args)

    def invoke(self, callee, args, line: int, arg_nodes=()):
        if isinstance(callee, NativeFn):
            try:
                return callee.fn(*args)
            except RuntimeError_:
                raise
            except TypeError as e:
                raise RuntimeError_(f"{callee.name}: {e}", line) from None
            except Exception as e:
                raise RuntimeError_(f"{callee.name}: {e}", line) from None

        if isinstance(callee, BoundMethod):
            args = [callee.instance] + args
            callee = callee.func

        if isinstance(callee, Function):
            self.depth += 1
            if self.depth > self.MAX_DEPTH:
                self.depth -= 1
                raise RuntimeError_(
                    f"stack overflow: {callee.name}() called itself too deep "
                    f"(limit {self.MAX_DEPTH})",
                    line,
                )
            scope = Env(callee.env)
            # The receiver is args[0] for a method and is not one of the
            # declared parameters, so params start one slot later.
            first = 0
            if callee.is_method:
                if not args:
                    raise RuntimeError_(
                        f"{callee.name}() called without an object", line
                    )
                scope.define("self", args[0])
                first = 1
            for i, p in enumerate(callee.decl.params):
                slot = i + first
                if slot < len(args):
                    scope.define(p.name, args[slot])
                elif p.default is not None:
                    scope.define(p.name, self.eval(p.default, scope))
                else:
                    raise RuntimeError_(
                        f"{callee.name}() needs a value for {p.name!r}", line
                    )
            # Extra positional arguments are an error, not silently ignored.
            extra = len(args) - len(callee.decl.params) - first
            if extra > 0:
                plural = "s" if extra != 1 else ""
                raise RuntimeError_(
                    f"{callee.name}() takes {len(callee.decl.params)} "
                    f"argument(s) but {extra} extra {plural} were given",
                    line,
                )
            try:
                self.exec_stmt(callee.decl.body, scope)
            except ReturnSignal as r:
                return r.value
            finally:
                self.depth -= 1
            return None

        raise RuntimeError_(f"{self.to_display(callee)} is not callable", line)


def run_source(src: str, out: Output | None = None, max_steps: int = 0) -> Interpreter:
    """Parse and run jaipl source. Convenience for tests and the CLI."""
    from .parser import parse

    interp = Interpreter(out=out, max_steps=max_steps)
    interp.run(parse(src))
    return interp


def run_file(path: str | Path, out: Output | None = None) -> Interpreter:
    text = Path(path).read_text(encoding="utf-8")
    return run_source(text, out=out)