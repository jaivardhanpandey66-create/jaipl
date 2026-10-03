"""Run C++ from inside zing.

zing is meant to be usable from any editor on any machine, so the bridge
shells out to the system g++ rather than linking against a toolchain library.
That means it works wherever g++ is installed, and it fails with a clear
message everywhere else.

    import gpp
    let r = gpp.run("#include <cstdio>\\nint main(){ std::puts(\\"hi\\"); }")
    print(r.out)      // everything the program printed
    print(r.code)     // 0 on success

Compilation is cached by the hash of the source, so calling gpp.run twice
with the same program does not pay for g++ twice.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .interp import NativeFn, RuntimeError_
from .parser import Call, Import, Var

CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
) / "zing" / "gpp"

_TIMEOUT = float(os.environ.get("ZING_CPP_TIMEOUT", "30"))


def find_compiler() -> str | None:
    """Locate a C++ compiler, preferring g++ then clang++."""
    for name in ("g++", "clang++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _cache_key(source: str, compiler: str) -> str:
    h = hashlib.sha256()
    h.update(source.encode("utf-8"))
    h.update(compiler.encode("utf-8"))
    # The compiler's version is part of the key so upgrading g++ does not
    # silently reuse binaries built by the old one.
    try:
        ver = subprocess.run(
            [compiler, "--version"], capture_output=True, timeout=10
        ).stdout.decode("utf-8", "replace").splitlines()[0]
    except Exception:
        ver = "unknown"
    h.update(ver.encode("utf-8"))
    return h.hexdigest()[:32]


def compile_source(source: str, keep: bool = False) -> tuple[Path | None, str, str]:
    """Compile one C++ snippet.

    Returns (binary_path, compiler_stdout, compiler_stderr). binary_path is
    None when compilation failed.
    """
    compiler = find_compiler()
    if not compiler:
        raise RuntimeError_(
            "no C++ compiler found. Install g++ (Linux: 'sudo apt install "
            "g++', macOS: 'xcode-select --install') and try again."
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(source, compiler)
    binary = CACHE_DIR / key
    src_path = CACHE_DIR / f"{key}.cpp"

    # Reuse only if the binary is newer than the recorded source.
    if binary.exists() and src_path.exists():
        if src_path.stat().st_mtime <= binary.stat().st_mtime:
            return binary, "", ""

    src_path.write_text(source, encoding="utf-8")
    cmd = [
        compiler, "-std=c++20", "-O0", "-g",
        str(src_path), "-o", str(binary),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError_(
            f"compiling took longer than {_TIMEOUT:.0f}s"
        ) from None

    if proc.returncode != 0:
        src_path.unlink(missing_ok=True)
        return None, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode(
            "utf-8", "replace"
        )

    if not keep:
        src_path.unlink(missing_ok=True)
    return binary, proc.stdout.decode("utf-8", "replace"), ""


def _run_binary(binary: Path, stdin_text: str = "") -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [str(binary)],
            input=stdin_text.encode("utf-8"),
            capture_output=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError_(
            f"the program ran longer than {_TIMEOUT:.0f}s "
            f"(infinite loop?)"
        ) from None
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def gpp_run(source, interp=None):
    """gpp.run(source) -> a map with out, err and code."""
    if not isinstance(source, str):
        raise RuntimeError_("gpp.run() needs the C++ source as a string")
    binary, cout, cerr = compile_source(source)
    if binary is None:
        raise RuntimeError_(
            "the C++ code did not compile:\n" + cerr.strip() + cout.strip()
        )
    code, out, err = _run_binary(binary)
    return {"code": code, "out": out, "err": err}


def gpp_run_file(path, interp=None):
    """gpp.runFile(path) -> the same map, compiling a real .cpp file."""
    if not isinstance(path, str):
        raise RuntimeError_("gpp.runFile() needs a path string")
    p = Path(path).expanduser()
    if not p.exists():
        raise RuntimeError_(f"no such file: {path}")
    binary, cout, cerr = compile_source(p.read_text(encoding="utf-8"))
    if binary is None:
        raise RuntimeError_(
            f"{path} did not compile:\n" + cerr.strip() + cout.strip()
        )
    code, out, err = _run_binary(binary)
    return {"code": code, "out": out, "err": err}


def gpp_compile_only(source, interp=None):
    """gpp.compile(source) -> a map with ok and the compiler messages."""
    if not isinstance(source, str):
        raise RuntimeError_("gpp.compile() needs the C++ source as a string")
    binary, cout, cerr = compile_source(source)
    return {
        "ok": binary is not None,
        "out": (cout + cerr).strip(),
    }


def gpp_version(interp=None) -> str:
    compiler = find_compiler()
    if not compiler:
        return "no C++ compiler found"
    try:
        proc = subprocess.run([compiler, "--version"], capture_output=True)
        return proc.stdout.decode("utf-8", "replace").splitlines()[0]
    except Exception:
        return compiler


# A module is a plain dict of callables. The interpreter hands it over when it
# sees 'import gpp'.
def make_module() -> dict:
    return {
        "run": NativeFn("gpp.run", gpp_run, wants_interp=True),
        "runFile": NativeFn("gpp.runFile", gpp_run_file, wants_interp=True),
        "compile": NativeFn("gpp.compile", gpp_compile_only, wants_interp=True),
        "version": NativeFn("gpp.version", gpp_version, wants_interp=True),
    }