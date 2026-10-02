"""Build planning for C++.

Pure Python: turns a "current file" into a concrete g++/cmake invocation
without executing anything, so the planner is unit testable and the UI can
show the user exactly what will run before it runs.

Three project shapes are recognised, in priority order:

1. **CMake**  -- a ``CMakeLists.txt`` anywhere up from the file. Configures
   once into a private build dir, then ``cmake --build``.
2. **Make**   -- a ``Makefile`` beside the file. Uses ``make``.
3. **g++**    -- the default. Every ``.cpp`` in the file's directory is
   compiled together and linked into one binary, which is what people
   expect when they press F5 on ``main.cpp`` in a small project. A lone
   file compiles alone.

The private build directory is ``.arcide-build`` in the project root, so no
artefacts land next to sources and the explorer can hide it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

BUILD_DIRNAME = ".arcide-build"

SOURCE_EXTS = (".cpp", ".cxx", ".cc", ".C", ".c++")
HEADER_EXTS = (".h", ".hpp", ".hxx", ".hh", ".inl", ".ipp")

# Warnings we always want; they cost nothing and catch real bugs.
BASE_WARNINGS = ["-Wall", "-Wextra", "-Wpedantic"]

# Debug and release flag sets. Note -g3 and not -g -g3: the level already
# subsumes plain -g and passing both is just noise in the command line.
DEBUG_FLAGS = ["-g3", "-O0", "-fno-omit-frame-pointer"]
RELEASE_FLAGS = ["-O2", "-DNDEBUG"]

# g++ 15 supports these; we probe rather than assume.
KNOWN_STANDARDS = ["c++26", "c++23", "c++20", "c++17", "c++14", "c++11"]

# Default to C++20 even when the compiler also understands C++23/26. The
# newest standard is usually a moving target that trips up ordinary code;
# the project can still opt into a newer one from Settings.
DEFAULT_STANDARD = "c++20"


@dataclass
class Toolchain:
    """What we found on this machine."""

    cxx: str = "g++"
    cc: str = "gcc"
    cmake: str | None = None
    make: str | None = None
    gdb: str | None = None
    standard: str = "c++20"
    standards_supported: list[str] = field(default_factory=list)

    @property
    def has_gpp(self) -> bool:
        return shutil.which(self.cxx) is not None


def detect_toolchain(cxx: str = "g++") -> Toolchain:
    """Probe the compiler for its supported -std values.

    A compiler that rejects ``-std=c++23`` should not get it in the flags,
    so the standard is chosen by actually trying to compile, not by reading
    a version number.
    """
    t = Toolchain()
    t.cxx = shutil.which(cxx) or cxx
    t.cc = shutil.which("gcc") or "gcc"
    t.cmake = shutil.which("cmake")
    t.make = shutil.which("make") or shutil.which("gmake")
    t.gdb = shutil.which("gdb")

    import subprocess
    import tempfile

    probe_src = "int main(){return 0;}\n"
    for std in KNOWN_STANDARDS:
        with tempfile.TemporaryDirectory() as d:
            s = Path(d) / "p.cpp"
            s.write_text(probe_src)
            try:
                r = subprocess.run(
                    [t.cxx, f"-std={std}", "-fsyntax-only", str(s)],
                    capture_output=True, timeout=25,
                )
            except (OSError, subprocess.SubprocessError):
                break
            if r.returncode != 0:
                break
            t.standards_supported.append(std)
    if t.standards_supported:
        if DEFAULT_STANDARD in t.standards_supported:
            t.standard = DEFAULT_STANDARD
        else:
            t.standard = t.standards_supported[0]
    return t


@dataclass
class BuildPlan:
    """Everything needed to build and run one target."""

    kind: str  # 'g++' | 'cmake' | 'make'
    project_root: Path
    source: Path
    sources: list[Path]
    binary: Path
    build_dir: Path
    compile_cmd: list[str]
    run_cmd: list[str]
    needs_configure: bool = False
    configure_cmd: list[str] = field(default_factory=list)
    target: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def display(self) -> str:
        return " ".join(self.compile_cmd)

    def run_display(self) -> str:
        return " ".join(self.run_cmd)


def _find_upwards(start: Path, names: tuple[str, ...]) -> Path | None:
    """Nearest ancestor (inclusive) containing any of ``names``."""
    cur = start.resolve()
    for d in [cur, *cur.parents]:
        for n in names:
            if (d / n).is_file():
                return d
    return None


def _sources_beside(source: Path) -> list[Path]:
    """All C++ sources in the source file's own directory."""
    out = sorted(
        p for p in source.parent.iterdir()
        if p.is_file() and p.suffix in SOURCE_EXTS
    )
    # Prefer a file literally called main.cpp as the entry point, but every
    # .cpp in the folder is still compiled and linked in.
    return out


def _cmake_target_name(root: Path) -> str:
    """Guess the cmake executable target from add_executable(...)."""
    text = ""
    for name in ("CMakeLists.txt",):
        p = root / name
        if p.is_file():
            try:
                text = p.read_text(errors="replace")
            except OSError:
                return ""
    m = re.search(r"add_executable\s*\(\s*([A-Za-z0-9_\-]+)", text)
    return m.group(1) if m else ""


def _cmake_binary_target(binary: Path) -> str:
    """The path cmake will actually produce for a given target name."""
    return str(binary)


def plan(
    source: str | os.PathLike[str],
    tc: Toolchain | None = None,
    debug_build: bool = True,
    standard: str | None = None,
    extra_flags: list[str] | None = None,
) -> BuildPlan:
    """Build a :class:`BuildPlan` for ``source``. Raises on bad input."""
    tc = tc or detect_toolchain()
    src = Path(source).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"no such file: {src}")
    if src.suffix not in SOURCE_EXTS and src.suffix not in HEADER_EXTS:
        raise ValueError(f"not a C++ source file: {src.name}")
    if src.suffix in HEADER_EXTS:
        raise ValueError(
            f"{src.name} is a header - open the .cpp that includes it"
        )

    std = standard or tc.standard
    if tc.standards_supported and std not in tc.standards_supported:
        std = tc.standards_supported[0]
    flags = BASE_WARNINGS + (DEBUG_FLAGS if debug_build else RELEASE_FLAGS)
    flags += [f"-std={std}"]
    flags += extra_flags or []

    # ---- 1. CMake wins if there is a CMakeLists.txt above the file
    cmake_root = _find_upwards(src, ("CMakeLists.txt",))
    if cmake_root and tc.cmake:
        build_dir = cmake_root / "build" / "arcide"
        target = _cmake_target_name(cmake_root)
        notes = [f"CMake project at {cmake_root}"]
        if target:
            notes.append(f"target {target}")
        else:
            notes.append(
                "no add_executable() found - building the default target"
            )
        compile_cmd = [tc.cmake, "--build", str(build_dir)]
        if target:
            compile_cmd += ["--target", target]
        configure_cmd = [
            tc.cmake, "-S", str(cmake_root), "-B", str(build_dir),
            "-DCMAKE_BUILD_TYPE=" + ("Debug" if debug_build else "Release"),
            f"-DCMAKE_CXX_STANDARD={std.removeprefix('c++')}",
        ]
        # Where cmake drops the executable: build_dir/<target>, or just the
        # root of the build dir when we could not read a target name.
        binary = build_dir / target if target else build_dir
        run_cmd = [str(binary)] if target else []
        return BuildPlan(
            kind="cmake",
            project_root=cmake_root,
            source=src,
            sources=[src],
            binary=binary,
            build_dir=build_dir,
            compile_cmd=compile_cmd,
            run_cmd=run_cmd,
            needs_configure=True,
            configure_cmd=configure_cmd,
            target=target or None,
            notes=notes,
        )

    # ---- 2. Make
    make_root = _find_upwards(src, ("Makefile", "makefile", "GNUmakefile"))
    if make_root and tc.make and make_root == src.parent:
        binary = make_root / src.stem
        return BuildPlan(
            kind="make",
            project_root=make_root,
            source=src,
            sources=[src],
            binary=binary,
            build_dir=make_root,
            compile_cmd=[tc.make, "-C", str(make_root), src.stem],
            run_cmd=[str(binary)],
            notes=[f"Makefile in {make_root}"],
        )

    # ---- 3. g++ (the default)
    root = _find_upwards(src, ("CMakeLists.txt", ".git", ".hg")) or src.parent
    if root == src.parent:
        for d in src.parents:
            if (d / ".git").exists():
                root = d
                break

    sources = _sources_beside(src)
    if src not in sources:
        sources.append(src)
    sources = sorted(set(sources))

    build_dir = root / BUILD_DIRNAME
    name = src.stem
    # main.cpp linking to main.o is the common case; keep the binary named
    # after the file you pressed F5 on.
    binary = build_dir / name

    # g++ will not create the output directory, so we do. Creating it here
    # keeps the plan immediately runnable by any caller.
    build_dir.mkdir(parents=True, exist_ok=True)

    includes = [f"-I{d}" for d in {str(p.parent) for p in sources}]
    compile_cmd = [tc.cxx, *flags, *includes, *[str(p) for p in sources],
                   "-o", str(binary)]

    notes = [f"{len(sources)} source file(s) in {src.parent}"]
    if len(sources) > 1:
        notes.append("linked: " + ", ".join(p.name for p in sources))
    if debug_build:
        notes.append("debug (-g3 -O0)")
    else:
        notes.append("release (-O2 -DNDEBUG)")

    return BuildPlan(
        kind="g++",
        project_root=root,
        source=src,
        sources=sources,
        binary=binary,
        build_dir=build_dir,
        compile_cmd=compile_cmd,
        run_cmd=[str(binary)],
        notes=notes,
    )


def compile_commands_entry(plan_obj: BuildPlan) -> dict:
    """A ``compile_commands.json`` record for the current file."""
    cmd = plan_obj.compile_cmd
    try:
        idx = cmd.index("-o")
        cmd = cmd[:idx] + cmd[idx + 2:]
    except ValueError:
        pass
    return {
        "directory": str(plan_obj.project_root),
        "file": str(plan_obj.source),
        "output": str(plan_obj.binary),
        "arguments": cmd,
    }


def write_compile_commands(plans: list[BuildPlan], path: Path | None = None) -> Path:
    """Write compile_commands.json for the project's C++ files."""
    if not plans:
        raise ValueError("no build plans")
    root = plans[0].project_root
    target = path or (root / "compile_commands.json")
    seen: dict[str, dict] = {}
    for p in plans:
        e = compile_commands_entry(p)
        seen[e["file"]] = e
    target.write_text(json.dumps(list(seen.values()), indent=2) + "\n")
    return target