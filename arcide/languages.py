"""Multi-language support: which files are code, how to run them, how to
highlight them.

One table drives the whole editor. Adding a language means adding an entry,
not wiring up new code paths, which is what keeps 'support lots of
languages' from turning into a pile of special cases.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Language:
    name: str
    extensions: tuple
    # Shell command template. {file} is the path, {dir} its folder,
    # {name} the file without extension. A language with no runner is
    # 'edit only', which is normal for markup and config files.
    run: str = ""
    stop_after: bool = True
    keywords: tuple = ()
    line_comment: tuple = ("//",)
    block_comment: tuple = ("/*", "*/")
    strings: tuple = ('"', "'")
    indent_with_spaces: bool = True
    # Languages whose programs are run by our own interpreter rather than a
    # separate command line.
    internal: str = ""


def _run(file: str) -> str:
    return ""


# -- the table ----------------------------------------------------------

LANGUAGES: tuple = (
    Language(
        name="zing",
        extensions=(".zig",),
        run="zing run {file}",
        keywords=(
            "let", "var", "func", "class", "extends", "new", "self", "if",
            "elif", "else", "while", "for", "in", "break", "continue",
            "return", "import", "and", "or", "not", "true", "false", "null",
        ),
        line_comment=("//",),
        block_comment=(),
        internal="zing",
    ),
    Language(
        name="C++",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".c++"),
        run="g++ -std=c++20 -O0 -g {file} -o {dir}/.arcide-run && {dir}/.arcide-run",
        keywords=(
            "alignas", "alignof", "auto", "bool", "break", "case", "catch",
            "char", "class", "const", "constexpr", "consteval", "continue",
            "decltype", "default", "delete", "do", "double", "else",
            "enum", "explicit", "export", "extern", "false", "float", "for",
            "friend", "goto", "if", "inline", "int", "long", "namespace",
            "new", "noexcept", "nullptr", "operator", "private", "protected",
            "public", "register", "return", "short", "signed", "sizeof",
            "static", "struct", "switch", "template", "this", "throw", "true",
            "try", "typedef", "typeid", "typename", "union", "unsigned",
            "using", "virtual", "void", "volatile", "while",
        ),
    ),
    Language(
        name="C",
        extensions=(".c", ".h"),
        run="gcc -std=c17 -O0 -g {file} -o {dir}/.arcide-run && {dir}/.arcide-run",
        keywords=(
            "auto", "break", "case", "char", "const", "continue", "default",
            "do", "double", "else", "enum", "extern", "float", "for", "goto",
            "if", "inline", "int", "long", "register", "return", "short",
            "signed", "sizeof", "static", "struct", "switch", "typedef",
            "union", "unsigned", "void", "volatile", "while",
        ),
    ),
    Language(
        name="Python",
        extensions=(".py", ".pyw"),
        run="python3 {file}",
        keywords=(
            "and", "as", "assert", "async", "await", "break", "class",
            "continue", "def", "del", "elif", "else", "except", "False",
            "finally", "for", "from", "global", "if", "import", "in", "is",
            "lambda", "None", "nonlocal", "not", "or", "pass", "raise",
            "return", "True", "try", "while", "with", "yield",
        ),
        line_comment=("#",),
        block_comment=(),
    ),
    Language(
        name="JavaScript",
        extensions=(".js", ".mjs", ".cjs", ".jsx"),
        run="node {file}",
        keywords=(
            "async", "await", "break", "case", "catch", "class", "const",
            "continue", "default", "delete", "do", "else", "export",
            "extends", "false", "finally", "for", "function", "if",
            "import", "in", "instanceof", "let", "new", "null", "of",
            "return", "static", "super", "switch", "this", "throw", "true",
            "try", "typeof", "var", "void", "while", "yield",
        ),
    ),
    Language(
        name="TypeScript",
        extensions=(".ts", ".tsx"),
        run="npx --yes tsx {file}",
        keywords=(
            "abstract", "any", "as", "async", "await", "boolean", "break",
            "case", "catch", "class", "const", "continue", "declare",
            "default", "do", "else", "enum", "export", "extends", "false",
            "finally", "for", "from", "function", "if", "implements",
            "import", "in", "interface", "let", "new", "null", "number",
            "of", "private", "public", "readonly", "return", "static",
            "string", "super", "switch", "this", "throw", "true", "try",
            "type", "typeof", "var", "void", "while", "yield",
        ),
    ),
    Language(
        name="Java",
        extensions=(".java",),
        run="java {file}",
        keywords=(
            "abstract", "assert", "boolean", "break", "byte", "case",
            "catch", "char", "class", "const", "continue", "default", "do",
            "double", "else", "enum", "extends", "final", "finally", "float",
            "for", "if", "implements", "import", "instanceof", "int",
            "interface", "long", "native", "new", "package", "private",
            "protected", "public", "record", "return", "static", "strictfp",
            "super", "switch", "synchronized", "this", "throw", "throws",
            "transient", "try", "var", "void", "while", "yield",
        ),
    ),
    Language(
        name="Rust",
        extensions=(".rs",),
        run="rustc -O -o {dir}/.arcide-run {file} && {dir}/.arcide-run",
        keywords=(
            "as", "async", "await", "break", "const", "continue", "crate",
            "dyn", "else", "enum", "extern", "false", "fn", "for", "if",
            "impl", "in", "let", "loop", "match", "mod", "move", "mut",
            "pub", "ref", "return", "self", "Self", "static", "struct",
            "super", "trait", "true", "type", "unsafe", "use", "where",
            "while",
        ),
    ),
    Language(
        name="Go",
        extensions=(".go",),
        run="go run {file}",
        keywords=(
            "break", "case", "chan", "const", "continue", "default",
            "defer", "else", "fallthrough", "for", "func", "go", "goto",
            "if", "import", "interface", "map", "package", "range",
            "return", "select", "struct", "switch", "type", "var",
        ),
    ),
    Language(
        name="Shell",
        extensions=(".sh", ".bash", ".zsh"),
        run="bash {file}",
        keywords=(
            "case", "do", "done", "elif", "else", "esac", "fi", "for",
            "function", "if", "in", "local", "return", "then", "until",
            "while",
        ),
        line_comment=("#",),
        block_comment=(),
    ),
    Language(
        name="Ruby",
        extensions=(".rb",),
        run="ruby {file}",
        keywords=(
            "alias", "and", "begin", "break", "case", "class", "def",
            "defined?", "do", "else", "elsif", "end", "ensure", "false",
            "for", "if", "in", "module", "next", "nil", "not", "or", "redo",
            "rescue", "retry", "return", "self", "super", "then", "true",
            "unless", "until", "when", "while", "yield",
        ),
        line_comment=("#",),
        block_comment=(),
    ),
    Language(
        name="Lua",
        extensions=(".lua",),
        run="lua {file}",
        keywords=(
            "and", "break", "do", "else", "elseif", "end", "false", "for",
            "function", "goto", "if", "in", "local", "nil", "not", "or",
            "repeat", "return", "then", "true", "until", "while",
        ),
        line_comment=("--",),
        block_comment=("--[[", "]]"),
    ),
    Language(
        name="HTML",
        extensions=(".html", ".htm"),
        keywords=(
            "a", "body", "div", "head", "h1", "html", "img", "input", "li",
            "link", "meta", "p", "script", "span", "style", "title", "ul",
        ),
        line_comment=(),
        block_comment=("<!--", "-->"),
        indent_with_spaces=False,
    ),
    Language(
        name="CSS",
        extensions=(".css",),
        keywords=(
            "align", "background", "border", "bottom", "color", "content",
            "display", "flex", "font", "gap", "grid", "height", "justify",
            "left", "margin", "padding", "position", "right", "top",
            "width",
        ),
        block_comment=("/*", "*/"),
    ),
    Language(
        name="JSON",
        extensions=(".json",),
        keywords=("true", "false", "null"),
        line_comment=(),
        block_comment=(),
        strings=('"',),
    ),
    Language(
        name="Markdown",
        extensions=(".md", ".markdown"),
        keywords=(),
        line_comment=(),
        block_comment=(),
        strings=(),
    ),
)

BY_EXTENSION: dict = {}
for _lang in LANGUAGES:
    for _ext in _lang.extensions:
        BY_EXTENSION[_ext] = _lang

PLAIN = Language(name="Plain text", extensions=(".txt",), keywords=())


def for_path(path: str) -> Language:
    """The language for a file path, or plain text when unknown."""
    ext = os.path.splitext(str(path))[1].lower()
    return BY_EXTENSION.get(ext, PLAIN)


def for_name(name: str) -> Language | None:
    for lang in LANGUAGES:
        if lang.name == name:
            return lang
    return None


def all_names() -> list:
    return [lang.name for lang in LANGUAGES]


def is_runnable(lang: Language) -> bool:
    return bool(lang.run)


def command_for(lang: Language, path: str) -> list:
    """The argv for running `path` as `lang`.

    Raises ValueError when the language has no runner, so the caller can
    explain the problem instead of launching an empty command.
    """
    if not lang.run:
        raise ValueError(f"{lang.name} files cannot be run")
    directory = os.path.dirname(os.path.abspath(path)) or "."
    stem = os.path.splitext(os.path.basename(path))[0]
    line = lang.run.format(
        file=shlex.quote(os.path.abspath(path)),
        dir=shlex.quote(directory),
        name=shlex.quote(stem),
    )
    return ["bash", "-lc", line]