#!/usr/bin/env bash
#
# zing installer for Linux and macOS.
#
#   curl -fsSL https://jaivardhanpandey66-create.github.io/zing/install.sh | sh
#
# Installs the 'zing' command into ~/.local/bin. Nothing is written outside
# your home directory and no sudo is needed, so a failed install never leaves
# the system half-changed.
#
# Options:
#   --prefix DIR      install somewhere else (default: ~/.local)
#   --with-associate  also register .zig files and a desktop entry
#   --uninstall       remove an existing install
#   --version         print what would be installed and stop
#   --local PATH      install from a checkout on this machine, no download
#
set -euo pipefail

VERSION="0.1.0"

# Where the archive lives. zing.dev is not registered yet, so the GitHub
# Pages site is the source of truth; the raw file is the fallback if Pages
# is unreachable.
PAGES_URL="https://jaivardhanpandey66-create.github.io/zing"
RAW_URL="https://raw.githubusercontent.com/jaivardhanpandey66-create/zing/main"
REPO="https://github.com/jaivardhanpandey66-create/zing"
REPO="zing-lang/zing"
PREFIX="$HOME/.local"
ASSOCIATE=0
UNINSTALL=0
LOCAL_PATH=""
DRY_RUN=0

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)        PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
    --with-associate|--with-associations) ASSOCIATE=1; shift ;;
    --uninstall)     UNINSTALL=1; shift ;;
    --version)       DRY_RUN=1; shift ;;
    --local)         LOCAL_PATH="${2:?--local needs a path}"; shift 2 ;;
    -h|--help)
      sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown option $1 (try --help)" ;;
  esac
done

BIN_DIR="$PREFIX/bin"
SHARE_DIR="$PREFIX/share/zing"
TARGET="$BIN_DIR/zing"

# --- uninstall ---------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
  if [ -e "$TARGET" ]; then
    say "removing $TARGET"
    rm -f "$TARGET"
    rm -rf "$SHARE_DIR"
  else
    say "nothing installed at $TARGET"
  fi
  if [ "$ASSOCIATE" = 1 ]; then
    rm -f "$HOME/.local/share/applications/zing.desktop"
    say "removed desktop entry"
  fi
  say "done"
  exit 0
fi

if [ "$DRY_RUN" = 1 ]; then
  say "zing $VERSION"
  say "would install to: $TARGET"
  exit 0
fi

case "$(uname -s)" in
  Linux|Darwin) ;;
  *) die "this installer covers Linux and macOS. On Windows, download the installer from $PAGES_URL" ;;
esac

command -v python3 >/dev/null 2>&1 || \
  die "python3 is required (3.11 or newer). On Ubuntu: sudo apt install python3"
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || \
  die "python3 $PYV is too old; zing needs 3.11 or newer"

mkdir -p "$BIN_DIR"

# --- get the files -----------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ -n "$LOCAL_PATH" ]; then
  [ -d "$LOCAL_PATH/arcide/zing" ] || \
    die "$LOCAL_PATH does not look like a zing checkout (no arcide/zing)"
  say "installing from $LOCAL_PATH"
  mkdir -p "$SHARE_DIR"
  cp -R "$LOCAL_PATH/arcide" "$SHARE_DIR/"
  cp -R "$LOCAL_PATH/examples" "$SHARE_DIR/" 2>/dev/null || true
  cp "$LOCAL_PATH/ZING.md" "$SHARE_DIR/" 2>/dev/null || true
  RUNTIME="$SHARE_DIR"
else
  # Release tarball first; fall back to the source archive so a missing or
  # unpublished release does not break the one-line install.
  URLS="
  https://github.com/jaivardhanpandey66-create/zing/releases/download/v$VERSION/zing-v$VERSION.tar.gz
  https://codeload.github.com/jaivardhanpandey66-create/zing/tar.gz/refs/heads/main
  "
  say "downloading zing $VERSION"
  fetch() {
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$1" -o "$WORK/zing.tar.gz"
    else
      wget -qO "$WORK/zing.tar.gz" "$1"
    fi
  }
  OK=""
  for url in $URLS; do
    say "  trying $url"
    if fetch "$url" 2>/dev/null && [ -s "$WORK/zing.tar.gz" ]; then
      OK="$url"; break
    fi
    rm -f "$WORK/zing.tar.gz"
  done
  [ -n "$OK" ] || die "download failed from every mirror. Install from a
     checkout with --local PATH, or read $PAGES_URL for manual steps"
  say "unpacking"
  # Two archive shapes are in play: a release tarball is flat, while the
  # GitHub source archive wraps everything in a branch-named directory.
  # Unpack somewhere scratch and find the real root either way.
  UNPACK="$WORK/unpack"
  mkdir -p "$UNPACK"
  tar -xzf "$WORK/zing.tar.gz" -C "$UNPACK"
  ROOT=""
  if [ -d "$UNPACK/arcide/zing" ]; then
    ROOT="$UNPACK"
  else
    for d in "$UNPACK"/*/; do
      [ -d "$d/arcide/zing" ] && { ROOT="$d"; break; }
    done
  fi
  [ -n "$ROOT" ] || die "the archive did not contain arcide/zing"

  mkdir -p "$SHARE_DIR"
  cp -R "$ROOT/arcide" "$SHARE_DIR/"
  cp -R "$ROOT/examples" "$SHARE_DIR/" 2>/dev/null || true
  cp "$ROOT/ZING.md" "$SHARE_DIR/" 2>/dev/null || true
  RUNTIME="$SHARE_DIR"
fi

# --- the command -------------------------------------------------------
say "installing the zing command to $TARGET"
cat > "$TARGET" <<LAUNCHER
#!/usr/bin/env bash
export PYTHONPATH="$RUNTIME\${PYTHONPATH:+:\$PYTHONPATH}"
exec "\${ZING_PYTHON:-python3}" -m arcide.zing.cli "\$@"
LAUNCHER
chmod +x "$TARGET"

# --- PATH --------------------------------------------------------------
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    warn "$BIN_DIR is not on your PATH"
    warn "add this to your shell profile:"
    warn "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    ;;
esac

# --- desktop integration ----------------------------------------------
if [ "$ASSOCIATE" = 1 ]; then
  if [ "$(uname -s)" = "Linux" ]; then
    say "registering the .zig file type"
    mkdir -p "$HOME/.local/share/mime/packages" "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/mime/packages/zing.xml" <<'MIME'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="text/x-zing">
    <comment>zing source file</comment>
    <glob pattern="*.zig"/>
    <sub-class-of type="text/plain"/>
  </mime-type>
</mime-info>
MIME
    update-mime-database "$HOME/.local/share/mime" 2>/dev/null || true
    mkdir -p "$HOME/.config"
    touch "$HOME/.config/mimeapps.list"
    grep -q 'text/x-zing.desktop' "$HOME/.config/mimeapps.list" 2>/dev/null || \
      printf '[Default Applications]\ntext/x-zing=zing.desktop\n' >> "$HOME/.config/mimeapps.list"

    cat > "$HOME/.local/share/applications/zing.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=zing Program
Comment=Run a zing program
Exec=$TARGET %f
Terminal=true
MimeType=text/x-zing;
NoDisplay=false
Categories=Development;IDE;
DESKTOP
    chmod +x "$HOME/.local/share/applications/zing.desktop"
    say "double-clicking a .zig file will now run it"
  else
    warn "macOS file association is handled by the .app bundle, not this script"
    warn "use: open -a zing file.zig   (after installing the app)"
  fi
fi

# --- verify ------------------------------------------------------------
# Run from a directory that has no arcide/ in it: otherwise Python finds the
# source tree through the working directory and a broken PYTHONPATH still
# looks like it worked.
say "checking the install"
( cd / && "$TARGET" version >/dev/null 2>&1 ) \
  || die "the installed command did not run"
printf 'print("zing works")\n' > "$WORK/t.zig"
OUT="$( cd / && "$TARGET" run "$WORK/t.zig" )" \
  || die "a test program did not run"
[ "$OUT" = "zing works" ] || die "unexpected test output: $OUT"

say "installed zing $VERSION"
[ "$OUT" = "zing works" ] && printf '   try:  zing repl\n          zing run %s\n' \
  "$SHARE_DIR/examples/shapes.zig" 2>/dev/null || true