"""GDB/MI2 protocol: a real parser and a session driver.

Pure Python apart from the subprocess in :class:`Debugger`, so the record
parser is unit tested against captured gdb output rather than against a
live debugger.

MI is line oriented. Each line is one record:

    (gdb)                                  result-record terminator
    ^done,bkpt={number="1",file="a.cpp"}    result record
    *stopped,reason="breakpoint-hit"        async record
    =thread-group-added,id="i1"             async exec record
    ~"console output\\n"                    console stream
    @"target output\\n"                     target stream
    &"log text\\n"                          log stream

Values are cstrings, tuples and lists, and they nest. The parser below
handles all of that, including the escapes gdb emits inside strings.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- values


@dataclass(frozen=True)
class MIList:
    items: tuple[Any, ...] = ()

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def as_dict(self) -> dict:
        """Interpret a list of single-entry tuples as a dict."""
        out = {}
        for it in self.items:
            if isinstance(it, MITuple):
                d = it.as_dict()
                if d:
                    out.update(d)
        return out


@dataclass(frozen=True)
class MITuple:
    entries: tuple[tuple[str, Any], ...] = ()

    def as_dict(self) -> dict:
        return {k: v for k, v in self.entries}

    def get(self, key: str, default=None):
        for k, v in self.entries:
            if k == key:
                return v
        return default

    def __contains__(self, key: str) -> bool:
        return any(k == key for k, _ in self.entries)


@dataclass(frozen=True)
class MIStream:
    text: str = ""


@dataclass(frozen=True)
class MIResult:
    """A parsed record: kind, class token and payload."""

    kind: str          # '^', '*', '=' or '+'
    cls: str           # 'done', 'running', 'error', 'stopped', ...
    payload: Any = None
    token: int | None = None  # numeric prefix, e.g. "7^done,..."

    @property
    def ok(self) -> bool:
        return self.cls in ("done", "running")

    @property
    def error_message(self) -> str:
        d = self.payload.as_dict() if isinstance(self.payload, MITuple) else {}
        return str(d.get("msg", ""))


_UNESCAPE = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
    "f": "\f", "v": "\v", "0": "\0", "\\": "\\", '"': '"', "'": "'",
}
_UNESCAPE_RE = re.compile(r"\\(x[0-9a-fA-F]{1,2}|[0-7]{1,3}|.)")


def _unescape(s: str) -> str:
    def sub(m: re.Match[str]) -> str:
        g = m.group(1)
        if g[0] == "x":
            return chr(int(g[1:], 16))
        if g[0] in "01234567" and len(g) > 1:
            return chr(int(g, 8))
        return _UNESCAPE.get(g, g)

    return _UNESCAPE_RE.sub(sub, s)


class _Parser:
    """Recursive-descent parser for one MI value."""

    def __init__(self, s: str, i: int = 0):
        self.s = s
        self.i = i

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def parse_value(self) -> Any:
        self.ws()
        if self.i >= len(self.s):
            return None
        c = self.s[self.i]
        if c == '"':
            return self.parse_string()
        if c == "{":
            return self.parse_tuple()
        if c == "[":
            return self.parse_list()
        # A bare 'key=value' with no braces is a var-list. GDB sends these
        # inside lists -- '-stack-list-frames' answers with
        # stack=[frame={...},frame={...}] -- and without this the whole
        # list would be swallowed as one long string.
        if (c.isalpha() or c == "_") and self._looks_like_vars():
            return self.parse_bare_vars()
        # bare const: a value with no quotes, e.g. class=Some::Type
        j = self.i
        while j < len(self.s) and self.s[j] not in ',}]':
            j += 1
        raw = self.s[self.i:j].strip()
        self.i = j
        return raw

    def _looks_like_vars(self) -> bool:
        """True if the text at self.i is 'key=value[,key=value]...'."""
        j = self.i
        while j < len(self.s) and (self.s[j].isalnum() or self.s[j] in "_-"):
            j += 1
        if j == self.i or j >= len(self.s):
            return False
        k = j
        while k < len(self.s) and self.s[k].isspace():
            k += 1
        return k < len(self.s) and self.s[k] == "="

    def parse_bare_vars(self) -> MITuple:
        """Parse 'key=value,key=value' with no surrounding braces."""
        entries: list[tuple[str, Any]] = []
        while self.i < len(self.s):
            before = self.i
            self.ws()
            key = self.parse_key()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "=":
                self.i += 1
                entries.append((key, self.parse_value()))
            else:
                entries.append((key, None))
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
            elif self.i < len(self.s) and self.s[self.i] in "}]":
                break
            else:
                break
            if self.i <= before:
                break
        return MITuple(tuple(entries))

    def parse_string(self) -> str:
        assert self.s[self.i] == '"'
        self.i += 1
        out = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\" and self.i + 1 < len(self.s):
                out.append(c)
                out.append(self.s[self.i + 1])
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                return _unescape("".join(out))
            out.append(c)
            self.i += 1
        return _unescape("".join(out))

    def parse_key(self) -> str:
        """Read an MI key.

        GDB writes keys as bare identifiers (``number``, ``stopped-threads``)
        and only *values* are cstrings, so keys must not be parsed with
        :meth:`parse_string`. A few other MI producers do quote keys, so
        accept that too.
        """
        if self.i < len(self.s) and self.s[self.i] == '"':
            return self.parse_string()
        j = self.i
        while j < len(self.s) and (
            self.s[j].isalnum() or self.s[j] in "-_.$:"
        ):
            j += 1
        if j == self.i:
            raise AssertionError(f"expected a key at {self.i}")
        key = self.s[self.i:j]
        self.i = j
        return key

    def parse_tuple(self) -> MITuple:
        assert self.s[self.i] == "{"
        self.i += 1
        entries: list[tuple[str, Any]] = []
        while self.i < len(self.s):
            self.ws()
            if self.i >= len(self.s):
                break
            if self.s[self.i] == "}":
                self.i += 1
                break
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            key = self.parse_key()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "=":
                self.i += 1
                entries.append((key, self.parse_value()))
            else:
                entries.append((key, None))
        return MITuple(tuple(entries))

    def parse_list(self) -> MIList:
        assert self.s[self.i] == "["
        self.i += 1
        items: list[Any] = []
        while self.i < len(self.s):
            self.ws()
            if self.i >= len(self.s):
                break
            if self.s[self.i] == "]":
                self.i += 1
                break
            before = self.i
            items.append(self.parse_value())
            # No forward progress means malformed input; stop rather than
            # spin forever inside an IDE.
            if self.i <= before:
                break
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
        return MIList(tuple(items))

    def parse_vars(self) -> MITuple:
        """Parse a top-level payload: a sequence of ``key=value`` pairs.

        This is the shape of every MI result and async record, e.g.
        ``^done,bkpt={...},thread-groups=["i1"]``. It is not a tuple and not
        a list -- it is a var-list, which is why parsing it as a single
        value silently yields one long string.

        Keys here are bare identifiers (``bkpt``, ``stopped-threads``),
        unlike the keys *inside* a tuple, which are quoted cstrings. That
        asymmetry is easy to get wrong and breaks every lookup.
        """
        entries: list[tuple[str, Any]] = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                break
            c = self.s[self.i]
            if c in "}]":
                break
            if c == ",":
                self.i += 1
                continue
            j = self.i
            while j < len(self.s) and (
                self.s[j].isalnum() or self.s[j] in "-_.$"
            ):
                j += 1
            if j == self.i:
                # Not an identifier: skip a byte and keep going rather than
                # abandoning the rest of the record.
                self.i += 1
                continue
            key = self.s[self.i:j]
            self.i = j
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "=":
                self.i += 1
                entries.append((key, self.parse_value()))
            else:
                entries.append((key, None))
        return MITuple(tuple(entries))


def parse_record(line: str) -> MIResult | None:
    """Parse one MI line. Returns ``None`` for prompts and noise."""
    line = line.strip()
    if not line:
        return None

    # gdb echoes the command token as a bare numeric *prefix*:
    #     7^done,bkpt={...}
    # It is not a "token=" field in the payload, which is the obvious thing
    # to assume and the reason every synchronous command used to time out.
    # The prefix must be stripped *before* the kind is read, otherwise the
    # leading digit makes the record look unrecognised and it is dropped.
    token = None
    mtok = re.match(r"^(\d+)", line)
    if mtok:
        token = int(mtok.group(1))
        line = line[mtok.end():]
        if not line:
            return None

    kind = line[0]
    if kind in ("~", "@", "&"):
        # stream records: ~"text"
        p = _Parser(line, 1)
        try:
            text = p.parse_value()
        except (AssertionError, IndexError):
            return None
        return MIResult(kind, "stream", MIStream(str(text)), token)
    if kind not in ("^", "*", "="):
        return None

    rest = line[1:]

    # Trailing (gdb) prompt must go or it becomes part of the last value.
    m = re.search(r"\(gdb\)\s*$", rest)
    if m:
        rest = rest[: m.start()]

    if "," in rest:
        cls, payload_s = rest.split(",", 1)
        p = _Parser(payload_s)
        try:
            payload = p.parse_vars()
        except (AssertionError, IndexError, RecursionError):
            payload = None
    else:
        cls, payload = rest.rstrip(), None
    return MIResult(kind, cls.strip(), payload, token)


# ---------------------------------------------------------------- events


@dataclass
class Frame:
    level: int
    func: str
    file: str | None
    line: int | None
    addr: str | None = None
    fullname: str | None = None

    @classmethod
    def from_tuple(cls, t: MITuple) -> "Frame":
        d = t.as_dict()

        def _int(k):
            v = d.get(k)
            try:
                return int(str(v))
            except (TypeError, ValueError):
                return None

        return cls(
            level=_int("level") or 0,
            func=str(d.get("func", "?")),
            file=d.get("file"),
            line=_int("line"),
            addr=d.get("addr"),
            fullname=d.get("fullname"),
        )


@dataclass
class Breakpoint:
    number: int
    file: str | None = None
    line: int | None = None
    func: str | None = None
    verified: bool = True

    @classmethod
    def from_tuple(cls, t: MITuple) -> "Breakpoint":
        d = t.as_dict()

        def _int(k):
            v = d.get(k)
            try:
                return int(str(v))
            except (TypeError, ValueError):
                return None

        return cls(
            number=_int("number") or 0,
            file=d.get("file"),
            line=_int("line"),
            func=d.get("func"),
            verified=str(d.get("verified", "yes")).lower()
            not in ("no", "off", "breakpoint-disabled"),
        )


class DebuggerError(RuntimeError):
    pass


# ---------------------------------------------------------------- session

Listener = Callable[[str, Any], None]


class Debugger:
    """A gdb MI2 session.

    Not thread safe for commands, but safe to attach many listeners: a
    background reader thread turns gdb's output into callbacks, so the GTK
    main loop never blocks on the debugger.
    """

    def __init__(self, gdb: str = "gdb", log: Callable[[str], None] | None = None):
        self.gdb = gdb
        self.proc: subprocess.Popen | None = None
        self.log = log or (lambda _s: None)
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()
        self._out: queue.Queue[str] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._pending: dict[int, MIResult] = {}
        self._next_token = 1
        self.state = "exited"
        self.frames: list[Frame] = []
        self.console: list[str] = []

    # -- plumbing ---------------------------------------------------------
    def on(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def _emit(self, kind: str, payload: Any) -> None:
        for fn in list(self._listeners):
            try:
                fn(kind, payload)
            except Exception as exc:  # a bad listener must not kill gdb
                self.log(f"listener error: {exc}")

    def start(self, binary: str, args: list[str] | None = None) -> None:
        if self.proc and self.proc.poll() is None:
            return
        cmd = [self.gdb, "--interpreter=mi2", "-q", "--nx"]
        if args:
            cmd += ["--args", binary, *args]
        else:
            cmd.append(binary)
        self.log(" ".join(cmd))
        # gdb resolves a relative "file.cpp:12" against *its own* cwd, so a
        # breakpoint set from a different directory silently fails with
        # "No compiled code for line N". Give gdb the binary's directory and
        # let the UI pass absolute paths anyway.
        cwd = os.path.dirname(os.path.abspath(binary)) or None
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.state = "running"
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            rec = parse_record(line)
            if rec is None:
                if line.strip():
                    self.log(line.strip())
                continue

            if rec.kind in ("~", "@") and isinstance(rec.payload, MIStream):
                text = rec.payload.text
                if text:
                    self.console.append(text)
                    self._emit("stdout", text)

            elif rec.kind == "&":
                if isinstance(rec.payload, MIStream):
                    self.log(rec.payload.text)

            elif rec.kind == "*" and rec.cls == "stopped":
                self.state = "stopped"
                self._emit("stopped", rec.payload)

            elif rec.kind == "*" and rec.cls == "running":
                self.state = "running"
                self._emit("running", rec.payload)

            elif rec.kind == "*" and rec.cls == "exited":
                self.state = "exited"
                code = None
                if isinstance(rec.payload, MITuple):
                    v = rec.payload.get("exit-code")
                    try:
                        code = int(str(v))
                    except (TypeError, ValueError):
                        code = None
                self._emit("exited", code)

            elif rec.kind == "^":
                # Match the reply to a token so synchronous calls unblock.
                tok = rec.token
                if isinstance(rec.payload, MITuple):
                    t = rec.payload.get("token")
                    if t is not None and tok is None:
                        try:
                            tok = int(str(t))
                        except ValueError:
                            tok = None
                if tok is not None:
                    self._pending[tok] = rec
                self._emit("result", rec)
                if rec.cls == "error":
                    self.log("gdb error: " + rec.error_message)

    def _send(self, command: str, timeout: float = 20.0) -> MIResult:
        if not self.proc or self.proc.poll() is not None:
            raise DebuggerError("gdb is not running")
        with self._lock:
            tok = self._next_token
            self._next_token += 1
            self.proc.stdin.write(f"{tok}{command}\n")
            self.proc.stdin.flush()
        result = self._wait_for_token(tok, timeout)
        if result is not None and result.cls == "error":
            raise DebuggerError(result.error_message or command)
        return result or MIResult("^", "done", None)

    def _wait_for_token(self, tok: int, timeout: float) -> MIResult | None:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if tok in self._pending:
                return self._pending.pop(tok)
            time.sleep(0.01)
        return None

    # -- commands ---------------------------------------------------------
    def set_breakpoint(self, file: str, line: int, temporary: bool = False):
        cmd = f"-break-insert {'-t ' if temporary else ''}{os.fspath(file)}:{int(line)}"
        res = self._send(cmd)
        if isinstance(res.payload, MITuple):
            bk = res.payload.get("bkpt")
            if isinstance(bk, MITuple):
                return Breakpoint.from_tuple(bk)
        return None

    def set_function_breakpoint(self, func: str):
        res = self._send(f"-break-insert {func}")
        if isinstance(res.payload, MITuple):
            bk = res.payload.get("bkpt")
            if isinstance(bk, MITuple):
                return Breakpoint.from_tuple(bk)
        return None

    def delete_breakpoint(self, number: int) -> bool:
        try:
            self._send(f"-break-delete {int(number)}")
            return True
        except DebuggerError:
            return False

    def list_breakpoints(self) -> list[Breakpoint]:
        res = self._send("-list-breakpoints")
        if isinstance(res.payload, MITuple):
            bkpts = res.payload.get("BreakpointTable")
            if isinstance(bkpts, MITuple):
                b = bkpts.get("body")
                if isinstance(b, MIList):
                    return [
                        Breakpoint.from_tuple(x)
                        for x in b
                        if isinstance(x, MITuple)
                    ]
        return []

    def run(self) -> None:
        self.state = "running"
        self._send("-exec-run", timeout=60)

    def cont(self) -> None:
        self.state = "running"
        self._send("-exec-continue", timeout=60)

    def next(self) -> None:
        self._send("-exec-next")

    def step(self) -> None:
        self._send("-exec-step")

    def finish(self) -> None:
        self._send("-exec-finish")

    def interrupt(self) -> bool:
        """Break a running program (the IDE's 'stop' button)."""
        try:
            self._send("-exec-interrupt", timeout=8)
            return True
        except DebuggerError:
            # Older gdb has no MI interrupt; fall back to SIGINT.
            if self.proc:
                try:
                    self.proc.send_signal(2)
                    return True
                except (OSError, ValueError):
                    return False
            return False

    def stack_frames(self) -> list[Frame]:
        res = self._send("-stack-list-frames")
        if isinstance(res.payload, MITuple):
            st = res.payload.get("stack")
            if isinstance(st, MIList):
                self.frames = [
                    Frame.from_tuple(x) for x in st if isinstance(x, MITuple)
                ]
        return self.frames

    def locals(self) -> dict[str, str]:
        """Local variables of the selected frame, name -> printed value."""
        res = self._send("-stack-list-variables")
        if isinstance(res.payload, MITuple):
            v = res.payload.get("variables")
            if isinstance(v, MIList):
                out = {}
                for entry in v:
                    if isinstance(entry, MITuple):
                        d = entry.as_dict()
                        if "name" in d:
                            out[str(d["name"])] = str(d.get("value", ""))
                return out
        return {}

    def evaluate(self, expr: str) -> str:
        res = self._send(f'-data-evaluate-expression {_mi_quote(expr)}')
        if isinstance(res.payload, MITuple):
            return str(res.payload.get("value", ""))
        return ""

    def quit(self) -> None:
        if not self.proc:
            return
        try:
            self._send("-gdb-exit", timeout=3)
        except Exception:
            pass
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.state = "exited"


def _mi_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'