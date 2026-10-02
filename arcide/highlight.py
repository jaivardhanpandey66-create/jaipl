"""Syntax highlighting for every language the editor knows.

GtkSourceView would be the usual choice, but it is not installed here and
should not be a hard requirement, so highlighting is done with tags on a
plain TextView. That also means it works identically on any machine with
GTK, which matters for an editor meant to travel.

Highlighting is regex driven and forgiving: an unterminated string colours
the rest of the line instead of derailing the scan, because a half-written
line is the normal state of a file being typed into.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .languages import Language, PLAIN


@dataclass
class Style:
    """How one token class is painted."""

    foreground: str | None = None
    background: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False


# A dark theme in the same family as the Stark palette used elsewhere.
THEME = {
    "keyword": Style("#00BFFF", bold=True),
    "type": Style("#7FC9F3"),
    "string": Style("#9CE88B"),
    "number": Style("#F2A65A"),
    "comment": Style("#5C7080", italic=True),
    "function": Style("#FFD93B"),
    "self": Style("#FF8AC2", italic=True),
    "literal": Style("#FF8AC2"),
    "operator": Style("#C9D6E4"),
    "preprocessor": Style("#C792EA"),
    "error": Style("#FF5F56", bold=True, underline=True),
}

_TOKEN_ORDER = (
    "comment",
    "string",
    "number",
    "preprocessor",
    "keyword",
    "type",
    "literal",
    "self",
    "function",
    "operator",
)

_COMMON_TYPES = frozenset({
    "int", "float", "double", "char", "bool", "void", "long", "short",
    "string", "str", "list", "map", "dict", "set", "tuple", "object",
    "number", "boolean", "any", "var",
})


def _escape(text: str) -> str:
    return re.escape(text)


class Highlighter:
    """Finds token spans in a line. One instance per language."""

    def __init__(self, lang: Language):
        self.lang = lang
        self.patterns: list = []
        self._build()

    def _add(self, kind: str, regex: str) -> None:
        self.patterns.append((kind, re.compile(regex)))

    def _build(self) -> None:
        lang = self.lang

        # Strings first: a '#' inside a string is not a comment.
        if lang.strings:
            chars = "".join(_escape(c) for c in lang.strings)
            self._add(
                "string",
                rf"(?:{chars})(?:\\.|[^\\{chars}])*(?:{chars})?"
                rf"|(?:{chars})[^\\{chars}]*$",
            )

        for marker in lang.block_comment:
            if marker.endswith("-->"):
                self._add("comment", r"<!--.*?-->")
                self._add("comment", r"<!--.*$")
            elif marker.endswith("]]"):
                self._add("comment", re.escape(marker) + r".*?" + re.escape(
                    lang.block_comment[1]))
            else:
                self._add(
                    "comment",
                    re.escape(marker) + r".*?" + re.escape(lang.block_comment[1]),
                )
                self._add(
                    "comment",
                    re.escape(marker) + r".*$",
                )

        for marker in lang.line_comment:
            self._add("comment", re.escape(marker) + r".*$")

        self._add("number", r"\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
        self._add(
            "number",
            r"\b0[xXbBoO][0-9a-fA-F_]+\b",
        )

        if lang.keywords:
            words = "|".join(_escape(k) for k in sorted(lang.keywords))
            self._add("keyword", rf"\b(?:{words})\b")

        if lang.name in ("C", "C++"):
            self._add("preprocessor", r"^\s*#\s*\w+")
        elif lang.name in ("Python", "Shell", "Ruby", "Lua"):
            self._add("preprocessor", rf"^\s*{_escape(lang.line_comment[0] if lang.line_comment else '#')}.*$")

        if _COMMON_TYPES:
            types = "|".join(_escape(t) for t in sorted(_COMMON_TYPES))
            self._add("type", rf"\b(?:{types})\b")

        literals = "|".join(_escape(x) for x in ("true", "false", "null", "nil",
                                                "None", "True", "False", "self", "this"))
        self._add("literal", rf"\b(?:{literals})\b")

        # A name directly before '(' reads as a call.
        self._add("function", r"\b[A-Za-z_]\w*(?=\s*\()")

        self._add(
            "operator",
            r"[-+*/%=<>!&|^~?:]+",
        )

    def spans(self, line: str) -> list:
        """Non-overlapping (kind, start, end) spans for one line.

        Earlier rules win, because a string must not be recoloured by the
        keyword rule that happens to match a word inside it.
        """
        if self.lang is PLAIN or not self.patterns:
            return []

        taken = [False] * len(line)
        out = []
        for kind, regex in self.patterns:
            for m in regex.finditer(line):
                start, end = m.span()
                if start >= end:
                    continue
                if any(taken[start:end]):
                    continue
                for i in range(start, end):
                    taken[i] = True
                out.append((kind, start, end))
        out.sort(key=lambda s: s[1])
        return out