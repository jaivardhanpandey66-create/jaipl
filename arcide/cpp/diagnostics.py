"""Parsing g++/clang diagnostics.

Feeds the Problems panel and lets a double-click jump straight to the
offending line. Pure Python, no GTK.

g++'s canonical diagnostic is::

    main.cpp:12:20: error: expected ';' before '}' token
    main.cpp: In function 'int main()':
    main.cpp:12:5: note: candidate: 'int main()' ...

We always pass ``-fdiagnostics-color=never`` so no ANSI escapes reach the
parser, but we strip them anyway so a coloured build still parses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# file:line:col: severity: message     (the 3-part form)
DIAG = re.compile(
    r"""^
    (?P<file>[^:\n]+):
    (?P<line>\d+)
    (?::(?P<col>\d+))?
    :\s*
    (?P<severity>fatal\s+error|error|warning|note|remark)
    :\s*
    (?P<message>.*)$
    """,
    re.VERBOSE,
)

# file:line: severity: message         (no column)
DIAG_NOCOL = re.compile(
    r"""^
    (?P<file>[^:\n]+):
    (?P<line>\d+)
    :\s*
    (?P<severity>fatal\s+error|error|warning|note|remark)
    :\s*
    (?P<message>.*)$
    """,
    re.VERBOSE,
)

# In function 'int main()':   /  At global scope:
CONTEXT = re.compile(r"^(?P<file>[^:\n]+):\s*(?P<ctx>In .*|At global scope.*)$")

# /usr/include/c++/13/vector:1234:5: note: candidate ...
NOTES = re.compile(r"^In file included from (?P<inc>[^:]+):?$")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One compiler message with a place to jump to."""

    file: str
    line: int          # 1-based, as printed
    col: int | None    # 1-based, or None
    severity: str      # 'error' | 'warning' | 'note' | 'remark' | 'fatal error'
    message: str

    @property
    def is_error(self) -> bool:
        return self.severity in ("error", "fatal error")

    @property
    def is_note(self) -> bool:
        return self.severity in ("note", "remark")

    @property
    def location(self) -> str:
        if self.col:
            return f"{self.file}:{self.line}:{self.col}"
        return f"{self.file}:{self.line}"

    def __str__(self) -> str:
        sev = self.severity.upper()
        return f"{self.file}:{self.line}:{self.col or '-'}: {sev}: {self.message}"


@dataclass(frozen=True, slots=True)
class BuildReport:
    """Everything one build produced."""

    diagnostics: tuple[Diagnostic, ...]
    raw: str
    returncode: int

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "error")

    @property
    def fatals(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "fatal error")

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "warning")

    @property
    def notes(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.is_note)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.errors and not self.fatals

    def summary(self) -> str:
        e, w = len(self.errors) + len(self.fatals), len(self.warnings)
        if e == 0 and w == 0:
            return "no problems"
        parts = []
        if e:
            parts.append(f"{e} error{'s' if e != 1 else ''}")
        if w:
            parts.append(f"{w} warning{'s' if w != 1 else ''}")
        return ", ".join(parts)


def parse(output: str, returncode: int = 0) -> BuildReport:
    """Parse combined compiler stdout/stderr into a :class:`BuildReport`."""
    diags: list[Diagnostic] = []
    last_context: str | None = None

    for line in output.splitlines():
        line = ANSI.sub("", line).rstrip()
        if not line:
            continue

        m = CONTEXT.match(line)
        if m:
            last_context = m.group("ctx")
            continue

        m = DIAG.match(line) or DIAG_NOCOL.match(line)
        if not m:
            continue

        sev = " ".join(m.group("severity").split())
        diags.append(
            Diagnostic(
                file=m.group("file").strip(),
                line=int(m.group("line")),
                col=int(m.group("col")) if m.group("col") else None,
                severity=sev,
                message=m.group("message").strip(),
            )
        )

    # Drop notes that merely repeat a location we already have; they add
    # noise to the Problems list without adding anywhere to jump to.
    deduped: list[Diagnostic] = []
    seen: set[tuple[str, int, int | None, str]] = set()
    for d in diags:
        key = (d.file, d.line, d.col, d.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(d)

    del last_context
    return BuildReport(tuple(deduped), output, returncode)


def linker_error(output: str) -> str | None:
    """Detect a link failure that has no file:line to jump to.

    ``undefined reference to 'foo()'`` and ``ld returned 1 exit status``
    are the two you actually hit in a C++ project, and neither produces a
    diagnostic, so without this they would look like a mysterious non-zero
    exit.
    """
    text = ANSI.sub("", output)
    interesting = []
    for line in text.splitlines():
        if re.search(r"undefined reference|multiple definition|ld returned|"
                     r"collect2: error|cannot find -l|No such file or directory.*\.o",
                     line):
            interesting.append(line.strip())
    if not interesting:
        return None
    return "\n".join(interesting[:20])


def summarise(report: BuildReport) -> str:
    """One line for the status bar."""
    if report.ok:
        return "build succeeded" if not report.warnings else (
            f"built with {len(report.warnings)} warning"
            f"{'s' if len(report.warnings) != 1 else ''}"
        )
    link = linker_error(report.raw)
    if link and not report.errors and not report.fatals:
        return "link failed"
    return report.summary()