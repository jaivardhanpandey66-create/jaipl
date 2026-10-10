#!/usr/bin/env bash
# Assemble zing.app. Run this on macOS, or any machine with the tools.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
app="$root/dist/zing.app"
VERSION="$(/usr/bin/grep -A2 'CFBundleShortVersionString' "$here/zing.app/Contents/Info.plist" | /usr/bin/grep -o '[0-9][0-9.]*' | head -1)"

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

cp "$here/zing.app/Contents/MacOS/zing" "$app/Contents/MacOS/zing"
chmod +x "$app/Contents/MacOS/zing"
cp "$here/zing.app/Contents/Info.plist" "$app/Contents/Info.plist"
if [ -f "$here/zing.app/Contents/Resources/zing.icns" ]; then
  cp "$here/zing.app/Contents/Resources/zing.icns" "$app/Contents/Resources/zing.icns"
elif [ -f "$root/packaging/icons/zing.icns" ]; then
  cp "$root/packaging/icons/zing.icns" "$app/Contents/Resources/zing.icns"
fi

mkdir -p "$app/Contents/Resources/runtime"
cp -R "$root/arcide" "$app/Contents/Resources/runtime/arcide"
cp -R "$root/examples" "$app/Contents/Resources/examples" 2>/dev/null || true

# A .app outside /Applications is quarantined and refuses to run, so the
# ad-hoc signature keeps it usable straight from the downloads folder.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$app" >/dev/null 2>&1 \
    && echo "ad-hoc signed" || echo "note: unsigned"
fi

# A .zip keeps the bundle's permissions, which a .dmg or a bare folder does
# not always survive.
cd "$root/dist"
ditto -c -k --sequesterRsrc --keepParent zing.app "zing-$VERSION-macos.zip"
echo "built dist/zing-$VERSION-macos.zip"
