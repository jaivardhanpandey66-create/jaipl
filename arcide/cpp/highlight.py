"""C++ tokenizer.

Pure Python, no GTK import, so it can be unit tested headlessly.

Produces a flat list of ``Token`` records covering the whole source. The
highlighter walks these to build Pango markup, the completion engine reads
the token stream to learn which identifiers are in scope, and the outline
widget looks at ``kind == 'preproc'`` lines to find ``#include``.

The tokenizer is deliberately lenient: unbalanced quotes or a stray
backslash must never raise, because a half-typed file is the normal state
of an editor. Whatever we can classify we classify, and the rest becomes
'text'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterator


class Kind(str, Enum):
    """Token categories. Values double as highlight-group suffixes."""

    TEXT = "text"
    COMMENT = "comment"
    DOC_COMMENT = "doc"
    STRING = "string"
    CHAR = "char"
    NUMBER = "number"
    PREPROC = "preproc"
    KEYWORD = "keyword"
    TYPE = "type"
    BUILTIN = "builtin"
    LITERAL = "literal"
    OPERATOR = "operator"
    PUNCT = "punct"
    IDENT = "ident"
    FUNCTION = "function"
    INCLUDE = "include"
    TODO = "todo"


# Reserved words. Kept as one frozenset so lookups are O(1).
KEYWORDS = frozenset(
    """
    alignas alignof and asm auto bitand bitor break case catch class compl
    const constexpr consteval constinit const_cast continue co_await
    co_return co_yield decltype default delete do double dynamic_cast else
    enum explicit export extern false float for friend goto if inline int
    long mutable namespace new noexcept not nullptr operator or private
    protected public reflexpr register reinterpret_cast requires return short
    signed sizeof static static_assert static_cast struct switch template
    this thread_local throw true try typedef typeid typename union unsigned
    using virtual void volatile wchar_t while xor xor_eq or_eq and_eq not_eq
    concept requires_ co_await_
    """.split()
)

# Reserved but not keywords (future-proofing, MS extensions, C compat).
CONTROL_KEYWORDS = frozenset({"if", "else", "for", "while", "do", "switch",
                              "case", "default", "break", "continue",
                              "return", "goto", "try", "catch", "throw"})

# Storage / type-specifier keywords read better in their own colour.
STORAGE = frozenset(
    """
    auto const constexpr consteval constinit extern inline mutable register
    static thread_local typedef using virtual explicit friend constexpr
    """.split()
)

# Built-in scalar types and the standard library headers' most common
# spellings, coloured like types.
TYPES = frozenset(
    """
    bool char char8_t char16_t char32_t double float int long short signed
    size_t ssize_t wchar_t int8_t int16_t int32_t int64_t uint8_t uint16_t
    uint32_t uint64_t intptr_t uintptr_t ptrdiff_t intmax_t uintmax_t
    std string vector map unordered_map set unordered_set array deque list
    forward_list stack queue pair tuple optional variant any unique_ptr
    shared_ptr weak_ptr function span bitset set multimap multiset ostream
    istream stringstream iostream algorithm numeric iterator memory
    utility chrono thread mutex atomic filesystem regex
    """.split()
)

BUILTINS = frozenset(
    """
    alignof alignas and asm static_assert noexcept constexpr typeid
    sizeof decltype nullptr true false offsetof containerof
    """.split()
)

LITERALS = frozenset({"true", "false", "nullptr", "NULL", "nullptr_t"})

# Raw strings, R"delim( ... )delim" -- the one C++ lexing rule that a naive
# scanner always gets wrong, and the most common source of cascading bogus
# syntax errors when it does.
_RAW_STRING = re.compile(r'(?:u8|u|U|L)?R"(?P<delim>[^()\\ ]{0,16})\(')

_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
# 0x1f  0b1010  077  1'000'000  1.5e-3f  3.14L  42ULL
_NUMBER = re.compile(
    r"""
    (?:
        0[xX][0-9a-fA-F']+
      | 0[bB][01']+
      | (?:[0-9][0-9']*)? \.[0-9][0-9']* (?:[eEpP][+-]?[0-9]+)?
      | [0-9][0-9']* (?:[eE][+-]?[0-9]+)? [fFlLuU]*
    )
    """,
    re.VERBOSE,
)

_TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK|NOTE|BUG)\b")

# A declaration's identifier, for FUNCTION classification. Deliberately
# simple: IDENT immediately followed by '(' and preceded by a type-ish token.
_FUNC_START = re.compile(r"[A-Za-z_~][A-Za-z0-9_:<>,*&\s]*[A-Za-z_~][A-Za-z0-9_~]*\s*\(")


@dataclass(slots=True)
class Token:
    """One lexical token.

    ``line`` and ``col`` are 0-based here; the UI layer converts to the
    1-based line numbers g++ prints in its diagnostics.
    """

    kind: Kind
    text: str
    line: int
    col: int

    @property
    def end_col(self) -> int:
        return self.col + len(self.text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind.value}, {self.text!r}, {self.line}:{self.col})"


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ch == "$"


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or ch == "$"


class Tokenizer:
    """Incremental tokenizer over a whole buffer.

    ``tokenize`` returns tokens for the entire text. For long files we cap
    the work so a stray 10 MB paste cannot freeze the UI thread; callers get
    a ``truncated`` flag back.
    """

    MAX_CHARS = 2_000_000

    def __init__(self, text: str, max_chars: int | None = None):
        if max_chars is not None:
            self.MAX_CHARS = max_chars
        self.text = text if len(text) <= self.MAX_CHARS else text[: self.MAX_CHARS]
        self.truncated = len(text) > self.MAX_CHARS
        self.pos = 0
        self.line = 0
        self.col = 0
        self.n = len(self.text)

    # -- position helpers -------------------------------------------------
    def _advance(self, count: int) -> None:
        """Move the cursor, tracking line/column across newlines."""
        chunk = self.text[self.pos : self.pos + count]
        nl = chunk.count("\n")
        if nl:
            self.line += nl
            self.col = len(chunk) - chunk.rfind("\n") - 1
        else:
            self.col += len(chunk)
        self.pos += count

    def _emit(self, kind: Kind, text: str, line: int, col: int) -> Token:
        return Token(kind, text, line, col)

    # -- main loop --------------------------------------------------------
    def tokenize(self) -> list[Token]:
        out: list[Token] = []
        t = self.text
        pending_brace_depth = 0
        # Track whether the previous significant token makes the next
        # identifier a function call.
        prev_sig: Token | None = None

        while self.pos < self.n:
            ch = t[self.pos]

            # newline
            if ch == "\n":
                self._advance(1)
                continue

            # whitespace
            if ch in " \t\r\f\v":
                self._advance(1)
                continue

            start_line, start_col = self.line, self.col

            # ---- comments
            if t.startswith("//", self.pos):
                end = t.find("\n", self.pos)
                end = self.n if end == -1 else end
                raw = t[self.pos : end]
                kind = Kind.DOC_COMMENT if raw.startswith(("///", "//!")) else Kind.COMMENT
                out.append(self._emit(kind, raw, start_line, start_col))
                self._advance(len(raw))
                prev_sig = None
                continue

            if t.startswith("/*", self.pos):
                raw = self._read_block_comment()
                kind = (
                    Kind.DOC_COMMENT
                    if raw.startswith(("/**", "/*!", "/*<"))
                    else Kind.COMMENT
                )
                out.append(self._emit(kind, raw, start_line, start_col))
                self._advance(len(raw))
                prev_sig = None
                continue

            # ---- raw strings
            m = _RAW_STRING.match(t, self.pos)
            if m:
                raw = self._read_raw_string(m)
                if raw is not None:
                    out.append(self._emit(Kind.STRING, raw, start_line, start_col))
                    self._advance(len(raw))
                    prev_sig = None
                    continue
                # Unterminated raw string: fall through and let the quote be
                # read as an ordinary string so one bad literal cannot
                # recolour the rest of the file.

            # ---- normal strings and chars
            if ch in ('"', "'"):
                raw, kind = self._read_quoted(ch)
                out.append(self._emit(kind, raw, start_line, start_col))
                self._advance(len(raw))
                prev_sig = None
                continue

            # ---- preprocessor
            if ch == "#" and self._at_line_start():
                raw = self._read_preproc_line()
                out.append(self._emit(Kind.PREPROC, raw, start_line, start_col))
                self._advance(len(raw))
                prev_sig = None
                continue

            # ---- numbers
            if ch.isdigit() or (
                ch == "." and self.pos + 1 < self.n and t[self.pos + 1].isdigit()
            ):
                m = _NUMBER.match(t, self.pos)
                if m:
                    raw = m.group(0)
                    out.append(self._emit(Kind.NUMBER, raw, start_line, start_col))
                    self._advance(len(raw))
                    prev_sig = out[-1]
                    continue

            # ---- identifiers / keywords
            if _is_ident_start(ch):
                m = _IDENT.match(t, self.pos)
                word = m.group(0)
                kind = self._classify_ident(word, prev_sig)
                tok = self._emit(kind, word, start_line, start_col)
                out.append(tok)
                self._advance(len(word))

                # An identifier immediately followed by '(' is a call or a
                # declaration. Distinguish by whether it is followed by a
                # parameter list that ends with ') {' or just ')'.
                after = self._peek_non_space()
                if after == "(":
                    tok.kind = Kind.FUNCTION if self._looks_like_decl(out) else tok.kind
                prev_sig = tok
                continue

            # ---- operators and punctuation
            tok = self._emit(Kind.OPERATOR, ch, start_line, start_col)
            out.append(tok)
            self._advance(1)
            if ch in "{}()":
                prev_sig = None
            else:
                prev_sig = tok

        del pending_brace_depth
        return out

    # -- helpers ----------------------------------------------------------
    def _peek_non_space(self) -> str:
        j = self.pos
        while j < self.n and self.text[j] in " \t\r\n\f\v":
            j += 1
        return self.text[j] if j < self.n else ""

    def _at_line_start(self) -> bool:
        j = self.pos - 1
        while j >= 0 and self.text[j] in " \t":
            j -= 1
        return j < 0 or self.text[j] == "\n"

    def _classify_ident(self, word: str, prev_sig: Token | None) -> Kind:
        if word in LITERALS:
            return Kind.LITERAL
        if word in BUILTINS:
            return Kind.BUILTIN
        if word in KEYWORDS:
            if word in STORAGE:
                return Kind.TYPE if word in ("typedef",) else Kind.KEYWORD
            return Kind.KEYWORD
        # A capitalised identifier that is not a known type is probably a
        # user type. Cheap heuristic, but it colours most code correctly.
        if word[0].isupper() and word not in TYPES:
            return Kind.TYPE
        if word in TYPES:
            return Kind.TYPE
        return Kind.IDENT

    def _looks_like_decl(self, out: list[Token]) -> bool:
        """True if the identifier just emitted heads a function declaration.

        Walk back over the tokens: a '(' preceded by an identifier that was
        itself preceded by a type means ``ReturnType name(``.
        """
        if len(out) < 3:
            return False
        name_tok = out[-1]
        if name_tok.kind not in (Kind.IDENT, Kind.TYPE, Kind.KEYWORD):
            return False
        # find the '(' token
        i = len(out) - 1
        depth = 0
        while i >= 0:
            if out[i].text == "(":
                break
            if out[i].text in (")", "]", "}", ";", "{"):
                return False
            i -= 1
        if i < 1:
            return False
        before = out[i - 1]
        after = out[i - 1].text
        return before.kind in (Kind.IDENT, Kind.TYPE, Kind.KEYWORD) and after not in (
            "if", "for", "while", "switch", "catch", "return",
        )

    def _read_block_comment(self) -> str:
        """Read /* ... */ tolerating an unterminated comment."""
        end = self.text.find("*/", self.pos + 2)
        if end == -1:
            return self.text[self.pos :]
        return self.text[self.pos : end + 2]

    def _read_raw_string(self, m: re.Match[str]) -> str | None:
        """Read ``R"delim( ... )delim"``.

        Returns ``None`` when the literal is never terminated. C++ allows
        raw strings to span lines, so a missing terminator really does run
        to end of buffer -- but in an editor that means a half-typed line
        blanks the entire file, which is far worse than a slightly wrong
        highlight. The caller falls back to ordinary string handling.
        """
        delim = m.group("delim")
        closer = f'){delim}"'
        end = self.text.find(closer, m.end())
        if end == -1:
            return None
        return self.text[self.pos : end + len(closer)]

    def _read_quoted(self, quote: str) -> tuple[str, Kind]:
        """Read a quoted literal. Unterminated stops at the newline.

        Returning at the newline is important: it means one stray quote
        cannot recolour the entire rest of the file.
        """
        i = self.pos + 1
        t, n = self.text, self.n
        while i < n:
            c = t[i]
            if c == "\\":
                i += 2
                continue
            if c == "\n":
                break
            if c == quote:
                return t[self.pos : i + 1], (
                    Kind.STRING if quote == '"' else Kind.CHAR
                )
            i += 1
        raw = t[self.pos : i]
        return raw, Kind.STRING if quote == '"' else Kind.CHAR

    def _read_preproc_line(self) -> str:
        """Read to end of line, honouring backslash continuations."""
        i = self.pos
        n = self.n
        t = self.text
        while i < n:
            c = t[i]
            if c == "\\" and i + 1 < n and t[i + 1] == "\n":
                i += 2
                continue
            if c == "\n":
                break
            # a comment ends the directive even mid-line
            if t.startswith("//", i):
                j = t.find("\n", i)
                i = n if j == -1 else j
                break
            i += 1
        return t[self.pos : i]

    # -- public helpers ---------------------------------------------------
    def includes(self) -> list[str]:
        """Every ``#include`` target in the file, in order."""
        out = []
        for tok in self.tokenize():
            if tok.kind is Kind.PREPROC and "#include" in tok.text:
                m = re.search(r'[<"]([^>"]+)[>"]', tok.text)
                if m:
                    out.append(m.group(1))
        return out


def tokenize(text: str) -> list[Token]:
    """Convenience wrapper around :class:`Tokenizer`."""
    return Tokenizer(text).tokenize()


def iter_tokens(text: str) -> Iterator[Token]:
    yield from tokenize(text)


# -- completion support ----------------------------------------------------

def identifiers(text: str) -> set[str]:
    """Every user identifier defined or referenced in ``text``.

    Used by the completion engine to offer names that are actually in the
    translation unit rather than only language keywords.
    """
    out: set[str] = set()
    for tok in tokenize(text):
        if tok.kind is Kind.IDENT and len(tok.text) > 1:
            out.add(tok.text)
    return out


def defined_symbols(text: str) -> set[str]:
    """Identifiers that look like *declarations* in this buffer.

    More selective than :func:`identifiers`: picks up function names,
    class/struct names and variable declarations, which is what you want at
    the top of an autocomplete list.
    """
    out: set[str] = set()
    toks = tokenize(text)
    for i, tok in enumerate(toks):
        if tok.kind is Kind.TYPE and tok.text not in KEYWORDS:
            out.add(tok.text)
        elif (
            tok.kind is Kind.IDENT
            and tok.text not in KEYWORDS
            and tok.text not in BUILTINS
            and tok.text not in LITERALS
            and i + 1 < len(toks)
            and toks[i + 1].text == "("
            and tok.text.isidentifier()
        ):
            out.add(tok.text)
        elif (
            tok.kind is Kind.FUNCTION
            and tok.text.isidentifier()
            and tok.text not in KEYWORDS
        ):
            out.add(tok.text)
    return out


def comments_and_todos(text: str) -> list[tuple[int, str]]:
    """(line, marker) for every TODO/FIXME/... in the file."""
    out = []
    for tok in tokenize(text):
        if tok.kind in (Kind.COMMENT, Kind.DOC_COMMENT):
            for m in _TODO.finditer(tok.text):
                out.append((tok.line, m.group(1)))
    return out