"""Minimal canonical formatter for zing.

Not a pretty-printer: it only fixes what is objective -- indentation that
matches brace depth, no trailing whitespace, exactly one trailing newline,
and spaces after commas. Keeping it conservative means 'zing fmt' can never
change what a program means, which a real pretty-printer could.
"""

from __future__ import annotations

from .lexer import Token, tokenize

INDENT = "    "


def _split_lines(tokens: list[Token]) -> list[list[Token]]:
    lines: list[list[Token]] = [[]]
    for t in tokens:
        # The end-of-file marker is not source text; rendering it would
        # append a stray 'None' statement to the program.
        if t.kind == "eof":
            continue
        if t.kind == "newline":
            lines.append([])
        else:
            lines[-1].append(t)
    return lines


def _render(toks: list[Token]) -> str:
    """Put a single logical line back together, spacing tokens sensibly."""
    out = ""
    prev: Token | None = None
    for t in toks:
        # The lexer stores a string's contents without its quotes, so the
        # quotes have to go back on here or the program stops meaning
        # anything.
        if t.kind == "string":
            text = '"' + str(t.value).replace('"', '\\"') + '"'
        else:
            text = str(t.value)

        if prev is None:
            out = text
            prev = t
            continue

        pt = str(prev.value)
        if pt == "." or text == ".":
            out += text
        elif text in (")", "]", ",", ";"):
            out += text
        elif pt in ("(", "["):
            out += text
        elif text == "(" and (prev.kind == "ident" or pt in (")", "]")):
            out += text  # a call, not a new group
        elif pt == "," or pt == ";":
            out += " " + text
        else:
            out += " " + text
        prev = t
    return out


def format_source(src: str) -> str:
    """Format, then prove the result still means the same thing.

    The proof is the important part. A formatter that can change a program's
    meaning is worse than no formatter, so the output is re-parsed and
    compared against the input's syntax tree. If they differ, the input is
    returned untouched and 'verified' is False, and the caller refuses to
    write.
    """
    tokens = tokenize(src)
    lines = _split_lines(tokens)

    depth = 0
    rendered: list[str] = []
    for toks in lines:
        text = _render(toks).rstrip()
        if not text:
            # Collapse runs of blank lines to at most one.
            if not rendered or rendered[-1] != "":
                rendered.append("")
            continue

        # A closing brace at the start of the line belongs to the outer level.
        lead_close = 1 if text.startswith("}") else 0
        level = max(0, depth - lead_close)
        rendered.append(INDENT * level + text)

        # Track depth from this line's own braces so a one-line
        # '{ ... }' body neither opens nor closes the block level.
        net = sum(1 for t in toks if t.value in ("{",)) - sum(
            1 for t in toks if t.value in ("}",)
        )
        depth = max(0, depth + net)

    while rendered and rendered[-1] == "":
        rendered.pop()
    result = "\n".join(rendered) + "\n"

    verified = _same_meaning(src, result)
    return result if verified else src


def _shape(node):
    """A comparable form of the syntax tree with line numbers removed.

    Formatting moves code between lines, so two trees that mean the same
    thing still differ in their 'line' fields. Everything else must match.
    """
    import dataclasses

    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        parts = []
        for f in dataclasses.fields(node):
            if f.name == "line":
                continue
            parts.append((f.name, _shape(getattr(node, f.name))))
        return (type(node).__name__, tuple(parts))
    if isinstance(node, (list, tuple)):
        return tuple(_shape(x) for x in node)
    return node


def _same_meaning(a: str, b: str) -> bool:
    """True when both sources parse to the same tree, ignoring line numbers."""
    from .parser import parse

    try:
        return _shape(parse(a)) == _shape(parse(b))
    except Exception:
        # If we cannot compare, do not touch the file.
        return False