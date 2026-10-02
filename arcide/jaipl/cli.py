"""jaipl command line.

This is the entry point that makes the language usable from any editor:
every editor can run 'jaipl run game.jai', and the IDE just calls the same
thing. Nothing here imports GTK or anything outside the standard library,
so the CLI runs on any machine with Python 3.11+.

Commands:
    jaipl run FILE     run a program (use - to read stdin)
    jaipl check FILE   parse only, report problems, run nothing
    jaipl fmt FILE     rewrite the file with canonical formatting
    jaipl repl         interactive prompt
    jaipl version      print the version
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .interp import ExitSignal, Interpreter, Output
from .lexer import JaiError, LexError
from .parser import ParseError, parse

VERSION = "0.1.0"

# ANSI colour, switched off when the output is not a terminal or when
# NO_COLOR is set (https://no-color.org). Editors capture output through a
# pipe, and stray escape codes in a run log are just noise.
_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
if _COLOR:
    _C = {
        "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
        "blue": "\033[34m", "cyan": "\033[36m", "bold": "\033[1m",
        "off": "\033[0m",
    }
else:
    _C = {k: "" for k in
          ("red", "green", "yellow", "blue", "cyan", "bold", "off")}


def _read_source(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"jaipl: no such file: {path}")
    return p.read_text(encoding="utf-8")


def _caret(line: int, col: int, text: str, color: str) -> str:
    """Point at the problem, the way a compiler does.

    The caret line matters: editors that show only the first line of an
    error give you a number and nothing to act on.
    """
    lines = text.splitlines()
    if not (1 <= line <= len(lines)):
        return ""
    src = lines[line - 1].replace("\t", " ")
    pad = " " * max(0, col - 1)
    return (
        f"{_C['blue']}{line:>5} | {_C['off']}{src}\n"
        f"{' ' * 5} | {pad}{_C[color]}^{_C['off']}"
    )


def _report(err: Exception, path: str, text: str) -> int:
    """Print a clean error. Returns the process exit code."""
    if isinstance(err, (LexError, ParseError)):
        line = getattr(err, "line", 0) or 0
        col = getattr(err, "col", 0) or 1
        print(
            f"{_C['red']}{_C['bold']}{path}:{line}:{col}: "
            f"{_C['off']}{err}",
            file=sys.stderr,
        )
        caret = _caret(line, col, text, "red")
        if caret:
            print(caret, file=sys.stderr)
        print(
            f"{_C['yellow']}jaipl: could not parse {path}"
            f"{_C['off']}",
            file=sys.stderr,
        )
        return 2
    from .interp import RuntimeError_

    if isinstance(err, RuntimeError_):
        print(
            f"{_C['red']}{_C['bold']}{err}{_C['off']}",
            file=sys.stderr,
        )
        return 1
    print(f"{_C['red']}jaipl: {type(err).__name__}: {err}{_C['off']}",
          file=sys.stderr)
    return 1


def cmd_run(path: str, args: list[str], max_steps: int = 0) -> int:
    try:
        text = _read_source(path)
    except SystemExit as e:
        print(_C["red"] + str(e) + _C["off"], file=sys.stderr)
        return 2

    out = Output()
    try:
        prog = parse(text)
    except (LexError, ParseError) as e:
        return _report(e, path, text)

    interp = Interpreter(out=out, max_steps=max_steps)
    try:
        interp.run(prog)
    except ExitSignal as e:
        return e.code
    except (LexError, ParseError, JaiError) as e:
        return _report(e, path, text)
    except RecursionError:
        print(
            f"{_C['red']}jaipl: the program recursed too deeply for the "
            f"interpreter{_C['off']}",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(f"\n{_C['yellow']}interrupted{_C['off']}", file=sys.stderr)
        return 130
    return interp.exited or 0


def cmd_check(path: str) -> int:
    text = _read_source(path)
    try:
        prog = parse(text)
    except (LexError, ParseError) as e:
        return _report(e, path, text)
    funcs = sum(1 for s in prog.body if type(s).__name__ == "FuncDecl")
    classes = sum(1 for s in prog.body if type(s).__name__ == "ClassDecl")
    print(
        f"{_C['green']}ok{_C['off']} "
        f"{path}: {len(prog.body)} statement(s), {funcs} function(s), "
        f"{classes} class(es), no syntax errors"
    )
    return 0


def cmd_fmt(path: str) -> int:
    from .fmt import format_source

    text = _read_source(path)
    try:
        new = format_source(text)
    except (LexError, ParseError) as e:
        return _report(e, path, text)
    if path == "-":
        sys.stdout.write(new)
        return 0
    p = Path(path)
    if new != text:
        p.write_text(new, encoding="utf-8")
        print(f"formatted {path}")
    else:
        print(f"{path} already formatted")
    return 0


def cmd_repl() -> int:
    interp = Interpreter(out=Output())
    print(
        f"{_C['cyan']}jaipl {VERSION}{_C['off']} -- "
        f"type an expression, or 'quit' to leave"
    )
    buffer: list[str] = []
    while True:
        prompt = "... " if buffer else "jai> "
        try:
            line = input(_C["bold"] + prompt + _C["off"])
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        stripped = line.strip()
        if not buffer and stripped in ("quit", "exit", ":q"):
            return 0
        buffer.append(line)
        source = "\n".join(buffer)
        # Try as a statement; if that fails try as an expression to print.
        try:
            prog = parse(source)
            for stmt in prog.body:
                interp.exec_stmt(stmt, interp.globals)
            buffer = []
            continue
        except (LexError, ParseError):
            pass
        try:
            value = interp.eval(parse(source).body[-1], interp.globals)
            print(interp.to_display(value))
            buffer = []
        except JaiError as e:
            if "unexpected end of file" in str(e) or "end of statement" in str(e):
                continue  # keep reading, the block is not finished yet
            print(_C["red"] + str(e) + _C["off"])
            buffer = []


USAGE = f"""{_C['bold']}jaipl {_C['off']} -- a small language for building things

  jaipl run FILE     run a program ('-' reads stdin)
  jaipl check FILE   check syntax without running
  jaipl fmt FILE     format the file in place
  jaipl repl         interactive prompt
  jaipl version      print the version
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv[0] in ("-v", "--version", "version"):
        print(f"jaipl {VERSION}")
        return 0

    cmd, rest = argv[0], argv[1:]
    if cmd == "run":
        if not rest:
            print(_C["red"] + "jaipl run: needs a file" + _C["off"],
                  file=sys.stderr)
            return 2
        return cmd_run(rest[0], rest[1:])
    if cmd == "check":
        if not rest:
            print(_C["red"] + "jaipl check: needs a file" + _C["off"],
                  file=sys.stderr)
            return 2
        return cmd_check(rest[0])
    if cmd == "fmt":
        if not rest:
            print(_C["red"] + "jaipl fmt: needs a file" + _C["off"],
                  file=sys.stderr)
            return 2
        return cmd_fmt(rest[0])
    if cmd == "repl":
        return cmd_repl()

    print(_C["red"] + f"jaipl: unknown command {cmd!r}" + _C["off"],
          file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())